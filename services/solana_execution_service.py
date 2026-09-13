"""
services/solana_execution_service.py
======================================
Real Solana trade execution via Jupiter Aggregator v6.

Flow:
  1. get_jupiter_quote()  — get best route for SOL → token
  2. get_swap_transaction() — build the versioned transaction
  3. execute_buy()        — sign with bot wallet keypair + send via RPC
  4. confirm_transaction() — poll for confirmation

Jupiter API docs: https://station.jup.ag/docs/apis/swap-api
"""

import asyncio
import base64
import json
import logging
from typing import Optional

import aiohttp

from utils.config import settings, get_rpc_url, mark_rpc_rate_limited

logger = logging.getLogger(__name__)

JUPITER_QUOTE_URL       = "https://quote-api.jup.ag/v6/quote"
JUPITER_QUOTE_URL_LITE  = "https://lite.jup.ag/v6/quote"
JUPITER_SWAP_URL        = "https://quote-api.jup.ag/v6/swap"
JUPITER_SWAP_URL_LITE   = "https://lite.jup.ag/v6/swap"
PUMPPORTAL_TRADE   = "https://pumpportal.fun/api/trade-local"
SOL_MINT           = "So11111111111111111111111111111111111111112"

PLATFORM_AUTO    = "auto"
PLATFORM_JUPITER = "jupiter"
PLATFORM_PUMPFUN = "pumpfun"


# ── Jupiter helpers ────────────────────────────────────────────────────────────

