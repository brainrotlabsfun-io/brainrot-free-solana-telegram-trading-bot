"""
services/wallet_discovery_worker.py
=====================================
Daily Dragon Intel pipeline — automatically discovers the best copy-trade
wallet candidates and stores them as subscribable system presets.

Pipeline (runs every DISCOVERY_INTERVAL_HOURS hours):

  1. Pull trending tokens from GMGN across all categories
     (completing curve, soaring, recently bonded to DEX)

  2. Fetch top traders for each token (concurrently, rate-limited)

  3. Count cross-token appearances — wallets topping multiple tokens
     simultaneously (Dragon's core signal)

  4. Score each repeated wallet via the gmgn smartmoney endpoint
     (win rate, 7d PnL, 30d PnL, hold time, tags)

  5. Compute composite intel_score:
       intel_score = (win_rate × 40) + (pnl_score × 30)
                   + (appearance_score × 20) + (hold_score × 10)
     where:
       pnl_score         = min(pnl_7d / 1000, 30) / 30  → 0–1
       appearance_score  = min(appearances / 5, 1)       → 0–1
       hold_score        = 1.0 if 5min < avg_hold < 4hr else 0.5

  6. Categorise into 4 preset buckets:
       hot_today    — highest intel_score overall (best all-rounders)
       consistent   — highest win_rate (≥ 60%)
       snipers      — shortest avg hold time (fast flippers)
       high_pnl     — highest pnl_7d in USD

  7. Write top-10 per preset to discovered_wallets table

  8. Notify all subscribed users that their preset has been refreshed
     and sync their copy_trade_wallets list accordingly

Tier gating:
  FREE          — can view presets + subscribe, max 3 wallets (shared with manual)
"""

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Optional

from aiogram import Bot

from database.sqlite_db import get_db

logger = logging.getLogger(__name__)

DISCOVERY_INTERVAL_HOURS = 24    # how often to run the full pipeline
TOKENS_PER_CATEGORY      = 15   # tokens to pull from each GMGN category
TOP_TRADERS_PER_TOKEN    = 25   # wallets to check per token
MIN_APPEARANCES          = 2    # must appear on this many tokens to qualify
MAX_WALLETS_TO_SCORE     = 40   # cap gmgn scoring calls per run
WALLETS_PER_PRESET       = 10   # top N stored per preset key

PRESET_KEYS = ["hot_today", "consistent", "snipers", "high_pnl"]

PRESET_LABELS = {
    "hot_today":  "🔥 Hot Today",
    "consistent": "🎯 Consistent Winners",
    "snipers":    "⚡ Fast Snipers",
    "high_pnl":   "💰 High PnL",
}

_running = False
_last_run_ts = 0.0
_current_status = "idle"


def get_worker_status() -> dict:
    return {
        "running":     _running,
        "last_run_ts": _last_run_ts,
        "status":      _current_status,
    }


def stop() -> None:
    global _running
    _running = False


async def start(bot: Bot) -> None:
    global _running, _last_run_ts, _current_status
    _running = True
    _current_status = "idle"
    logger.info("Wallet discovery worker started.")

    while _running:
        now = time.time()
        elapsed_hours = (now - _last_run_ts) / 3600

        if elapsed_hours >= DISCOVERY_INTERVAL_HOURS or _last_run_ts == 0:
            try:
                _current_status = "running"
                await run_discovery(bot)
                _last_run_ts    = time.time()
                _current_status = "idle"
            except Exception as e:
                logger.error(f"Wallet discovery error: {e}", exc_info=True)
                _current_status = "error"

        # Sleep in 5-minute chunks so stop() is responsive
        for _ in range(60):
            if not _running:
                break
            await asyncio.sleep(300)

    logger.info("Wallet discovery worker stopped.")


