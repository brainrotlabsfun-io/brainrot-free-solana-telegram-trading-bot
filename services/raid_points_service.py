"""
services/raid_points_service.py
================================
Handles all raid point aggregation, leaderboard queries, and user rank lookups.
"""

import aiosqlite
import logging
from typing import Optional

from database.db import DB_PATH

logger = logging.getLogger(__name__)


async def award_points(user_id: int, username: str, points: int) -> None:
    """
    Adds points to a user's total in the raid_points table.
    Creates the row if the user doesn't exist yet.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # INSERT OR IGNORE creates the row if missing, then UPDATE adds points
        await db.execute("""
            INSERT INTO raid_points (user_id, username, total_points)
            VALUES (?, ?, 0)
            ON CONFLICT(user_id) DO NOTHING
        """, (user_id, username))

        await db.execute("""
            UPDATE raid_points
            SET total_points = total_points + ?,
                username = ?
            WHERE user_id = ?
        """, (points, username, user_id))

        await db.commit()


async def get_user_points(user_id: int) -> int:
    """Returns a user's current total raid points (0 if not found)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT total_points FROM raid_points WHERE user_id = ?
        """, (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def get_user_rank(user_id: int) -> Optional[int]:
    """
    Returns the user's current leaderboard rank (1-based).
    Returns None if user has no points yet.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT COUNT(*) + 1
            FROM raid_points
            WHERE total_points > (
                SELECT COALESCE(total_points, 0)
                FROM raid_points
                WHERE user_id = ?
            )
        """, (user_id,)) as cursor:
            row = await cursor.fetchone()
            # Check if user exists in the table at all
            async with db.execute(
                "SELECT 1 FROM raid_points WHERE user_id = ?", (user_id,)
            ) as check:
                exists = await check.fetchone()
                if not exists:
                    return None
            return row[0] if row else None


async def get_user_raids_completed(user_id: int) -> int:
    """Returns the number of raids a user has completed."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT COUNT(*) FROM raid_participants WHERE user_id = ?
        """, (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def get_user_stats(user_id: int, username: str) -> dict:
    """
    Returns a full stats dict for a user:
    - raids_completed
    - total_points
    - rank
    """
    raids_completed = await get_user_raids_completed(user_id)
    total_points = await get_user_points(user_id)
    rank = await get_user_rank(user_id)

    return {
        "raids_completed": raids_completed,
        "total_points": total_points,
        "rank": rank,
        "username": username,
    }


async def get_leaderboard(limit: int = 10) -> list[dict]:
    """
    Returns the top N users by total_points, ordered descending.
    Each entry: {"rank": int, "username": str, "total_points": int}
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT user_id, username, total_points
            FROM raid_points
            ORDER BY total_points DESC
            LIMIT ?
        """, (limit,)) as cursor:
            rows = await cursor.fetchall()

        result = []
        for i, row in enumerate(rows, start=1):
            result.append({
                "rank": i,
                "username": row["username"] or f"User{row['user_id']}",
                "total_points": row["total_points"],
            })
        return result
