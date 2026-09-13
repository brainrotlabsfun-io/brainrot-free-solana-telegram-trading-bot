"""
services/burn_activation_service.py
=====================================
Orchestrates the full burn-to-SUPREME activation pipeline.

Steps after a user submits a burn TX signature:
  1. Validate wallet is linked
  2. Anti-fraud: tx signature not already used
  3. Anti-fraud: tx not claimed by another user
  4. Write pending burn_activations record
  5. Call solana_verification_service to confirm on-chain
  6. Update burn_activations status (verified / failed)
  7. If verified: update user_burn_stats (cumulative totals)
  8. If burn >= threshold: activate SUPREME in holder_access
  9. Check founding badge eligibility
 10. Award badges via badge_service
 11. Return full result summary

No private keys are used. The user signs their own burn transaction.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from database.sqlite_db import get_db
from services.solana_verification_service import verify_burn_transaction
from services.badge_service import evaluate_and_award_badges
from utils.config import settings

logger = logging.getLogger(__name__)


# ── Public read helpers ────────────────────────────────────────────────────────

async def get_burn_stats(user_id: int) -> dict:
    """Returns user_burn_stats row as dict, or zero-defaults if none exists."""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM user_burn_stats WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return dict(row)
    return {
        "user_id":          user_id,
        "total_burned":     0.0,
        "burn_count":       0,
        "last_burn_at":     None,
        "highest_badge_key": None,
        "updated_at":       None,
    }


async def get_activation_status(user_id: int) -> dict:
    """Returns a summary of wallet link, SUPREME status, and last burn."""
    async with get_db() as db:
        async with db.execute(
            "SELECT wallet_address FROM wallet_links WHERE user_id = ?", (user_id,)
        ) as cur:
            wrow = await cur.fetchone()

        async with db.execute(
            "SELECT * FROM holder_access WHERE user_id = ?", (user_id,)
        ) as cur:
            access = await cur.fetchone()

        async with db.execute("""
            SELECT * FROM burn_activations
            WHERE user_id = ?
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,)) as cur:
            last_burn = await cur.fetchone()

    active_tier = (
        access["tier"]
        if (access is not None
            and access["active"] == 1
            and _not_expired(access["expires_at"] if "expires_at" in access.keys() else None))
        else "free"
    )
    is_supreme       = active_tier in ("supreme", "supreme_black")
    is_supreme_black = active_tier == "supreme_black"

    return {
        "wallet_linked":    wrow is not None,
        "wallet_address":   wrow["wallet_address"] if wrow else None,
        "is_supreme":       is_supreme,
        "is_supreme_black": is_supreme_black,
        "active_tier":      active_tier,
        "activated_via":    access["activated_via"] if access else None,
        "activation_tx":    access["activation_tx_signature"] if access else None,
        "activated_at":     access["activated_at"] if access else None,
        "expires_at":       access["expires_at"] if access else None,
        "last_burn_status": last_burn["status"] if last_burn else None,
        "last_burn_amount": last_burn["burned_amount"] if last_burn else 0.0,
        "last_burn_tx":     last_burn["tx_signature"] if last_burn else None,
    }


