"""
services/brainrot_gate.py
=========================
Premium access gate for $BRAINROT token holders.

Current state: PLACEHOLDER — always returns False for token verification.
Real on-chain verification will be implemented in a future module.

$BRAINROT Token Contract:
<your-token-mint>

Future implementation will:
- Accept a Solana wallet address from the user
- Query on-chain balance of $BRAINROT via RPC or Helius API
- Return True if balance meets the minimum threshold
- Cache the result to avoid repeated RPC calls
"""

import logging
from typing import Optional
from utils.config import settings

logger = logging.getLogger(__name__)

# ── Config Constants (adjust when real verification is implemented) ─────────────
BRAINROT_TOKEN_CONTRACT = settings.BRAINROT_MINT
MINIMUM_HOLD_AMOUNT = 1_000  # minimum $BRAINROT tokens required for premium


async def check_brainrot_holder(wallet_address: str) -> bool:
    """
    Checks whether a given Solana wallet holds enough $BRAINROT for premium access.

    PLACEHOLDER — currently returns False for all wallets.
    Replace the body of this function when Solana RPC integration is ready.

    Args:
        wallet_address: The user's Solana public key as a string.

    Returns:
        True if the wallet holds >= MINIMUM_HOLD_AMOUNT of $BRAINROT.
        False otherwise (or on any error).
    """
    # TODO: Implement real on-chain check. Example steps:
    #
    # from solana.rpc.async_api import AsyncClient
    # from spl.token.async_client import AsyncToken
    #
    # async with AsyncClient("https://api.mainnet-beta.solana.com") as client:
    #     token = AsyncToken(client, PublicKey(BRAINROT_TOKEN_CONTRACT), ...)
    #     balance = await token.get_balance(PublicKey(wallet_address))
    #     return balance.value.ui_amount >= MINIMUM_HOLD_AMOUNT

    logger.debug(f"[brainrot_gate] check_brainrot_holder called for {wallet_address} — placeholder returning False")
    return False


async def is_premium_user(user_id: int) -> bool:
    """
    Checks whether a Telegram user currently has premium status.

    PLACEHOLDER — currently returns False for all users.
    When wallet linking is implemented, this will:
    1. Look up the wallet address linked to user_id in the database
    2. Call check_brainrot_holder() with that wallet
    3. Return the result

    Args:
        user_id: Telegram user ID.

    Returns:
        True if the user has premium access, False otherwise.
    """
    # TODO: Query database for linked wallet, then call check_brainrot_holder()
    #
    # linked_wallet = await get_linked_wallet(user_id)
    # if not linked_wallet:
    #     return False
    # return await check_brainrot_holder(linked_wallet)

    logger.debug(f"[brainrot_gate] is_premium_user called for user {user_id} — placeholder returning False")
    return False


def get_premium_benefits_text() -> str:
    """Returns a formatted string describing premium benefits for display."""
    return (
        "👑 <b>$BRAINROT Premium Benefits</b>\n"
        "─────────────────────────\n\n"
        "🔥 <b>Double raid points</b> on every completed raid\n"
        "⚡ <b>Early raid alerts</b> before public announcements\n"
        "🏆 <b>Premium leaderboard</b> with exclusive rankings\n"
        "🎯 <b>Exclusive raids</b> with higher reward tiers\n"
        "🚀 <b>Priority access</b> to upcoming bot features\n\n"
        f"Token: <code>{BRAINROT_TOKEN_CONTRACT}</code>\n"
        f"Minimum hold: <b>{MINIMUM_HOLD_AMOUNT:,} $BRAINROT</b>"
    )
