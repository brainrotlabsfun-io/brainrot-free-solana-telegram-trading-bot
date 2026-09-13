"""
services/affiliate_payment_worker.py
======================================
Background poller — watches the payment wallet for $100 Supreme signup payments.
Fires every 15 seconds. When a payment matches a pending affiliate signup record,
it:
  1. Grants permanent Supreme Black access (activated_via='affiliate_payment')
  2. Creates a $21 commission in the ledger if a referral wallet was provided
  3. DMs the user with confirmation

This worker runs INDEPENDENTLY from sol_payment_worker. Both poll the same
PAYMENT_WALLET but use different pending tables:
  sol_payment_pending       → existing timed access ($5/$25/$40)
  affiliate_signup_pending  → new $100 Supreme signup

Replay protection uses the shared processed_sol_txs table.
"""

import asyncio
import logging

from aiogram import Bot

from services.affiliate_service import (
    get_all_pending_affiliate_signups,
    confirm_qualifying_payment,
)
from services.affiliate_payout_service import pay_commission
from services.sol_payment_service import (
    fetch_recent_signatures,
    fetch_tx_details,
    mark_tx_processed,
    PAYMENT_WALLET,
)
from utils.config import settings, get_rpc_url

logger = logging.getLogger(__name__)

_running = False

# Allow ±0.05 SOL variance for the $100 signup
AFFILIATE_AMOUNT_TOLERANCE = 0.05


def stop() -> None:
    global _running
    _running = False


async def start(bot: Bot) -> None:
    global _running
    _running = True
    logger.info("Affiliate payment worker started — watching for $100 Supreme signups.")

    seen_sigs: set[str] = set()

    while _running:
        try:
            await _poll(bot, seen_sigs)
        except Exception as e:
            logger.error(f"affiliate_payment_worker error: {e}", exc_info=True)
        await asyncio.sleep(5)

    logger.info("Affiliate payment worker stopped.")


async def _poll(bot: Bot, seen_sigs: set) -> None:
    pending = await get_all_pending_affiliate_signups()
    if not pending:
        return

    # Two lookup strategies:
    # 1. Exact from_wallet match (fast, reliable when wallet matches fee payer)
    # 2. Amount-only match (fallback — handles Phantom routing, different fee payers)
    wallet_map: dict[str, dict] = {p["from_wallet"]: p for p in pending}

    sigs = await fetch_recent_signatures(get_rpc_url(), limit=50)
    new_sigs = [s for s in sigs if s not in seen_sigs]

    for sig in new_sigs:
        seen_sigs.add(sig)
        details = await fetch_tx_details(get_rpc_url(), sig)
        if not details:
            continue

        from_wallet = details["from_wallet"]
        amount_sol  = details["amount_sol"]

        # Strategy 1: exact from_wallet match
        pending_rec = wallet_map.get(from_wallet)

        # Strategy 2: amount match — fee payer may differ from linked wallet
        if not pending_rec:
            matches = [
                p for p in pending
                if abs(amount_sol - float(p["expected_sol"])) <= AFFILIATE_AMOUNT_TOLERANCE
            ]
            if matches:
                # Prefer the record whose from_wallet appears anywhere in the TX details,
                # otherwise take the oldest pending (first created = most likely sender).
                pending_rec = next(
                    (m for m in matches if m["from_wallet"] == from_wallet),
                    sorted(matches, key=lambda r: r.get("initiated_at", ""))[0],
                )
                logger.info(
                    f"affiliate_worker: amount-matched {amount_sol:.4f} SOL "
                    f"→ user {pending_rec['user_id']} (fee-payer {from_wallet[:10]}...)"
                )

        if not pending_rec:
            continue

        expected = float(pending_rec["expected_sol"])
        if abs(amount_sol - expected) > AFFILIATE_AMOUNT_TOLERANCE:
            continue

        user_id          = pending_rec["user_id"]
        affiliate_wallet = pending_rec.get("affiliate_wallet")

        # Skip if user already has Supreme Black — they may have sent a duplicate TX
        from services.brainrot_token_gate import get_active_tier
        if await get_active_tier(user_id) == "supreme_black":
            logger.info(
                f"affiliate_worker: user {user_id} already supreme_black — "
                f"duplicate TX {sig[:20]}, ignoring"
            )
            continue

        # Replay protection — shared table with sol_payment_worker
        if not await mark_tx_processed(sig, user_id):
            logger.info(f"affiliate_worker: TX {sig[:20]} already processed, skip")
            continue

        # Confirm payment, grant access, create commission
        result = await confirm_qualifying_payment(
            user_id    = user_id,
            tx_hash    = sig,
            amount_sol = amount_sol,
            amount_usd = 100.0,
        )

        if result["success"]:
            # Auto-payout: send 21% SOL to affiliate wallet immediately
            if result["commission_created"] and affiliate_wallet and result["commission_id"]:
                try:
                    await pay_commission(
                        affiliate_wallet   = affiliate_wallet,
                        amount_sol_received = amount_sol,
                        commission_id      = result["commission_id"],
                    )
                except Exception as e:
                    logger.error(f"affiliate_worker: auto-payout failed for commission #{result['commission_id']}: {e}")

            await _notify_user(
                bot,
                user_id,
                amount_sol,
                result["commission_created"],
                affiliate_wallet,
            )
        else:
            logger.warning(
                f"affiliate_worker: confirm_qualifying_payment failed "
                f"user={user_id} error={result['error']}"
            )

    # Keep seen_sigs bounded
    if len(seen_sigs) > 500:
        to_remove = list(seen_sigs)[:len(seen_sigs) - 200]
        for s in to_remove:
            seen_sigs.discard(s)


async def _notify_user(
    bot: Bot,
    user_id: int,
    amount_sol: float,
    commission_created: bool,
    affiliate_wallet: str | None,
) -> None:
    referral_line = ""
    if commission_created and affiliate_wallet:
        short_aff = affiliate_wallet[:6] + "..." + affiliate_wallet[-4:]
        referral_line = (
            f"\n<code>┌─ REFERRAL ───────────────────────┐\n"
            f"│  Affiliate  {short_aff:<23}│\n"
            f"│  Commission 21% SOL sent ✅       │\n"
            f"└──────────────────────────────────┘</code>\n"
        )

    text = (
        "╔══════════════════════════════╗\n"
        "║  🔱 <b>SUPREME BLACK — ACTIVATED</b> ║\n"
        "╚══════════════════════════════╝\n\n"
        "<code>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</code>\n"
        "Payment confirmed on-chain ✅\n"
        "Supreme Black access is now LIVE.\n"
        "<code>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</code>\n\n"
        f"<code>┌─ PAYMENT SUMMARY ────────────────┐\n"
        f"│  PAID     {amount_sol:.4f} SOL              │\n"
        f"│  TIER     Supreme Black           │\n"
        f"│  ACCESS   Permanent ∞             │\n"
        f"│  STATUS   ONLINE ⚡               │\n"
        f"└──────────────────────────────────┘</code>\n"
        f"{referral_line}\n"
        "All Supreme Black features are unlocked.\n"
        "<b>Welcome to the network ⚫</b>"
    )
    try:
        await bot.send_message(user_id, text, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"affiliate_worker: could not notify user {user_id}: {e}")
