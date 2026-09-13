"""
services/sol_payment_service.py
================================
SOL-payment-based timed Supreme Black access.

Tiers (fixed SOL amounts):
  0.05 SOL (~$5)  → 12 hours
  0.20 SOL (~$25) → 3 days  (72 hours)
  0.30 SOL (~$40) → 7 days  (168 hours)

Detection: RPC poll of business wallet every 15s.
Replay protection: processed_sol_txs table (UNIQUE tx_signature).
Sender matching: user's linked bot wallet address must be the TX signer.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import aiohttp

from database.sqlite_db import get_db
from utils.config import settings

logger = logging.getLogger(__name__)

# ── Business wallet (dev auto-trader wallet) ──────────────────────────────────
# Receiving wallet for paid features. Set PAYMENT_WALLET in .env to your own
# SOL address. While it is blank, payment flows stay disabled rather than
# showing users an empty address to send funds to.
PAYMENT_WALLET = settings.PAYMENT_WALLET


def payments_enabled() -> bool:
    """True only when a receiving wallet has been configured."""
    return bool(PAYMENT_WALLET)

# ── Tiers ─────────────────────────────────────────────────────────────────────
SOL_TIERS = [
    {"sol": 0.05, "hours": 12,  "label": "12 Hour Trial",  "approx_usd": "~$5"},
    {"sol": 0.20, "hours": 72,  "label": "3 Day Access",   "approx_usd": "~$25"},
    {"sol": 0.30, "hours": 168, "label": "7 Day Access",   "approx_usd": "~$40"},
]

# Allow ±0.003 SOL variance (dust/fees)
AMOUNT_TOLERANCE = 0.003

# Pending payment window — 30 minutes
PENDING_EXPIRY_MINUTES = 30


async def initiate_payment(user_id: int, tier_index: int, from_wallet: str) -> dict:
    """Record a pending payment. Overwrites any previous pending for this user."""
    tier = SOL_TIERS[tier_index]
    async with get_db() as db:
        await db.execute("""
            INSERT INTO sol_payment_pending
                (user_id, expected_sol, duration_hours, from_wallet, expires_at)
            VALUES (?, ?, ?, ?, datetime('now', ?))
            ON CONFLICT(user_id) DO UPDATE SET
                expected_sol   = ?,
                duration_hours = ?,
                from_wallet    = ?,
                initiated_at   = CURRENT_TIMESTAMP,
                expires_at     = datetime('now', ?)
        """, (
            user_id, tier["sol"], tier["hours"], from_wallet,
            f"+{PENDING_EXPIRY_MINUTES} minutes",
            tier["sol"], tier["hours"], from_wallet,
            f"+{PENDING_EXPIRY_MINUTES} minutes",
        ))
        await db.commit()
    return tier


async def get_pending(user_id: int) -> Optional[dict]:
    """Returns active pending payment record for user, or None if expired/none."""
    async with get_db() as db:
        async with db.execute("""
            SELECT * FROM sol_payment_pending
            WHERE user_id = ? AND expires_at > datetime('now')
        """, (user_id,)) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def get_all_pending() -> list[dict]:
    """Returns all non-expired pending payments across all users."""
    async with get_db() as db:
        async with db.execute("""
            SELECT * FROM sol_payment_pending
            WHERE expires_at > datetime('now')
        """) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def grant_timed_access(user_id: int, duration_hours: int, from_wallet: str = "") -> None:
    """Grant Supreme Black access for the given duration. Sets activated_via='sol_payment'."""
    expires = datetime.utcnow() + timedelta(hours=duration_hours)
    expires_str = expires.strftime("%Y-%m-%d %H:%M:%S")
    async with get_db() as db:
        await db.execute("""
            INSERT INTO holder_access
                (user_id, wallet_address, tier, active, activated_via,
                 activated_at, expires_at, updated_at)
            VALUES (?, ?, 'supreme_black', 1, 'sol_payment',
                    CURRENT_TIMESTAMP, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                tier          = 'supreme_black',
                active        = 1,
                activated_via = 'sol_payment',
                activated_at  = CURRENT_TIMESTAMP,
                expires_at    = ?,
                wallet_address = COALESCE(NULLIF(?, ''), wallet_address),
                updated_at    = CURRENT_TIMESTAMP
        """, (user_id, from_wallet, expires_str, expires_str, from_wallet))
        await db.execute(
            "DELETE FROM sol_payment_pending WHERE user_id = ?", (user_id,)
        )
        await db.commit()
    logger.info(
        f"Granted SUPREME BLACK (sol_payment) to user {user_id} "
        f"for {duration_hours}h — expires {expires_str}"
    )


async def mark_tx_processed(tx_sig: str, user_id: int) -> bool:
    """
    Insert into processed_sol_txs. Returns False if already present (replay attack).
    """
    async with get_db() as db:
        try:
            await db.execute(
                "INSERT INTO processed_sol_txs (tx_signature, user_id) VALUES (?, ?)",
                (tx_sig, user_id),
            )
            await db.commit()
            return True
        except Exception:
            return False  # UNIQUE constraint — already processed


async def fetch_recent_signatures(rpc_url: str, limit: int = 30) -> list[str]:
    """Fetch recent confirmed TX signatures for the payment wallet."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [PAYMENT_WALLET, {"limit": limit, "commitment": "confirmed"}],
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                rpc_url, json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                return [s["signature"] for s in (data.get("result") or [])]
    except Exception as e:
        logger.warning(f"sol_payment: getSignaturesForAddress failed: {e}")
        return []


async def fetch_tx_details(rpc_url: str, sig: str) -> Optional[dict]:
    """
    Fetch a transaction and return {"from_wallet": str, "amount_sol": float}
    if the payment wallet received SOL, else None.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            sig,
            {
                "encoding": "json",
                "maxSupportedTransactionVersion": 0,
                "commitment": "confirmed",
            },
        ],
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                rpc_url, json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                tx = data.get("result")
                if not tx:
                    return None

                meta = tx.get("meta", {}) or {}
                if meta.get("err"):
                    return None  # failed TX

                msg  = tx["transaction"]["message"]
                # Handle both legacy and versioned transaction formats
                keys = (
                    msg.get("accountKeys")
                    or msg.get("staticAccountKeys")
                    or []
                )
                # Versioned TXs may return objects instead of strings
                if keys and isinstance(keys[0], dict):
                    keys = [k.get("pubkey", "") for k in keys]

                pre  = meta.get("preBalances", [])
                post = meta.get("postBalances", [])

                # Find the payment wallet index
                biz_idx = next(
                    (i for i, k in enumerate(keys) if k == PAYMENT_WALLET), None
                )
                if biz_idx is None or biz_idx >= len(pre):
                    return None

                received_lamports = post[biz_idx] - pre[biz_idx]
                if received_lamports <= 0:
                    return None  # wallet sent SOL, not received

                amount_sol  = received_lamports / 1_000_000_000
                from_wallet = keys[0] if keys else ""  # signer / fee payer

                return {"from_wallet": from_wallet, "amount_sol": amount_sol}
    except Exception as e:
        logger.warning(f"sol_payment: getTransaction({sig[:20]}) failed: {e}")
        return None
