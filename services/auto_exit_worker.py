"""
services/auto_exit_worker.py
==============================
Supreme Black Auto-Exit price watcher background loop.

Design:
  - Polls every POLL_INTERVAL seconds.
  - Fetches prices for all 'watching'/'partial' positions concurrently.
  - Skips positions whose user has auto-exit disabled.
  - Evaluates triggers in deterministic order via auto_exit_service.evaluate_and_fire().
  - Gracefully skips broken positions; never crashes the loop.
  - Restart-safe: all state lives in the database.
"""

import asyncio
import logging

from aiogram import Bot
from utils.config import settings

logger = logging.getLogger(__name__)

POLL_INTERVAL   = 8    # seconds between full scan cycles
MAX_PRICE_RETRIES = 2  # retries per token on price fetch failure

_running = False


def stop() -> None:
    global _running
    _running = False


async def _backfill_position_state() -> None:
    """
    Startup sync: register any open tracked_positions that are missing from
    position_state. Covers cases where _confirm_and_log failed silently or
    positions existed before the auto-exit system was introduced.
    """
    from database.sqlite_db import get_db
    from services.auto_exit_service import register_position, get_auto_exit_settings

    async with get_db() as db:
        async with db.execute("""
            SELECT tp.id, tp.user_id, tp.token_address, tp.buy_price_sol, tp.opened_at
            FROM tracked_positions tp
            LEFT JOIN position_state ps ON ps.position_id = tp.id
            WHERE tp.status = 'open' AND ps.id IS NULL
        """) as cur:
            missing = await cur.fetchall()

    if not missing:
        return

    logger.info(f"Auto-exit backfill: registering {len(missing)} untracked open position(s)")
    for row in missing:
        try:
            ae_s      = await get_auto_exit_settings(row["user_id"])
            preset_id = ae_s.get("selected_preset_id")
            await register_position(
                position_id     = row["id"],
                user_id         = row["user_id"],
                token_address   = row["token_address"],
                entry_price_sol = float(row["buy_price_sol"] or 0),
                preset_id       = preset_id,
                opened_at       = row["opened_at"],
            )
            logger.info(f"Backfilled position_state for pos_id={row['id']} user={row['user_id']}")
        except Exception as e:
            logger.warning(f"Backfill failed for pos_id={row['id']}: {e}")


async def _cleanup_zombie_positions() -> None:
    """
    Close positions that have NEVER had a price fetched AND are older than
    MAX_HOLD minutes past their opened_at time.  These are tokens that were
    bought when the price API was broken and have zero entry/current price.
    They cannot be evaluated by the trigger engine and would clog the watcher
    indefinitely — close them so the worker can focus on live positions.
    """
    from database.sqlite_db import get_db
    ZOMBIE_GRACE_MINUTES = 30   # Close if price still 0 after 30 min

    async with get_db() as db:
        async with db.execute("""
            SELECT position_id FROM position_state
            WHERE status IN ('watching', 'partial')
              AND entry_price_sol  <= 0
              AND current_price_sol <= 0
              AND last_checked_at IS NULL
              AND opened_at <= datetime('now', ? || ' minutes')
        """, (f"-{ZOMBIE_GRACE_MINUTES}",)) as cur:
            rows = await cur.fetchall()

    if not rows:
        return

    ids = [r[0] for r in rows]
    logger.warning(
        f"Closing {len(ids)} zombie positions (0-price, >{ZOMBIE_GRACE_MINUTES}m old). "
        "These tokens had no market data at buy time."
    )
    chunk = 200
    for i in range(0, len(ids), chunk):
        batch = ids[i:i+chunk]
        placeholders = ",".join("?" * len(batch))
        async with get_db() as db:
            await db.execute(
                f"UPDATE position_state SET status='closed', updated_at=CURRENT_TIMESTAMP "
                f"WHERE position_id IN ({placeholders})", batch
            )
            await db.execute(
                f"UPDATE tracked_positions SET status='closed', closed_at=CURRENT_TIMESTAMP "
                f"WHERE id IN ({placeholders}) AND status='open'", batch
            )
            await db.commit()


