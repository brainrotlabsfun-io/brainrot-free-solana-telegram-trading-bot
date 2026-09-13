"""
services/sniper_alert_service.py
==================================
Smart Alert settings management.
Actual alert delivery is triggered by the auto-buy / feed scanning loop.
"""

from database.sqlite_db import get_db


async def get_alert_settings(user_id: int) -> dict:
    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO sniper_alert_settings (user_id) VALUES (?)", (user_id,)
        )
        await db.commit()
        async with db.execute(
            "SELECT * FROM sniper_alert_settings WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else {"user_id": user_id, "enabled": 0}


async def toggle_alerts(user_id: int) -> bool:
    """Toggles alerts on/off. Returns new state (True = enabled)."""
    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO sniper_alert_settings (user_id) VALUES (?)", (user_id,)
        )
        async with db.execute(
            "SELECT enabled FROM sniper_alert_settings WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            current = row[0] if row else 0
        new_val = 0 if current else 1
        await db.execute(
            "UPDATE sniper_alert_settings SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (new_val, user_id),
        )
        await db.commit()
    return bool(new_val)


async def set_alerts_enabled(user_id: int, enabled: bool) -> None:
    async with get_db() as db:
        await db.execute("""
            INSERT INTO sniper_alert_settings (user_id, enabled)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET enabled = ?, updated_at = CURRENT_TIMESTAMP
        """, (user_id, int(enabled), int(enabled)))
        await db.commit()
