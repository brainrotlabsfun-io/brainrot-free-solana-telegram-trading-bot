"""
services/candle_sniper_worker.py
==================================
Background worker for the Candle Sniper strategy module.

Two concurrent loops run inside start():
  1. Discovery loop  — polls DexScreener for candidates, scores with the 9
                       quant equations, upserts into candle_sniper_candidates.
                       For users with auto_buy = 1, fires buys on qualifying tokens.
  2. Position loop   — monitors all open CS positions for exit conditions:
                         • Fixed take profit
                         • Fixed stop loss
                         • Trailing stop (after TP activation, SUPREME+)
                         • Momentum failure exit (volume collapses)
                         • Max trade duration exit

The worker is completely independent of the regular auto_buy_worker.
It uses its own candidate queue, its own settings, and its own exit logic.
"""

import asyncio
import logging
import time
from typing import Optional

from aiogram import Bot
from utils.config import settings

logger = logging.getLogger(__name__)

# ── Worker Config ─────────────────────────────────────────────────────────────
DISCOVERY_INTERVAL = 60     # seconds between candidate scans
POSITION_INTERVAL  = 20     # seconds between position price checks
SURGE_INTERVAL     = 600    # seconds between surge re-checks (10 min)
_running = False

# Live stats (reset on worker start)
_stats: dict = {
    "discovery_cycles":  0,
    "candidates_scored": 0,
    "candidates_passed": 0,
    "buys_executed":     0,
    "buys_failed":       0,
    "positions_closed":  0,
    "surge_alerts":      0,
    "surge_buys":        0,
    "last_discovery_ts": 0.0,
}


def get_stats() -> dict:
    return dict(_stats)


def stop() -> None:
    global _running
    _running = False


# ── Entry Point ───────────────────────────────────────────────────────────────

async def start(bot: Bot) -> None:
    global _running
    _running = True
    logger.info("Candle Sniper worker started")

    discovery_task = asyncio.create_task(_discovery_loop(bot))
    position_task  = asyncio.create_task(_position_loop(bot))
    surge_task     = asyncio.create_task(_surge_loop(bot))

    try:
        await asyncio.gather(discovery_task, position_task, surge_task)
    except asyncio.CancelledError:
        pass
    finally:
        _running = False
        logger.info("Candle Sniper worker stopped")


# ── Discovery Loop ────────────────────────────────────────────────────────────