async def _fetch_prices_batch(tokens: list[str]) -> dict[str, float | None]:
    """
    Fetch prices for many tokens using DexScreener batch API (30 per request).
    Returns a dict {token_address: price_in_sol | None}.
    Uses a semaphore so at most 5 batch requests are in-flight at once.
    """
    import aiohttp
    BATCH_SIZE = 30
    results: dict[str, float | None] = {t: None for t in tokens}
    best_liq: dict[str, float] = {}
    sem = asyncio.Semaphore(5)

    async def _one_batch(batch: list[str]) -> None:
        async with sem:
            try:
                url = f"https://api.dexscreener.com/latest/dex/tokens/{','.join(batch)}"
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as s:
                    async with s.get(url) as r:
                        if r.status != 200:
                            return
                        data = await r.json()
                for pair in (data.get("pairs") or []):
                    if pair.get("chainId") != "solana":
                        continue
                    addr = (pair.get("baseToken") or {}).get("address", "")
                    if addr not in results:
                        continue
                    native = pair.get("priceNative")
                    if not native:
                        continue
                    liq = float((pair.get("liquidity") or {}).get("usd") or 0)
                    if results[addr] is None or liq > best_liq.get(addr, 0):
                        results[addr] = float(native)
                        best_liq[addr] = liq
            except Exception as e:
                logger.warning(f"DexScreener batch price error: {e}")

    batches = [tokens[i:i+BATCH_SIZE] for i in range(0, len(tokens), BATCH_SIZE)]
    await asyncio.gather(*[_one_batch(b) for b in batches])
    return results


async def _purge_old_records() -> None:
    """
    Daily maintenance — removes stale rows that build up memory and slow scans.
    Runs automatically every ~24h via the scan counter in start().
    """
    from database.sqlite_db import get_db
    async with get_db() as db:
        # Failed sell attempts older than 48h — no debugging value after 2 days
        r = await db.execute(
            "DELETE FROM sell_executions WHERE status='failed' AND created_at < datetime('now','-48 hours')"
        )
        deleted_sells = r.rowcount

        # Queued buy jobs that never executed after 6h — stale, bot was restarted
        r = await db.execute(
            "DELETE FROM auto_buy_jobs WHERE status='queued' AND created_at < datetime('now','-6 hours')"
        )
        deleted_jobs = r.rowcount

        # Closed position_state rows older than 14 days — history lives in tracked_positions
        r = await db.execute(
            "DELETE FROM position_state WHERE status='closed' AND last_checked_at < datetime('now','-14 days')"
        )
        deleted_ps = r.rowcount

        # Discovery runs older than 7 days
        r = await db.execute(
            "DELETE FROM discovery_runs WHERE started_at < datetime('now','-7 days')"
        )
        deleted_dr = r.rowcount

        await db.commit()

    logger.info(
        f"[DB purge] sell_executions={deleted_sells} auto_buy_jobs={deleted_jobs} "
        f"position_state={deleted_ps} discovery_runs={deleted_dr}"
    )


async def start(bot: Bot) -> None:
    global _running
    _running = True
    logger.info("Auto-exit watcher started.")
    from services.auto_exit_service import clear_stale_pending_sells
    # Clear stale 'pending' AND 'sent' records from previous crashes/restarts.
    await clear_stale_pending_sells(max_age_minutes=5)
    # NOTE: zombie cleanup intentionally removed — it was closing DB records without
    # executing sells, leaving tokens stranded in the wallet with no watcher.
    # The batch price fetcher handles 1000+ tokens fine (~38 requests at 30/batch).
    # Blind sell logic in evaluate_and_fire handles 0-price tokens past max_hold.
    # Backfill any open positions missing from position_state
    await _backfill_position_state()
    _scan_count = 0
    while _running:
        try:
            await _scan(bot)
            _scan_count += 1
            # Re-run backfill every ~5 minutes (37 cycles × 8s ≈ 296s)
            if _scan_count % 37 == 0:
                await _backfill_position_state()
            # DB purge once every ~24 hours (10800 cycles × 8s ≈ 86400s)
            if _scan_count % 10800 == 0:
                await _purge_old_records()
        except Exception as e:
            logger.error(f"Auto-exit watcher top-level error: {e}", exc_info=True)
        await asyncio.sleep(POLL_INTERVAL)
    logger.info("Auto-exit watcher stopped.")