async def run_discovery(bot: Optional[Bot] = None) -> dict:
    """
    Execute the full Dragon intel pipeline.
    Returns a summary dict. Can be called manually (e.g. from admin command).
    """
    logger.info("Dragon Intel: starting wallet discovery pipeline…")
    run_id = await _log_run_start()

    from services.gmgn_service import (
        get_new_pump_tokens, get_top_traders, get_wallet_stats,
    )

    # ── Step 1: Pull trending tokens ─────────────────────────────────────────
    categories   = ["completing", "soaring", "bonded"]
    token_tasks  = [get_new_pump_tokens(cat, limit=TOKENS_PER_CATEGORY) for cat in categories]
    cat_results  = await asyncio.gather(*token_tasks, return_exceptions=True)

    contracts = []
    for cat, result in zip(categories, cat_results):
        if isinstance(result, Exception):
            logger.warning(f"Discovery: failed to fetch {cat} tokens: {result}")
            continue
        for t in (result or []):
            addr = (
                t.get("address") or t.get("base_address") or
                t.get("mint")    or t.get("contract_address") or ""
            ).strip()
            if addr and addr not in contracts:
                contracts.append(addr)

    if not contracts:
        logger.warning("Dragon Intel: no tokens fetched — aborting run")
        await _log_run_finish(run_id, 0, 0, "failed")
        return {"status": "failed", "reason": "no tokens fetched"}

    logger.info(f"Dragon Intel: {len(contracts)} unique tokens to scan")

    # ── Step 2: Fetch top traders for each token ──────────────────────────────
    sem          = asyncio.Semaphore(6)
    wallet_tokens: dict[str, list[str]] = defaultdict(list)  # wallet → tokens where topped

    async def _fetch_token_traders(addr: str):
        async with sem:
            traders = await get_top_traders(addr, limit=TOP_TRADERS_PER_TOKEN)
        for t in traders:
            w = t.get("wallet") or ""
            if w:
                wallet_tokens[w].append(addr)

    await asyncio.gather(*[_fetch_token_traders(c) for c in contracts])

    # ── Step 3: Find cross-token repeated winners ─────────────────────────────
    repeated = {
        w: tokens
        for w, tokens in wallet_tokens.items()
        if len(tokens) >= MIN_APPEARANCES
    }

    logger.info(f"Dragon Intel: {len(repeated)} wallets appeared on 2+ tokens")

    if not repeated:
        await _log_run_finish(run_id, len(contracts), 0, "no_repeated_wallets")
        return {"status": "no_repeated_wallets", "tokens_scanned": len(contracts)}

    # ── Step 4: Score each repeated wallet via gmgn ───────────────────────────
    # Sort by appearances descending, cap to save API quota
    top_candidates = sorted(repeated.items(), key=lambda x: len(x[1]), reverse=True)
    top_candidates = top_candidates[:MAX_WALLETS_TO_SCORE]

    score_sem    = asyncio.Semaphore(5)
    scored       = []

    async def _score_wallet(wallet: str, tokens: list[str]):
        async with score_sem:
            stats = await get_wallet_stats(wallet)
        if not stats:
            return
        score = _compute_intel_score(stats, len(tokens))
        scored.append({
            "wallet_address": wallet,
            "win_rate":       stats.get("winrate")              or 0,
            "pnl_7d":         stats.get("realized_profit_7d")   or 0,
            "pnl_30d":        stats.get("realized_profit_30d")  or 0,
            "appearances":    len(tokens),
            "avg_hold_secs":  stats.get("avg_holding_period")   or 0,
            "tags":           json.dumps(stats.get("tags") or []),
            "intel_score":    score,
        })

    await asyncio.gather(*[_score_wallet(w, t) for w, t in top_candidates])

    logger.info(f"Dragon Intel: scored {len(scored)} wallets")

    if not scored:
        await _log_run_finish(run_id, len(contracts), 0, "scoring_failed")
        return {"status": "scoring_failed"}

    # ── Step 5: Categorise into preset buckets ────────────────────────────────
    presets = _build_presets(scored)

    # ── Step 6: Write to DB ───────────────────────────────────────────────────
    total_stored = 0
    for preset_key, wallets in presets.items():
        await _store_preset(preset_key, wallets)
        total_stored += len(wallets)

    logger.info(
        f"Dragon Intel: discovery complete — "
        f"{len(contracts)} tokens, {len(scored)} wallets scored, "
        f"{total_stored} stored across {len(presets)} presets"
    )

    await _log_run_finish(run_id, len(contracts), len(scored), "success")

    # ── Step 7: Notify subscribers ────────────────────────────────────────────
    if bot:
        await _notify_subscribers(bot, presets)

    # ── Step 8: Sync copy trade wallets for all subscribers ──────────────────
    await _sync_all_subscriber_copy_lists()

    return {
        "status":         "success",
        "tokens_scanned": len(contracts),
        "wallets_scored": len(scored),
        "stored":         total_stored,
        "presets":        {k: len(v) for k, v in presets.items()},
    }


# ── Scoring Formula ───────────────────────────────────────────────────────────

def _compute_intel_score(stats: dict, appearances: int) -> float:
    """
    Composite score 0–100:
      win_rate score    (0–40 pts) — quality signal
      pnl score         (0–30 pts) — profitability signal
      appearance score  (0–20 pts) — cross-token consistency
      hold time score   (0–10 pts) — not a bot, not a bag holder
    """
    wr  = float(stats.get("winrate") or 0)
    p7  = float(stats.get("realized_profit_7d") or 0)
    hold = float(stats.get("avg_holding_period") or 0)

    win_score   = wr * 40                               # 0–40
    pnl_score   = min(p7 / 1000, 30)                    # $30k → 30pts cap
    app_score   = min(appearances / 5, 1.0) * 20        # 5+ appearances → 20pts
    # Sweet spot hold: 5 min (300s) to 4 hours (14400s)
    if 300 <= hold <= 14400:
        hold_score = 10.0
    elif hold < 300 or hold > 86400:
        hold_score = 2.0    # too fast (bot) or too slow (bag holder)
    else:
        hold_score = 6.0

    return round(win_score + pnl_score + app_score + hold_score, 2)