def _not_expired(expires_at: Optional[str]) -> bool:
    if expires_at is None:
        return True  # permanent
    try:
        return datetime.utcnow() < datetime.fromisoformat(expires_at)
    except ValueError:
        return True


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def submit_burn_for_verification(
    user_id:      int,
    tx_signature: str,
) -> dict:
    """
    Full verification and activation pipeline.

    Returns:
        {
            "success":               bool,
            "error":                 str | None,
            "burned_amount":         float,
            "supreme_activated":     bool,
            "newly_awarded_badges":  list[dict],
            "total_burned":          float,
            "highest_badge":         str | None,
        }
    """
    # ── 1. Wallet must be linked ───────────────────────────────────────────────
    async with get_db() as db:
        async with db.execute(
            "SELECT wallet_address FROM wallet_links WHERE user_id = ?", (user_id,)
        ) as cur:
            wrow = await cur.fetchone()

    if not wrow:
        return _fail("No wallet linked. Link your wallet first via the SUPREME Access page.")

    linked_wallet = wrow["wallet_address"]

    # ── 2 & 3. Anti-fraud checks ──────────────────────────────────────────────
    async with get_db() as db:
        async with db.execute(
            "SELECT user_id, status FROM burn_activations WHERE tx_signature = ?",
            (tx_signature,),
        ) as cur:
            existing_tx = await cur.fetchone()

    if existing_tx:
        if existing_tx["status"] == "verified":
            return _fail("This transaction has already been used for an activation.")
        if existing_tx["user_id"] != user_id:
            return _fail("This transaction was submitted by a different account.")

    # ── 4. Record pending activation ──────────────────────────────────────────
    now = datetime.utcnow().isoformat()
    async with get_db() as db:
        await db.execute("""
            INSERT OR IGNORE INTO burn_activations
                (user_id, wallet_address, token_mint, required_amount,
                 burned_amount, tx_signature, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0.0, ?, 'pending', ?, ?)
        """, (
            user_id, linked_wallet, settings.BRAINROT_MINT,
            settings.SUPREME_REQUIRED_BURN_AMOUNT,
            tx_signature, now, now,
        ))
        await db.commit()

    # ── 5. On-chain verification ──────────────────────────────────────────────
    verification = await verify_burn_transaction(
        tx_signature           = tx_signature,
        expected_wallet        = linked_wallet,
        expected_mint          = settings.BRAINROT_MINT,
        required_amount_tokens = settings.SUPREME_REQUIRED_BURN_AMOUNT,
    )

    status = "verified" if verification["valid"] else "failed"
    async with get_db() as db:
        await db.execute("""
            UPDATE burn_activations
            SET burned_amount = ?,
                status       = ?,
                verified_at  = ?,
                updated_at   = ?
            WHERE tx_signature = ? AND user_id = ?
        """, (
            verification.get("burned_amount", 0.0),
            status,
            now if verification["valid"] else None,
            now,
            tx_signature, user_id,
        ))
        await db.commit()

    if not verification["valid"]:
        return _fail(
            verification.get("error", "Burn verification failed."),
            burned_amount=verification.get("burned_amount", 0.0),
        )

    burned_amount = verification["burned_amount"]

    # ── 7. Update cumulative burn stats ───────────────────────────────────────
    async with get_db() as db:
        await db.execute("""
            INSERT INTO user_burn_stats
                (user_id, total_burned, burn_count, last_burn_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                total_burned = total_burned + ?,
                burn_count   = burn_count + 1,
                last_burn_at = ?,
                updated_at   = ?
        """, (
            user_id, burned_amount, now, now,
            burned_amount, now, now,
        ))
        await db.commit()

    stats     = await get_burn_stats(user_id)
    new_total = stats["total_burned"]
    new_count = stats["burn_count"]

    # ── 8. Activate SUPREME / SUPREME BLACK based on cumulative total ─────────
    #
    # Use new_total (cumulative across all burns) — a user who burns 10M across
    # five transactions should earn the same tier as someone who burned 10M in one.
    # Never downgrade: if already supreme_black, keep it.
    #
    is_activated      = new_total >= settings.SUPREME_REQUIRED_BURN_AMOUNT
    is_black          = new_total >= settings.SUPREME_BLACK_REQUIRED_BURN_AMOUNT
    supreme_activated = False

    if is_activated:
        # Determine which tier to grant — never downgrade an existing black user
        async with get_db() as db:
            async with db.execute(
                "SELECT tier FROM holder_access WHERE user_id=? AND active=1", (user_id,)
            ) as cur:
                existing = await cur.fetchone()
        current_tier = existing["tier"] if existing else "free"

        if current_tier == "supreme_black":
            # Already at the top — nothing to change
            grant_tier = "supreme_black"
        elif is_black:
            grant_tier = "supreme_black"
        else:
            grant_tier = "supreme"

        expires_at: Optional[str] = None
        if not settings.SUPREME_PERMANENT_UNLOCK:
            expires_at = (
                datetime.utcnow() + timedelta(days=settings.SUPREME_DURATION_DAYS)
            ).isoformat()

        async with get_db() as db:
            await db.execute("""
                INSERT INTO holder_access
                    (user_id, wallet_address, tier, active, activated_via,
                     activation_tx_signature, activated_at, expires_at, updated_at)
                VALUES (?, ?, ?, 1, 'burn', ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    tier                    = ?,
                    active                  = 1,
                    activated_via           = 'burn',
                    activation_tx_signature = ?,
                    activated_at            = ?,
                    expires_at              = ?,
                    updated_at              = ?
            """, (
                user_id, linked_wallet, grant_tier, tx_signature, now, expires_at, now,
                grant_tier, tx_signature, now, expires_at, now,
            ))
            await db.commit()

        supreme_activated = True
        logger.info(
            f"{grant_tier.upper()} activated via burn: user={user_id} "
            f"tx={tx_signature[:12]}... single={burned_amount:,.0f} "
            f"total={new_total:,.0f}"
        )

    # ── 9. Founding eligibility ───────────────────────────────────────────────
    is_founding = await _check_founding_eligibility(user_id)

    # ── 10. Award badges ──────────────────────────────────────────────────────
    newly_awarded = await evaluate_and_award_badges(
        user_id      = user_id,
        total_burned = new_total,
        burn_count   = new_count,
        is_activated = is_activated,
        is_founding  = is_founding,
        source_tx    = tx_signature,
    )

    updated_stats = await get_burn_stats(user_id)

    return {
        "success":              True,
        "error":                None,
        "burned_amount":        burned_amount,
        "supreme_activated":    supreme_activated,
        "newly_awarded_badges": newly_awarded,
        "total_burned":         updated_stats["total_burned"],
        "highest_badge":        updated_stats.get("highest_badge_key"),
    }


