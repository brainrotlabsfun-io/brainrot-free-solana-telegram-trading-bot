"""
services/auto_buy_service.py
==============================
Auto-buy settings management and job queue.
Actual on-chain execution is in solana_execution_service.py.

Risk controls enforced:
  - max buy size via entitlements
  - max buys per hour via entitlements + cooldown
  - kill switch
  - low-balance protection
  - blacklist enforcement
  - duplicate token prevention per session
"""

import logging
from typing import Optional
from database.sqlite_db import get_db
from utils.config import settings

logger = logging.getLogger(__name__)

DEFAULTS = {
    "enabled":               0,
    "max_buy_size_sol":      0.05,
    "max_buys_per_hour":     5,
    "score_threshold":       40,   # 40+ triggers DexScreener lookup for real vol/buys data
    "slippage":              18.0,
    "priority_fee":          0.005,
    "cooldown_seconds":      60,
    "min_initial_buy_sol":   0.1,  # 0.1 SOL in bonding curve — filters ~90% of rug launches
    "kill_switch":           0,
    "liq_exit_preset_id":    None,
    "min_wallet_balance_sol":  0.05,
    "daily_spend_limit_sol":   0.0,
    "min_market_cap_usd":      0.0,    # 0 = no filter
    "max_market_cap_usd":      0.0,    # 0 = no filter
}


async def get_auto_buy_settings(user_id: int) -> dict:
    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO auto_buy_settings (user_id) VALUES (?)", (user_id,)
        )
        await db.commit()
        async with db.execute(
            "SELECT * FROM auto_buy_settings WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        return {**DEFAULTS, "user_id": user_id}

    result = dict(row)
    # Sanitise bad values that may have slipped in from early DB rows
    if int(result.get("score_threshold") or 0) < 1:
        result["score_threshold"] = DEFAULTS["score_threshold"]
        await update_auto_buy_field(user_id, "score_threshold", DEFAULTS["score_threshold"])
    if float(result.get("max_buy_size_sol") or 0) <= 0:
        result["max_buy_size_sol"] = DEFAULTS["max_buy_size_sol"]
    if float(result.get("priority_fee") or 0) < 0.001:
        result["priority_fee"] = DEFAULTS["priority_fee"]
    # Slippage of ≤1.5% causes almost all pump.fun buys to fail; bump it up
    if float(result.get("slippage") or 0) < 5.0:
        result["slippage"] = DEFAULTS["slippage"]
        await update_auto_buy_field(user_id, "slippage", DEFAULTS["slippage"])
    return result


async def update_auto_buy_field(user_id: int, field: str, value) -> bool:
    allowed = set(DEFAULTS.keys())
    if field not in allowed:
        return False
    async with get_db() as db:
        await db.execute(f"""
            INSERT INTO auto_buy_settings (user_id, {field})
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                {field} = ?,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, value, value))
        await db.commit()
    return True


async def toggle_auto_buy(user_id: int) -> bool:
    """Toggles auto-buy on/off. Returns new enabled state.
    When turning ON, also clears the kill switch so a previous kill does not silently block buys."""
    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO auto_buy_settings (user_id) VALUES (?)", (user_id,)
        )
        await db.commit()  # flush insert before reading
        async with db.execute(
            "SELECT enabled FROM auto_buy_settings WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            current = row[0] if row else 0
        new_val = 0 if current else 1
        if new_val == 1:
            # Turning ON — clear kill switch so it doesn't silently block execution
            await db.execute(
                "UPDATE auto_buy_settings SET enabled = 1, kill_switch = 0, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (user_id,),
            )
        else:
            await db.execute(
                "UPDATE auto_buy_settings SET enabled = 0, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (user_id,),
            )
        await db.commit()
    return bool(new_val)


async def toggle_kill_switch(user_id: int) -> bool:
    """Activates or deactivates the kill switch. Returns new state."""
    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO auto_buy_settings (user_id) VALUES (?)", (user_id,)
        )
        async with db.execute(
            "SELECT kill_switch FROM auto_buy_settings WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            current = row[0] if row else 0
        new_val = 0 if current else 1
        await db.execute(
            "UPDATE auto_buy_settings SET kill_switch = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (new_val, user_id),
        )
        await db.commit()
    return bool(new_val)


async def count_buys_last_hour(user_id: int) -> int:
    """Returns number of submitted auto-buy jobs in the last 60 minutes."""
    async with get_db() as db:
        async with db.execute("""
            SELECT COUNT(*) FROM auto_buy_jobs
            WHERE user_id = ?
              AND created_at >= datetime('now', '-1 hour')
              AND status NOT IN ('failed', 'cancelled')
        """, (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def log_auto_buy_job(
    user_id: int,
    token_address: str,
    amount_sol: float = 0.0,
    score: int = 0,
    source: str = "auto_buy",
) -> int:
    """Creates a new auto_buy_job entry. Returns job ID."""
    async with get_db() as db:
        cursor = await db.execute("""
            INSERT INTO auto_buy_jobs (user_id, token_address, amount_sol, score, status, source)
            VALUES (?, ?, ?, ?, 'queued', ?)
        """, (user_id, token_address, amount_sol, score, source))
        await db.commit()
        return cursor.lastrowid


async def update_job_status(job_id: int, status: str) -> None:
    async with get_db() as db:
        try:
            await db.execute(
                "UPDATE auto_buy_jobs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, job_id),
            )
        except Exception:
            # updated_at column may not exist on older DB — fall back
            await db.execute(
                "UPDATE auto_buy_jobs SET status = ? WHERE id = ?",
                (status, job_id),
            )
        await db.commit()


async def get_liq_sniper_jobs(user_id: int, limit: int = 30) -> list[dict]:
    """Returns recent auto_buy_jobs tagged as 'liq_sniper' for this user."""
    async with get_db() as db:
        async with db.execute("""
            SELECT id, token_address, amount_sol, score, status, created_at
            FROM auto_buy_jobs
            WHERE user_id = ? AND source = 'liq_sniper'
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_id, limit)) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]


def validate_auto_buy_settings(settings: dict, entitlements) -> list[str]:
    """
    Returns a list of validation errors.
    Empty list = all good.
    """
    errors = []
    max_allowed = entitlements.max_buy_size_limit_sol
    buy_size = float(settings.get("max_buy_size_sol", 0))

    if buy_size <= 0:
        errors.append("Max buy size must be > 0 SOL.")
    if buy_size > max_allowed:
        errors.append(f"Max buy size exceeds your tier limit ({max_allowed} SOL).")

    score_threshold = int(settings.get("score_threshold", 0))
    if not (1 <= score_threshold <= 100):
        errors.append("Score threshold must be 1–100.")

    slippage = float(settings.get("slippage", 0))
    if not (0.1 <= slippage <= 50):
        errors.append("Slippage must be between 0.1% and 50%.")

    cooldown = int(settings.get("cooldown_seconds", 0))
    if cooldown < 0:
        errors.append("Cooldown must be >= 0 seconds.")

    return errors