# ── Preset Builder ────────────────────────────────────────────────────────────

def _build_presets(scored: list[dict]) -> dict[str, list[dict]]:
    """Partition scored wallets into 4 preset categories, top-N each."""
    n = WALLETS_PER_PRESET

    hot_today  = sorted(scored, key=lambda x: x["intel_score"], reverse=True)[:n]

    consistent = sorted(
        [w for w in scored if w["win_rate"] >= 0.55],
        key=lambda x: x["win_rate"],
        reverse=True,
    )[:n]

    snipers    = sorted(
        [w for w in scored if 60 <= w["avg_hold_secs"] <= 3600],
        key=lambda x: x["avg_hold_secs"],
    )[:n]

    high_pnl   = sorted(
        [w for w in scored if w["pnl_7d"] > 0],
        key=lambda x: x["pnl_7d"],
        reverse=True,
    )[:n]

    return {
        "hot_today":  hot_today,
        "consistent": consistent,
        "snipers":    snipers,
        "high_pnl":   high_pnl,
    }


# ── DB Helpers ────────────────────────────────────────────────────────────────

async def _store_preset(preset_key: str, wallets: list[dict]) -> None:
    """Replace the current preset wallets with the freshly discovered set."""
    async with get_db() as db:
        # Remove old entries for this preset
        await db.execute(
            "DELETE FROM discovered_wallets WHERE preset_key = ?", (preset_key,)
        )
        for w in wallets:
            await db.execute("""
                INSERT INTO discovered_wallets
                    (wallet_address, preset_key, win_rate, pnl_7d, pnl_30d,
                     appearances, avg_hold_secs, tags, intel_score, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(wallet_address) DO UPDATE SET
                    preset_key   = excluded.preset_key,
                    win_rate     = excluded.win_rate,
                    pnl_7d       = excluded.pnl_7d,
                    pnl_30d      = excluded.pnl_30d,
                    appearances  = excluded.appearances,
                    avg_hold_secs = excluded.avg_hold_secs,
                    tags         = excluded.tags,
                    intel_score  = excluded.intel_score,
                    last_updated = CURRENT_TIMESTAMP
            """, (
                w["wallet_address"], preset_key, w["win_rate"], w["pnl_7d"],
                w["pnl_30d"], w["appearances"], w["avg_hold_secs"],
                w["tags"], w["intel_score"],
            ))
        await db.commit()


async def get_preset_wallets(preset_key: str) -> list[dict]:
    async with get_db() as db:
        async with db.execute("""
            SELECT * FROM discovered_wallets
            WHERE preset_key = ?
            ORDER BY intel_score DESC
        """, (preset_key,)) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_all_presets_summary() -> dict:
    """Return {preset_key: {count, top_score, last_updated}} for all presets."""
    result = {}
    async with get_db() as db:
        for key in PRESET_KEYS:
            async with db.execute("""
                SELECT COUNT(*) as cnt,
                       MAX(intel_score) as top_score,
                       MAX(last_updated) as updated
                FROM discovered_wallets WHERE preset_key = ?
            """, (key,)) as cur:
                row = await cur.fetchone()
            result[key] = {
                "count":       row["cnt"]       if row else 0,
                "top_score":   row["top_score"] if row else 0,
                "last_updated": row["updated"]  if row else None,
            }
    return result


async def get_last_run_info() -> Optional[dict]:
    async with get_db() as db:
        async with db.execute("""
            SELECT * FROM discovery_runs ORDER BY id DESC LIMIT 1
        """) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def _log_run_start() -> int:
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO discovery_runs (status) VALUES ('running')"
        )
        run_id = cur.lastrowid
        await db.commit()
    return run_id


async def _log_run_finish(run_id: int, tokens: int, wallets: int, status: str):
    async with get_db() as db:
        await db.execute("""
            UPDATE discovery_runs
            SET finished_at = CURRENT_TIMESTAMP, tokens_scanned = ?,
                wallets_found = ?, status = ?
            WHERE id = ?
        """, (tokens, wallets, status, run_id))
        await db.commit()


# ── Subscription Management ───────────────────────────────────────────────────

