"""
services/token_data_provider.py
================================
Token data fetching layer.  Uses DexScreener API (free, no auth).
Replace or extend with Helius / Birdeye / on-chain RPC as needed.

Public API:
  get_token_summary(address)          -> dict | None
  get_new_launches(limit)             -> list[dict]
  get_ranked_candidates_for_user(...) -> list[dict]
"""

import aiohttp
import logging
from datetime import datetime, timezone
from typing import Optional
from utils.config import settings

logger = logging.getLogger(__name__)

_BASE = "https://api.dexscreener.com"
_TIMEOUT = aiohttp.ClientTimeout(total=12)


def _age_minutes(created_at_ms: Optional[int]) -> Optional[int]:
    if not created_at_ms:
        return None
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    return max(0, int((now_ms - created_at_ms) / 60_000))


def _normalize_pair(pair: dict, override_address: str = "") -> dict:
    base    = pair.get("baseToken", {})
    liq     = pair.get("liquidity", {})
    vol     = pair.get("volume", {})
    chg     = pair.get("priceChange", {})
    h1      = pair.get("txns", {}).get("h1", {})
    h24     = pair.get("txns", {}).get("h24", {})
    mcap    = pair.get("marketCap") or pair.get("fdv") or 0
    return {
        "address":          override_address or base.get("address", ""),
        "name":             base.get("name", "Unknown"),
        "symbol":           base.get("symbol", "???"),
        "price_usd":        float(pair.get("priceUsd") or 0),
        "liquidity_usd":    float(liq.get("usd") or 0),
        "volume_h24":       float(vol.get("h24") or 0),
        "volume_h1":        float(vol.get("h1") or 0),
        "buys_h1":          int(h1.get("buys", 0)),
        "sells_h1":         int(h1.get("sells", 0)),
        "buys_h24":         int(h24.get("buys", 0)),
        "sells_h24":        int(h24.get("sells", 0)),
        "age_minutes":      _age_minutes(pair.get("pairCreatedAt")),
        "market_cap":       float(mcap),
        "price_change_h1":  float(chg.get("h1") or 0),
        "price_change_h6":  float(chg.get("h6") or 0),
        "price_change_h24": float(chg.get("h24") or 0),
        "dex":              pair.get("dexId", "unknown"),
        "pair_address":     pair.get("pairAddress", ""),
        "source":           "dexscreener",
    }


async def get_token_summary(token_address: str) -> Optional[dict]:
    """
    Returns normalized token data for a Solana token address, or None on failure.
    Uses the best Solana pair by liquidity from DexScreener.
    """
    url = f"{_BASE}/latest/dex/tokens/{token_address}"
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"DexScreener status {resp.status} for {token_address}")
                    return None
                data = await resp.json()

        pairs = data.get("pairs") or []
        sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
        if not sol_pairs:
            sol_pairs = pairs
        if not sol_pairs:
            return None

        # Best pair = highest USD liquidity
        pair = max(sol_pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))
        return _normalize_pair(pair, override_address=token_address)

    except Exception as exc:
        logger.error(f"get_token_summary({token_address}): {exc}")
        return None


async def get_token_price_in_sol(token_mint: str) -> Optional[float]:
    """
    Returns current token price denominated in SOL.

    Priority:
      1. DexScreener — works for all Solana tokens, no auth required
      2. pump.fun bonding curve API — fallback for tokens still on the curve
    Returns None only if both sources fail.
    """
    # ── 1. DexScreener ────────────────────────────────────────────────────────
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(
                f"{_BASE}/latest/dex/tokens/{token_mint}"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = [
                        p for p in (data.get("pairs") or [])
                        if p.get("chainId") == "solana"
                    ]
                    if pairs:
                        best = max(pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))
                        native = best.get("priceNative")
                        if native and float(native) > 0:
                            return float(native)
    except Exception as exc:
        logger.debug(f"DexScreener price miss for {token_mint[:8]}: {exc}")

    # ── 2. pump.fun bonding curve fallback ───────────────────────────────────
    # Works for any token still on the bonding curve (address ends with "pump")
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(
                f"https://frontend-api.pump.fun/coins/{token_mint}",
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 200:
                    coin = await resp.json()
                    vsr  = coin.get("virtual_sol_reserves")    # lamports
                    vtr  = coin.get("virtual_token_reserves")  # raw (6 decimals)
                    if vsr and vtr and int(vtr) > 0:
                        # price per token in SOL
                        price = (int(vsr) / 1e9) / (int(vtr) / 1e6)
                        return price
    except Exception as exc:
        logger.debug(f"pump.fun price miss for {token_mint[:8]}: {exc}")

    return None


async def get_new_launches(limit: int = 100) -> list[dict]:
    """
    Returns recent Solana token launches from DexScreener, sorted newest first.
    Filters to Solana chain only.
    """
    url = f"{_BASE}/latest/dex/pairs/solana"
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()

        pairs = data.get("pairs") or []
        results = []
        for pair in pairs:
            if pair.get("chainId") != "solana":
                continue
            norm = _normalize_pair(pair)
            if norm["address"]:
                results.append(norm)

        results.sort(key=lambda x: x.get("age_minutes") or 9999)
        return results[:limit]

    except Exception as exc:
        logger.error(f"get_new_launches: {exc}")
        return []


async def get_ranked_candidates_for_user(
    user_id: int,
    user_settings: dict,
    blacklist: list[str],
    entitlements,
) -> list[dict]:
    """
    Fetches new launches, applies user filters + blacklist, scores candidates.
    Returns ranked list respecting tier feed_result_limit.
    """
    from services.sniper_score_service import score_token

    raw = await get_new_launches(limit=200)

    bl_set = {a.lower() for a in blacklist}
    min_liq  = float(user_settings.get("min_liquidity", 1000))
    min_vol  = float(user_settings.get("min_volume", 500))
    min_buys = int(user_settings.get("min_buys", 5))
    max_age  = int(user_settings.get("max_token_age_minutes", 120))

    filtered = []
    for token in raw:
        if token["address"].lower() in bl_set:
            continue
        if token["liquidity_usd"] < min_liq:
            continue
        if token["volume_h1"] < min_vol:
            continue
        if token["buys_h1"] < min_buys:
            continue
        age = token.get("age_minutes")
        if age is not None and age > max_age:
            continue

        result = score_token(token, user_settings, entitlements)
        token["score"]      = result["score"]
        token["rating"]     = result["rating"]
        token["risk_notes"] = result["risk_notes"]
        token["summary"]    = result["summary"]
        if result.get("premium_notes"):
            token["premium_notes"] = result["premium_notes"]
        filtered.append(token)

    filtered.sort(key=lambda x: x.get("score", 0), reverse=True)
    limit = entitlements.feed_result_limit
    return filtered[:limit]