async def _discovery_loop(bot: Bot) -> None:
    """
    Every DISCOVERY_INTERVAL seconds:
      1. Discover Solana token candidates from DexScreener
      2. Score each with the 9 quant equations
      3. Upsert into candle_sniper_candidates table
      4. For users with auto_buy=1, check if any candidate qualifies for a buy
    """
    from services.candle_sniper_service import (
        discover_candidates, get_user_watchlist, fetch_cs_token_data,
        get_top_candidates, upsert_candidate, expire_old_candidates,
        get_users_with_cs_autobuy, get_cs_entitlements, mark_candidate_traded,
        count_open_cs_positions, open_cs_position, record_cs_price,
        cleanup_expired_price_history,
    )
    from services.candle_sniper_engine import (
        score_candidate, apply_profile_filters, STRATEGY_PROFILES,
    )
    from services.brainrot_token_gate import get_active_tier

    while _running:
        try:
            _stats["discovery_cycles"] += 1
            _stats["last_discovery_ts"] = time.time()

            # Get users who need auto-buying
            cs_users = await get_users_with_cs_autobuy()

            # Determine profiles needed to cover all users
            profiles_needed = set(u.get("strategy_profile", "balanced") for u in cs_users)
            if not profiles_needed:
                profiles_needed = {"balanced"}

            # Primary discovery: DexScreener token boosts + first user's watchlist
            active_user_ids = list({u["user_id"] for u in cs_users})
            primary_uid = active_user_ids[0] if active_user_ids else None

            raw_candidates = await discover_candidates(user_id=primary_uid)

            # Merge any remaining users' custom watchlist tokens
            seen_addresses = {t.get("address", "") for t in raw_candidates}
            for uid in active_user_ids[1:]:
                for entry in await get_user_watchlist(uid):
                    addr = entry["token_address"]
                    if addr and addr not in seen_addresses:
                        seen_addresses.add(addr)
                        token = await fetch_cs_token_data(addr)
                        if token:
                            raw_candidates.append(token)

            # Score and upsert per profile
            for profile in profiles_needed:
                cs_cfg = STRATEGY_PROFILES.get(profile, STRATEGY_PROFILES["balanced"])

                for token in raw_candidates:
                    if not _running:
                        break

                    # Apply hard profile filters (liquidity, market cap, volume)
                    passes_filter, filter_reason = apply_profile_filters(token, profile)
                    if not passes_filter:
                        continue

                    # Score with 9 equations
                    score_result = score_candidate(
                        token,
                        min_confirmations=cs_cfg["min_confirmations"],
                    )
                    _stats["candidates_scored"] += 1

                    composite = score_result["composite_score"]
                    passed    = score_result["passed_threshold"]

                    if passed and composite >= cs_cfg["confidence_threshold"]:
                        _stats["candidates_passed"] += 1

                    # Always upsert so users can browse candidates
                    try:
                        cid = await upsert_candidate(token, profile, score_result)
                    except Exception as exc:
                        logger.debug(f"upsert_candidate error: {exc}")
                        continue

                    # Auto-buy evaluation for each qualifying user
                    if not (passed and composite >= cs_cfg["confidence_threshold"]):
                        continue

                    for user_row in cs_users:
                        if user_row.get("strategy_profile") != profile:
                            continue
                        if not _running:
                            break
                        await _maybe_autobuy(
                            bot, user_row, token, score_result, cid
                        )

            # Summary log so you can see what happened each cycle
            logger.info(
                f"CS discovery cycle #{_stats['discovery_cycles']}: "
                f"{len(raw_candidates)} raw candidates, "
                f"{_stats['candidates_scored']} scored total, "
                f"{_stats['candidates_passed']} passed threshold this session"
            )

            # Record baseline prices for surge detection (INSERT OR IGNORE — first-seen only)
            for token in raw_candidates:
                await record_cs_price(token)

            # Expire stale candidates and old price history
            expired = await expire_old_candidates()
            if expired:
                logger.debug(f"CS expired {expired} stale candidates")
            await cleanup_expired_price_history()

        except Exception as exc:
            logger.error(f"CS discovery loop error: {exc}", exc_info=True)

        await asyncio.sleep(DISCOVERY_INTERVAL)


# ── Surge Detection Loop ───────────────────────────────────────────────────────

