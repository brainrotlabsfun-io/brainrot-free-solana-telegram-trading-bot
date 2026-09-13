"""
services/sniper_settings_service.py
=====================================
Manages per-user sniper settings in the sniper_settings table.
Provides defaults on first access.
"""

import logging
from database.sqlite_db import get_db

logger = logging.getLogger(__name__)

DEFAULTS = {
    "min_liquidity":              3_000.0,  # $3k+ liq — basic rug filter
    "min_volume":                 1_000.0,  # $1k+ vol — real trading activity
    "min_buys":                   8,        # 8 buy txns minimum
    "max_token_age_minutes":      60,       # 60min window — catches momentum not just brand-new
    "max_risk_level":             3,
    "default_buy_size":           0.05,
    "default_slippage":           18.0,
    "strict_mode":                0,
    "preferred_platform":         "auto",
    # SUPREME-only fields (stored for all, enforced by entitlements)
    "auto_filter_enabled":        0,
    "prioritize_fresh_launches":  0,
    "prioritize_liquidity_strength": 0,
    "auto_hide_weak_metadata":    0,
    "auto_hide_low_momentum":     0,
    "instant_alert_on_match":     0,
    "premium_ranking_boost":      0,
    # Strategy: "none" | "volume_spike" | "graduate_hunter" | "micro_cap_sweep" | "panic_ride" | "smart_project"
    "strategy_mode":              "volume_spike",  # default to momentum-aware scoring
}


async def get_settings(user_id: int) -> dict:
    """Returns user's sniper settings, inserting defaults if not yet present."""
    async with get_db() as db:
        await db.execute("""
            INSERT OR IGNORE INTO sniper_settings (user_id) VALUES (?)
        """, (user_id,))
        await db.commit()

        async with db.execute(
            "SELECT * FROM sniper_settings WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else {**DEFAULTS, "user_id": user_id}


async def update_setting(user_id: int, field: str, value) -> bool:
    """Updates a single setting field. Returns True on success."""
    allowed = set(DEFAULTS.keys())
    if field not in allowed:
        return False

    async with get_db() as db:
        await db.execute(f"""
            INSERT INTO sniper_settings (user_id, {field}, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                {field} = ?,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, value, value))
        await db.commit()
    return True


async def apply_preset_to_settings(user_id: int, preset: dict) -> None:
    """Overwrites user settings with values from a preset."""
    fields = [k for k in DEFAULTS if k in preset]
    if not fields:
        return
    set_clause = ", ".join(f"{f} = ?" for f in fields)
    values     = [preset[f] for f in fields] + [user_id]

    async with get_db() as db:
        await db.execute(f"""
            UPDATE sniper_settings
            SET {set_clause}, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, values)
        await db.commit()
