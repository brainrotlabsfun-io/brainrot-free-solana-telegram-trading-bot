"""
services/affiliate_service.py
================================
Affiliate / referral commission system for BRAINROTONCHAIN_BOT.

ADDITIVE LAYER — the existing burn access system (burn_activations,
holder_access, wallet_links, user_burn_stats) is NOT touched here.
These are separate, independently tracked records.

Access states are distinct:
  burn_access_verified      → holder_access.activated_via = 'burn'
  supreme_payment_verified  → supreme_payment_verifications.payment_status = 'confirmed'
  affiliate_commission_created → commission_ledger row exists

A user can have burn access active AND affiliate data tracked simultaneously.
"""

import logging
from datetime import datetime
from typing import Optional

from database.sqlite_db import get_db

logger = logging.getLogger(__name__)

COMMISSION_PCT = 0.21   # 21% of the qualifying signup amount
SIGNUP_PENDING_EXPIRY_MINUTES = 30

# ── Tier structure (locked) ────────────────────────────────────────────────────

TIER_STRUCTURE = [
    (10,    "Entry"),
    (20,    "Connected"),
    (30,    "Plugged In"),
    (40,    "Operator"),
    (50,    "Earner"),
    (100,   "Closer"),
    (250,   "Power Broker"),
    (1000,  "Money Circle"),
    (10000, "Sovereign"),
]


def get_affiliate_tier(referrals: int) -> tuple[str, Optional[tuple[int, str]]]:
    """
    Returns (current_tier_name, next_tier_tuple_or_None).
    next_tier_tuple is (threshold, name) for the next milestone, or None if max.
    """
    current_tier = "None"
    next_tier: Optional[tuple[int, str]] = None

    for threshold, name in TIER_STRUCTURE:
        if referrals >= threshold:
            current_tier = name
        elif next_tier is None:
            next_tier = (threshold, name)

    return current_tier, next_tier


# ── Profile helpers ────────────────────────────────────────────────────────────

