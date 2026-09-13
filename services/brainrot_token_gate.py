"""
services/brainrot_token_gate.py
================================
BRAINROT token-gated access control for the Sniper Tool.

Tiers:
  free          — basic sniper access, limited automation
  supreme       — $BRAINROT holder, full sniper access + advanced automation
  supreme_black — top tier, includes Auto-Exit Manager + all supreme features

Current implementation: database-backed manual allowlist.
Future: replace is_supreme_holder() body with on-chain Solana token
        balance verification against the $BRAINROT contract.

$BRAINROT Contract: <your-token-mint>
"""

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Optional

from database.sqlite_db import get_db
from utils.config import settings

logger = logging.getLogger(__name__)

BRAINROT_CONTRACT = settings.BRAINROT_MINT


# ── Entitlement Model ──────────────────────────────────────────────────────────

@dataclass
class SniperEntitlements:
    tier:                     str    # "free" | "supreme" | "supreme_black"
    is_holder:                bool
    has_supreme_access:       bool
    has_supreme_black:        bool   # Supreme Black tier — unlocks Auto-Exit Manager
    auto_buy_enabled_allowed: bool
    max_buy_size_limit_sol:   float
    max_buys_per_hour_limit:  int
    watch_targets_limit:      int
    presets_limit:            int
    blacklist_limit:          int
    feed_result_limit:        int
    has_basic_alerts:         bool
    has_smart_alerts:         bool
    has_advanced_filtering:   bool
    has_priority_ranking:     bool
    has_auto_exit:            bool   # Auto-Exit Manager access

    def to_dict(self) -> dict:
        return {
            "tier":                    self.tier,
            "is_holder":               self.is_holder,
            "has_supreme_access":      self.has_supreme_access,
            "has_supreme_black":       self.has_supreme_black,
            "auto_buy_enabled_allowed": self.auto_buy_enabled_allowed,
            "max_buy_size_limit_sol":  self.max_buy_size_limit_sol,
            "max_buys_per_hour_limit": self.max_buys_per_hour_limit,
            "watch_targets_limit":     self.watch_targets_limit,
            "presets_limit":           self.presets_limit,
            "blacklist_limit":         self.blacklist_limit,
            "feed_result_limit":       self.feed_result_limit,
            "has_basic_alerts":        self.has_basic_alerts,
            "has_smart_alerts":        self.has_smart_alerts,
            "has_advanced_filtering":  self.has_advanced_filtering,
            "has_priority_ranking":    self.has_priority_ranking,
            "has_auto_exit":           self.has_auto_exit,
        }


# ── Entitlement Factory ────────────────────────────────────────────────────────

def _build_free() -> SniperEntitlements:
    return SniperEntitlements(
        tier                     = "free",
        is_holder                = False,
        has_supreme_access       = False,
        has_supreme_black        = False,
        auto_buy_enabled_allowed = True,
        max_buy_size_limit_sol   = settings.FREE_MAX_BUY_SOL,
        max_buys_per_hour_limit  = settings.FREE_MAX_BUYS_PER_HOUR,
        watch_targets_limit      = settings.FREE_WATCH_LIMIT,
        presets_limit            = settings.FREE_PRESETS_LIMIT,
        blacklist_limit          = settings.FREE_BLACKLIST_LIMIT,
        feed_result_limit        = settings.FREE_FEED_LIMIT,
        has_basic_alerts         = True,
        has_smart_alerts         = False,
        has_advanced_filtering   = False,
        has_priority_ranking     = False,
        has_auto_exit            = False,
    )


def _build_supreme() -> SniperEntitlements:
    return SniperEntitlements(
        tier                     = "supreme",
        is_holder                = True,
        has_supreme_access       = True,
        has_supreme_black        = False,
        auto_buy_enabled_allowed = True,
        max_buy_size_limit_sol   = settings.SUPREME_MAX_BUY_SOL,
        max_buys_per_hour_limit  = settings.SUPREME_MAX_BUYS_PER_HOUR,
        watch_targets_limit      = settings.SUPREME_WATCH_LIMIT,
        presets_limit            = settings.SUPREME_PRESETS_LIMIT,
        blacklist_limit          = settings.SUPREME_BLACKLIST_LIMIT,
        feed_result_limit        = settings.SUPREME_FEED_LIMIT,
        has_basic_alerts         = True,
        has_smart_alerts         = True,
        has_advanced_filtering   = True,
        has_priority_ranking     = True,
        has_auto_exit            = False,
    )


def _build_supreme_black() -> SniperEntitlements:
    """Supreme Black — no buy caps, unlimited automation, Auto-Exit Manager."""
    return SniperEntitlements(
        tier                     = "supreme_black",
        is_holder                = True,
        has_supreme_access       = True,
        has_supreme_black        = True,
        auto_buy_enabled_allowed = True,
        max_buy_size_limit_sol   = 9999.0,   # no cap for Supreme Black
        max_buys_per_hour_limit  = 9999,     # no cap for Supreme Black
        watch_targets_limit      = 9999,
        presets_limit            = 9999,
        blacklist_limit          = 9999,
        feed_result_limit        = 9999,
        has_basic_alerts         = True,
        has_smart_alerts         = True,
        has_advanced_filtering   = True,
        has_priority_ranking     = True,
        has_auto_exit            = True,
    )


