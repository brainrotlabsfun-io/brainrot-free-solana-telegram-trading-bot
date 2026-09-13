"""
services/sniper_presets_service.py
===================================
CRUD for sniper presets.
"""

import json
import logging
from typing import Optional
from database.sqlite_db import get_db

logger = logging.getLogger(__name__)

_SAVE_KEYS = [
    # sniper_settings — feed filtering
    "min_liquidity", "min_volume", "min_buys", "max_token_age_minutes",
    "max_risk_level", "default_buy_size", "default_slippage", "strict_mode",
    "preferred_platform", "auto_filter_enabled", "prioritize_fresh_launches",
    "prioritize_liquidity_strength", "auto_hide_weak_metadata",
    "auto_hide_low_momentum", "instant_alert_on_match", "premium_ranking_boost",
    "strategy_mode",
    # auto_buy_settings — execution behaviour (required for preset load to actually work)
    "score_threshold", "max_buy_size_sol", "slippage", "max_buys_per_hour",
    "cooldown_seconds", "priority_fee", "min_initial_buy_sol",
    "min_market_cap_usd", "max_market_cap_usd",
]

# Built-in starter preset templates
BUILTIN_TEMPLATES = [
    {
        "name": "Momentum",
        "min_liquidity": 10000, "min_volume": 5000, "min_buys": 30,
        "max_token_age_minutes": 30, "max_risk_level": 2,
        "default_buy_size": 0.1, "default_slippage": 15.0, "strict_mode": 1,
        "auto_filter_enabled": 1, "prioritize_fresh_launches": 0,
        "prioritize_liquidity_strength": 1, "auto_hide_weak_metadata": 1,
        "auto_hide_low_momentum": 1, "instant_alert_on_match": 1,
        "premium_ranking_boost": 1, "strategy_mode": "none",
    },
    {
        "name": "Fresh Launch Hunter",
        "min_liquidity": 1000, "min_volume": 500, "min_buys": 5,
        "max_token_age_minutes": 10, "max_risk_level": 4,
        "default_buy_size": 0.05, "default_slippage": 20.0, "strict_mode": 0,
        "auto_filter_enabled": 1, "prioritize_fresh_launches": 1,
        "prioritize_liquidity_strength": 0, "auto_hide_weak_metadata": 0,
        "auto_hide_low_momentum": 0, "instant_alert_on_match": 1,
        "premium_ranking_boost": 1, "strategy_mode": "none",
    },
    {
        "name": "Strict Filter",
        "min_liquidity": 25000, "min_volume": 10000, "min_buys": 80,
        "max_token_age_minutes": 60, "max_risk_level": 1,
        "default_buy_size": 0.2, "default_slippage": 10.0, "strict_mode": 1,
        "auto_filter_enabled": 1, "prioritize_fresh_launches": 0,
        "prioritize_liquidity_strength": 1, "auto_hide_weak_metadata": 1,
        "auto_hide_low_momentum": 1, "instant_alert_on_match": 1,
        "premium_ranking_boost": 1, "strategy_mode": "none",
    },
]


def _unpack(row: dict) -> dict:
    """Merge settings_json fields into the row dict."""
    blob = row.get("settings_json")
    if blob:
        try:
            row.update(json.loads(blob))
        except Exception:
            pass
    return row


async def get_presets(user_id: int) -> list[dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM sniper_presets WHERE user_id = ? ORDER BY created_at ASC",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [_unpack(dict(r)) for r in rows]


async def get_preset(preset_id: int, user_id: int) -> Optional[dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM sniper_presets WHERE id = ? AND user_id = ?",
            (preset_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
            return _unpack(dict(row)) if row else None


async def count_presets(user_id: int) -> int:
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM sniper_presets WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def create_preset_from_settings(
    user_id: int,
    name: str,
    settings: dict,
) -> int:
    """Saves current settings as a named preset. Returns new preset ID."""
    blob = json.dumps({k: settings[k] for k in _SAVE_KEYS if k in settings})
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO sniper_presets (user_id, name, settings_json) VALUES (?, ?, ?)",
            (user_id, name, blob),
        )
        await db.commit()
        return cursor.lastrowid


async def delete_preset(preset_id: int, user_id: int) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM sniper_presets WHERE id = ? AND user_id = ?",
            (preset_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_preset_pnl(user_id: int, preset_id: int, next_preset_at: str = None) -> dict:
    """
    Compute P&L for trades that opened while this preset was active.
    'Active' = from preset created_at until either next_preset_at or now.
    Returns: {total_pnl, trades, wins, losses, win_rate}
    """
    async with get_db() as db:
        async with db.execute(
            "SELECT created_at FROM sniper_presets WHERE id = ? AND user_id = ?",
            (preset_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return {"total_pnl": 0.0, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0}

        from_dt  = row[0]
        until_dt = next_preset_at or "9999-12-31"

        async with db.execute("""
            SELECT
                COUNT(DISTINCT tp.id)                                       AS trades,
                COALESCE(SUM(pe.pnl_sol), 0.0)                             AS total_pnl,
                SUM(CASE WHEN pe.pnl_sol > 0 THEN 1 ELSE 0 END)           AS wins,
                SUM(CASE WHEN pe.pnl_sol < 0 THEN 1 ELSE 0 END)           AS losses
            FROM tracked_positions tp
            JOIN position_events pe ON pe.position_id = tp.id
            WHERE tp.user_id = ?
              AND tp.opened_at >= ?
              AND tp.opened_at <  ?
        """, (user_id, from_dt, until_dt)) as cur:
            r = await cur.fetchone()

    if not r or r[0] == 0:
        return {"total_pnl": 0.0, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0}

    trades   = r[0] or 0
    total    = float(r[1] or 0.0)
    wins     = r[2] or 0
    losses   = r[3] or 0
    win_rate = (wins / trades * 100) if trades > 0 else 0.0
    return {"total_pnl": total, "trades": trades, "wins": wins, "losses": losses, "win_rate": win_rate}


async def get_presets_with_pnl(user_id: int) -> list[dict]:
    """Returns all presets for a user, each enriched with P&L stats, sorted by P&L desc."""
    presets = await get_presets(user_id)
    if not presets:
        return []

    # Build time windows: each preset is active from its created_at until the next one
    for i, p in enumerate(presets):
        next_at = presets[i + 1]["created_at"] if i + 1 < len(presets) else None
        pnl     = await get_preset_pnl(user_id, p["id"], next_at)
        p.update(pnl)

    # Sort by total_pnl descending so best performer is first
    presets.sort(key=lambda x: x.get("total_pnl", 0.0), reverse=True)
    return presets
