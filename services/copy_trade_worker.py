"""
services/copy_trade_worker.py
==============================
Background worker that monitors tracked wallets for swap transactions
and executes copy trades for subscribed users.

Monitoring strategy:
  - Every POLL_INTERVAL seconds, collect all unique wallet addresses
    actively tracked by enabled users.
  - For each wallet: call getSignaturesForAddress (limit=5) to get recent txs.
  - Only process signatures not yet seen (tracked via _last_sig per wallet).
  - For each new signature: call getTransaction and parse swap direction.
  - Fan out to all users tracking that wallet and apply their risk controls.
  - Execute via existing execute_buy / execute_sell.

RPC concurrency is capped by a semaphore to avoid rate-limiting.
"""

import asyncio
import json
import logging
import time
from typing import Optional

import aiohttp

from utils.config import settings, get_rpc_url

logger = logging.getLogger(__name__)

POLL_INTERVAL   = 15      # seconds between full wallet scans
RPC_SEMAPHORE   = 30      # max concurrent RPC calls
RPC_TIMEOUT     = 8       # seconds per RPC call
SOL_MINT        = "So11111111111111111111111111111111111111112"
LAMPORTS_PER_SOL = 1_000_000_000

LOW_BALANCE_NOTIFY_COOLDOWN = 1800  # seconds between low-balance alerts per user (30 min)
_running = False
# wallet_address → last processed signature (so we don't re-process)
_last_sig: dict[str, str] = {}
_low_balance_last_notified: dict[int, float] = {}  # user_id → timestamp

# ── Live stats ─────────────────────────────────────────────────────────────────
_stats: dict = {
    "scans_completed":    0,
    "wallets_monitored":  0,
    "swaps_detected":     0,
    "trades_executed":    0,
    "trades_skipped":     0,
    "trades_failed":      0,
    "last_scan_ts":       0.0,
    "last_trade_ts":      0.0,
    "last_trade_symbol":  "",
}


def get_stats() -> dict:
    return dict(_stats)


def stop() -> None:
    global _running
    _running = False


async def start(bot) -> None:
    global _running, _last_sig, _stats
    _running = True
    _last_sig = {}
    for k in _stats:
        _stats[k] = 0.0 if k.endswith("_ts") else (0 if isinstance(_stats[k], int) else "")

    logger.info("Copy trade worker started.")
    while _running:
        try:
            await _scan(bot)
        except Exception as e:
            logger.error(f"Copy trade worker error: {e}", exc_info=True)
        await asyncio.sleep(POLL_INTERVAL)
    logger.info("Copy trade worker stopped.")


# ── Core scan ─────────────────────────────────────────────────────────────────

async def _scan(bot) -> None:
    from services.copy_trade_service import get_all_active_tracked_wallets

    wallets = await get_all_active_tracked_wallets()
    if not wallets:
        _stats["scans_completed"] += 1
        _stats["last_scan_ts"]    = time.time()
        if _stats["scans_completed"] % 10 == 1:   # log once per ~2.5 min
            logger.info("CT worker: no active wallets (copy trading off, no wallets added, or kill_switch on)")
        return

    _stats["wallets_monitored"] = len(wallets)
    logger.info(f"CT scan: monitoring {len(wallets)} wallet(s)")
    sem = asyncio.Semaphore(RPC_SEMAPHORE)

    tasks = [_check_wallet(bot, addr, sem) for addr in wallets]
    await asyncio.gather(*tasks, return_exceptions=True)

    _stats["scans_completed"] += 1
    _stats["last_scan_ts"]    = time.time()


async def _check_wallet(bot, wallet_address: str, sem: asyncio.Semaphore) -> None:
    """Fetch recent signatures for a wallet and process any new swaps."""
    async with sem:
        sigs = await _get_recent_signatures(wallet_address, limit=15)

    if not sigs:
        return

    # Find the boundary: only process sigs newer than our last known
    last_known = _last_sig.get(wallet_address)
    new_sigs = []
    for sig_info in sigs:
        sig = sig_info.get("signature", "")
        if not sig:
            continue
        if sig == last_known:
            break
        new_sigs.append(sig_info)

    if new_sigs:
        # Update last known to the most recent signature
        _last_sig[wallet_address] = sigs[0].get("signature", last_known)

    for sig_info in reversed(new_sigs):   # oldest first
        sig = sig_info.get("signature", "")
        if not sig:
            continue
        async with sem:
            swap = await _parse_swap_from_signature(wallet_address, sig)
        if swap:
            _stats["swaps_detected"] += 1
            logger.info(
                f"Copy trade swap detected: wallet={wallet_address[:8]} "
                f"token={swap['token_mint'][:8]} dir={swap['direction']} "
                f"sol={swap['sol_amount']:.4f} sig={sig[:12]}"
            )
            await _fan_out(bot, wallet_address, swap)