async def _scan(bot: Bot) -> None:
    from services.auto_exit_service import (
        get_active_position_states,
        get_auto_exit_settings,
        get_preset,
        update_position_price,
    )
    positions = await get_active_position_states()
    if not positions:
        return

    logger.debug(f"Auto-exit watcher: {len(positions)} active positions")

    # Group positions by token to avoid duplicate price fetches
    token_to_positions: dict[str, list[dict]] = {}
    for ps in positions:
        token_to_positions.setdefault(ps["token_address"], []).append(ps)

    # Fetch prices using DexScreener batch API (30 tokens per request)
    # This avoids the 1-request-per-token pattern that causes rate limiting.
    unique_tokens = list(token_to_positions.keys())
    prices = await _fetch_prices_batch(unique_tokens)
    priced_count = sum(1 for v in prices.values() if v)
    logger.debug(f"Price batch: {priced_count}/{len(unique_tokens)} tokens priced")

    # Sort: positions with a live price (real value) first, zero-price last.
    # This ensures high-value positions are evaluated and sold before dust.
    positions = sorted(
        positions,
        key=lambda p: prices.get(p["token_address"]) or 0.0,
        reverse=True,
    )

    # Evaluate each position
    for ps in positions:
        token     = ps["token_address"]
        pos_id    = ps["position_id"]
        user_id   = ps["user_id"]
        current   = prices.get(token)

        try:
            # Update stored price only when we have valid data
            if current and current > 0:
                await update_position_price(pos_id, current)

            # Load user's auto-exit settings
            ae_settings = await get_auto_exit_settings(user_id)

            # If auto-exit is explicitly paused by the user, skip this position.
            # Auto-enable in two situations:
            #   1. updated_at is NULL → row was just created, user never touched settings
            #   2. selected_preset_id is set → user applied a preset (they intend auto-exit ON)
            # Only truly skip if user explicitly disabled it AND has NOT applied a preset.
            if not ae_settings.get("enabled"):
                never_configured  = not ae_settings.get("updated_at")
                has_preset        = bool(ae_settings.get("selected_preset_id"))
                should_auto_enable = never_configured or has_preset
                if not should_auto_enable:
                    logger.debug(f"[{pos_id}] Auto-exit disabled for user={user_id} — skipping")
                    continue
                # Auto-enable: user either has no prior config or chose a preset
                from services.auto_exit_service import update_auto_exit_field as _uaef
                await _uaef(user_id, "enabled", 1)
                ae_settings["enabled"] = 1
                reason = "has preset configured" if has_preset else "first active position"
                logger.info(f"Auto-exit auto-enabled for user={user_id} ({reason})")

            # Load preset — fall back to first system preset if user hasn't chosen one
            preset_id = ps.get("preset_id") or ae_settings.get("selected_preset_id")
            if not preset_id:
                from services.auto_exit_service import get_system_presets
                sys_presets = await get_system_presets()
                if not sys_presets:
                    logger.warning(f"[{pos_id}] No system presets seeded — cannot evaluate position")
                    continue
                preset = sys_presets[0]   # default: ⚡ Quick Flip
                logger.info(
                    f"[{pos_id}] No exit preset set for user={user_id} — "
                    f"using default '{preset['name']}'"
                )
            else:
                preset = await get_preset(int(preset_id))
                if not preset:
                    continue

            # Re-read fresh position state (price was just updated)
            from services.auto_exit_service import get_active_position_states as _gps
            fresh_states = await _gps()
            fresh_ps = next((p for p in fresh_states if p["position_id"] == pos_id), None)
            if not fresh_ps:
                continue  # position was closed by a concurrent cycle

            from services.auto_exit_service import evaluate_and_fire
            await evaluate_and_fire(fresh_ps, preset, ae_settings, bot)

        except Exception as e:
            logger.warning(f"Auto-exit evaluate error pos={pos_id}: {e}", exc_info=True)
            # Never let one broken position crash the whole scan
