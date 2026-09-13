"""
services/premium_service.py
===========================
Premium user access control for the Raid Hub.

Current implementation: manual allowlist managed by admin commands.
Future: replace is_premium() with on-chain $BRAINROT token verification.

Token contract: configured via BRAINROT_MINT in .env
"""

import logging
from typing import Optional

from database.sqlite_db import get_db

logger = logging.getLogger(__name__)


async def is_premium(user_id: int) -> bool:
    """
    Returns True if the user currently has active premium access.

    Replace this body with on-chain token verification when ready:
    from services.brainrot_gate import check_brainrot_holder
    wallet = await get_linked_wallet(user_id)
    return await check_brainrot_holder(wallet) if wallet else False
    """
    async with get_db() as db:
        async with db.execute(
            "SELECT 1 FROM premium_users WHERE user_id = ? AND active = 1", (user_id,)
        ) as cursor:
            return await cursor.fetchone() is not None


async def grant_premium(user_id: int, entitlement_type: str = "manual") -> bool:
    """Grant premium access to a user. Creates or reactivates their record."""
    async with get_db() as db:
        await db.execute("""
            INSERT INTO premium_users (user_id, active, entitlement_type)
            VALUES (?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                active           = 1,
                entitlement_type = ?
        """, (user_id, entitlement_type, entitlement_type))
        await db.commit()
    logger.info(f"Premium granted: user {user_id} ({entitlement_type})")
    return True


async def revoke_premium(user_id: int) -> bool:
    """Revoke premium access. Returns True if the user record existed."""
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE premium_users SET active = 0 WHERE user_id = ?", (user_id,)
        )
        await db.commit()
        changed = cursor.rowcount > 0
    if changed:
        logger.info(f"Premium revoked: user {user_id}")
    return changed


async def get_all_premium_users() -> list[dict]:
    """Returns all users with active premium access."""
    async with get_db() as db:
        async with db.execute("""
            SELECT pu.user_id, pu.entitlement_type, pu.created_at,
                   u.username, u.first_name
            FROM premium_users pu
            LEFT JOIN users u ON pu.user_id = u.telegram_user_id
            WHERE pu.active = 1
            ORDER BY pu.created_at DESC
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