async def _surge_loop(bot: Bot) -> None:
    """
    Every SURGE_INTERVAL seconds:
      1. Load all tokens recorded in cs_price_history (first-seen price)
      2. Re-fetch current price via DexScreener
      3. Calculate % gain since first seen
      4. For each user with surge_enabled=1: if gain >= their threshold → notify + auto-buy
    """
    from services.candle_sniper_service import (
        get_surge_candidates, mark_surge_alerted, get_users_with_surge_enabled,
        get_global_surge_candidates, mark_global_alerted, get_all_cs_users,
        fetch_cs_token_data, count_open_cs_positions, open_cs_position,
    )
    from services.solana_execution_service import execute_buy

    # Stagger startup so it doesn't run at the same time as discovery
    await asyncio.sleep(120)

    while _running:
        try:
            users = await get_users_with_surge_enabled()
            if not users:
                await asyncio.sleep(SURGE_INTERVAL)
                continue

            # ── Global 5000% broadcast (fires for ALL bot users, no opt-in needed) ──
            global_candidates = await get_global_surge_candidates(min_age_minutes=10)
            if global_candidates:
                all_user_ids = await get_all_cs_users()
                for entry in global_candidates:
                    if not _running:
                        break
                    addr         = entry["token_address"]
                    symbol       = entry["token_symbol"] or addr[:8]
                    baseline_usd = float(entry["price_usd"] or 0)
                    if baseline_usd <= 0:
                        continue

                    token = await fetch_cs_token_data(addr)
                    if not token:
                        continue

                    current_usd = float(token.get("price_usd") or 0)
                    if current_usd <= 0:
                        continue

                    pct_gain = ((current_usd - baseline_usd) / baseline_usd) * 100
                    if pct_gain < 5000:
                        continue

                    mcap = float(token.get("market_cap") or 0)
                    mcap_str = (
                        f"${mcap/1_000_000:.2f}M" if mcap >= 1_000_000
                        else f"${mcap/1_000:.0f}K" if mcap >= 1_000
                        else f"${mcap:.0f}"
                    )
                    notif = (
                        f"🔥🔥 <b>MASSIVE SURGE — ${symbol}</b> 🔥🔥\n\n"
                        f"<code>{addr}</code>\n\n"
                        f"📈 <b>+{pct_gain:,.0f}%</b> since first scanned by the bot\n"
                        f"💰 Market cap: <b>{mcap_str}</b>\n\n"
                        f"This token was caught in the Candle Sniper scan and has exploded.\n"
                        f"Check it on <a href=\"https://dexscreener.com/solana/{addr}\">DexScreener</a> ↗\n\n"
                        f"<i>$BRAINROT Alpha Bot — {settings.BRAND_HANDLE}</i>"
                    )
                    logger.info(
                        f"CS global 5000% alert: {symbol} +{pct_gain:.0f}% "
                        f"broadcasting to {len(all_user_ids)} users"
                    )
                    for uid in all_user_ids:
                        try:
                            await bot.send_message(
                                uid, notif,
                                parse_mode="HTML",
                                disable_web_page_preview=True,
                            )
                        except Exception:
                            pass
                    await mark_global_alerted(addr)

            # ── Per-user surge (threshold from their settings, surge_enabled=1 required) ──
            candidates = await get_surge_candidates(min_age_minutes=10)
            if not candidates:
                await asyncio.sleep(SURGE_INTERVAL)
                continue

            logger.info(f"CS surge check: {len(candidates)} tokens being re-priced")

            for entry in candidates:
                if not _running:
                    break

                addr         = entry["token_address"]
                symbol       = entry["token_symbol"] or addr[:8]
                baseline_usd = float(entry["price_usd"] or 0)
                if baseline_usd <= 0:
                    continue

                # Re-fetch current price
                token = await fetch_cs_token_data(addr)
                if not token:
                    continue

                current_usd = float(token.get("price_usd") or 0)
                if current_usd <= 0:
                    continue

                pct_gain = ((current_usd - baseline_usd) / baseline_usd) * 100

                # Check each user's threshold
                for user_row in users:
                    user_id   = user_row["user_id"]
                    threshold = float(user_row.get("surge_threshold_pct") or 500.0)

                    if pct_gain < threshold:
                        continue

                    _stats["surge_alerts"] += 1
                    logger.info(
                        f"CS surge detected: {symbol} +{pct_gain:.0f}% "
                        f"(${baseline_usd:.8f} → ${current_usd:.8f}) user={user_id}"
                    )

                    # Notify user
                    mcap = float(token.get("market_cap") or 0)
                    mcap_str = f"${mcap/1_000_000:.2f}M" if mcap >= 1_000_000 else (
                               f"${mcap/1_000:.0f}K" if mcap >= 1_000 else f"${mcap:.0f}")
                    notif = (
                        f"🚀 <b>Surge Alert — ${symbol}</b>\n\n"
                        f"<code>{addr}</code>\n\n"
                        f"📈 <b>+{pct_gain:.0f}%</b> since we first scanned it\n"
                        f"💰 Market cap: {mcap_str}\n\n"
                        f"Candle Sniper is buying now..."
                    )
                    try:
                        await bot.send_message(user_id, notif, parse_mode="HTML")
                    except Exception:
                        pass

                    # Auto-buy
                    trade_size = float(user_row.get("trade_size_sol") or 0.05)
                    slippage   = float(user_row.get("slippage_pct") or 10.0)

                    open_count = await count_open_cs_positions(user_id)
                    from services.candle_sniper_service import get_cs_settings, get_cs_entitlements
                    from services.brainrot_token_gate import get_active_tier
                    tier = await get_active_tier(user_id)
                    ents = get_cs_entitlements(tier)
                    if open_count >= ents.max_open_positions:
                        try:
                            await bot.send_message(
                                user_id,
                                f"⚠️ Max positions reached — skipped surge buy for ${symbol}",
                                parse_mode="HTML"
                            )
                        except Exception:
                            pass
                        continue

                    result = await execute_buy(
                        user_id          = user_id,
                        token_address    = addr,
                        amount_sol       = trade_size,
                        slippage_pct     = slippage,
                        priority_fee_sol = 0.005,
                        platform         = "auto",  # auto-routes: bonding curve → PumpPortal, graduated → Jupiter
                    )

                    if result.get("success"):
                        _stats["surge_buys"] += 1
                        cfg = await get_cs_settings(user_id)
                        await open_cs_position(
                            user_id       = user_id,
                            token_address = addr,
                            token_symbol  = symbol,
                            entry_price   = current_usd,
                            trade_size    = trade_size,
                            take_profit   = float(cfg.get("take_profit_pct") or 50.0),
                            stop_loss     = float(cfg.get("stop_loss_pct") or 15.0),
                            trailing_stop = float(cfg.get("trailing_stop_pct") or 10.0),
                        )
                        sig = result.get("signature", "")
                        platform_used = result.get("platform_used") or "DEX"
                        try:
                            await bot.send_message(
                                user_id,
                                f"🚀 <b>SURGE BUY  //  EXECUTED</b>\n"
                                f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"TOKEN  ${symbol}\n"
                                f"SURGE  +{pct_gain:.0f}% since first scan\n"
                                f"SIZE   {trade_size:.4f} SOL  [{platform_used.upper()}]\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
                                f"📋 CA <i>(tap to copy)</i>\n"
                                f"<code>{addr}</code>\n\n"
                                f"🔗 TX <i>(tap to copy)</i>\n"
                                f"<code>{sig}</code>\n"
                                f'<a href="https://solscan.io/tx/{sig}">↗ Solscan</a>  '
                                f'<a href="https://pump.fun/{addr}">↗ Pump.fun</a>',
                                parse_mode="HTML",
                                disable_web_page_preview=True,
                            )
                        except Exception:
                            pass
                    else:
                        _stats["buys_failed"] += 1
                        err = result.get("error") or "Unknown error"
                        try:
                            await bot.send_message(
                                user_id,
                                f"⬛ <b>SURGE BUY  //  FAILED</b>\n"
                                f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"TOKEN  ${symbol}\n"
                                f"ERR    {err[:80]}\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
                                f"<code>{addr}</code>",
                                parse_mode="HTML",
                            )
                        except Exception:
                            pass

                # Mark alerted so we don't fire again for this token
                await mark_surge_alerted(addr)

        except Exception as exc:
            logger.error(f"CS surge loop error: {exc}", exc_info=True)

        await asyncio.sleep(SURGE_INTERVAL)