async def get_affiliate_profile(affiliate_wallet: str) -> Optional[dict]:
    """Returns affiliate_profiles row as dict, or None if not found."""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM affiliate_profiles WHERE affiliate_wallet_address = ?",
            (affiliate_wallet,),
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def get_affiliate_profile_by_user_id(user_id: int) -> Optional[dict]:
    """
    Returns the affiliate profile linked to a user_id, or None.
    Looks up the user's linked wallet first (wallet_links), then finds their profile.
    """
    async with get_db() as db:
        async with db.execute(
            "SELECT wallet_address FROM wallet_links WHERE user_id = ?", (user_id,)
        ) as cur:
            wrow = await cur.fetchone()
        if not wrow:
            return None
        async with db.execute(
            "SELECT * FROM affiliate_profiles WHERE affiliate_wallet_address = ?",
            (wrow["wallet_address"],),
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def get_or_create_affiliate_profile(
    affiliate_wallet: str,
    user_id: Optional[int] = None,
    telegram_username: Optional[str] = None,
) -> dict:
    """
    Returns existing affiliate profile or creates a new one.
    Does NOT overwrite existing user_id/username if already set.
    """
    existing = await get_affiliate_profile(affiliate_wallet)
    if existing:
        # Update user_id/username if not set yet
        if user_id and not existing.get("user_id"):
            async with get_db() as db:
                await db.execute(
                    "UPDATE affiliate_profiles SET user_id=?, telegram_username=?, updated_at=? "
                    "WHERE affiliate_wallet_address=?",
                    (user_id, telegram_username, datetime.utcnow().isoformat(), affiliate_wallet),
                )
                await db.commit()
            existing["user_id"] = user_id
            existing["telegram_username"] = telegram_username
        return existing

    now = datetime.utcnow().isoformat()
    async with get_db() as db:
        await db.execute("""
            INSERT OR IGNORE INTO affiliate_profiles
                (user_id, telegram_username, affiliate_wallet_address,
                 total_referrals, total_commission_earned_usd,
                 total_commission_paid_usd, unpaid_commission_usd,
                 current_tier, highest_tier, created_at, updated_at)
            VALUES (?, ?, ?, 0, 0, 0, 0, 'None', 'None', ?, ?)
        """, (user_id, telegram_username, affiliate_wallet, now, now))
        await db.commit()

    return await get_affiliate_profile(affiliate_wallet)


# ── Referral tracking ──────────────────────────────────────────────────────────

async def get_user_referral(user_id: int) -> Optional[dict]:
    """Returns the referral_events row for a referred user, or None."""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM referral_events WHERE referred_user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def record_referral(
    referred_user_id: int,
    affiliate_wallet: str,
    user_linked_wallet: Optional[str] = None,
    self_referral_allowed: bool = False,
) -> dict:
    """
    Records that referred_user_id was referred by affiliate_wallet.

    Anti-abuse:
    - One referral record per user (UNIQUE on referred_user_id)
    - Self-referral check: if user's own wallet matches affiliate_wallet, deny unless allowed

    Returns {"success": bool, "error": str | None}
    """
    # Self-referral check
    if (not self_referral_allowed
            and user_linked_wallet
            and user_linked_wallet.lower() == affiliate_wallet.lower()):
        return {"success": False, "error": "Self-referral is not allowed."}

    # Check if already referred
    existing = await get_user_referral(referred_user_id)
    if existing:
        return {
            "success": False,
            "error": "You already have a referral registered.",
        }

    now = datetime.utcnow().isoformat()
    async with get_db() as db:
        try:
            await db.execute("""
                INSERT INTO referral_events
                    (referred_user_id, affiliate_wallet_address,
                     supreme_signup_status, affiliate_commission_eligible,
                     created_at, updated_at)
                VALUES (?, ?, 'pending', 0, ?, ?)
            """, (referred_user_id, affiliate_wallet, now, now))
            await db.commit()
        except Exception:
            return {"success": False, "error": "Referral already registered."}

    return {"success": True, "error": None}


# ── Pending signup management ──────────────────────────────────────────────────

async def initiate_affiliate_signup(
    user_id: int,
    from_wallet: str,
    expected_sol: float,
    affiliate_wallet: Optional[str] = None,
) -> None:
    """Record a pending $100 Supreme signup. Overwrites any previous pending for this user."""
    async with get_db() as db:
        await db.execute("""
            INSERT INTO affiliate_signup_pending
                (user_id, from_wallet, expected_sol, affiliate_wallet, expires_at)
            VALUES (?, ?, ?, ?, datetime('now', ?))
            ON CONFLICT(user_id) DO UPDATE SET
                from_wallet      = ?,
                expected_sol     = ?,
                affiliate_wallet = ?,
                initiated_at     = CURRENT_TIMESTAMP,
                expires_at       = datetime('now', ?)
        """, (
            user_id, from_wallet, expected_sol, affiliate_wallet,
            f"+{SIGNUP_PENDING_EXPIRY_MINUTES} minutes",
            from_wallet, expected_sol, affiliate_wallet,
            f"+{SIGNUP_PENDING_EXPIRY_MINUTES} minutes",
        ))
        await db.commit()


async def get_pending_affiliate_signup(user_id: int) -> Optional[dict]:
    """Returns active pending affiliate signup for user, or None if expired/none."""
    async with get_db() as db:
        async with db.execute("""
            SELECT * FROM affiliate_signup_pending
            WHERE user_id = ? AND expires_at > datetime('now')
        """, (user_id,)) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def get_all_pending_affiliate_signups() -> list[dict]:
    """Returns all non-expired pending affiliate signups."""
    async with get_db() as db:
        async with db.execute("""
            SELECT * FROM affiliate_signup_pending
            WHERE expires_at > datetime('now')
        """) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ── Payment confirmation + commission creation ─────────────────────────────────

async def confirm_qualifying_payment(
    user_id: int,
    tx_hash: str,
    amount_sol: float,
    amount_usd: float = 100.0,
) -> dict:
    """
    Called when a $100 qualifying payment is confirmed on-chain.

    Steps:
    1. Create/update supreme_payment_verifications record
    2. Grant permanent Supreme access via holder_access (activated_via='affiliate_payment')
    3. Look up referral_events for this user
    4. If referral exists: create commission_ledger entry (idempotent)
    5. Update affiliate_profiles stats + tier
    6. Remove from affiliate_signup_pending

    Returns:
        {
            "success":             bool,
            "error":               str | None,
            "commission_created":  bool,
            "affiliate_wallet":    str | None,
            "commission_usd":      float,
        }
    """
    now = datetime.utcnow().isoformat()

    # ── 1. Record payment verification ────────────────────────────────────────
    async with get_db() as db:
        # Check for duplicate tx
        async with db.execute(
            "SELECT id FROM supreme_payment_verifications WHERE payment_tx_hash = ?",
            (tx_hash,),
        ) as cur:
            existing_tx = await cur.fetchone()
        if existing_tx:
            return {
                "success": False,
                "error": "This transaction has already been processed.",
                "commission_created": False,
                "affiliate_wallet": None,
                "commission_usd": 0.0,
            }

        await db.execute("""
            INSERT OR IGNORE INTO supreme_payment_verifications
                (user_id, payment_amount_usd, payment_amount_sol,
                 payment_tx_hash, payment_status, verified_at,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, 'confirmed', ?, ?, ?)
        """, (user_id, amount_usd, amount_sol, tx_hash, now, now, now))

        # ── 2. Grant permanent Supreme Black access ────────────────────────────
        # activated_via='affiliate_payment' — distinct from 'burn' and 'sol_payment'
        await db.execute("""
            INSERT INTO holder_access
                (user_id, wallet_address, tier, active, activated_via,
                 activation_tx_signature, activated_at, expires_at, updated_at)
            VALUES (?, '', 'supreme_black', 1, 'affiliate_payment', ?, ?, NULL, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                tier                    = 'supreme_black',
                active                  = 1,
                activated_via           = 'affiliate_payment',
                activation_tx_signature = ?,
                activated_at            = ?,
                expires_at              = NULL,
                updated_at              = ?
        """, (user_id, tx_hash, now, now, tx_hash, now, now))

        # ── 3. Update referral_event status ───────────────────────────────────
        await db.execute("""
            UPDATE referral_events
            SET supreme_signup_status = 'confirmed',
                affiliate_commission_eligible = 1,
                updated_at = ?
            WHERE referred_user_id = ?
        """, (now, user_id))

        # Remove from pending
        await db.execute(
            "DELETE FROM affiliate_signup_pending WHERE user_id = ?", (user_id,)
        )

        await db.commit()

    # ── 4. Check for referral and create commission ────────────────────────────
    referral = await get_user_referral(user_id)
    commission_created = False
    affiliate_wallet: Optional[str] = None

    commission_amount = round(amount_usd * COMMISSION_PCT, 4)
    commission_id: Optional[int] = None

    if referral and referral.get("affiliate_commission_eligible"):
        affiliate_wallet = referral["affiliate_wallet_address"]

        async with get_db() as db:
            try:
                cur = await db.execute("""
                    INSERT INTO commission_ledger
                        (affiliate_wallet_address, referred_user_id,
                         commission_amount_usd, commission_status,
                         created_at, updated_at)
                    VALUES (?, ?, ?, 'pending', ?, ?)
                """, (affiliate_wallet, user_id, commission_amount, now, now))
                commission_id = cur.lastrowid
                await db.commit()
                commission_created = True
            except Exception:
                # UNIQUE(referred_user_id) — commission already exists, skip
                logger.warning(
                    f"affiliate: commission for user {user_id} already exists, skipping"
                )

        if commission_created:
            # ── 5. Update affiliate profile stats + tier ───────────────────────
            await _increment_affiliate_stats(affiliate_wallet, commission_amount)

    logger.info(
        f"affiliate: qualifying payment confirmed user={user_id} "
        f"tx={tx_hash[:16]}... amount={amount_sol:.4f} SOL "
        f"commission={'yes $' + str(commission_amount) if commission_created else 'no'} "
        f"affiliate={affiliate_wallet[:10] + '...' if affiliate_wallet else 'none'}"
    )

    return {
        "success": True,
        "error": None,
        "commission_created": commission_created,
        "commission_id": commission_id,
        "affiliate_wallet": affiliate_wallet,
        "commission_usd": commission_amount if commission_created else 0.0,
        "amount_sol": amount_sol,
    }


async def _increment_affiliate_stats(affiliate_wallet: str, commission_usd: float) -> None:
    """
    Increments total_referrals, earned/unpaid amounts, and recalculates tier.
    Creates profile if it doesn't exist yet.
    """
    await get_or_create_affiliate_profile(affiliate_wallet)

    now = datetime.utcnow().isoformat()
    async with get_db() as db:
        await db.execute("""
            UPDATE affiliate_profiles
            SET total_referrals             = total_referrals + 1,
                total_commission_earned_usd = total_commission_earned_usd + ?,
                unpaid_commission_usd       = unpaid_commission_usd + ?,
                updated_at                  = ?
            WHERE affiliate_wallet_address = ?
        """, (commission_usd, commission_usd, now, affiliate_wallet))
        await db.commit()

    # Recalculate tier
    profile = await get_affiliate_profile(affiliate_wallet)
    if not profile:
        return

    referrals = profile["total_referrals"]
    current_tier, _ = get_affiliate_tier(referrals)

    # Never downgrade highest_tier
    old_highest = profile.get("highest_tier") or "None"
    highest_idx = next(
        (i for i, (_, n) in enumerate(TIER_STRUCTURE) if n == old_highest), -1
    )
    new_idx = next(
        (i for i, (_, n) in enumerate(TIER_STRUCTURE) if n == current_tier), -1
    )
    new_highest = current_tier if new_idx > highest_idx else old_highest

    async with get_db() as db:
        await db.execute("""
            UPDATE affiliate_profiles
            SET current_tier = ?,
                highest_tier = ?,
                updated_at   = ?
            WHERE affiliate_wallet_address = ?
        """, (current_tier, new_highest, now, affiliate_wallet))
        await db.commit()


# ── Admin helpers ──────────────────────────────────────────────────────────────

async def get_unpaid_commissions() -> list[dict]:
    """Returns all pending (unpaid) commission entries with affiliate wallet."""
    async with get_db() as db:
        async with db.execute("""
            SELECT cl.*, ap.telegram_username
            FROM commission_ledger cl
            LEFT JOIN affiliate_profiles ap
                ON cl.affiliate_wallet_address = ap.affiliate_wallet_address
            WHERE cl.commission_status = 'pending'
            ORDER BY cl.created_at ASC
        """) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def mark_commission_paid(commission_id: int, payout_tx_hash: str) -> bool:
    """
    Marks a commission as paid. Updates commission_ledger and affiliate_profiles.
    Returns True if updated, False if not found.
    """
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM commission_ledger WHERE id = ?", (commission_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return False

        now = datetime.utcnow().isoformat()
        amount = row["commission_amount_usd"]
        wallet = row["affiliate_wallet_address"]

        await db.execute("""
            UPDATE commission_ledger
            SET commission_status = 'paid',
                payout_tx_hash    = ?,
                updated_at        = ?
            WHERE id = ?
        """, (payout_tx_hash, now, commission_id))

        # Move from unpaid to paid in profile
        await db.execute("""
            UPDATE affiliate_profiles
            SET total_commission_paid_usd = total_commission_paid_usd + ?,
                unpaid_commission_usd     = MAX(0, unpaid_commission_usd - ?),
                updated_at                = ?
            WHERE affiliate_wallet_address = ?
        """, (amount, amount, now, wallet))

        await db.commit()
    return True


async def get_all_affiliate_profiles(limit: int = 50) -> list[dict]:
    """Returns all affiliate profiles ordered by total earned, for admin view."""
    async with get_db() as db:
        async with db.execute("""
            SELECT * FROM affiliate_profiles
            ORDER BY total_commission_earned_usd DESC
            LIMIT ?
        """, (limit,)) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_affiliate_commissions(affiliate_wallet: str, limit: int = 20) -> list[dict]:
    """Returns commission_ledger entries for a specific affiliate wallet."""
    async with get_db() as db:
        async with db.execute("""
            SELECT * FROM commission_ledger
            WHERE affiliate_wallet_address = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (affiliate_wallet, limit)) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]
