"""
services/raid_hub_service.py
============================
All database operations for the user-generated Raid Hub.
Handles: hub_raids, hub_participants, users tables.

Point awarding is delegated to points_service.py.
"""

import aiosqlite
import logging
from datetime import datetime, timedelta
from typing import Optional

from database.sqlite_db import get_db
from services.points_service import (
    award_points,
    get_user_points,
    get_user_rank,
    POINTS_CREATE_RAID,
    POINTS_JOIN_RAID,
    POINTS_COMPLETE_RAID,
    POINTS_CREATOR_BONUS,
)

logger = logging.getLogger(__name__)

HUB_PER_PAGE = 5


# ══════════════════════════════════════════════════════════════════════════════
# USER REGISTRATION
# ══════════════════════════════════════════════════════════════════════════════

async def ensure_user_exists(
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
) -> None:
    """
    Upserts a user into the users table.
    Called at the start of any meaningful hub interaction.
    """
    async with get_db() as db:
        await db.execute("""
            INSERT INTO users (telegram_user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                username   = excluded.username,
                first_name = excluded.first_name
        """, (user_id, username, first_name))
        await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# RAID CREATION
# ══════════════════════════════════════════════════════════════════════════════

async def count_user_raids_today(user_id: int) -> int:
    """How many hub raids has this user created today?"""
    async with get_db() as db:
        async with db.execute("""
            SELECT COUNT(*) FROM hub_raids
            WHERE creator_user_id = ?
              AND date(created_at) = date('now')
        """, (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def create_hub_raid(
    creator_id: int,
    creator_username: str,
    title: str,
    platform: str,
    target_link: str,
    instructions: str,
    comment_ideas: Optional[str],
    hashtag_ideas: Optional[str],
    expiry_hours: int,
    auto_approve: bool,
) -> int:
    """
    Inserts a new hub raid and awards the creator points.
    Returns the new raid's ID.
    """
    expiry_at = datetime.utcnow() + timedelta(hours=expiry_hours)
    status = "active" if auto_approve else "pending"
    approved_at = datetime.utcnow().isoformat() if auto_approve else None

    async with get_db() as db:
        cursor = await db.execute("""
            INSERT INTO hub_raids
                (creator_user_id, title, platform, target_link, instructions,
                 comment_ideas, hashtag_ideas, expiry_at, reward_points,
                 status, approved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            creator_id, title, platform, target_link, instructions,
            comment_ideas, hashtag_ideas, expiry_at.isoformat(),
            POINTS_COMPLETE_RAID,
            status,
            approved_at,
        ))
        await db.commit()
        raid_id = cursor.lastrowid

    await award_points(creator_id, POINTS_CREATE_RAID, creator_username)
    logger.info(f"Hub raid created: '{title}' (ID: {raid_id}) by user {creator_id}")
    return raid_id


# ══════════════════════════════════════════════════════════════════════════════
# RAID QUERIES
# ══════════════════════════════════════════════════════════════════════════════

async def _expire_stale_raids(db) -> None:
    """Marks expired active raids as 'expired'. Run before listing."""
    await db.execute("""
        UPDATE hub_raids
        SET status = 'expired'
        WHERE status = 'active'
          AND expiry_at < CURRENT_TIMESTAMP
    """)
    await db.commit()


async def get_active_hub_raids(
    page: int = 0,
) -> tuple[list[dict], int]:
    """
    Returns (raids_on_page, total_active_count).
    Featured raids appear first.
    """
    prem_filter = ""

    async with get_db() as db:
        await _expire_stale_raids(db)

        async with db.execute(f"""
            SELECT COUNT(*) FROM hub_raids hr
            WHERE hr.status = 'active' {prem_filter}
        """) as cursor:
            total = (await cursor.fetchone())[0]

        async with db.execute(f"""
            SELECT hr.*, u.username AS creator_username
            FROM hub_raids hr
            LEFT JOIN users u ON hr.creator_user_id = u.telegram_user_id
            WHERE hr.status = 'active' {prem_filter}
            ORDER BY hr.featured DESC, hr.created_at DESC
            LIMIT ? OFFSET ?
        """, (HUB_PER_PAGE, page * HUB_PER_PAGE)) as cursor:
            rows = await cursor.fetchall()

    return [dict(r) for r in rows], total


async def get_hub_raid(raid_id: int) -> Optional[dict]:
    """Fetch a single hub raid with creator username."""
    async with get_db() as db:
        async with db.execute("""
            SELECT hr.*, u.username AS creator_username
            FROM hub_raids hr
            LEFT JOIN users u ON hr.creator_user_id = u.telegram_user_id
            WHERE hr.id = ?
        """, (raid_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def is_participant(raid_id: int, user_id: int) -> bool:
    async with get_db() as db:
        async with db.execute(
            "SELECT 1 FROM hub_participants WHERE raid_id = ? AND user_id = ?",
            (raid_id, user_id),
        ) as cursor:
            return await cursor.fetchone() is not None


async def has_completed_raid(raid_id: int, user_id: int) -> bool:
    async with get_db() as db:
        async with db.execute(
            "SELECT 1 FROM hub_participants WHERE raid_id = ? AND user_id = ? AND status = 'completed'",
            (raid_id, user_id),
        ) as cursor:
            return await cursor.fetchone() is not None


async def get_hub_participant_count(raid_id: int) -> int:
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM hub_participants WHERE raid_id = ?", (raid_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def get_hub_completion_count(raid_id: int) -> int:
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM hub_participants WHERE raid_id = ? AND status = 'completed'",
            (raid_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def get_my_hub_raids(user_id: int) -> list[dict]:
    async with get_db() as db:
        async with db.execute("""
            SELECT
                hr.*,
                (SELECT COUNT(*) FROM hub_participants hp WHERE hp.raid_id = hr.id) AS join_count,
                (SELECT COUNT(*) FROM hub_participants hp
                 WHERE hp.raid_id = hr.id AND hp.status = 'completed')             AS completion_count
            FROM hub_raids hr
            WHERE hr.creator_user_id = ?
            ORDER BY hr.created_at DESC
        """, (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_joined_hub_raids(user_id: int) -> list[dict]:
    async with get_db() as db:
        async with db.execute("""
            SELECT
                hr.id, hr.title, hr.platform, hr.status AS raid_status,
                hp.status AS participation_status,
                hp.joined_at, hp.completed_at
            FROM hub_participants hp
            JOIN hub_raids hr ON hp.raid_id = hr.id
            WHERE hp.user_id = ?
            ORDER BY hp.joined_at DESC
        """, (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# PARTICIPATION
# ══════════════════════════════════════════════════════════════════════════════

async def join_hub_raid(
    raid_id: int,
    user_id: int,
    username: str,
) -> tuple[bool, str]:
    """
    Joins a raid. Returns (success, message).
    Awards join points on success.
    """
    raid = await get_hub_raid(raid_id)
    if not raid:
        return False, "Raid not found."
    if raid["status"] != "active":
        return False, "This raid is no longer accepting participants."
    if raid["creator_user_id"] == user_id:
        return False, "You cannot join your own raid."
    if await is_participant(raid_id, user_id):
        return False, "You have already joined this raid."

    try:
        async with get_db() as db:
            await db.execute("""
                INSERT INTO hub_participants (raid_id, user_id, status)
                VALUES (?, ?, 'joined')
            """, (raid_id, user_id))
            await db.commit()
    except aiosqlite.IntegrityError:
        return False, "You have already joined this raid."

    await award_points(user_id, POINTS_JOIN_RAID, username)
    logger.info(f"User {user_id} joined hub raid {raid_id} (+{POINTS_JOIN_RAID} pts)")
    return True, "Joined!"


async def complete_hub_raid(
    raid_id: int,
    user_id: int,
    username: str,
    proof_text: Optional[str] = None,
) -> tuple[bool, str, int]:
    """
    Marks a raid as completed. Returns (success, message, points_awarded).
    Awards completion points to the completer and bonus to the creator.
    """
    if not await is_participant(raid_id, user_id):
        return False, "You must join the raid before marking it complete.", 0
    if await has_completed_raid(raid_id, user_id):
        return False, "You have already completed this raid.", 0

    raid = await get_hub_raid(raid_id)
    if not raid:
        return False, "Raid not found.", 0
    if raid["status"] != "active":
        return False, "This raid is no longer active.", 0

    points = POINTS_COMPLETE_RAID

    async with get_db() as db:
        await db.execute("""
            UPDATE hub_participants
            SET status       = 'completed',
                completed_at = CURRENT_TIMESTAMP,
                proof_text   = ?
            WHERE raid_id = ? AND user_id = ?
        """, (proof_text, raid_id, user_id))
        await db.commit()

    await award_points(user_id, points, username)

    # Creator bonus
    creator_id = raid["creator_user_id"]
    creator_name = raid.get("creator_username") or ""
    await award_points(creator_id, POINTS_CREATOR_BONUS, creator_name)

    logger.info(f"User {user_id} completed hub raid {raid_id} (+{points} pts)")
    return True, "Completed!", points


# ══════════════════════════════════════════════════════════════════════════════
# STATS
# ══════════════════════════════════════════════════════════════════════════════

async def get_user_hub_stats(user_id: int, username: str) -> dict:
    """Full stats for the My Points page."""
    total_points  = await get_user_points(user_id)
    rank          = await get_user_rank(user_id)
    my_raids      = await get_my_hub_raids(user_id)
    joined_raids  = await get_joined_hub_raids(user_id)

    raids_completed = sum(
        1 for r in joined_raids if r["participation_status"] == "completed"
    )

    return {
        "username":       username,
        "total_points":   total_points,
        "rank":           rank,
        "raids_created":  len(my_raids),
        "raids_joined":   len(joined_raids),
        "raids_completed": raids_completed,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════

async def get_pending_hub_raids() -> list[dict]:
    async with get_db() as db:
        async with db.execute("""
            SELECT hr.*, u.username AS creator_username
            FROM hub_raids hr
            LEFT JOIN users u ON hr.creator_user_id = u.telegram_user_id
            WHERE hr.status = 'pending'
            ORDER BY hr.created_at ASC
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def approve_hub_raid(raid_id: int, admin_id: int) -> bool:
    async with get_db() as db:
        cursor = await db.execute("""
            UPDATE hub_raids
            SET status = 'active', approved_at = CURRENT_TIMESTAMP, approved_by = ?
            WHERE id = ? AND status = 'pending'
        """, (admin_id, raid_id))
        await db.commit()
        return cursor.rowcount > 0


async def reject_hub_raid(raid_id: int) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE hub_raids SET status = 'rejected' WHERE id = ? AND status = 'pending'",
            (raid_id,),
        )
        await db.commit()
        return cursor.rowcount > 0


async def close_hub_raid(raid_id: int) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE hub_raids SET status = 'closed' WHERE id = ? AND status IN ('active','pending')",
            (raid_id,),
        )
        await db.commit()
        return cursor.rowcount > 0


async def toggle_feature_hub_raid(raid_id: int) -> Optional[bool]:
    """Toggles featured flag. Returns new state or None if raid not found."""
    async with get_db() as db:
        async with db.execute(
            "SELECT featured FROM hub_raids WHERE id = ?", (raid_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            new_val = 0 if row[0] else 1

        await db.execute(
            "UPDATE hub_raids SET featured = ? WHERE id = ?", (new_val, raid_id)
        )
        await db.commit()
        return bool(new_val)


async def get_hub_raid_stats() -> dict:
    async with get_db() as db:
        async def count(query: str) -> int:
            async with db.execute(query) as c:
                return (await c.fetchone())[0]

        return {
            "total_raids":       await count("SELECT COUNT(*) FROM hub_raids"),
            "active_raids":      await count("SELECT COUNT(*) FROM hub_raids WHERE status='active'"),
            "pending_raids":     await count("SELECT COUNT(*) FROM hub_raids WHERE status='pending'"),
            "closed_raids":      await count("SELECT COUNT(*) FROM hub_raids WHERE status='closed'"),
            "total_joins":       await count("SELECT COUNT(*) FROM hub_participants"),
            "total_completions": await count("SELECT COUNT(*) FROM hub_participants WHERE status='completed'"),
            "unique_raiders":    await count("SELECT COUNT(DISTINCT user_id) FROM hub_participants"),
            "total_users":       await count("SELECT COUNT(*) FROM users"),
        }