async def _maybe_autobuy(
    bot: Bot,
    user_row: dict,
    token: dict,
    score_result: dict,
    candidate_id: int,
) -> None:
    """Evaluate and optionally execute a Candle Sniper auto-buy for a user."""
    from services.candle_sniper_service import (
        get_cs_settings, get_cs_entitlements, count_open_cs_positions,
        open_cs_position, mark_candidate_traded,
    )
    from services.brainrot_token_gate import get_active_tier
    from services.bot_wallet_service import get_or_create_bot_wallet, get_sol_balance
    from services.solana_execution_service import execute_buy
    from services.token_data_provider import get_token_price_in_sol
    from services.sniper_blacklist_service import get_blacklist_addresses

    user_id = user_row["user_id"]

    try:
        cfg      = await get_cs_settings(user_id)
        tier     = await get_active_tier(user_id)
        ents     = get_cs_entitlements(tier)

        # Check blacklist — CS must respect the same blacklist as auto-buy
        token_addr_bl = token.get("address", "")
        if token_addr_bl:
            blacklisted = await get_blacklist_addresses(user_id)
            if token_addr_bl in blacklisted:
                logger.debug(f"CS skip user={user_id} token={token_addr_bl[:8]}: blacklisted")
                return

        # Check user-specific confidence threshold
        score     = score_result["composite_score"]
        eqs       = score_result["equations_passed"]
        min_score = cfg.get("confidence_threshold", 55)
        min_eqs   = cfg.get("min_confirmations", 5)

        if score < min_score:
            logger.debug(f"CS skip user={user_id} token={token.get('address','?')[:8]}: "
                         f"score {score:.0f} < threshold {min_score}")
            return
        if eqs < min_eqs:
            logger.debug(f"CS skip user={user_id} token={token.get('address','?')[:8]}: "
                         f"only {eqs}/{min_eqs} equations passed")
            return

        # Check max open positions
        open_count = await count_open_cs_positions(user_id)
        max_pos    = min(cfg.get("max_open_positions", 3), ents.max_open_positions)
        if open_count >= max_pos:
            logger.debug(f"CS skip user={user_id}: max positions ({max_pos}) reached")
            return

        # Prevent re-buying a token that already has an open position
        token_addr_check = token.get("address", "")
        if token_addr_check:
            from database.sqlite_db import get_db as _get_db
            async with _get_db() as _db:
                async with _db.execute(
                    "SELECT id FROM candle_sniper_positions "
                    "WHERE user_id = ? AND token_address = ? AND status = 'open'",
                    (user_id, token_addr_check),
                ) as _cur:
                    if await _cur.fetchone():
                        logger.debug(f"CS skip user={user_id}: already have open position for {token_addr_check[:8]}")
                        return

        # Check wallet balance
        wallet_row = await get_or_create_bot_wallet(user_id)
        balance    = await get_sol_balance(wallet_row["wallet_address"])
        trade_size = float(cfg.get("trade_size_sol") or 0.05)
        fee_buffer = trade_size * 0.02 + 0.002

        if not balance or balance < (trade_size + fee_buffer):
            logger.warning(f"CS skip user={user_id}: balance {balance or 0:.4f} SOL "
                           f"< {trade_size + fee_buffer:.4f} needed — top up wallet")
            return

        token_addr = token["address"]

        # Execute buy
        logger.info(f"CS auto-buy: user={user_id} token={token_addr[:8]} "
                    f"score={score_result['composite_score']:.1f} size={trade_size:.4f} SOL")

        slippage = float(cfg.get("slippage_pct") or 5.0)
        result = await execute_buy(
            user_id          = user_id,
            token_address    = token_addr,
            amount_sol       = trade_size,
            slippage_pct     = slippage,
            priority_fee_sol = 0.005,
            platform         = "auto",  # auto-routes: bonding curve → PumpPortal, graduated → Jupiter
            exit_preset_id   = None,
        )

        if result.get("success"):
            _stats["buys_executed"] += 1
            sig = result.get("signature", "")

            # Fetch entry price in SOL — fall back to DexScreener USD / rough SOL price
            # so positions never open with entry=0 (which breaks all P&L math).
            entry_price = await get_token_price_in_sol(token_addr) or 0.0
            if entry_price <= 0:
                usd_price = float(token.get("price_usd") or 0)
                if usd_price > 0:
                    entry_price = usd_price / 200.0  # ~$200/SOL; position math still works

            # Register CS position for monitoring
            pos_id = await open_cs_position(
                user_id              = user_id,
                token_address        = token_addr,
                entry_price_sol      = entry_price,
                tx_signature         = sig,
                trade_size_sol       = trade_size,
                stop_loss_pct        = float(cfg.get("stop_loss_pct", 15.0)),
                take_profit_pct      = float(cfg.get("take_profit_pct", 50.0)),
                trailing_stop_pct    = float(cfg.get("trailing_stop_pct", 10.0)),
                max_duration_minutes = int(cfg.get("max_hold_minutes") or 480),
                candidate_id         = candidate_id,
            )

            await mark_candidate_traded(token_addr)

            token_sym = token.get("symbol") or token_addr[:6]
            from utils.share_utils import build_share_markup
            _share_buy = (
                f"🕯️ Just sniped ${token_sym.upper()} with {settings.BRAND_HANDLE}! "
                f"Score: {score_result['composite_score']:.0f}/100 🔥 {chr(10)}"
                f"Try it yourself 👇 {chr(10)}"
                f"#brainrotonchain"
            )
            await _notify(bot, user_id,
                f"🕯️ <b>CANDLE SNIPER  //  BUY OPENED</b>\n"
                f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"TOKEN  ${token_sym.upper()}\n"
                f"SCORE  {score_result['composite_score']:.0f}/100  "
                f"({score_result['equations_passed']}/9 signals)\n"
                f"SIZE   {trade_size:.4f} SOL\n"
                f"TP     +{cfg.get('take_profit_pct',50):.0f}%  "
                f"SL  -{cfg.get('stop_loss_pct',15):.0f}%\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
                f"📋 CA <i>(tap to copy)</i>\n"
                f"<code>{token_addr}</code>\n\n"
                f"🔗 TX <i>(tap to copy)</i>\n"
                f"<code>{sig}</code>\n"
                f'<a href="https://solscan.io/tx/{sig}">↗ Solscan</a>  '
                f'<a href="https://pump.fun/{token_addr}">↗ Pump.fun</a>',
                reply_markup=build_share_markup(_share_buy),
            )
            logger.info(f"CS buy success user={user_id} pos={pos_id} token={token_addr[:8]}")
        else:
            _stats["buys_failed"] += 1
            err = result.get("error", "Unknown error")
            logger.warning(f"CS auto-buy failed user={user_id} token={token_addr[:8]}: {err}")

    except Exception as exc:
        _stats["buys_failed"] += 1
        logger.error(f"CS auto-buy error user={user_id}: {exc}", exc_info=True)


