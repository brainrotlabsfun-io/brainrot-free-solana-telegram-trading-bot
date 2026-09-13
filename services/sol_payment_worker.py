"""
services/sol_payment_worker.py
================================
Background poller — watches the dev auto-trader wallet for incoming SOL payments.
Fires every 15 seconds. When a payment matches a pending record, grants timed
Supreme Black access and DMs the user.
"""

import asyncio
import logging

from aiogram import Bot

from services.sol_payment_service import (
    get_all_pending,
    fetch_recent_signatures,
    fetch_tx_details,
    mark_tx_processed,
    grant_timed_access,
    SOL_TIERS,
    AMOUNT_TOLERANCE,
)
from utils.config import settings, get_rpc_url

logger = logging.getLogger(__name__)

_running = False


def stop() -> None:
    global _running
    _running = False


async def start(bot: Bot) -> None:
    global _running
    _running = True
    logger.info("SOL payment worker started — watching dev wallet.")

    seen_sigs: set[str] = set()

    while _running:
        try:
            await _poll(bot, seen_sigs)
        except Exception as e:
            logger.error(f"sol_payment_worker error: {e}", exc_info=True)
        await asyncio.sleep(15)

    logger.info("SOL payment worker stopped.")


async def _poll(bot: Bot, seen_sigs: set) -> None:
    pending = await get_all_pending()
    if not pending:
        return

    # Build lookup: from_wallet → pending record
    wallet_map: dict[str, dict] = {p["from_wallet"]: p for p in pending}

    sigs = await fetch_recent_signatures(get_rpc_url(), limit=30)
    new_sigs = [s for s in sigs if s not in seen_sigs]

    for sig in new_sigs:
        seen_sigs.add(sig)
        details = await fetch_tx_details(get_rpc_url(), sig)
        if not details:
            continue

        from_wallet = details["from_wallet"]
        amount_sol  = details["amount_sol"]

        pending_rec = wallet_map.get(from_wallet)
        if not pending_rec:
            continue

        expected = float(pending_rec["expected_sol"])
        if abs(amount_sol - expected) > AMOUNT_TOLERANCE:
            logger.info(
                f"sol_payment: wallet {from_wallet[:10]} sent {amount_sol:.4f} SOL "
                f"(expected {expected:.4f}) — outside tolerance, skip"
            )
            continue

        user_id        = pending_rec["user_id"]
        duration_hours = int(pending_rec["duration_hours"])

        # Replay protection — bail if already credited
        if not await mark_tx_processed(sig, user_id):
            logger.info(f"sol_payment: TX {sig[:20]} already processed, skip")
            continue

        await grant_timed_access(user_id, duration_hours, from_wallet)

        # Match tier label for the notification
        tier = next(
            (t for t in SOL_TIERS if abs(t["sol"] - expected) < 0.001), None
        )
        label = tier["label"] if tier else f"{duration_hours}h Access"

        await _notify_user(bot, user_id, label, duration_hours, amount_sol)

    # Keep seen_sigs bounded
    if len(seen_sigs) > 500:
        to_remove = list(seen_sigs)[:len(seen_sigs) - 200]
        for s in to_remove:
            seen_sigs.discard(s)


async def _notify_user(
    bot: Bot,
    user_id: int,
    label: str,
    duration_hours: int,
    amount_sol: float,
) -> None:
    dur_str = (
        f"{duration_hours}h"
        if duration_hours < 48
        else f"{duration_hours // 24}d"
    )
    text = (
        "╔══════════════════════════════╗\n"
        "║  🔱 <b>SUPREME BLACK — ACTIVATED</b> ║\n"
        "╚══════════════════════════════╝\n\n"
        "<code>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</code>\n"
        "Payment confirmed on-chain ✅\n"
        "You just fueled the dev auto-trader.\n"
        "Full Supreme Black access is now LIVE.\n"
        "<code>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</code>\n\n"
        f"<code>┌─ ACCESS SUMMARY ─────────────┐\n"
        f"│  TIER     {label:<21}│\n"
        f"│  DURATION {dur_str:<21}│\n"
        f"│  PAID     {amount_sol:.4f} SOL              │\n"
        f"│  STATUS   ONLINE ⚡             │\n"
        f"└──────────────────────────────┘</code>\n\n"
        "Auto-Exit, unlimited trades, all filters — everything's unlocked.\n"
        "Your timer has started. <b>Go make some moves ⚫</b>"
    )
    try:
        await bot.send_message(user_id, text, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"sol_payment: could not notify user {user_id}: {e}")
