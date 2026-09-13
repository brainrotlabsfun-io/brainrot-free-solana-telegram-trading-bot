"""
services/points_service.py
==========================
Point tracking for the Raid Hub.
Uses the user_points table.

Point constants are defined here and imported by raid_hub_service.py.
"""

import logging
from typing import Optional

from database.sqlite_db import get_db

logger = logging.getLogger(__name__)

# ── Point Constants ────────────────────────────────────────────────────────────
POINTS_CREATE_RAID   = 5    # For publishing a raid
POINTS_JOIN_RAID     = 2    # For joining any raid
POINTS_COMPLETE_RAID = 10   # For marking a raid complete
POINTS_CREATOR_BONUS = 1    # Awarded to creator per completion of their raid

# Premium users earn this multiplier on completion points
PREMIUM_MULTIPLIER   = 2


async def award_points(user_id: int, points: int, username: Optional[str] = None) -> None:
    """
    Add points to a user's running total.
    Creates the row if the user has no points record yet.
    """
    async with get_db() as db:
        await db.execute("""
            INSERT INTO user_points (user_id, username, total_points, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                total_points = total_points + ?,
                updated_at   = CURRENT_TIMESTAMP,
                username     = COALESCE(?, username)
        """, (user_id, username, points, points, username))
        await db.commit()


async def get_user_points(user_id: int) -> int:
    """Returns a user's current total points (0 if no record)."""
    async with get_db() as db:
        async with db.execute(
            "SELECT total_points FROM user_points WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def get_user_rank(user_id: int) -> Optional[int]:
    """
    Returns the user's 1-based leaderboard rank.
    Returns None if the user has no points record.
    """
    async with get_db() as db:
        async with db.execute(
            "SELECT total_points FROM user_points WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            user_pts = row[0]

        async with db.execute(
            "SELECT COUNT(*) + 1 FROM user_points WHERE total_points > ?", (user_pts,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 1


async def get_leaderboard(limit: int = 10) -> list[dict]:
    """Returns top N users by total points, ranked 1-based."""
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    async with get_db() as db:
        async with db.execute("""
            SELECT user_id, username, total_points
            FROM user_points
            ORDER BY total_points DESC
            LIMIT ?
        """, (limit,)) as cursor:
            rows = await cursor.fetchall()

    result = []
    for i, row in enumerate(rows, 1):
        result.append({
            "rank":         i,
            "medal":        medals.get(i, f"{i}."),
            "username":     row["username"] or f"User{row['user_id']}",
            "total_points": row["total_points"],
        })
    return result