# ── Public API ─────────────────────────────────────────────────────────────────

async def get_entitlements(user_id: int) -> SniperEntitlements:
    """Returns SniperEntitlements for the given user."""
    tier = await get_active_tier(user_id)
    if tier == "supreme_black":
        return _build_supreme_black()
    if tier == "supreme":
        return _build_supreme()
    return _build_free()


async def get_active_tier(user_id: int) -> str:
    """
    Returns the user's active tier: 'free', 'supreme', or 'supreme_black'.

    Priority order (highest wins):
      1. holder_access.tier = 'supreme_black'  (explicit DB grant or new burn)
      2. user_badges has 'supreme_black' badge  (earned via burn — retroactive compat)
      3. holder_access.tier = 'supreme'
      4. 'free'

    The badge fallback ensures users who burned 50M+ before the supreme_black
    tier existed are automatically recognised without an admin re-grant.
    """
    async with get_db() as db:
        async with db.execute(
            "SELECT tier, expires_at FROM holder_access "
            "WHERE user_id = ? AND active = 1 "
            "ORDER BY CASE tier WHEN 'supreme_black' THEN 0 WHEN 'supreme' THEN 1 ELSE 2 END LIMIT 1",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()

        # Check if user has the supreme_black badge (retroactive compatibility)
        async with db.execute(
            "SELECT id FROM user_badges WHERE user_id = ? AND badge_key = 'supreme_black' AND active = 1",
            (user_id,),
        ) as cursor:
            badge_row = await cursor.fetchone()

    # Badge alone is enough to qualify for supreme_black
    if badge_row is not None:
        return "supreme_black"

    if row is None:
        return "free"

    expires_at: Optional[str] = row["expires_at"]
    if expires_at is not None:
        try:
            if datetime.utcnow() >= datetime.fromisoformat(str(expires_at).replace(" ", "T")):
                return "free"
        except ValueError:
            pass

    return row["tier"] if row["tier"] in ("supreme", "supreme_black") else "free"


async def is_supreme_holder(user_id: int) -> bool:
    """Returns True for supreme OR supreme_black users."""
    return await get_active_tier(user_id) in ("supreme", "supreme_black")


async def is_supreme_black(user_id: int) -> bool:
    """Returns True only for supreme_black users."""
    return await get_active_tier(user_id) == "supreme_black"


async def grant_supreme(user_id: int, wallet_address: str = "") -> None:
    """Grant SUPREME access to a user (admin command — manual grant)."""
    async with get_db() as db:
        await db.execute("""
            INSERT INTO holder_access
                (user_id, wallet_address, tier, active, activated_via, updated_at)
            VALUES (?, ?, 'supreme', 1, 'manual', CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                tier           = 'supreme',
                active         = 1,
                activated_via  = 'manual',
                wallet_address = COALESCE(NULLIF(?, ''), wallet_address),
                updated_at     = CURRENT_TIMESTAMP
        """, (user_id, wallet_address, wallet_address))
        await db.commit()
    logger.info(f"SUPREME granted (manual) to user {user_id}")


async def grant_supreme_black(user_id: int, wallet_address: str = "") -> None:
    """Grant SUPREME BLACK access to a user (admin command)."""
    async with get_db() as db:
        await db.execute("""
            INSERT INTO holder_access
                (user_id, wallet_address, tier, active, activated_via, updated_at)
            VALUES (?, ?, 'supreme_black', 1, 'manual', CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                tier           = 'supreme_black',
                active         = 1,
                activated_via  = 'manual',
                wallet_address = COALESCE(NULLIF(?, ''), wallet_address),
                updated_at     = CURRENT_TIMESTAMP
        """, (user_id, wallet_address, wallet_address))
        await db.commit()
    logger.info(f"SUPREME BLACK granted (manual) to user {user_id}")


async def revoke_supreme(user_id: int) -> None:
    """Revoke SUPREME access from a user."""
    async with get_db() as db:
        await db.execute(
            "UPDATE holder_access SET active = 0 WHERE user_id = ?", (user_id,)
        )
        await db.commit()
    logger.info(f"SUPREME revoked from user {user_id}")


async def link_wallet_to_tier(user_id: int, wallet_address: str) -> None:
    """Link a wallet address for future on-chain tier verification."""
    async with get_db() as db:
        await db.execute("""
            INSERT INTO holder_access (user_id, wallet_address, tier, active)
            VALUES (?, ?, 'free', 0)
            ON CONFLICT(user_id) DO UPDATE SET wallet_address = ?
        """, (user_id, wallet_address, wallet_address))
        await db.commit()