async def get_jupiter_quote(
    output_mint: str,
    amount_sol: float,
    slippage_bps: int = 150,
) -> Optional[dict]:
    """
    Fetches the best Jupiter route for SOL → token.
    slippage_bps: basis points (150 = 1.5%)
    Returns the raw quoteResponse dict or None on failure.
    """
    amount_lamports = int(amount_sol * 1_000_000_000)
    params = {
        "inputMint":        SOL_MINT,
        "outputMint":       output_mint,
        "amount":           amount_lamports,
        "slippageBps":      slippage_bps,
        "onlyDirectRoutes": "false",
    }
    urls = [JUPITER_QUOTE_URL, JUPITER_QUOTE_URL_LITE]
    connector = aiohttp.TCPConnector(force_close=True, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        for url in urls:
            for attempt in range(3):  # retry up to 3x per URL on transient DNS/network errors
                try:
                    async with session.get(
                        url, params=params,
                        headers={"Accept": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=12),
                    ) as resp:
                        if resp.status != 200:
                            logger.warning(f"Jupiter quote HTTP {resp.status} ({url})")
                            break  # bad status — try next URL, not retry
                        data = await resp.json()
                        if "error" in data:
                            logger.warning(f"Jupiter quote error ({url}): {data['error']}")
                            break
                        return data
                except Exception as e:
                    if attempt < 2:
                        await asyncio.sleep(0.5 * (attempt + 1))
                    else:
                        logger.warning(f"Jupiter quote unavailable ({url}): {e}")
    return None


async def get_swap_transaction(
    quote_response: dict,
    user_public_key: str,
    priority_fee_lamports: int = 5000,
) -> Optional[str]:
    """
    Posts to Jupiter /swap and returns a base64-encoded VersionedTransaction.
    """
    body = {
        "quoteResponse":             quote_response,
        "userPublicKey":             user_public_key,
        "wrapAndUnwrapSol":          True,
        "dynamicComputeUnitLimit":   True,
        "prioritizationFeeLamports": priority_fee_lamports,
    }
    swap_urls = [JUPITER_SWAP_URL, JUPITER_SWAP_URL_LITE]
    connector = aiohttp.TCPConnector(force_close=True, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        for swap_url in swap_urls:
            for attempt in range(3):
                try:
                    async with session.post(
                        swap_url, json=body,
                        headers={"Content-Type": "application/json", "Accept": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        if resp.status != 200:
                            logger.warning(f"Jupiter swap HTTP {resp.status} ({swap_url})")
                            break
                        data = await resp.json()
                        tx = data.get("swapTransaction")
                        if tx:
                            return tx
                        break
                except Exception as e:
                    if attempt < 2:
                        await asyncio.sleep(0.5 * (attempt + 1))
                    else:
                        logger.warning(f"Jupiter swap unavailable ({swap_url}): {e}")
    return None


def _sign_transaction(swap_b64: str, keypair) -> Optional[bytes]:
    """Sign a base64 Jupiter VersionedTransaction with a solders Keypair."""
    try:
        from solders.transaction import VersionedTransaction
        tx_bytes = base64.b64decode(swap_b64)
        tx       = VersionedTransaction.from_bytes(tx_bytes)
        signed   = VersionedTransaction(tx.message, [keypair])
        return bytes(signed)
    except Exception as e:
        logger.error(f"Transaction signing failed: {e}")
        return None


_BONDING_CURVE_COMPLETE = "__BONDING_CURVE_COMPLETE__"  # sentinel for graduated token


def _is_bonding_curve_complete_error(err: dict) -> bool:
    """Returns True if the RPC error is pump.fun custom error 6005 (BondingCurveComplete)."""
    if not isinstance(err, dict):
        return False
    data = err.get("data") or {}
    instr_err = (data.get("err") or {}).get("InstructionError", [])
    if len(instr_err) >= 2 and isinstance(instr_err[1], dict):
        return instr_err[1].get("Custom") == 6005
    return False


async def _send_raw_transaction(signed_tx_bytes: bytes) -> Optional[str]:
    """
    Sends a signed transaction to the Solana RPC and returns the signature.
    Returns _BONDING_CURVE_COMPLETE sentinel if pump.fun bonding curve has graduated.
    """
    encoded = base64.b64encode(signed_tx_bytes).decode()
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sendTransaction",
        "params": [
            encoded,
            {
                "encoding":              "base64",
                "skipPreflight":         False,
                "maxRetries":            8,
                "preflightCommitment":   "processed",
            },
        ],
    }
    for attempt in range(3):
        rpc_url = get_rpc_url()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    rpc_url,
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 429:
                        mark_rpc_rate_limited(rpc_url)
                        continue  # immediately try next RPC
                    data = await resp.json()
                    if "error" in data:
                        err = data["error"]
                        if isinstance(err, dict) and err.get("code") == 429:
                            mark_rpc_rate_limited(rpc_url)
                            continue  # immediately try next RPC
                        if _is_bonding_curve_complete_error(err):
                            logger.warning("sendTransaction: BondingCurveComplete — token graduated, will retry via Jupiter")
                            return _BONDING_CURVE_COMPLETE
                        logger.warning(f"sendTransaction RPC error: {err}")
                        return None
                    return data.get("result")  # transaction signature
        except Exception as e:
            logger.error(f"sendTransaction exception ({rpc_url[:40]}): {e}")
            if attempt < 2:
                await asyncio.sleep(0.5)
    return None


async def confirm_transaction(signature: str, max_retries: int = 30) -> dict:
    """
    Polls RPC until the transaction is confirmed or max_retries is reached.
    Returns {"signature": str, "status": "confirmed"|"failed"|"timeout"}.
    30 retries × 2s = 60s — matches Solana's ~150-block tx expiry window.
    """
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignatureStatuses",
        "params": [[signature], {"searchTransactionHistory": True}],
    }
    for attempt in range(max_retries):
        await asyncio.sleep(2)
        try:
            rpc_url = get_rpc_url()
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    rpc_url,
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 429:
                        mark_rpc_rate_limited(rpc_url)
                        continue  # immediately try next RPC
                    data  = await resp.json()
                    value = (data.get("result", {}).get("value") or [None])[0]
                    if value is None:
                        continue
                    if value.get("err"):
                        return {"signature": signature, "status": "failed", "err": str(value["err"])}
                    conf = value.get("confirmationStatus", "")
                    if conf in ("confirmed", "finalized"):
                        return {"signature": signature, "status": "confirmed"}
        except Exception as e:
            logger.warning(f"confirm_transaction attempt {attempt}: {e}")

    return {"signature": signature, "status": "timeout"}


# ── PumpPortal bonding curve buy ──────────────────────────────────────────────

async def _pumpfun_buy_transaction(
    wallet_address: str,
    token_mint: str,
    amount_sol: float,
    slippage_pct: float,
    priority_fee_sol: float,
) -> Optional[str]:
    """
    Fetches a signed-ready VersionedTransaction from PumpPortal for a bonding-curve buy.
    Returns base64-encoded transaction or None on failure.
    """
    base_body = {
        "action":           "buy",
        "mint":             token_mint,
        "amount":           amount_sol,
        "denominatedInSol": "true",
        "slippage":         slippage_pct,
        "priorityFee":      priority_fee_sol,
        "publicKey":        wallet_address,
    }
    # Try bonding curve first; if 400 (graduated), fall back to Raydium pool
    for pool in ("pump", "raydium"):
        try:
            body = {**base_body, "pool": pool}
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    PUMPPORTAL_TRADE,
                    data=body,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 400 and pool == "pump":
                        logger.warning("PumpPortal pool=pump returned 400, retrying with pool=raydium")
                        continue
                    if resp.status != 200:
                        text = await resp.text()
                        logger.warning(f"PumpPortal trade failed {resp.status} (pool={pool}): {text[:200]}")
                        return None
                    raw_bytes = await resp.read()
                    return base64.b64encode(raw_bytes).decode()
        except Exception as e:
            logger.error(f"PumpPortal trade exception (pool={pool}): {e}")
            return None
    return None


# ── Main execute function ──────────────────────────────────────────────────────

async def _is_pumpfun_bonding_curve(token_address: str) -> bool:
    """Returns True if the token is still on pump.fun's bonding curve (not graduated)."""
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                if resp.status == 200:
                    data  = await resp.json()
                    pairs = data.get("pairs") or []
                    if not pairs:
                        return True
                    dex_ids = {p.get("dexId", "").lower() for p in pairs}
                    graduated = {"raydium", "orca", "meteora", "lifinity", "aldrin", "saber"}
                    return not bool(dex_ids & graduated)
    except Exception:
        pass
    return True


async def execute_buy(
    user_id: int,
    token_address: str,
    amount_sol: float,
    slippage_pct: float = 15.0,
    priority_fee_sol: float = 0.005,
    platform: str = PLATFORM_AUTO,
    exit_preset_id: Optional[int] = None,
) -> dict:
    """
    Full buy pipeline with platform routing.

    platform = "auto"    → pump.fun tokens use PumpPortal; others use Jupiter; auto-fallback
    platform = "jupiter" → Jupiter only
    platform = "pumpfun" → PumpPortal bonding curve only

    Returns:
      {"success": bool, "signature": str|None, "error": str|None,
       "amount_sol": float, "token_address": str, "platform_used": str}
    """
    from services.bot_wallet_service import get_or_create_bot_wallet, get_keypair

    wallet_row = await get_or_create_bot_wallet(user_id)
    address    = wallet_row["wallet_address"]
    keypair    = get_keypair(wallet_row["encrypted_private_key"])

    slippage_bps       = int(slippage_pct * 100)
    priority_fee_lamps = int(priority_fee_sol * 1_000_000_000)

    # ── Determine routing order ───────────────────────────────────────────────
    if platform == PLATFORM_PUMPFUN:
        routes = ["pumpfun"]
    elif platform == PLATFORM_JUPITER:
        routes = ["jupiter"]
    else:
        # Auto: check bonding curve status and route accordingly
        on_bonding_curve = await _is_pumpfun_bonding_curve(token_address)
        if on_bonding_curve:
            routes = ["pumpfun", "jupiter"]
        else:
            routes = ["jupiter", "pumpfun"]

    route_errors: list[str] = []

    # Each route: build tx → sign → send. If RPC returns BondingCurveComplete, continue to next route.
    for route in routes:
        swap_b64      = None
        platform_used = None

        if route == "jupiter":
            quote = await get_jupiter_quote(token_address, amount_sol, slippage_bps)
            if quote:
                swap_b64 = await get_swap_transaction(quote, address, priority_fee_lamps)
                if swap_b64:
                    platform_used = "Jupiter"
                else:
                    route_errors.append("Jupiter: swap transaction build failed.")
                    continue
            else:
                route_errors.append("Jupiter: no route found for this token.")
                continue
        elif route == "pumpfun":
            swap_b64 = await _pumpfun_buy_transaction(
                address, token_address, amount_sol, slippage_pct, priority_fee_sol
            )
            if swap_b64:
                platform_used = "PumpFun"
            else:
                route_errors.append("PumpPortal: bonding curve buy failed (token may have graduated).")
                continue

        signed_bytes = _sign_transaction(swap_b64, keypair)
        if not signed_bytes:
            route_errors.append(f"{platform_used}: transaction signing failed.")
            continue

        sig = await _send_raw_transaction(signed_bytes)
        if sig == _BONDING_CURVE_COMPLETE:
            # Token just graduated — DexScreener hadn't updated yet. Fall through to Jupiter.
            route_errors.append("PumpFun: token graduated to Raydium (bonding curve complete).")
            # Ensure Jupiter is in the remaining routes
            if "jupiter" not in routes:
                routes = list(routes) + ["jupiter"]
            continue
        if not sig:
            route_errors.append(f"{platform_used}: RPC rejected the transaction.")
            continue

        # ── Success ──────────────────────────────────────────────────────────
        logger.info(f"TX sent via {platform_used} for user {user_id}: {sig}")
        asyncio.create_task(_confirm_and_log(user_id, sig, token_address, amount_sol, exit_preset_id))
        return {
            "success":       True,
            "signature":     sig,
            "error":         None,
            "amount_sol":    amount_sol,
            "token_address": token_address,
            "platform_used": platform_used,
        }

    combined = " | ".join(route_errors) if route_errors else "No route succeeded."
    return {
        "success": False,
        "error": combined,
        "signature": None, "amount_sol": amount_sol,
        "token_address": token_address, "platform_used": None,
    }


async def _confirm_and_log(
    user_id: int,
    signature: str,
    token_address: str,
    amount_sol: float,
    exit_preset_id: Optional[int] = None,
) -> None:
    """
    Background task: waits for on-chain confirmation then updates records.
    Notifies the user if the TX fails or expires so they know the buy did NOT complete.
    """
    from services.positions_service import add_position, log_transaction
    from services.token_data_provider import get_token_price_in_sol
    from services.auto_buy_service import update_job_status as _upd_job
    from database.sqlite_db import get_db

    result = await confirm_transaction(signature)
    status = result["status"]
    await log_transaction(user_id, token_address, signature, amount_sol, "buy", status)

    short_sig  = signature[:12]
    short_addr = token_address[:8]

    if status != "confirmed":
        # TX failed or timed out — correct the job entry and notify user
        on_chain_err = result.get("err", "")
        reason = (
            f"Transaction expired (network congestion)" if status == "timeout"
            else f"On-chain error: {on_chain_err}"
        )
        logger.warning(
            f"TX {short_sig}... {status} for user={user_id} token={short_addr}: {reason}"
        )
        # Fix job status — worker already marked it 'executed' optimistically
        async with get_db() as db:
            async with db.execute(
                "SELECT id FROM auto_buy_jobs WHERE user_id = ? AND token_address = ? "
                "AND status = 'executed' ORDER BY id DESC LIMIT 1",
                (user_id, token_address),
            ) as cur:
                row = await cur.fetchone()
            if row:
                await db.execute(
                    "UPDATE auto_buy_jobs SET status = 'failed' WHERE id = ?", (row[0],)
                )
                await db.commit()

        # Notify user
        try:
            from aiogram import Bot
            from utils.config import settings as _cfg
            _bot = Bot(token=_cfg.BOT_TOKEN)
            status_label = "TIMEOUT" if status == "timeout" else "FAILED"
            try:
                await _bot.send_message(
                    user_id,
                    f"⬛ <b>BUY TX  //  {status_label}</b>\n"
                    f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"ERR    {reason[:80]}\n"
                    f"SOL    not spent — no position opened\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
                    f"📋 CA <i>(tap to copy)</i>\n"
                    f"<code>{token_address}</code>\n\n"
                    f"🔗 TX <i>(tap to copy)</i>\n"
                    f"<code>{signature}</code>\n"
                    f'<a href="https://solscan.io/tx/{signature}">↗ Solscan</a>  '
                    f'<a href="https://pump.fun/{token_address}">↗ Pump.fun</a>',
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            finally:
                await _bot.session.close()
        except Exception as e:
            logger.warning(f"Failed to notify user={user_id} of TX failure: {e}")
        return

    # ── Confirmed ─────────────────────────────────────────────────────────────
    logger.info(f"TX {short_sig}... confirmed for user={user_id} token={short_addr}")
    from datetime import datetime, timezone
    confirmed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Retry entry price — new pump.fun tokens take 5-30s to appear in price APIs.
    # A zero entry price causes auto-exit to silently skip the position forever.
    entry_price = 0.0
    for attempt in range(6):
        p = await get_token_price_in_sol(token_address)
        if p and p > 0:
            entry_price = p
            break
        await asyncio.sleep(5)
    if entry_price <= 0:
        logger.warning(
            f"Entry price unavailable after retries for {short_addr} — "
            "position registered at 0, watcher will backfill on first cycle"
        )

    position_id = await add_position(
        user_id       = user_id,
        token_address = token_address,
        token_symbol  = token_address[:6] + "...",
        buy_price_sol = entry_price,
        amount_sol    = amount_sol,
        tx_signature  = signature,
    )
    if position_id:
        try:
            from services.auto_exit_service import get_auto_exit_settings, register_position
            ae_s = await get_auto_exit_settings(user_id)
            preset_id = exit_preset_id or ae_s.get("selected_preset_id")
            await register_position(
                position_id, user_id, token_address,
                entry_price, preset_id,
                opened_at=confirmed_at,   # anchor max_hold_minutes to actual buy time
            )
        except Exception as e:
            logger.warning(f"Auto-exit registration skipped for pos {position_id}: {e}")


async def _confirm_sell_and_log(user_id: int, signature: str, token_address: str) -> None:
    """
    Background task: confirms a sell TX on-chain.
    If it fails/expires, notifies the user so they know the sell did NOT complete
    and can manually retry.
    """
    result = await confirm_transaction(signature)
    status = result["status"]
    if status == "confirmed":
        logger.info(f"SELL TX {signature[:12]}... confirmed user={user_id} token={token_address[:8]}")
        return

    on_chain_err = result.get("err", "")
    reason = (
        "Transaction expired (network congestion)" if status == "timeout"
        else f"On-chain error: {on_chain_err}"
    )
    logger.warning(f"SELL TX {signature[:12]}... {status} user={user_id} token={token_address[:8]}: {reason}")

    try:
        from aiogram import Bot
        from utils.config import settings as _cfg
        _bot = Bot(token=_cfg.BOT_TOKEN)
        try:
            await _bot.send_message(
                user_id,
                f"⚠️ <b>SELL TX  //  {status.upper()}</b>\n"
                f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"ERR    {reason[:80]}\n"
                f"ACTION check wallet — tokens may NOT be sold\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
                f"📋 CA <i>(tap to copy)</i>\n"
                f"<code>{token_address}</code>\n\n"
                f"🔗 TX <i>(tap to copy)</i>\n"
                f"<code>{signature}</code>\n"
                f'<a href="https://solscan.io/tx/{signature}">↗ Solscan</a>  '
                f'<a href="https://pump.fun/{token_address}">↗ Pump.fun</a>',
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        finally:
            await _bot.session.close()
    except Exception as e:
        logger.warning(f"Failed to notify user={user_id} of sell TX failure: {e}")


async def _get_token_raw_balance(wallet_address: str, token_mint: str) -> tuple[int, int]:
    """
    Returns (raw_balance, decimals) for a given SPL token in a wallet.
    raw_balance is in the smallest unit (e.g. lamports for SOL).
    """
    body = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            wallet_address,
            {"mint": token_mint},
            {"encoding": "jsonParsed"},
        ],
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                get_rpc_url(), json=body,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data     = await resp.json()
                accounts = data.get("result", {}).get("value", [])
                if not accounts:
                    return 0, 6
                info     = accounts[0]["account"]["data"]["parsed"]["info"]
                decimals = int(info["tokenAmount"].get("decimals", 6))
                amount   = int(info["tokenAmount"].get("amount", 0))
                return amount, decimals
    except Exception as e:
        logger.warning(f"_get_token_raw_balance failed: {e}")
        return 0, 6


async def execute_sell(
    user_id: int,
    token_address: str,
    sell_pct: float,          # % of current token balance to sell (0-100)
    slippage_pct: float = 15.0,
    priority_fee_sol: float = 0.005,
    platform: str = PLATFORM_AUTO,
) -> dict:
    """
    Sell `sell_pct`% of the user's current token balance back to SOL.

    Returns:
      {"success": bool, "signature": str|None, "error": str|None,
       "sell_pct": float, "token_address": str, "platform_used": str}
    """
    from services.bot_wallet_service import get_or_create_bot_wallet, get_keypair

    wallet_row = await get_or_create_bot_wallet(user_id)
    address    = wallet_row["wallet_address"]
    keypair    = get_keypair(wallet_row["encrypted_private_key"])

    # Fetch current raw balance
    raw_balance, decimals = await _get_token_raw_balance(address, token_address)
    if raw_balance == 0:
        return {
            "success": False,
            "error": "No token balance found in bot wallet.",
            "signature": None, "sell_pct": sell_pct,
            "token_address": token_address, "platform_used": None,
        }

    # Always keep 1000 raw tokens as a permanent record in the wallet.
    # If the balance is already at or below the keep amount, nothing left to sell.
    KEEP_AMOUNT = 1_000
    if raw_balance <= KEEP_AMOUNT:
        return {
            "success": False,
            "error": "dust",
            "signature": None, "sell_pct": sell_pct,
            "token_address": token_address, "platform_used": None,
        }

    # Sell everything above the 1000-token keep amount
    sellable = raw_balance - KEEP_AMOUNT
    sell_raw = min(int(sellable * sell_pct / 100), sellable)
    if sell_raw == 0:
        return {
            "success": False,
            "error": "Calculated sell amount is zero (balance too small).",
            "signature": None, "sell_pct": sell_pct,
            "token_address": token_address, "platform_used": None,
        }

    slippage_bps       = int(slippage_pct * 100)
    priority_fee_lamps = int(priority_fee_sol * 1_000_000_000)
    sell_ui            = sell_raw / (10 ** decimals)  # human-readable amount

    # ── Determine routing order (mirror of execute_buy) ───────────────────────
    if platform == PLATFORM_PUMPFUN:
        routes = ["pumpfun"]
    elif platform == PLATFORM_JUPITER:
        routes = ["jupiter"]
    else:
        on_bonding_curve = await _is_pumpfun_bonding_curve(token_address)
        if on_bonding_curve:
            routes = ["pumpfun", "jupiter"]
        else:
            routes = ["jupiter", "pumpfun"]

    swap_b64      = None
    platform_used = None
    route_errors: list[str] = []

    for route in routes:
        if route == "jupiter":
            # Jupiter: sell token → SOL (inputMint=token, outputMint=SOL)
            # Try main URL first, fall back to lite URL on DNS/connection failure
            params = {
                "inputMint":   token_address,
                "outputMint":  SOL_MINT,
                "amount":      sell_raw,
                "slippageBps": slippage_bps,
            }
            for jup_url in (JUPITER_QUOTE_URL, JUPITER_QUOTE_URL_LITE):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            jup_url, params=params,
                            timeout=aiohttp.ClientTimeout(total=15),
                        ) as resp:
                            if resp.status == 200:
                                quote = await resp.json()
                                if "error" not in quote:
                                    swap_b64 = await get_swap_transaction(
                                        quote, address, priority_fee_lamps
                                    )
                                    if swap_b64:
                                        platform_used = "Jupiter"
                                        break
                                route_errors.append(f"Jupiter sell quote error: {quote.get('error', 'unknown')}")
                                break  # quote succeeded but had error — don't retry lite for same error
                            else:
                                route_errors.append(f"Jupiter quote HTTP {resp.status}")
                                break
                except Exception as e:
                    route_errors.append(f"Jupiter sell exception: {e}")
                    # DNS / connection error — try lite endpoint
                    continue
            if swap_b64:
                break

        elif route == "pumpfun":
            # PumpPortal: sell — try bonding curve first, fall back to raydium pool
            base_sell_body = {
                "action":           "sell",
                "mint":             token_address,
                "amount":           sell_ui,
                "denominatedInSol": "false",
                "slippage":         slippage_pct,
                "priorityFee":      priority_fee_sol,
                "publicKey":        address,
            }
            for sell_pool in ("pump", "raydium"):
                try:
                    body = {**base_sell_body, "pool": sell_pool}
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            PUMPPORTAL_TRADE, data=body,
                            timeout=aiohttp.ClientTimeout(total=20),
                        ) as resp:
                            if resp.status == 400 and sell_pool == "pump":
                                logger.warning("PumpPortal sell pool=pump returned 400, retrying with pool=raydium")
                                continue
                            if resp.status == 200:
                                raw_bytes = await resp.read()
                                swap_b64  = base64.b64encode(raw_bytes).decode()
                                platform_used = "PumpFun"
                                break
                            route_errors.append(f"PumpPortal sell HTTP {resp.status} (pool={sell_pool})")
                            break
                except Exception as e:
                    route_errors.append(f"PumpPortal sell exception: {e}")
                    break
            if swap_b64:
                break

    if not swap_b64:
        combined = " | ".join(route_errors) if route_errors else "No sell route succeeded."
        return {
            "success": False, "error": combined, "signature": None,
            "sell_pct": sell_pct, "token_address": token_address, "platform_used": None,
        }

    signed_bytes = _sign_transaction(swap_b64, keypair)
    if not signed_bytes:
        return {
            "success": False, "error": "Transaction signing failed.",
            "signature": None, "sell_pct": sell_pct,
            "token_address": token_address, "platform_used": platform_used,
        }

    sig = await _send_raw_transaction(signed_bytes)
    if not sig:
        return {
            "success": False, "error": "RPC rejected sell transaction.",
            "signature": None, "sell_pct": sell_pct,
            "token_address": token_address, "platform_used": platform_used,
        }

    logger.info(f"SELL TX via {platform_used} user={user_id} token={token_address[:8]} sig={sig[:12]}")
    asyncio.create_task(_confirm_sell_and_log(user_id, sig, token_address))
    return {
        "success":       True,
        "signature":     sig,
        "error":         None,
        "sell_pct":      sell_pct,
        "token_address": token_address,
        "platform_used": platform_used,
    }


async def get_token_balance(wallet_address: str, token_mint: str) -> Optional[float]:
    """Returns SPL token balance for a wallet (ui amount)."""
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            wallet_address,
            {"mint": token_mint},
            {"encoding": "jsonParsed"},
        ],
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                get_rpc_url(),
                json=body,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                accounts = data.get("result", {}).get("value", [])
                if not accounts:
                    return 0.0
                info = accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]
                return float(info.get("uiAmount") or 0.0)
    except Exception as e:
        logger.warning(f"getTokenBalance failed: {e}")
        return None
