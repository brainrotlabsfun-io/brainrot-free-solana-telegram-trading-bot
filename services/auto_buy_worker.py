"""
services/auto_buy_worker.py
=============================
Background worker that monitors the PumpPortal WebSocket feed and fires
automatic buys for users who have auto-buy enabled.

Key design decisions:
  - PumpPortal feed items use key "address" (not "mint") — we normalise this.
  - Brand-new pump.fun tokens are NOT on DexScreener yet (they're seconds old).
    For aggressive presets (score_threshold ≤ 20) we buy directly from the
    WebSocket event data without waiting for DexScreener.
  - For stricter presets we attempt a DexScreener lookup; if it fails we skip.
  - Loop cadence: POLL_INTERVAL seconds.
"""

import asyncio
import logging
import re
import time
from collections import defaultdict

from aiogram import Bot
from utils.config import settings

logger = logging.getLogger(__name__)

POLL_INTERVAL             = 6    # seconds between PumpPortal feed scans
ACTIVE_SCAN_INTERVAL      = 20   # seconds between active-token scans
DEXSCREENER_MIN_THRESHOLD = 35   # below this score we skip DexScreener and buy raw

# Smart project filter — tokens 30+ days old, $120k+ mcap, +5%+ 24h change
SMART_MIN_AGE_DAYS   = 30
SMART_MIN_MCAP       = 120_000
SMART_MIN_CHANGE_H24 = 5.0      # must be up at least 5% in last 24h
_CIRCUIT_BREAKER_LIMIT    = 10   # consecutive scan errors before pausing
_CIRCUIT_BREAKER_PAUSE    = 60   # seconds to pause when circuit breaker trips
_consecutive_errors       = 0    # reset on each successful scan
LOW_BALANCE_NOTIFY_COOLDOWN = 1800  # seconds between low-balance alerts per user (30 min)
_running                  = False
_seen: set[str]           = set()
_low_balance_last_notified: dict[int, float] = {}  # user_id → timestamp
_user_last_buy: dict[int, float] = {}              # user_id → timestamp of their last buy (per-user cooldown)
# DexScreener active-token scanner: tracks last evaluation time per address
_dex_seen: dict[str, float] = {}  # addr → timestamp of last evaluation
_DEX_TTL = 120  # re-evaluate same address at most once every 2 minutes

# ── Execution failure cooldown ─────────────────────────────────────────────────
# Tokens that failed execution are blocked for _EXEC_FAIL_TTL seconds.
# Prevents the scan loop retrying the same dead token 50+ times burning fees.
_exec_failed: dict[str, float] = {}   # addr → timestamp of last execution failure
_EXEC_FAIL_TTL = 1800  # 30 minutes — don't retry a token that failed execution

# ── Staged-mint watchlist ──────────────────────────────────────────────────────
# New mints from PumpPortal are staged here and NOT bought immediately.
# They are only evaluated after _STAGE_MIN_SEC seconds — if they got real volume
# by then, the scan loop will find them and fire a buy.
_staged_mints: dict[str, dict] = {}   # addr → {raw: dict, staged_at: float}
_STAGE_MIN_SEC = 600    # 10 minutes — minimum age before evaluating a staged mint
_STAGE_MAX_SEC = 7200   # 2 hours  — drop staged mints that never got volume
# ── Live scan statistics (reset on worker start) ───────────────────────────────
_stats: dict = {
    "scans_completed":          0,
    "tokens_evaluated":         0,
    "name_dupes_blocked":       0,
    "creator_dupes_blocked":    0,
    "creator_bl_blocked":       0,   # creator blacklist hits
    "token_bl_blocked":         0,   # token address blacklist hits
    "low_score_blocked":        0,
    "low_balance_blocked":      0,
    "buys_executed":            0,
    "buys_failed":              0,
    "last_scan_ts":             0.0,
    "last_buy_ts":              0.0,
    "last_token_seen":          "",
    "last_buy_symbol":          "",
}


def get_stats() -> dict:
    """Return a snapshot of the current session scan statistics."""
    return dict(_stats)


# Duplicate-name protection: normalized name → (first token address, creator address)
# Only blocks tokens that share BOTH the same name AND the same creator wallet.
_bought_name_fingerprints: dict[str, tuple[str, str]] = {}

# Creator tracking: creator_address → list of (token_addr, name, timestamp)
# Used to detect serial deployers (same creator, many tokens, similar names)
_creator_launches: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
_creator_logged: set[str] = set()   # suppress repeat log spam per creator
_creator_bought: set[str] = set()   # creators we've already successfully bought from
_CREATOR_WINDOW_SECS = 3600   # 1-hour rolling window
_CREATOR_DUPE_LIMIT  = 5      # block repeat tokens AFTER first buy from this creator


def _norm_name(name: str) -> str:
    """Normalize a token name to a fingerprint for duplicate detection.
    Strips spaces, special chars, and common copy-paste suffixes."""
    s = name.lower()
    s = re.sub(r'[^a-z0-9]', '', s)
    # Strip trailing noise that copycat projects append
    for suffix in ('2', '3', '4', '5', 'v2', 'v3', 'ii', 'iii', 'x',
                   'classic', 'real', 'official', 'og', 'reborn', 'new', 'pro'):
        if s.endswith(suffix) and len(s) > len(suffix) + 2:
            s = s[:-len(suffix)]
    return s