async def subscribe_to_preset(user_id: int, preset_key: str) -> tuple[bool, str]:
    if preset_key not in PRESET_KEYS:
        return False, "Unknown preset."
    async with get_db() as db:
        await db.execute("""
            INSERT INTO wallet_preset_subscriptions (user_id, preset_key, active)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, preset_key) DO UPDATE SET active = 1,
                subscribed_at = CURRENT_TIMESTAMP
        """, (user_id, preset_key))
        await db.commit()
    # Immediately sync wallets for this user
    await _sync_user_copy_list(user_id)
    return True, ""


async def unsubscribe_from_preset(user_id: int, preset_key: str) -> None:
    async with get_db() as db:
        await db.execute("""
            UPDATE wallet_preset_subscriptions
            SET active = 0
            WHERE user_id = ? AND preset_key = ?
        """, (user_id, preset_key))
        await db.commit()


async def get_user_subscriptions(user_id: int) -> list[str]:
    async with get_db() as db:
        async with db.execute("""
            SELECT preset_key FROM wallet_preset_subscriptions
            WHERE user_id = ? AND active = 1
        """, (user_id,)) as cur:
            rows = await cur.fetchall()
    return [r["preset_key"] for r in rows]


async def _sync_user_copy_list(user_id: int) -> int:
    """
    For a user's active preset subscriptions, add all discovered wallets
    to their copy_trade_wallets (respecting their tier wallet limit).
    Returns count of wallets added.
    """
    from services.copy_trade_service import (
        add_tracked_wallet, get_tracked_wallets, MAX_WALLETS
    )

    subs  = await get_user_subscriptions(user_id)
    if not subs:
        return 0

    current = await get_tracked_wallets(user_id)
    slots   = MAX_WALLETS - len(current)
    if slots <= 0:
        return 0

    added = 0
    existing_addrs = {w["wallet_address"] for w in current}

    for preset_key in subs:
        wallets = await get_preset_wallets(preset_key)
        for w in wallets:
            addr = w["wallet_address"]
            if addr in existing_addrs:
                continue
            if added >= slots:
                break
            label = f"{PRESET_LABELS.get(preset_key, preset_key)} (auto)"
            ok, _ = await add_tracked_wallet(user_id, addr, label=label)
            if ok:
                existing_addrs.add(addr)
                added += 1

    return added


async def _sync_all_subscriber_copy_lists() -> None:
    """Sync copy trade wallets for every user who has an active subscription."""
    async with get_db() as db:
        async with db.execute(
            "SELECT DISTINCT user_id FROM wallet_preset_subscriptions WHERE active = 1"
        ) as cur:
            rows = await cur.fetchall()

    user_ids = [r["user_id"] for r in rows]
    for uid in user_ids:
        try:
            added = await _sync_user_copy_list(uid)
            if added:
                logger.info(f"Discovery sync: added {added} wallets for user={uid}")
        except Exception as e:
            logger.warning(f"Discovery sync error user={uid}: {e}")


# ── Subscriber Notifications ──────────────────────────────────────────────────

async def _notify_subscribers(bot: Bot, presets: dict[str, list[dict]]) -> None:
    """
    Send a Telegram notification to every user subscribed to at least one
    preset whose wallets were refreshed this run.
    """
    async with get_db() as db:
        async with db.execute(
            "SELECT DISTINCT user_id FROM wallet_preset_subscriptions WHERE active = 1"
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        return

    subs_by_user: dict[int, list[str]] = defaultdict(list)
    async with get_db() as db:
        async with db.execute(
            "SELECT user_id, preset_key FROM wallet_preset_subscriptions WHERE active = 1"
        ) as cur:
            sub_rows = await cur.fetchall()

    for r in sub_rows:
        subs_by_user[r["user_id"]].append(r["preset_key"])

    import datetime
    date_str = datetime.datetime.utcnow().strftime("%b %d")

    for user_id, user_presets in subs_by_user.items():
        lines = [
            f"🧠 <b>Dragon Intel Refresh — {date_str}</b>\n",
            "Your copy trade wallets have been updated with today's smart money:\n",
        ]
        for pk in user_presets:
            label  = PRESET_LABELS.get(pk, pk)
            bucket = presets.get(pk) or []
            if not bucket:
                continue
            top    = bucket[0]
            wr_pct = top["win_rate"] * 100
            pnl    = top["pnl_7d"]
            lines.append(
                f"  {label}: "
                f"top wallet {wr_pct:.0f}% WR, ${pnl:,.0f} 7d PnL"
            )
        lines.append(
            "\n<i>Open Wallet Scout → Dragon Presets to manage subscriptions.</i>"
        )
        try:
            await bot.send_message(user_id, "\n".join(lines), disable_web_page_preview=True)
        except Exception as e:
            logger.debug(f"Discovery notify failed user={user_id}: {e}")