# ── Founding badge eligibility ─────────────────────────────────────────────────

async def _check_founding_eligibility(user_id: int) -> bool:
    """
    Returns True if the user qualifies for the founding_burner badge based on:
      - FOUNDING_BADGE_ENABLED config
      - FOUNDING_BADGE_CUTOFF date (optional)
      - FOUNDING_BADGE_MAX_USERS count cap (optional)
    """
    if not settings.FOUNDING_BADGE_ENABLED:
        return False

    now = datetime.utcnow()

    if settings.FOUNDING_BADGE_CUTOFF:
        try:
            cutoff = datetime.fromisoformat(settings.FOUNDING_BADGE_CUTOFF)
            if now > cutoff:
                return False
        except ValueError:
            logger.warning("FOUNDING_BADGE_CUTOFF has invalid format — ignoring.")

    if settings.FOUNDING_BADGE_MAX_USERS and settings.FOUNDING_BADGE_MAX_USERS > 0:
        async with get_db() as db:
            async with db.execute("""
                SELECT COUNT(DISTINCT user_id)
                FROM user_badges
                WHERE badge_key = 'founding_burner' AND active = 1
            """) as cur:
                count = (await cur.fetchone())[0]
        if count >= settings.FOUNDING_BADGE_MAX_USERS:
            return False

    return True


# ── Internal helpers ──────────────────────────────────────────────────────────

def _fail(error: str, burned_amount: float = 0.0) -> dict:
    return {
        "success":              False,
        "error":                error,
        "burned_amount":        burned_amount,
        "supreme_activated":    False,
        "newly_awarded_badges": [],
        "total_burned":         0.0,
        "highest_badge":        None,
    }
