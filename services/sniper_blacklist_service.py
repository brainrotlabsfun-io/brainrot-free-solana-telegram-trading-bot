"""
services/sniper_blacklist_service.py
======================================
Manages per-user token blacklist.
Blacklisted tokens are excluded from feeds and ranked candidates.
"""

from database.sqlite_db import get_db


async def get_blacklist(user_id: int) -> list[dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM sniper_blacklist WHERE user_id = ? ORDER BY added_at DESC",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_blacklist_addresses(user_id: int) -> list[str]:
    """Returns just the token addresses (used for filtering feeds)."""
    async with get_db() as db:
        async with db.execute(
            "SELECT token_address FROM sniper_blacklist WHERE user_id = ?", (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]


async def count_blacklist(user_id: int) -> int:
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM sniper_blacklist WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def add_to_blacklist(user_id: int, token_address: str, label: str = "") -> tuple[bool, str]:
    try:
        async with get_db() as db:
            await db.execute(
                "INSERT INTO sniper_blacklist (user_id, token_address, label) VALUES (?,?,?)",
                (user_id, token_address.strip(), label.strip()),
            )
            await db.commit()
        return True, "Token blacklisted."
    except Exception:
        return False, "Already in your blacklist."


async def remove_from_blacklist(row_id: int, user_id: int) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM sniper_blacklist WHERE id = ? AND user_id = ?",
            (row_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def is_blacklisted(user_id: int, token_address: str) -> bool:
    async with get_db() as db:
        async with db.execute(
            "SELECT 1 FROM sniper_blacklist WHERE user_id = ? AND token_address = ?",
            (user_id, token_address),
        ) as cursor:
            return await cursor.fetchone() is not None


# ── Creator blacklist ──────────────────────────────────────────────────────────

async def get_creator_blacklist_addresses(user_id: int) -> set[str]:
    async with get_db() as db:
        async with db.execute(
            "SELECT creator_address FROM creator_blacklist WHERE user_id = ?", (user_id,)
        ) as cursor:
            return {r[0] for r in await cursor.fetchall()}


async def add_creator_to_blacklist(user_id: int, creator_address: str, note: str = "") -> tuple[bool, str]:
    try:
        async with get_db() as db:
            await db.execute(
                "INSERT INTO creator_blacklist (user_id, creator_address, note) VALUES (?,?,?)",
                (user_id, creator_address.strip(), note),
            )
            await db.commit()
        return True, "Creator blacklisted."
    except Exception:
        return False, "Already in your creator blacklist."


async def remove_creator_from_blacklist(row_id: int, user_id: int) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM creator_blacklist WHERE id = ? AND user_id = ?",
            (row_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_creator_blacklist(user_id: int) -> list[dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM creator_blacklist WHERE user_id = ? ORDER BY added_at DESC",
            (user_id,),
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]