def get_duplicate_creators(min_launches: int = 2) -> list[dict]:
    """Return creators who launched multiple tokens in the tracking window."""
    now = time.time()
    results = []
    for creator, launches in _creator_launches.items():
        recent = [(a, n, t) for a, n, t in launches if now - t < _CREATOR_WINDOW_SECS]
        if len(recent) >= min_launches:
            results.append({
                "creator":   creator,
                "count":     len(recent),
                "tokens":    [(a, n) for a, n, _ in recent],
                "names":     list({n for _, n, _ in recent}),
            })
    return sorted(results, key=lambda x: x["count"], reverse=True)


def stop() -> None:
    global _running
    _running = False


def reset_seen() -> None:
    """Clear seen + staged buffers so the next scan re-evaluates all tokens.
    Called whenever auto-buy settings change significantly (e.g. preset applied)."""
    global _seen, _staged_mints, _dex_seen
    _seen         = set()
    _staged_mints = {}
    _dex_seen     = {}
    logger.info("Auto-buy worker: scan buffers cleared (settings change).")


async def start(bot: Bot) -> None:
    global _running, _seen, _dex_seen, _staged_mints, _stats, _consecutive_errors, _user_last_buy
    _running            = True
    _seen               = set()
    _dex_seen           = {}
    _staged_mints       = {}
    _user_last_buy      = {}
    _consecutive_errors = 0
    for k in _stats:
        _stats[k] = 0.0 if k.endswith("_ts") else (0 if isinstance(_stats[k], int) else "")
    logger.info("Auto-buy worker started — mint watcher + volume-surge scanner.")

    # Two tasks with one clear purpose each:
    #  1. mint_watcher: reads PumpPortal, stages new mints — NEVER buys
    #  2. mover_scan:   every 20s checks staged mints (10min+ old) + trending tokens for volume surges
    mint_task = asyncio.create_task(_mint_watcher_loop(bot))
    scan_task = asyncio.create_task(_mover_scan_loop(bot))

    try:
        await asyncio.gather(mint_task, scan_task)
    except asyncio.CancelledError:
        pass
    finally:
        _running = False
        logger.info("Auto-buy worker stopped.")


async def _mint_watcher_loop(bot: Bot) -> None:
    """
    Reads PumpPortal WebSocket feed and STAGES new mints — does NOT buy.
    Mints are held in _staged_mints until they are 10+ minutes old.
    The mover_scan_loop then checks if they got real volume and fires buys.
    """
    global _consecutive_errors
    while _running:
        try:
            await _watch_new_mints()
            _consecutive_errors = 0
        except Exception as e:
            _consecutive_errors += 1
            logger.error(f"Mint watcher error ({_consecutive_errors}): {e}", exc_info=True)
            if _consecutive_errors >= _CIRCUIT_BREAKER_LIMIT:
                _consecutive_errors = 0
                await asyncio.sleep(_CIRCUIT_BREAKER_PAUSE)
                continue
        await asyncio.sleep(POLL_INTERVAL)


async def _watch_new_mints() -> None:
    """Stage new PumpPortal mints for later volume-surge evaluation. No buying here."""
    from services.pumpportal_ws_service import pump_service
    raw_feed = pump_service.get_recent(limit=50)
    now = time.time()
    count = 0
    for t in raw_feed:
        addr = t.get("address") or t.get("mint") or ""
        if addr and addr not in _seen:
            _seen.add(addr)
            item = dict(t)
            item["address"] = addr
            _staged_mints[addr] = {"raw": item, "staged_at": now}
            count += 1
    if len(_seen) > 10_000:
        _seen.clear()
    _stats["scans_completed"] += 1
    _stats["last_scan_ts"]     = now
    if count:
        logger.debug(f"Staged {count} new mints — watching for volume surge in 10min+")


async def _mover_scan_loop(bot: Bot) -> None:
    """
    Every ACTIVE_SCAN_INTERVAL seconds:
      1. Check staged mints that are now 10+ min old — did they get real volume?
      2. Scan pump.fun trending + DexScreener for established tokens surging now.
    This is the ONLY place buys are triggered.
    """
    await asyncio.sleep(5)  # brief stagger so PumpPortal connects first
    while _running:
        try:
            await _scan_movers(bot)
        except Exception as e:
            logger.warning(f"Mover scan error: {e}")
        await asyncio.sleep(ACTIVE_SCAN_INTERVAL)