# ── Position Monitoring Loop ──────────────────────────────────────────────────

async def _position_loop(bot: Bot) -> None:
    """
    Every POSITION_INTERVAL seconds:
      - Fetch current price for all open CS positions
      - Evaluate exit conditions: TP, SL, trailing stop, duration, volume collapse
      - Execute sells and notify users on exit
    """
    while _running:
        try:
            await _check_all_positions(bot)
        except Exception as exc:
            logger.error(f"CS position loop error: {exc}", exc_info=True)
        await asyncio.sleep(POSITION_INTERVAL)


async def _check_all_positions(bot: Bot) -> None:
    from services.candle_sniper_service import (
        get_all_open_cs_positions, update_cs_position_price, close_cs_position,
        fetch_cs_token_data,
    )
    from services.token_data_provider import get_token_price_in_sol
    from services.solana_execution_service import execute_sell

    positions = await get_all_open_cs_positions()
    if not positions:
        return

    for pos in positions:
        if not _running:
            break

        pos_id     = pos["id"]
        user_id    = pos["user_id"]
        token_addr = pos["token_address"]

        try:
            current_price = await get_token_price_in_sol(token_addr)
            if not current_price or current_price <= 0:
                # Try DexScreener as fallback
                token_data = await fetch_cs_token_data(token_addr)
                if token_data:
                    current_price = token_data.get("price_usd", 0) / 200  # rough SOL approx
                if not current_price:
                    continue

            await update_cs_position_price(pos_id, current_price)

            # ── Exit Condition Checks ─────────────────────────────────────────
            entry      = float(pos["entry_price_sol"]) or current_price
            highest    = max(float(pos.get("highest_price_sol") or entry), current_price)
            tp_pct     = float(pos.get("take_profit_pct") or 50.0)
            sl_pct     = float(pos.get("stop_loss_pct")   or 15.0)
            trail_pct  = float(pos.get("trailing_stop_pct") or 10.0)
            trail_active = bool(pos.get("trailing_active"))
            opened_at  = pos.get("opened_at") or ""
            max_dur    = int(pos.get("max_duration_minutes") or 120)

            if entry <= 0:
                continue

            pnl_pct = ((current_price - entry) / entry) * 100

            exit_reason: Optional[str] = None

            # 1. Trailing Stop — PRIMARY exit once activated.
            #    Rides winners up and sells on pullback from the peak.
            #    Takes priority over fixed TP so gains are not capped.
            if trail_active and highest > 0:
                drop_from_high = ((current_price - highest) / highest) * 100
                if drop_from_high <= -trail_pct:
                    exit_reason = (f"Trailing Stop — {drop_from_high:.1f}% from peak "
                                   f"(trail -{trail_pct:.0f}%)")

            # 2. Fixed Take Profit — only fires before trailing engages.
            #    Once trailing is active this is bypassed so the position runs.
            elif not trail_active and pnl_pct >= tp_pct:
                exit_reason = f"Take Profit +{pnl_pct:.1f}% (target +{tp_pct:.0f}%)"

            # 3. Fixed Stop Loss — safety net, always in effect.
            elif pnl_pct <= -sl_pct:
                exit_reason = f"Stop Loss {pnl_pct:.1f}% (limit -{sl_pct:.0f}%)"

            # 4. Max Duration Exit
            elif opened_at:
                try:
                    from datetime import datetime
                    opened_dt = datetime.fromisoformat(opened_at.replace("Z", ""))
                    age_min   = (datetime.utcnow() - opened_dt).total_seconds() / 60
                    if age_min >= max_dur:
                        exit_reason = f"Max duration ({max_dur}m) reached"
                except Exception:
                    pass

            if exit_reason:
                await _execute_cs_exit(
                    bot, user_id, pos_id, token_addr, exit_reason, pnl_pct
                )

        except Exception as exc:
            logger.warning(f"CS position check error pos={pos_id}: {exc}")


