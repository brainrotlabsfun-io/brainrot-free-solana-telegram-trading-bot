"""
services/raid_service.py
========================
All database operations related to raids and raid participation.
Points are delegated to raid_points_service.py.
"""

import aiosqlite
import logging
from typing import Optional
from datetime import datetime, timedelta

from database.db import DB_PATH
from services.raid_points_service import award_points

logger = logging.getLogger(__name__)


# ── Read Operations ────────────────────────────────────────────────────────────

async def get_active_raid() -> Optional[dict]:
    """
    Returns the most recently created active raid, or None if none exist.
    Also auto-expires raids whose expires_at has passed.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Auto-expire any raids that have passed their expiry time
        await db.execute("""
            UPDATE raids
            SET active = 0
            WHERE active = 1
              AND expires_at IS NOT NULL
              AND expires_at < CURRENT_TIMESTAMP
        """)
        await db.commit()

        async with db.execute("""
            SELECT * FROM raids
            WHERE active = 1
            ORDER BY created_at DESC
            LIMIT 1
        """) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_raid_by_id(raid_id: int) -> Optional[dict]:
    """Returns a single raid by its ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM raids WHERE id = ?", (raid_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_all_raids_summary() -> list[dict]:
    """Returns all raids (active and ended) ordered by newest first."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT id, title, platform, active, reward_points, created_at
            FROM raids
            ORDER BY created_at DESC
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def has_user_completed_raid(user_id: int, raid_id: int) -> bool:
    """Returns True if the user has already completed this raid."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT 1 FROM raid_participants
            WHERE user_id = ? AND raid_id = ?
        """, (user_id, raid_id)) as cursor:
            return await cursor.fetchone() is not None


async def get_raid_participant_count(raid_id: int) -> int:
    """Returns the number of users who completed a given raid."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT COUNT(*) FROM raid_participants WHERE raid_id = ?
        """, (raid_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


# ── Write Operations ───────────────────────────────────────────────────────────

async def create_raid(
    title: str,
    platform: str,
    target_url: str,
    instructions: str,
    reward_points: int,
    expires_hours: int,
    created_by: int,
) -> int:
    """
    Inserts a new active raid into the database.
    Returns the new raid's ID.
    """
    expires_at = datetime.utcnow() + timedelta(hours=expires_hours)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO raids (title, target_url, platform, instructions, reward_points, created_by, expires_at, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """, (title, target_url, platform, instructions, reward_points, created_by, expires_at))
        await db.commit()
        logger.info(f"Raid created: '{title}' (ID: {cursor.lastrowid}) by admin {created_by}")
        return cursor.lastrowid


async def end_active_raids() -> int:
    """
    Sets all currently active raids to inactive.
    Returns the number of raids ended.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            UPDATE raids SET active = 0 WHERE active = 1
        """)
        await db.commit()
        count = cursor.rowcount
        logger.info(f"Ended {count} active raid(s).")
        return count


async def mark_raid_completed(
    raid_id: int,
    user_id: int,
    username: str,
    points: int,
) -> bool:
    """
    Records a user's raid completion and awards points.
    Returns True on success, False if already completed (race condition guard).
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO raid_participants (raid_id, user_id, username, points_awarded)
                VALUES (?, ?, ?, ?)
            """, (raid_id, user_id, username, points))
            await db.commit()

        # Award points in the raid_points table
        await award_points(user_id, username, points)
        logger.info(f"User {user_id} (@{username}) completed raid {raid_id} — +{points} pts")
        return True

    except aiosqlite.IntegrityError:
        # UNIQUE constraint hit — user already completed this raid
        return False
