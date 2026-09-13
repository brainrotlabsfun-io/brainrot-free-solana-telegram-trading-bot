"""
services/sniper_service.py
============================
Main coordinator for the Sniper Tool.
Ties together: entitlements, token data, scoring, settings, blacklist.

This is the primary entry point for the handler to call.
"""

import re
import logging
from typing import Optional

from services.brainrot_token_gate import get_entitlements, SniperEntitlements
from services.token_data_provider import get_token_summary, get_ranked_candidates_for_user
from services.sniper_score_service import score_token
from services.sniper_settings_service import get_settings
from services.sniper_blacklist_service import get_blacklist_addresses

logger = logging.getLogger(__name__)

# Solana address: base58, 32-44 chars
_SOLANA_RE = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')

# In-memory address cache for feed callbacks (short ID -> full address)
_addr_cache: dict[str, str] = {}
_cache_seq  = 0


def is_valid_solana_address(address: str) -> bool:
    return bool(_SOLANA_RE.match(address.strip()))


def cache_address(address: str) -> str:
    """Stores address in cache and returns a short numeric key for callback_data."""
    global _cache_seq
    _cache_seq  = (_cache_seq + 1) % 9999
    key         = str(_cache_seq)
    _addr_cache[key] = address
    return key


def get_cached_address(key: str) -> Optional[str]:
    return _addr_cache.get(key)


async def analyze_token_for_user(
    user_id: int,
    token_address: str,
) -> dict:
    """
    Full token analysis pipeline:
    1. Fetch entitlements
    2. Fetch token data from DexScreener
    3. Load user settings
    4. Score token
    Returns combined result dict.
    """
    entitlements = await get_entitlements(user_id)
    settings     = await get_settings(user_id)
    token_data   = await get_token_summary(token_address)

    if not token_data:
        return {"error": "Token not found on DexScreener. Check the address and try again."}

    score_result = score_token(token_data, settings, entitlements)

    return {
        "token":        token_data,
        "score":        score_result["score"],
        "rating":       score_result["rating"],
        "risk_notes":   score_result["risk_notes"],
        "summary":      score_result["summary"],
        "premium_notes":score_result.get("premium_notes"),
        "entitlements": entitlements,
        "tier":         entitlements.tier,
    }


async def get_feed_for_user(user_id: int) -> dict:
    """
    Builds ranked launch feed for a user applying their settings + blacklist.
    """
    entitlements = await get_entitlements(user_id)
    settings     = await get_settings(user_id)
    blacklist    = await get_blacklist_addresses(user_id)

    candidates   = await get_ranked_candidates_for_user(
        user_id, settings, blacklist, entitlements
    )

    return {
        "candidates":   candidates,
        "tier":         entitlements.tier,
        "limit":        entitlements.feed_result_limit,
        "count":        len(candidates),
        "entitlements": entitlements,
    }


def format_token_card(token: dict, index: int = 0) -> str:
    """Formats a single token into a compact display card for feeds."""
    score  = token.get("score", 0)
    rating = token.get("rating", "—")
    age    = token.get("age_minutes")
    age_s  = f"{age}m" if age is not None else "?"
    addr   = token.get("address", "")
    short  = addr[:6] + "..." + addr[-4:] if len(addr) > 10 else addr

    liq  = token.get("liquidity_usd", 0)
    vol  = token.get("volume_h1", 0)
    buys = token.get("buys_h1", 0)

    risks = token.get("risk_notes", [])
    risk_line = f"\n⚠️ {risks[0]}" if risks else ""

    return (
        f"{'─' * 28}\n"
        f"<b>{index}. {token.get('symbol','???')} — {token.get('name','Unknown')}</b>\n"
        f"<code>{short}</code>\n"
        f"💰 Liq: ${liq:,.0f}  📊 Vol: ${vol:,.0f}  🛒 Buys: {buys}\n"
        f"⏱ Age: {age_s}  |  {rating}  |  Score: {score}"
        f"{risk_line}"
    )
