"""
services/sniper_watch_service.py
==================================
Manages per-user sniper watch targets.
"""

from database.sqlite_db import get_db


async def get_watch_targets(user_id: int) -> list[dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM sniper_watch_targets WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def count_watch_targets(user_id: int) -> int:
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM sniper_watch_targets WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def add_watch_target(user_id: int, token_address: str) -> tuple[bool, str]:
    """Adds token to watch list. Returns (success, message)."""
    try:
        async with get_db() as db:
            await db.execute(
                "INSERT INTO sniper_watch_targets (user_id, token_address) VALUES (?,?)",
                (user_id, token_address.strip()),
            )
            await db.commit()
        return True, "Added to watch targets."
    except Exception:
        return False, "Already in your watch list."


async def remove_watch_target(row_id: int, user_id: int) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM sniper_watch_targets WHERE id = ? AND user_id = ?",
            (row_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def is_watching(user_id: int, token_address: str) -> bool:
    async with get_db() as db:
        async with db.execute(
            "SELECT 1 FROM sniper_watch_targets WHERE user_id = ? AND token_address = ?",
            (user_id, token_address),
        ) as cursor:
            return await cursor.fetchone() is not None


async def get_watch_target_by_id(row_id: int, user_id: int) -> dict | None:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM sniper_watch_targets WHERE id = ? AND user_id = ?",
            (row_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
    return dict(row) if row else None


async def update_watch_target_field(row_id: int, user_id: int, field: str, value) -> bool:
    allowed = {"alert_drop_pct", "alert_pump_pct", "quick_buy_sol", "alert_enabled", "token_symbol"}
    if field not in allowed:
        return False
    async with get_db() as db:
        cursor = await db.execute(
            f"UPDATE sniper_watch_targets SET {field} = ? WHERE id = ? AND user_id = ?",
            (value, row_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_all_alert_targets() -> list[dict]:
    """All watch targets with alerts enabled — used by price alert worker."""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM sniper_watch_targets WHERE alert_enabled = 1"
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def update_last_price(row_id: int, price_sol: float) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE sniper_watch_targets SET last_price_sol = ? WHERE id = ?",
            (price_sol, row_id),
        )
        await db.commit()


async def set_last_alerted(row_id: int) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE sniper_watch_targets SET last_alerted_at = CURRENT_TIMESTAMP WHERE id = ?",
            (row_id,),
        )
        await db.commit()