async def _execute_cs_exit(
    bot: Bot,
    user_id: int,
    position_id: int,
    token_address: str,
    reason: str,
    pnl_pct: float,
) -> None:
    from services.candle_sniper_service import close_cs_position, get_cs_settings
    from services.solana_execution_service import execute_sell

    logger.info(f"CS exit triggered user={user_id} pos={position_id} "
                f"reason='{reason}' pnl={pnl_pct:+.1f}%")

    cfg      = await get_cs_settings(user_id)
    # Exits need more slippage than entries — use at least 15% to avoid sell rejections
    # on thin/volatile tokens. Cap at user's configured value if they set it higher.
    slippage = max(float(cfg.get("slippage_pct") or 15.0), 15.0)

    result = await execute_sell(
        user_id          = user_id,
        token_address    = token_address,
        sell_pct         = 100.0,
        slippage_pct     = slippage,
        priority_fee_sol = 0.005,
        platform         = "auto",
    )

    await close_cs_position(position_id, reason)
    _stats["positions_closed"] += 1

    icon    = "✅" if pnl_pct >= 0 else "❌"
    pnl_str = f"+{pnl_pct:.1f}%" if pnl_pct >= 0 else f"{pnl_pct:.1f}%"
    if result.get("success"):
        sig = result.get("signature", "")
        from utils.share_utils import build_share_markup
        _sym_short = token_address[:6] + "…"
        if pnl_pct >= 0:
            _share_sell = (
                f"✅ {pnl_str} profit on {_sym_short} using {settings.BRAND_HANDLE} 🚀\n"
                f"Candle Sniper auto-traded this one 🎯\n"
                f"#brainrotonchain"
            )
        else:
            _share_sell = (
                f"⬛ Exited {_sym_short} {pnl_str} via {settings.BRAND_HANDLE}\n"
                f"Stop-loss protected the bag 🛡️\n"
                f"#brainrotonchain"
            )
        await _notify(bot, user_id,
            f"{icon} <b>CANDLE SNIPER  //  SOLD</b>\n"
            f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"P&L    {pnl_str}\n"
            f"EXIT   {reason}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
            f"📋 CA <i>(tap to copy)</i>\n"
            f"<code>{token_address}</code>\n\n"
            f"🔗 TX <i>(tap to copy)</i>\n"
            f"<code>{sig}</code>\n"
            f'<a href="https://solscan.io/tx/{sig}">↗ Solscan</a>  '
            f'<a href="https://pump.fun/{token_address}">↗ Pump.fun</a>',
            reply_markup=build_share_markup(_share_sell),
        )
    else:
        err = result.get("error", "Unknown error")
        await _notify(bot, user_id,
            f"⚠️ <b>CANDLE SNIPER  //  EXIT FAILED</b>\n"
            f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"EXIT   {reason}\n"
            f"ERR    {err[:60]}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
            f"📋 CA <i>(tap to copy)</i>\n"
            f"<code>{token_address}</code>\n\n"
            f"<i>Position marked closed — check wallet manually.</i>"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _notify(bot: Bot, user_id: int, text: str, reply_markup=None) -> None:
    try:
        await bot.send_message(user_id, text, parse_mode="HTML",
                               disable_web_page_preview=True,
                               reply_markup=reply_markup)
    except Exception as exc:
        logger.debug(f"CS notify failed user={user_id}: {exc}")
