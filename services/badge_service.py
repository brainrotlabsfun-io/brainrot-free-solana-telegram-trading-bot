"""
services/badge_service.py
==========================
Badge award and management for the $BRAINROT burn-reward system.

Responsibilities:
  - Seed default badge_definitions on startup (idempotent)
  - Evaluate which badges a user now qualifies for after a burn
  - Award missing badges (no duplicate awards)
  - Update highest_badge_key in user_burn_stats
  - Return newly earned badges and next-badge progress
"""

import logging
from datetime import datetime
from typing import Optional

from database.sqlite_db import get_db
from utils.badge_config import (
    BADGE_META,
    BADGE_BURN_THRESHOLDS,
    BADGE_BURN_COUNT_REQUIREMENTS,
    BADGE_REQUIRES_ACTIVATION,
    CUMULATIVE_BADGE_LADDER,
    BADGE_INITIATE,
    BADGE_VERIFIED_BURNER,
    BADGE_SUPREME_ACTIVATED,
    BADGE_FOUNDING_BURNER,
)

logger = logging.getLogger(__name__)


async def init_default_badges() -> None:
    """
    Seeds badge_definitions table from BADGE_META constants.
    Safe to call on every startup — uses INSERT OR IGNORE.
    """
    async with get_db() as db:
        for key, meta in BADGE_META.items():
            await db.execute("""
                INSERT OR IGNORE INTO badge_definitions
                    (badge_key, badge_name, description, min_total_burn,
                     min_burn_count, requires_activation, icon, tier_rank, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                key,
                meta["name"],
                meta["description"],
                BADGE_BURN_THRESHOLDS.get(key, 0),
                BADGE_BURN_COUNT_REQUIREMENTS.get(key, 1),
                1 if BADGE_REQUIRES_ACTIVATION.get(key, False) else 0,
                meta["icon"],
                meta["tier_rank"],
            ))
        await db.commit()
    logger.info("Badge definitions seeded / verified.")


async def evaluate_and_award_badges(
    user_id:      int,
    total_burned: float,
    burn_count:   int,
    is_activated: bool,
    is_founding:  bool,
    source_tx:    Optional[str] = None,
) -> list[dict]:
    """
    Checks all active badge definitions and awards any the user now qualifies for.
    Never awards the same badge twice.
    Returns a list of newly awarded badge dicts.
    """
    async with get_db() as db:
        # Load definitions
        async with db.execute(
            "SELECT * FROM badge_definitions WHERE active = 1"
        ) as cur:
            definitions = [dict(r) for r in await cur.fetchall()]

        # Existing badges the user already holds
        async with db.execute(
            "SELECT badge_key FROM user_badges WHERE user_id = ? AND active = 1",
            (user_id,),
        ) as cur:
            existing = {r["badge_key"] for r in await cur.fetchall()}

        newly_awarded: list[dict] = []
        now = datetime.utcnow().isoformat()

        for badge in definitions:
            key = badge["badge_key"]

            if key in existing:
                continue  # Already earned

            # ── Badge-specific qualification logic ────────────────────────────
            if key == BADGE_FOUNDING_BURNER:
                if not is_founding:
                    continue

            elif key in (BADGE_INITIATE, BADGE_VERIFIED_BURNER):
                if burn_count < 1:
                    continue

            elif key == BADGE_SUPREME_ACTIVATED:
                if not is_activated:
                    continue

            else:
                # Cumulative threshold badges
                if total_burned < badge["min_total_burn"]:
                    continue
                if burn_count < badge["min_burn_count"]:
                    continue
                if badge["requires_activation"] and not is_activated:
                    continue

            # Award
            await db.execute("""
                INSERT OR IGNORE INTO user_badges
                    (user_id, badge_key, awarded_at, source_tx_signature, active)
                VALUES (?, ?, ?, ?, 1)
            """, (user_id, key, now, source_tx))

            newly_awarded.append({
                "badge_key":   key,
                "badge_name":  badge["badge_name"],
                "icon":        badge["icon"],
                "description": badge["description"],
                "tier_rank":   badge["tier_rank"],
            })
            logger.info(f"Badge awarded: user={user_id} badge={key}")

        if newly_awarded:
            await db.commit()
            await _update_highest_badge(user_id, db)

        return newly_awarded


async def _update_highest_badge(user_id: int, db) -> None:
    """Writes the highest-ranked earned badge to user_burn_stats."""
    async with db.execute("""
        SELECT ub.badge_key, bd.tier_rank
        FROM user_badges ub
        JOIN badge_definitions bd ON bd.badge_key = ub.badge_key
        WHERE ub.user_id = ? AND ub.active = 1
        ORDER BY bd.tier_rank DESC
        LIMIT 1
    """, (user_id,)) as cur:
        row = await cur.fetchone()

    if row:
        await db.execute("""
            UPDATE user_burn_stats
            SET highest_badge_key = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, (row["badge_key"], user_id))
        await db.commit()


async def get_user_badges(user_id: int) -> list[dict]:
    """Returns all earned badges for a user, highest rank first."""
    async with get_db() as db:
        async with db.execute("""
            SELECT ub.badge_key, ub.awarded_at, ub.source_tx_signature,
                   bd.badge_name, bd.icon, bd.description, bd.tier_rank
            FROM user_badges ub
            JOIN badge_definitions bd ON bd.badge_key = ub.badge_key
            WHERE ub.user_id = ? AND ub.active = 1
            ORDER BY bd.tier_rank DESC
        """, (user_id,)) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_next_badge_progress(
    user_id:      int,
    total_burned: float,
) -> Optional[dict]:
    """
    Returns progress info toward the next cumulative badge the user hasn't earned.
    Returns None when all cumulative badges are earned.
    """
    async with get_db() as db:
        async with db.execute(
            "SELECT badge_key FROM user_badges WHERE user_id = ? AND active = 1",
            (user_id,),
        ) as cur:
            earned = {r["badge_key"] for r in await cur.fetchall()}

    for badge_key in CUMULATIVE_BADGE_LADDER:
        if badge_key not in earned:
            threshold    = BADGE_BURN_THRESHOLDS[badge_key]
            meta         = BADGE_META[badge_key]
            progress_pct = (
                min(100, int((total_burned / threshold) * 100))
                if threshold > 0 else 100
            )
            return {
                "badge_key":    badge_key,
                "badge_name":   meta["name"],
                "icon":         meta["icon"],
                "threshold":    threshold,
                "current":      total_burned,
                "remaining":    max(0.0, threshold - total_burned),
                "progress_pct": progress_pct,
            }

    return None  # All cumulative badges earned