# ── RPC Helpers ───────────────────────────────────────────────────────────────

async def _rpc_post(payload: dict) -> Optional[dict]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                get_rpc_url(),
                json=payload,
                timeout=aiohttp.ClientTimeout(total=RPC_TIMEOUT),
                headers={"Content-Type": "application/json"},
            ) as resp:
                return await resp.json(content_type=None)
    except Exception as e:
        logger.debug(f"RPC error: {e}")
        return None


async def _get_recent_signatures(wallet_address: str, limit: int = 5) -> list[dict]:
    """Return recent confirmed transaction signatures for a wallet."""
    data = await _rpc_post({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [wallet_address, {"limit": limit, "commitment": "confirmed"}],
    })
    if not data:
        return []
    return data.get("result") or []


async def _get_transaction(signature: str) -> Optional[dict]:
    """Fetch a full transaction with pre/post balances."""
    data = await _rpc_post({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            signature,
            {
                "encoding":                       "jsonParsed",
                "commitment":                     "confirmed",
                "maxSupportedTransactionVersion": 0,
            },
        ],
    })
    if not data:
        return None
    return data.get("result")


# ── Swap Parser ────────────────────────────────────────────────────────────────

async def _parse_swap_from_signature(wallet_address: str, signature: str) -> Optional[dict]:
    """
    Parse a transaction to determine if it's a token swap by the tracked wallet.

    Returns a dict with:
        token_mint   — the SPL token involved
        direction    — "buy" or "sell"
        sol_amount   — approximate SOL value of the swap
        signature    — transaction signature

    Returns None if the tx is not a swap or parsing fails.
    """
    tx = await _get_transaction(signature)
    if not tx:
        return None

    meta = tx.get("meta") or {}
    if meta.get("err"):
        return None   # failed transaction — skip

    # Build full account key list:
    # Static keys (accountKeys) + dynamically loaded addresses (writable then readonly).
    # Versioned transactions (Raydium v4, Jupiter v6) use Address Lookup Tables so the
    # wallet address may appear only in meta.loadedAddresses, not accountKeys.
    try:
        account_keys = tx["transaction"]["message"]["accountKeys"]
        key_list = []
        for k in account_keys:
            if isinstance(k, str):
                key_list.append(k)
            elif isinstance(k, dict):
                key_list.append(k.get("pubkey", ""))
    except (KeyError, TypeError):
        return None

    loaded = (meta.get("loadedAddresses") or {})
    for k in (loaded.get("writable") or []) + (loaded.get("readonly") or []):
        if isinstance(k, str):
            key_list.append(k)
        elif isinstance(k, dict):
            key_list.append(k.get("pubkey", ""))

    # Find the index of the tracked wallet
    try:
        wallet_idx = key_list.index(wallet_address)
    except ValueError:
        return None   # wallet not in this transaction

    # ── SOL balance change ────────────────────────────────────────────────────
    pre_balances  = meta.get("preBalances")  or []
    post_balances = meta.get("postBalances") or []

    if wallet_idx >= len(pre_balances) or wallet_idx >= len(post_balances):
        return None

    sol_delta = (post_balances[wallet_idx] - pre_balances[wallet_idx]) / LAMPORTS_PER_SOL
    # sol_delta < 0 → wallet spent SOL (buy)
    # sol_delta > 0 → wallet received SOL (sell)
    # Ignore tiny delta (fee-only transactions, not swaps)
    if abs(sol_delta) < 0.0001:
        return None

    # ── SPL token balance change ──────────────────────────────────────────────
    pre_token  = meta.get("preTokenBalances")  or []
    post_token = meta.get("postTokenBalances") or []

    # Build owner → mint → amount maps
    def _token_amounts(balances: list) -> dict:
        result = {}
        for b in balances:
            owner = b.get("owner") or ""
            mint  = b.get("mint")  or ""
            try:
                amt = float(b.get("uiTokenAmount", {}).get("uiAmount") or 0)
            except (TypeError, ValueError):
                amt = 0.0
            if owner and mint:
                result[(owner, mint)] = amt
        return result

    pre_map  = _token_amounts(pre_token)
    post_map = _token_amounts(post_token)

    # Find the token whose balance changed for this wallet
    all_keys = set(pre_map.keys()) | set(post_map.keys())
    token_mint = None
    token_delta = 0.0

    for (owner, mint) in all_keys:
        if owner != wallet_address:
            continue
        pre_amt  = pre_map.get((owner, mint), 0.0)
        post_amt = post_map.get((owner, mint), 0.0)
        delta    = post_amt - pre_amt
        if abs(delta) > abs(token_delta):
            token_delta = delta
            token_mint  = mint

    if not token_mint:
        return None   # no SPL token change — not a swap

    # Determine direction from SOL flow (more reliable than token flow)
    direction = "buy" if sol_delta < 0 else "sell"
    sol_amount = abs(sol_delta)

    return {
        "token_mint":  token_mint,
        "direction":   direction,
        "sol_amount":  sol_amount,
        "token_delta": token_delta,
        "signature":   signature,
        "timestamp":   time.time(),
    }