async def _scan_movers(bot: Bot) -> None:
    """
    The unified buy-trigger loop. Two token pools combined:

    Pool A — Staged mints (10+ min old):
      Tokens we saw mint via PumpPortal. We waited. Now we check if they got
      real volume/surge. If yes → buy. If still dead after 2h → drop.

    Pool B — Trending/mover tokens (pump.fun top market cap + DexScreener search):
      Established tokens already trading with volume. Catches tokens that are
      days/weeks old and spiking right now.

    Both pools feed through the same score + gate logic.
    """
    import aiohttp
    from services.token_data_provider import get_token_summary

    now   = time.time()
    addrs: list[str] = []

    # Addresses flagged as "smart projects" (30+ days, $120k+ mcap, +5% 24h)
    smart_addrs: set[str] = set()

    # ── Pool A: Staged mints ready for volume check ────────────────────────────
    expired_staged = []
    for addr, stage_data in list(_staged_mints.items()):
        age_sec = now - stage_data["staged_at"]
        if age_sec > _STAGE_MAX_SEC:
            expired_staged.append(addr)   # never got volume — drop it
        elif age_sec >= _STAGE_MIN_SEC:
            addrs.append(addr)             # old enough to check for volume surge
    for a in expired_staged:
        del _staged_mints[a]
    if expired_staged:
        logger.debug(f"Dropped {len(expired_staged)} staged mints that never got volume")

    # ── Pool B: Trending/mover tokens from external APIs ──────────────────────
    async with aiohttp.ClientSession() as session:
        # Source 1: pump.fun top market cap tokens (official frontend API)
        # These are the tokens shown on pump.fun's trending page — established tokens
        # sorted by market cap, not new launches. Exactly what the user wants.
        for pf_sort in ("market_cap", "last_trade_timestamp"):
            try:
                async with session.get(
                    f"https://frontend-api.pump.fun/coins"
                    f"?limit=50&offset=0&sort={pf_sort}&order=DESC&includeNsfw=false",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        coins = await resp.json()
                        for c in (coins if isinstance(coins, list) else []):
                            a = c.get("mint", "")
                            if a:
                                addrs.append(a)
            except Exception as e:
                logger.debug(f"pump.fun frontend ({pf_sort}): {e}")

        # Source 2: DexScreener search — returns Solana pairs ranked by volume/activity.
        # This catches tokens that have already moved to Raydium/Jupiter with real DEX volume.
        for q in ("sol", "pump"):
            try:
                async with session.get(
                    f"https://api.dexscreener.com/latest/dex/search?q={q}",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for pair in (data.get("pairs") or []):
                            if pair.get("chainId") == "solana":
                                a = (pair.get("baseToken") or {}).get("address", "")
                                if a:
                                    addrs.append(a)
            except Exception as e:
                logger.debug(f"DexScreener search ({q}): {e}")

        # Source 3: DexScreener boosted tokens — active promotions, often established tokens
        try:
            async with session.get(
                "https://api.dexscreener.com/token-boosts/latest/v1",
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for item in (data if isinstance(data, list) else []):
                        if item.get("chainId") == "solana":
                            a = item.get("tokenAddress", "")
                            if a:
                                addrs.append(a)
        except Exception as e:
            logger.debug(f"DexScreener boosts: {e}")

        # Source 4: DexScreener token profiles — established projects with real communities.
        # Tokens here skew 30+ days old with verified metadata.
        try:
            async with session.get(
                "https://api.dexscreener.com/token-profiles/latest/v1",
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 200:
                    profiles = await resp.json()
                    for item in (profiles if isinstance(profiles, list) else []):
                        if item.get("chainId") == "solana":
                            a = item.get("tokenAddress", "")
                            if a:
                                addrs.append(a)
                                smart_addrs.add(a)  # pre-flag for smart project check
        except Exception as e:
            logger.debug(f"DexScreener token profiles: {e}")

    # Deduplicate and apply TTL — don't re-evaluate same token more than once per 5 min
    fresh: list[str] = []
    for a in dict.fromkeys(addrs):  # dict.fromkeys preserves order and dedupes
        if now - _dex_seen.get(a, 0) >= _DEX_TTL:
            _dex_seen[a] = now
            fresh.append(a)

    # Prune stale dex_seen entries to avoid unbounded growth
    if len(_dex_seen) > 5_000:
        cutoff = now - _DEX_TTL * 3
        for k in [k for k, v in _dex_seen.items() if v < cutoff]:
            del _dex_seen[k]

    if not fresh:
        return

    eligible = await _get_autobuy_users()
    if not eligible:
        return

    staged_in_batch = sum(1 for a in fresh if a in _staged_mints)
    logger.info(
        f"Mover scan: {len(fresh)} tokens ({staged_in_batch} minted+aged, "
        f"{len(fresh)-staged_in_batch} trending), {len(eligible)} user(s)"
    )

    # Fetch DexScreener data concurrently (rate-limited)
    sem = asyncio.Semaphore(5)

    async def _fetch(addr: str):
        async with sem:
            try:
                return await get_token_summary(addr)
            except Exception:
                return None

    token_datas = await asyncio.gather(*[_fetch(a) for a in fresh])

    smart_min_age_min = SMART_MIN_AGE_DAYS * 24 * 60

    for token_data in token_datas:
        if not token_data or "error" in token_data:
            continue
        addr = token_data.get("address", "")
        if not addr:
            continue
        # Remove from staged once DexScreener has confirmed it (good or bad)
        _staged_mints.pop(addr, None)

        # Volume sanity check — skip dead tokens with no trading activity
        if (token_data.get("volume_h1") or 0) < 100:
            continue

        # Age gate: must be 10+ minutes old — wait for the post-mint dump to play out
        if (token_data.get("age_minutes") or 0) < 10:
            continue

        # ── Smart Project Check ───────────────────────────────────────────────
        # If this address came from DexScreener token profiles OR passes the
        # age/mcap/growth criteria, tag it so _maybe_buy_active can log it.
        age_min    = token_data.get("age_minutes") or 0
        mcap       = token_data.get("market_cap") or 0
        chg_h24    = token_data.get("price_change_h24") or 0
        # Smart project: must meet ALL three hard criteria — profile source alone is not enough
        is_smart = (
            age_min >= smart_min_age_min and
            mcap    >= SMART_MIN_MCAP and
            chg_h24 >= SMART_MIN_CHANGE_H24
        )
        token_data["_is_smart_project"] = is_smart

        for user_id in eligible:
            try:
                await _maybe_buy_active(bot, user_id, addr, token_data)
            except Exception as e:
                logger.warning(f"Active eval error user={user_id} token={addr[:8]}: {e}")


async def _maybe_buy_active(bot: Bot, user_id: int, addr: str, token_data: dict) -> None:
    """
    Evaluate a DexScreener-sourced active token for auto-buy.
    Identical gates to _maybe_buy except:
      - No initial_buy filter (bonding curve only — irrelevant for DEX tokens)
      - No creator/name-dupe check (not available for established tokens)
      - token_data is already fetched; scored directly
      - platform always jupiter (active tokens are on DEX, not bonding curve)
    """
    from services.auto_buy_service import (
        get_auto_buy_settings, count_buys_last_hour,
        log_auto_buy_job, update_job_status,
    )
    from services.sniper_settings_service import get_settings
    from services.sniper_blacklist_service import get_blacklist_addresses
    from services.bot_wallet_service import get_or_create_bot_wallet, get_sol_balance
    from services.sniper_score_service import score_token
    from services.solana_execution_service import execute_buy

    ab   = await get_auto_buy_settings(user_id)
    s    = await get_settings(user_id)

    if not ab.get("enabled") or ab.get("kill_switch"):
        return

    # Execution failure cooldown — skip tokens that recently failed to execute
    last_fail = _exec_failed.get(addr, 0)
    if time.time() - last_fail < _EXEC_FAIL_TTL:
        return

    # Token blacklist
    blacklisted = await get_blacklist_addresses(user_id)
    if addr in blacklisted:
        return

    # Rate limit
    buys_this_hour = await count_buys_last_hour(user_id)
    max_per_hour   = int(ab.get("max_buys_per_hour") or 5)
    if buys_this_hour >= max_per_hour:
        return

    # Cooldown between buys — per user, not global
    cooldown  = int(ab.get("cooldown_seconds") or 60)
    last_buy  = _user_last_buy.get(user_id, 0)
    if time.time() - last_buy < cooldown:
        return

    # ── Market cap filter ─────────────────────────────────────────────────────
    mcap_now     = float(token_data.get("market_cap") or 0)
    min_mcap     = float(ab.get("min_market_cap_usd") or 0)
    max_mcap     = float(ab.get("max_market_cap_usd") or 0)
    if min_mcap > 0 and mcap_now < min_mcap:
        return
    if max_mcap > 0 and mcap_now > max_mcap:
        return

    # Score threshold — enforce minimum of 20 so garbage settings can't let everything through
    threshold    = max(int(ab.get("score_threshold") or 40), 20)
    is_smart     = token_data.get("_is_smart_project", False)

    # Smart projects use a dedicated strategy mode calibrated for established tokens
    # (not volume_spike which is tuned for new launches with tiny liquidity pools)
    settings_for_score = dict(s)
    if is_smart:
        settings_for_score["strategy_mode"] = "smart_project"

    score_result = score_token(token_data, settings_for_score)
    score        = score_result["score"]

    sym = token_data.get("symbol") or addr[:6]
    logger.info(
        f"Active scan eval user={user_id} token={sym} score={score}/{threshold} "
        f"smart={is_smart} mcap={token_data.get('market_cap',0):.0f} "
        f"age_days={((token_data.get('age_minutes') or 0) / 1440):.0f} "
        f"chg_24h={token_data.get('price_change_h24',0):+.1f}%"
    )

    if score < threshold:
        _stats["low_score_blocked"] += 1
        return

    # Buy size + fees
    buy_size = float(ab.get("max_buy_size_sol") or 0.05)
    if buy_size <= 0:
        return

    priority     = float(ab.get("priority_fee") or 0.005)
    slippage     = float(ab.get("slippage") or 18.0)
    fee_reserve  = buy_size * 0.01 + priority + 0.002
    min_required = buy_size + fee_reserve

    row     = await get_or_create_bot_wallet(user_id)
    balance = await get_sol_balance(row["wallet_address"])
    if balance is None or balance < min_required:
        _stats["low_balance_blocked"] += 1
        logger.warning(f"Active scan skipped (low balance) user={user_id} bal={balance or 0:.5f} need={min_required:.5f}")
        return

    min_floor = float(ab.get("min_wallet_balance_sol") or 0)
    if min_floor > 0 and balance <= min_floor:
        return

    # Daily spend limit
    daily_limit = float(ab.get("daily_spend_limit_sol") or 0)
    if daily_limit > 0:
        from database.sqlite_db import get_db as _db
        async with _db() as db:
            async with db.execute(
                "SELECT COALESCE(SUM(amount_sol),0) FROM auto_buy_jobs "
                "WHERE user_id=? AND status='executed' AND created_at>=datetime('now','-24 hours')",
                (user_id,),
            ) as cur:
                row2 = await cur.fetchone()
                spent_24h = float(row2[0]) if row2 else 0.0
        if spent_24h + buy_size > daily_limit:
            return

    # Final gate re-read (user may have disabled mid-scan)
    ab_final = await get_auto_buy_settings(user_id)
    if not ab_final.get("enabled") or ab_final.get("kill_switch"):
        return

    job_id = await log_auto_buy_job(user_id, addr, buy_size, score, source="active_scan")

    result = await execute_buy(
        user_id          = user_id,
        token_address    = addr,
        amount_sol       = buy_size,
        slippage_pct     = slippage,
        priority_fee_sol = priority,
        platform         = "auto",  # auto-routes: bonding curve → PumpPortal, graduated → Jupiter
    )

    if result.get("success"):
        _stats["buys_executed"] += 1
        _stats["last_buy_ts"]    = time.time()
        _stats["last_buy_symbol"] = sym
        _user_last_buy[user_id]  = time.time()  # per-user cooldown
        await update_job_status(job_id, "executed")
        sig = result["signature"]
        from utils.share_utils import build_share_markup
        _share = (
            f"⬛ Auto-bought ${sym.upper()} (active scan) with {settings.BRAND_HANDLE} 🤖\n"
            f"Score: {score}/{threshold} — momentum detected 🔥\n"
            f"#brainrotonchain"
        )
        age_days = int((token_data.get("age_minutes") or 0) / 1440)
        mcap_k   = (token_data.get("market_cap") or 0) / 1000
        chg_24h  = token_data.get("price_change_h24") or 0
        tag      = "🧠 SMART PROJECT" if is_smart else "ACTIVE SCAN"
        await _notify(bot, user_id,
            f"⬛ <b>AUTO-BUY  //  {tag}</b>\n"
            f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"TOKEN  {sym.upper()}\n"
            f"SCORE  {score}/{threshold}\n"
            f"MCAP   ${mcap_k:.0f}K   AGE {age_days}d\n"
            f"24H    {chg_24h:+.1f}%\n"
            f"SIZE   {buy_size} SOL  [{(result.get('platform_used') or 'DEX').upper()}]\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
            f"📋 CA <i>(tap to copy)</i>\n"
            f"<code>{addr}</code>\n\n"
            f"🔗 TX <i>(tap to copy)</i>\n"
            f"<code>{sig}</code>\n"
            f'<a href="https://solscan.io/tx/{sig}">↗ Solscan</a>  '
            f'<a href="https://dexscreener.com/solana/{addr}">↗ DexScreener</a>',
            reply_markup=build_share_markup(_share),
        )
        logger.info(f"Active scan buy success user={user_id} token={addr[:8]} sig={sig[:12]}")
    else:
        _stats["buys_failed"] += 1
        await update_job_status(job_id, "failed")
        _exec_failed[addr] = time.time()  # cooldown — skip this token for 30 min
        logger.warning(f"Active scan buy failed user={user_id} token={addr[:8]}: {result.get('error')}")


# ── Core scan ─────────────────────────────────────────────────────────────────

async def _scan(bot: Bot) -> None:
    from services.pumpportal_ws_service import pump_service

    raw_feed = pump_service.get_recent(limit=50)

    # Normalise: PumpPortal uses "address", not "mint"
    new_items = []
    for t in raw_feed:
        addr = t.get("address") or t.get("mint") or ""
        if addr and addr not in _seen:
            _seen.add(addr)
            item = dict(t)
            item["address"] = addr   # ensure consistent key
            new_items.append(item)

    # Cap memory
    if len(_seen) > 10_000:
        _seen.clear()

    _stats["scans_completed"] += 1
    _stats["last_scan_ts"]    = time.time()

    if not new_items:
        return

    eligible = await _get_autobuy_users()
    if not eligible:
        return

    _stats["tokens_evaluated"] += len(new_items)
    if new_items:
        _stats["last_token_seen"] = new_items[-1].get("symbol") or new_items[-1]["address"][:8]

    logger.info(f"Auto-buy scan: {len(new_items)} new tokens, {len(eligible)} eligible user(s)")

    for raw_token in new_items:
        addr = raw_token["address"]
        for user_id in eligible:
            try:
                await _maybe_buy(bot, user_id, addr, raw_token)
            except Exception as e:
                logger.warning(f"Auto-buy error user={user_id} token={addr[:8]}: {e}", exc_info=True)


# ── Per-user evaluation ───────────────────────────────────────────────────────

async def _maybe_buy(bot: Bot, user_id: int, addr: str, raw_token: dict) -> None:
    from services.auto_buy_service import (
        get_auto_buy_settings, count_buys_last_hour,
        log_auto_buy_job, update_job_status,
    )
    from services.sniper_settings_service import get_settings
    from services.sniper_blacklist_service import get_blacklist_addresses
    from services.bot_wallet_service import get_or_create_bot_wallet, get_sol_balance
    from services.sniper_score_service import score_token
    from services.solana_execution_service import execute_buy

    ab   = await get_auto_buy_settings(user_id)
    s    = await get_settings(user_id)

    # ── Gates ─────────────────────────────────────────────────────────────────
    if not ab.get("enabled") or ab.get("kill_switch"):
        return

    # Execution failure cooldown
    last_fail = _exec_failed.get(addr, 0)
    if time.time() - last_fail < _EXEC_FAIL_TTL:
        return

    blacklisted = await get_blacklist_addresses(user_id)
    if addr in blacklisted:
        _stats["token_bl_blocked"] += 1
        return

    # ── Creator blacklist check ────────────────────────────────────────────────
    from services.sniper_blacklist_service import get_creator_blacklist_addresses
    creator = str(raw_token.get("creator") or "")
    if creator:
        blocked_creators = await get_creator_blacklist_addresses(user_id)
        if creator in blocked_creators:
            _stats["creator_bl_blocked"] += 1
            logger.debug(f"Auto-buy skipped (creator blacklisted) user={user_id} creator={creator[:8]}")
            return

        # Track this creator launch in the rolling window
        now_ts = time.time()
        _creator_launches[creator].append((addr, raw_token.get("name", ""), now_ts))
        # Prune entries older than the window
        _creator_launches[creator] = [
            (a, n, t) for a, n, t in _creator_launches[creator]
            if now_ts - t < _CREATOR_WINDOW_SECS
        ]
        creator_key = f"{creator}:{user_id}"
        if len(_creator_launches[creator]) > _CREATOR_DUPE_LIMIT and creator_key in _creator_bought:
            # Already bought one from this creator — block the rest
            _stats["creator_dupes_blocked"] += 1
            if creator_key not in _creator_logged:
                _creator_logged.add(creator_key)
                logger.info(
                    f"Auto-buy: creator {creator[:8]} serial deployer "
                    f"({len(_creator_launches[creator])} launches/hr) — already bought once, blocking further tokens for user={user_id}"
                )
            return

    # ── Duplicate name filter ──────────────────────────────────────────────────
    # Only block tokens that share BOTH the same name AND the same creator wallet.
    # Different wallets launching same-named tokens are independent projects.
    token_name = str(raw_token.get("name") or "")
    name_fp    = _norm_name(token_name) if token_name else ""
    if name_fp and name_fp in _bought_name_fingerprints:
        first_addr, first_creator = _bought_name_fingerprints[name_fp]
        if first_addr != addr and first_creator == creator:
            _stats["name_dupes_blocked"] += 1
            logger.info(
                f"Auto-buy skipped (duplicate name+creator '{token_name}') user={user_id} "
                f"token={addr[:8]} creator={creator[:8]} — first buy was {first_addr[:8]}"
            )
            return

    # ── Initial buy filter (Liquidity Sniper) ─────────────────────────────────
    min_init_buy = float(ab.get("min_initial_buy_sol") or 0)
    if min_init_buy > 0:
        initial_buy = float(
            raw_token.get("initial_buy") or raw_token.get("initialBuy") or 0
        )
        if initial_buy < min_init_buy:
            return  # token's initial buy below threshold — skip

    # Tag source for job tracking
    is_liq_sniper = min_init_buy > 0
    source = "liq_sniper" if is_liq_sniper else "auto_buy"
    liq_exit_preset_id = int(ab.get("liq_exit_preset_id") or 0) or None

    buys_this_hour = await count_buys_last_hour(user_id)
    max_per_hour   = int(ab.get("max_buys_per_hour") or 3)
    if buys_this_hour >= max_per_hour:
        return

    threshold = int(ab.get("score_threshold") or 30)

    # ── Build token dict for scoring ──────────────────────────────────────────
    # For aggressive presets we score using the raw WebSocket data directly.
    # For stricter presets we try DexScreener first; if it doesn't have the
    # token yet (brand-new pump.fun tokens take 5-15 min to index), fall back
    # to raw feed data rather than silently skipping.
    if threshold <= DEXSCREENER_MIN_THRESHOLD:
        token_data = _build_token_from_feed(raw_token, addr)
    else:
        from services.token_data_provider import get_token_summary
        token_data = await get_token_summary(addr)
        if not token_data or "error" in token_data:
            # DexScreener doesn't have it yet — fall back to raw feed data.
            # Score will reflect what we know (buy pressure + freshness).
            # If it doesn't meet the threshold, the score check below handles it.
            token_data = _build_token_from_feed(raw_token, addr)

    # ── Minimum age gate — never buy tokens under 10 minutes old ─────────────
    # We wait for the token to survive the initial dump and show real volume.
    # PumpPortal feed tokens have age_minutes=0 — they will always be skipped.
    # Tokens that pass DexScreener lookup will have a real age from pairCreatedAt.
    token_age = int(token_data.get("age_minutes") or 0)
    if token_age < 10:
        logger.debug(f"Auto-buy skipped (too fresh {token_age}m) user={user_id} token={addr[:8]}")
        return

    # ── Score ─────────────────────────────────────────────────────────────────
    score_result = score_token(token_data, s)
    score        = score_result["score"]
    logger.info(
        f"Auto-buy eval user={user_id} token={raw_token.get('symbol', addr[:8])} "
        f"score={score}/{threshold} v_sol={raw_token.get('v_sol_in_bonding_curve', 0):.2f} "
        f"liq={token_data.get('liquidity_usd', 0):.0f} vol={token_data.get('volume_h1', 0):.0f}"
    )

    if score < threshold:
        _stats["low_score_blocked"] += 1
        logger.info(
            f"Auto-buy skipped (low score) user={user_id} token={raw_token.get('symbol', addr[:8])} "
            f"score={score} threshold={threshold} v_sol={raw_token.get('v_sol_in_bonding_curve', 0):.2f}"
        )
        return

    # ── Buy size + execution params ───────────────────────────────────────────
    buy_size = float(ab.get("max_buy_size_sol") or 0.01)
    if buy_size <= 0:
        return
    platform = s.get("preferred_platform") or "auto"
    slippage = float(ab.get("slippage") or 15.0)
    priority = float(ab.get("priority_fee") or 0.005)

    # ── Balance ───────────────────────────────────────────────────────────────
    row     = await get_or_create_bot_wallet(user_id)
    balance = await get_sol_balance(row["wallet_address"])
    # pump.fun charges ~1% protocol fee + Solana priority fee + token-account rent.
    # Token-2022 account creation (first buy of any token) costs ~0.002 SOL in rent.
    # We always reserve this — if the account already exists the extra acts as safety margin.
    fee_reserve  = buy_size * 0.01 + priority + 0.002
    min_required = buy_size + fee_reserve
    if balance is None or balance < min_required:
        _stats["low_balance_blocked"] += 1
        logger.warning(f"Auto-buy skipped (low balance) user={user_id} bal={(balance or 0):.5f} need={min_required:.5f}")
        # Only notify once per cooldown window to avoid Telegram flood control
        last_notified = _low_balance_last_notified.get(user_id, 0)
        if time.time() - last_notified >= LOW_BALANCE_NOTIFY_COOLDOWN:
            _low_balance_last_notified[user_id] = time.time()
            await _notify(bot, user_id,
                f"⬛ <b>AUTO-BUY  //  LOW BAL</b>\n"
                f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"BAL    {(balance or 0):.5f} SOL\n"
                f"NEED   {min_required:.5f} SOL\n"
                f"STATUS skipped — deposit to resume</code>"
            )
        return

    # ── Wallet floor / auto-stop protection ───────────────────────────────────
    min_floor = float(ab.get("min_wallet_balance_sol") or 0)
    if min_floor > 0 and balance is not None and balance <= min_floor:
        _stats["low_balance_blocked"] += 1
        logger.warning(
            f"Auto-buy HALTED — wallet floor reached: user={user_id} "
            f"bal={balance:.5f} floor={min_floor:.5f} SOL"
        )
        # Kill the auto-buy and set kill switch so it doesn't restart silently
        from services.auto_buy_service import toggle_kill_switch as _ks
        from database.sqlite_db import get_db as _db
        async with _db() as db:
            await db.execute(
                "UPDATE auto_buy_settings SET enabled = 0, kill_switch = 1, "
                "updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (user_id,),
            )
            await db.commit()
        last_notified = _low_balance_last_notified.get(user_id, 0)
        if time.time() - last_notified >= LOW_BALANCE_NOTIFY_COOLDOWN:
            _low_balance_last_notified[user_id] = time.time()
            await _notify(bot, user_id,
                f"⬛ <b>AUTO-BUY  //  HALTED</b>\n"
                f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"BAL    {(balance or 0):.5f} SOL\n"
                f"FLOOR  {min_floor:.5f} SOL\n"
                f"STATUS wallet floor hit — auto-buy off\n"
                f"ACTION deposit SOL + re-enable</code>"
            )
        return

    # ── Daily spend limit ──────────────────────────────────────────────────────
    daily_limit = float(ab.get("daily_spend_limit_sol") or 0)
    if daily_limit > 0:
        from database.sqlite_db import get_db as _db2
        async with _db2() as db:
            async with db.execute(
                "SELECT COALESCE(SUM(amount_sol),0) FROM auto_buy_jobs "
                "WHERE user_id = ? AND status = 'executed' "
                "AND created_at >= datetime('now','-24 hours')",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
                spent_24h = float(row[0]) if row else 0.0
        if spent_24h + buy_size > daily_limit:
            logger.info(
                f"Daily spend limit reached: user={user_id} spent={spent_24h:.4f} "
                f"limit={daily_limit:.4f} SOL — skipping buy"
            )
            last_notified = _low_balance_last_notified.get(user_id, 0)
            if time.time() - last_notified >= LOW_BALANCE_NOTIFY_COOLDOWN:
                _low_balance_last_notified[user_id] = time.time()
                await _notify(bot, user_id,
                    f"🔒 <b>AUTO-BUY  //  DAILY LIMIT REACHED</b>\n"
                    f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"SPENT TODAY  {spent_24h:.4f} SOL\n"
                    f"LIMIT        {daily_limit:.4f} SOL\n"
                    f"STATUS       buys paused until reset\n"
                    f"RESETS       24h rolling window</code>"
                )
            return

    # ── Final enabled guard (re-read DB in case user pressed stop mid-scan) ───
    ab_final = await get_auto_buy_settings(user_id)
    if not ab_final.get("enabled") or ab_final.get("kill_switch"):
        logger.info(f"Auto-buy aborted pre-execute (stopped mid-scan) user={user_id} token={addr[:8]}")
        return

    # ── Execute ───────────────────────────────────────────────────────────────
    job_id = await log_auto_buy_job(user_id, addr, buy_size, score, source=source)

    result = await execute_buy(
        user_id          = user_id,
        token_address    = addr,
        amount_sol       = buy_size,
        slippage_pct     = slippage,
        priority_fee_sol = priority,
        platform         = platform,
        exit_preset_id   = liq_exit_preset_id if is_liq_sniper else None,
    )

    if result["success"]:
        _stats["buys_executed"] += 1
        _stats["last_buy_ts"]    = time.time()
        _stats["last_buy_symbol"] = raw_token.get("symbol") or addr[:6]
        await update_job_status(job_id, "executed")
        # Lock this name+creator pair so copycat tokens from the same wallet are skipped
        if name_fp and name_fp not in _bought_name_fingerprints:
            _bought_name_fingerprints[name_fp] = (addr, creator)
        # Mark creator as bought — subsequent spam tokens from them will now be blocked
        if creator:
            _creator_bought.add(f"{creator}:{user_id}")
        sig  = result["signature"]
        plat = result.get("platform_used", "?")
        sym  = raw_token.get("symbol") or addr[:6]
        from utils.share_utils import build_share_markup
        _share_ab = (
            f"⬛ Auto-bought ${sym.upper()} with {settings.BRAND_HANDLE} 🤖\n"
            f"Score: {score}/100 — the bot is hunting 👀\n"
            f"#brainrotonchain"
        )
        await _notify(bot, user_id,
            f"⬛ <b>AUTO-BUY  //  EXECUTED</b>\n"
            f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"TOKEN  {sym.upper()}\n"
            f"SCORE  {score}/100\n"
            f"SIZE   {buy_size} SOL  [{plat.upper()}]\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
            f"📋 CA <i>(tap to copy)</i>\n"
            f"<code>{addr}</code>\n\n"
            f"🔗 TX <i>(tap to copy)</i>\n"
            f"<code>{sig}</code>\n"
            f'<a href="https://solscan.io/tx/{sig}">↗ Solscan</a>  '
            f'<a href="https://pump.fun/{addr}">↗ Pump.fun</a>',
            reply_markup=build_share_markup(_share_ab),
        )
        logger.info(f"Auto-buy executed user={user_id} token={addr[:8]} sig={sig[:12]}")
    else:
        _stats["buys_failed"] += 1
        await update_job_status(job_id, "failed")
        _exec_failed[addr] = time.time()  # cooldown — skip this token for 30 min
        logger.warning(f"Auto-buy failed user={user_id} token={addr[:8]}: {result['error']}")


def _build_token_from_feed(raw: dict, addr: str) -> dict:
    """
    Build a minimal token dict from a raw PumpPortal WebSocket event.
    Used when DexScreener doesn't have the token yet (it's seconds old).

    Primary quality signal: vSolInBondingCurve (real SOL locked in the curve).
    This is far more reliable than initialBuy because it reflects the actual
    market depth at the moment of the event — not just the creator's first tx.

    vSolInBondingCurve thresholds (SOL):
      < 1   → freshly minted, almost no buyer interest           → 1 synthetic buy
      1-5   → minor early interest                               → 10 buys
      5-20  → real momentum building                             → 50 buys
      20-50 → strong interest, approaching graduation range      → 100 buys
      > 50  → near graduation (~69 SOL), extremely high interest → 150 buys

    We also correct for the buy-pressure bias: every token arrives with
    buys_h1=1 sells_h1=0 which gives automatic 100% buy ratio and 20/20 pts.
    We set sells proportional to curve depth so the scorer must earn those pts.
    """
    initial_buy  = float(raw.get("initial_buy") or raw.get("initialBuy") or 0)
    v_sol        = float(raw.get("v_sol_in_bonding_curve") or raw.get("vSolInBondingCurve") or 0)

    # Use vSolInBondingCurve as primary; fall back to initialBuy if not present
    curve_sol = v_sol if v_sol > 0 else initial_buy

    if curve_sol >= 50:
        synthetic_buys = 150
        synthetic_sells = 10   # still buying heavily
    elif curve_sol >= 20:
        synthetic_buys = 100
        synthetic_sells = 15
    elif curve_sol >= 5:
        synthetic_buys = 50
        synthetic_sells = 10
    elif curve_sol >= 1:
        synthetic_buys = 10
        synthetic_sells = 3
    else:
        synthetic_buys = 1
        synthetic_sells = 1   # unknown — treat as neutral, not automatic 100% ratio

    # Volume proxy: use curve_sol as the demand signal (converted to rough USD)
    vol_proxy_usd = curve_sol * 150  # SOL → rough USD

    return {
        "address":                addr,
        "name":                   raw.get("name", "Unknown"),
        "symbol":                 raw.get("symbol", "???"),
        "price_usd":              0.0,
        "liquidity_usd":          0.0,
        "volume_h1":              vol_proxy_usd,
        "buys_h1":                synthetic_buys,
        "sells_h1":               synthetic_sells,
        "age_minutes":            0,
        "dex":                    "pumpfun",
        "market_cap":             raw.get("market_cap") or raw.get("marketCapSol", 0),
        "v_sol_in_bonding_curve": curve_sol,
        "initial_buy":            initial_buy,
    }


async def _notify(bot: Bot, user_id: int, text: str, reply_markup=None) -> None:
    try:
        await bot.send_message(user_id, text, parse_mode="HTML",
                               disable_web_page_preview=True,
                               reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"Auto-buy notify failed user={user_id}: {e}")


async def _get_autobuy_users() -> list[int]:
    from database.sqlite_db import get_db
    async with get_db() as db:
        async with db.execute(
            "SELECT user_id FROM auto_buy_settings WHERE enabled = 1 AND kill_switch = 0"
        ) as cur:
            rows = await cur.fetchall()
    return [r[0] for r in rows]