# ── Fan-out & Execution ───────────────────────────────────────────────────────

async def _fan_out(bot, wallet_address: str, swap: dict) -> None:
    """Distribute a detected swap to all users tracking this wallet."""
    from services.copy_trade_service import get_users_tracking_wallet
    users = await get_users_tracking_wallet(wallet_address)

    tasks = [
        _maybe_copy(bot, wallet_address, swap, user_row)
        for user_row in users
    ]
    await asyncio.gather(*tasks, return_exceptions=True)


async def _maybe_copy(bot, wallet_address: str, swap: dict, user_row: dict) -> None:
    """
    Evaluate and optionally execute a copy trade for a single user.

    Gate order:
      1. Direction filter (copy_buys / copy_sells setting)
      2. Duplicate TX check
      3. Tier limits
      4. Hourly rate limit
      5. Cooldown between trades
      6. Token blacklist
      7. Token whitelist (Supreme Black — if whitelist not empty, must be in it)
      8. Liquidity filter (Supreme / Supreme Black)
      9. Max buy protection
     10. Balance check
     11. Execute
    """
    from services.copy_trade_service import (
        is_tx_processed, mark_tx_processed, count_copy_trades_last_hour,
        get_last_trade_time, log_copy_trade_job, update_copy_trade_job,
        get_copy_trade_entitlements, get_blacklisted_addresses,
        get_whitelisted_addresses,
    )
    from services.bot_wallet_service import get_or_create_bot_wallet, get_sol_balance
    from services.solana_execution_service import execute_buy, execute_sell

    user_id   = user_row["user_id"]
    token     = swap["token_mint"]
    direction = swap["direction"]
    sig       = swap["signature"]
    leader_sol = swap["sol_amount"]

    # 1. Direction gate
    if direction == "buy" and not user_row.get("copy_buys"):
        logger.info(f"CT skip (copy_buys=off) user={user_id} token={token[:8]}")
        return
    if direction == "sell" and not user_row.get("copy_sells"):
        logger.info(f"CT skip (copy_sells=off) user={user_id} token={token[:8]}")
        return

    # 2. Duplicate TX check
    if await is_tx_processed(sig, user_id):
        return

    # 3. Tier entitlements
    ents = await get_copy_trade_entitlements(user_id)
    if direction == "sell" and not ents.can_copy_sells:
        await mark_tx_processed(sig, user_id, wallet_address, token, direction)
        return

    # 4. Hourly rate limit
    trades_this_hour = await count_copy_trades_last_hour(user_id)
    max_per_hour     = min(int(user_row.get("max_trades_per_hour") or 30),
                           ents.max_trades_per_hour)
    if trades_this_hour >= max_per_hour:
        logger.info(f"Copy trade rate-limited user={user_id} ({trades_this_hour}/{max_per_hour}/hr)")
        return

    # 5. Cooldown
    if ents.can_use_cooldown:
        cooldown = int(user_row.get("cooldown_seconds") or 0)
        if cooldown > 0:
            last_ts = await get_last_trade_time(user_id)
            elapsed = time.time() - last_ts
            if elapsed < cooldown:
                logger.info(f"CT skip (cooldown) user={user_id} ({elapsed:.0f}s < {cooldown}s)")
                return

    # 6. Token blacklist
    if ents.can_use_blacklist:
        bl = await get_blacklisted_addresses(user_id)
        if token in bl:
            logger.info(f"Copy trade skipped (blacklisted) user={user_id} token={token[:8]}")
            job_id = await log_copy_trade_job(user_id, wallet_address, token, direction,
                                              leader_sol, 0.0, sig)
            await update_copy_trade_job(job_id, "skipped", skip_reason="token blacklisted")
            await mark_tx_processed(sig, user_id, wallet_address, token, direction)
            _stats["trades_skipped"] += 1
            return

    # 7. Token whitelist (only enforced when whitelist is non-empty)
    if ents.can_use_whitelist:
        wl = await get_whitelisted_addresses(user_id)
        if wl and token not in wl:
            logger.info(f"Copy trade skipped (not whitelisted) user={user_id} token={token[:8]}")
            job_id = await log_copy_trade_job(user_id, wallet_address, token, direction,
                                              leader_sol, 0.0, sig)
            await update_copy_trade_job(job_id, "skipped", skip_reason="not in whitelist")
            await mark_tx_processed(sig, user_id, wallet_address, token, direction)
            _stats["trades_skipped"] += 1
            return

    # 8. Liquidity filter
    if ents.can_use_liq_filter:
        min_liq = float(user_row.get("min_liquidity_usd") or 0)
        if min_liq > 0:
            liq = await _get_token_liquidity(token)
            if liq is not None and liq < min_liq:
                logger.info(
                    f"Copy trade skipped (low liq ${liq:.0f} < ${min_liq:.0f}) "
                    f"user={user_id} token={token[:8]}"
                )
                job_id = await log_copy_trade_job(user_id, wallet_address, token, direction,
                                                  leader_sol, 0.0, sig)
                await update_copy_trade_job(job_id, "skipped", skip_reason=f"low liquidity ${liq:.0f}")
                await mark_tx_processed(sig, user_id, wallet_address, token, direction)
                _stats["trades_skipped"] += 1
                return

    # 9. Compute copy trade size
    copy_size_mode  = user_row.get("copy_size_mode") or "fixed"
    fixed_amount    = float(user_row.get("fixed_amount_sol") or 0.05)
    pct_amount      = float(user_row.get("percentage_amount") or 10.0)
    max_buy         = float(user_row.get("max_buy_amount_sol") or 0.5)

    if copy_size_mode == "percentage" and ents.can_use_percentage:
        copy_sol = leader_sol * (pct_amount / 100.0)
    else:
        copy_sol = fixed_amount

    # Enforce max buy protection
    if ents.can_use_max_buy_prot and max_buy > 0:
        copy_sol = min(copy_sol, max_buy)

    copy_sol = max(copy_sol, 0.001)   # minimum viable trade

    slippage     = float(user_row.get("max_slippage") or 15.0)
    priority_fee = float(user_row.get("priority_fee") or 0.005)

    # 10. Balance checks
    wallet_row  = await get_or_create_bot_wallet(user_id)
    bot_address = wallet_row["wallet_address"]

    if direction == "buy":
        balance     = await get_sol_balance(bot_address)
        fee_reserve = copy_sol * 0.01 + priority_fee + 0.002
        min_needed  = copy_sol + fee_reserve
        if balance is None or balance < min_needed:
            logger.warning(
                f"Copy trade skipped (low SOL balance) user={user_id} "
                f"bal={balance or 0:.5f} need={min_needed:.5f}"
            )
            last_notified = _low_balance_last_notified.get(user_id, 0)
            if time.time() - last_notified >= LOW_BALANCE_NOTIFY_COOLDOWN:
                _low_balance_last_notified[user_id] = time.time()
                await _notify(bot, user_id,
                    f"⚠️ <b>Copy Trade skipped</b> — insufficient balance.\n"
                    f"Balance: {(balance or 0):.5f} SOL | Need: {min_needed:.5f} SOL\n"
                    f"Top up your bot wallet to resume copy trading."
                )
            return

    if direction == "sell":
        from services.solana_execution_service import _get_token_raw_balance
        raw_bal, _ = await _get_token_raw_balance(bot_address, token)
        if raw_bal == 0:
            # Bot never bought this token — silently skip the copy sell
            logger.info(
                f"Copy sell skipped (no token balance) user={user_id} token={token[:8]}"
            )
            await mark_tx_processed(sig, user_id, wallet_address, token, direction)
            return

    # 11. Mark processed before execution to prevent duplicate runs
    await mark_tx_processed(sig, user_id, wallet_address, token, direction)

    # Log job
    job_id = await log_copy_trade_job(
        user_id, wallet_address, token, direction, leader_sol, copy_sol, sig
    )

    # Notify user: copy detected
    short_wallet = wallet_address[:6] + "..." + wallet_address[-4:]
    short_token  = token[:6] + "..." + token[-4:]
    dir_icon     = "🟢 BUY" if direction == "buy" else "🔴 SELL"
    await _notify(bot, user_id,
        f"📋 <b>COPY TRADE  //  DETECTED</b>\n"
        f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"DIR    {dir_icon}\n"
        f"LEADER {leader_sol:.4f} SOL  [{short_wallet}]\n"
        f"COPY   {copy_sol:.4f} SOL\n"
        f"STATUS executing...</code>\n\n"
        f"📋 CA <i>(tap to copy)</i>\n"
        f"<code>{token}</code>"
    )

    # Execute — retry once after 4s to handle newly-traded/just-graduated tokens
    # that may not be indexed by Jupiter immediately.
    result = None
    for attempt in range(2):
        try:
            if direction == "buy":
                result = await execute_buy(
                    user_id          = user_id,
                    token_address    = token,
                    amount_sol       = copy_sol,
                    slippage_pct     = slippage,
                    priority_fee_sol = priority_fee,
                    platform         = "auto",
                )
            else:
                result = await execute_sell(
                    user_id          = user_id,
                    token_address    = token,
                    sell_pct         = 100.0,
                    slippage_pct     = slippage,
                    priority_fee_sol = priority_fee,
                    platform         = "auto",
                )
        except Exception as e:
            logger.error(f"Copy trade execute error user={user_id} token={token[:8]}: {e}")
            result = {"success": False, "error": str(e)}

        if result and result.get("success"):
            break
        if attempt == 0:
            logger.info(
                f"Copy trade attempt 1 failed user={user_id} token={token[:8]} dir={direction} "
                f"— retrying in 4s: {(result or {}).get('error', '')}"
            )
            await asyncio.sleep(4)

    if not result or not result.get("success"):
        err = (result or {}).get("error", "Unknown error")
        await update_copy_trade_job(job_id, "failed", skip_reason=err[:200])
        await _notify(bot, user_id,
            f"❌ <b>COPY TRADE  //  FAILED</b>\n"
            f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"DIR    {dir_icon}\n"
            f"ERR    {err[:60]}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
            f"📋 CA <i>(tap to copy)</i>\n"
            f"<code>{token}</code>"
        )
        _stats["trades_failed"] += 1
        logger.warning(f"Copy trade failed (both attempts) user={user_id} token={token[:8]} dir={direction}: {err}")
        return

    if result.get("success"):
        tx_sig = result.get("signature", "")
        plat   = result.get("platform_used", "?")
        await update_copy_trade_job(job_id, "executed", tx_signature=tx_sig)
        _stats["trades_executed"] += 1
        _stats["last_trade_ts"]     = time.time()
        _stats["last_trade_symbol"] = short_token

        await _notify(bot, user_id,
            f"✅ <b>COPY TRADE  //  EXECUTED</b>\n"
            f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"DIR    {dir_icon}\n"
            f"SIZE   {copy_sol:.4f} SOL  [{plat.upper()}]\n"
            f"LEADER {short_wallet}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
            f"📋 CA <i>(tap to copy)</i>\n"
            f"<code>{token}</code>\n\n"
            f"🔗 TX <i>(tap to copy)</i>\n"
            f"<code>{tx_sig}</code>\n"
            f'<a href="https://solscan.io/tx/{tx_sig}">↗ Solscan</a>  '
            f'<a href="https://pump.fun/{token}">↗ Pump.fun</a>  '
            f'<a href="https://solscan.io/tx/{sig}">↗ Leader TX</a>'
        )
        logger.info(
            f"Copy trade executed user={user_id} token={token[:8]} "
            f"dir={direction} size={copy_sol:.4f} sig={tx_sig[:12]}"
        )
    else:
        err = result.get("error", "Unknown error")
        await update_copy_trade_job(job_id, "failed", skip_reason=err[:200])
        _stats["trades_failed"] += 1
        await _notify(bot, user_id,
            f"❌ <b>COPY TRADE  //  FAILED</b>\n"
            f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"DIR    {dir_icon}\n"
            f"ERR    {err[:60]}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
            f"📋 CA <i>(tap to copy)</i>\n"
            f"<code>{token}</code>"
        )
        logger.warning(f"Copy trade failed user={user_id} token={token[:8]}: {err}")


# ── Liquidity Helper ──────────────────────────────────────────────────────────

async def _get_token_liquidity(token_address: str) -> Optional[float]:
    """Quick DexScreener liquidity lookup. Returns None on failure."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{token_address}",
                timeout=aiohttp.ClientTimeout(total=6),
            ) as resp:
                data = await resp.json(content_type=None)
        pairs = (data or {}).get("pairs") or []
        if not pairs:
            return None
        # Use the pair with highest liquidity
        liq_values = [
            float(p.get("liquidity", {}).get("usd") or 0)
            for p in pairs
        ]
        return max(liq_values) if liq_values else None
    except Exception:
        return None


# ── Notification ──────────────────────────────────────────────────────────────

async def _notify(bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"Copy trade notify failed user={user_id}: {e}")
