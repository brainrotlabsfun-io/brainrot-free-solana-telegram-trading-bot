"""
services/gmgn_service.py
=========================
Raw async API layer for gmgn.ai — mirrors the Dragon tool's data-fetching
mechanics adapted for aiohttp.

All wallet intelligence data comes from gmgn.ai endpoints.
No Solana RPC is used for wallet scoring — gmgn pre-computes win rates,
PnL, and hold times from on-chain data.

Anti-rate-limit strategy:
  - asyncio.Semaphore caps concurrency
  - 429 responses trigger exponential backoff
  - Realistic browser headers on every request
  - 3 retries per call with jittered delay
"""

import asyncio
import logging
import random
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL      = "https://gmgn.ai"
SOLANA_FM_URL = "https://api.solana.fm"

REQUEST_TIMEOUT = 12       # seconds per request
MAX_RETRIES     = 3
RETRY_DELAY     = 1.5      # base delay, doubled on each retry
MAX_CONCURRENCY = 8        # simultaneous requests to gmgn

_semaphore: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    return _semaphore


# ── Headers ───────────────────────────────────────────────────────────────────
# Match Dragon's header set — gmgn checks for these

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]


def _build_headers() -> dict:
    return {
        "User-Agent":      random.choice(_USER_AGENTS),
        "Host":            "gmgn.ai",
        "Referer":         "https://gmgn.ai/?chain=sol",
        "Origin":          "https://gmgn.ai",
        "DNT":             "1",
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "Sec-Fetch-Dest":  "empty",
        "Sec-Fetch-Mode":  "cors",
        "Sec-Fetch-Site":  "same-origin",
    }


# ── Core Fetch ────────────────────────────────────────────────────────────────

async def _get(url: str, params: dict = None, host: str = "gmgn") -> Optional[dict]:
    """
    Single async GET with retry and rate-limit backoff.
    Returns parsed JSON dict or None on failure.
    """
    headers = _build_headers()
    if host != "gmgn":
        headers["Host"] = "api.solana.fm"
        headers.pop("Referer", None)
        headers.pop("Origin", None)

    for attempt in range(MAX_RETRIES):
        try:
            async with _get_semaphore():
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url,
                        params=params,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                        ssl=False,
                    ) as resp:
                        if resp.status == 429:
                            wait = RETRY_DELAY * (2 ** attempt) + random.uniform(0, 1)
                            logger.debug(f"GMGN rate-limited, waiting {wait:.1f}s")
                            await asyncio.sleep(wait)
                            continue
                        if resp.status != 200:
                            logger.debug(f"GMGN HTTP {resp.status} for {url}")
                            return None
                        return await resp.json(content_type=None)
        except asyncio.TimeoutError:
            logger.debug(f"GMGN timeout (attempt {attempt+1}) {url}")
        except Exception as e:
            logger.debug(f"GMGN error (attempt {attempt+1}): {e}")

        if attempt < MAX_RETRIES - 1:
            await asyncio.sleep(RETRY_DELAY * (attempt + 1))

    return None


# ── Wallet Intelligence ───────────────────────────────────────────────────────

async def get_wallet_stats(wallet_address: str) -> Optional[dict]:
    """
    Fetch a wallet's smart-money stats from gmgn (7-day window).

    Returns:
        {
            winrate:             float   (0.0 – 1.0)
            realized_profit_7d:  float   (USD)
            realized_profit_30d: float   (USD)
            total_profit_pnl:    float   (all-time %)
            avg_holding_period:  float   (seconds → caller converts to mins)
            buy_7d:              int
            buy_30d:             int
            sol_balance:         float
            tags:                list[str]
            pnl_lt_minus_dot5x_num: int  (trades that lost >50%)
            pnl_2x_num:          int     (2x+ trades)
            pnl_5x_num:          int     (5x+ trades)
            pnl_10x_num:         int     (10x+ trades)
        }
    None if the wallet is unknown or the request fails.
    """
    url  = f"{BASE_URL}/defi/quotation/v1/smartmoney/sol/walletNew/{wallet_address}"
    data = await _get(url, params={"period": "7d"})
    if not data:
        return None

    d = data.get("data") or {}
    if not d:
        return None

    return {
        "winrate":               _safe_float(d.get("winrate")),
        "realized_profit_7d":   _safe_float(d.get("realized_profit_7d")),
        "realized_profit_30d":  _safe_float(d.get("realized_profit_30d")),
        "total_profit_pnl":     _safe_float(d.get("total_profit_pnl")),
        "avg_holding_period":   _safe_float(d.get("avg_holding_peroid")),  # gmgn typo
        "buy_7d":               int(d.get("buy_7d") or 0),
        "buy_30d":              int(d.get("buy_30d") or 0),
        "sol_balance":          _safe_float(d.get("sol_balance")),
        "tags":                 d.get("tags") or [],
        "pnl_lt_minus_dot5x_num": int(d.get("pnl_lt_minus_dot5x_num") or 0),
        "pnl_2x_num":           int(d.get("pnl_2x_num") or 0),
        "pnl_5x_num":           int(d.get("pnl_5x_num") or 0),
        "pnl_10x_num":          int(d.get("pnl_10x_num") or 0),
    }


# ── Top Traders per Token ─────────────────────────────────────────────────────

async def get_top_traders(contract_address: str, limit: int = 20) -> list[dict]:
    """
    Fetch top-performing wallets for a token, sorted by realized profit.
    Returns up to `limit` entries, each with:
        {
            wallet:            str
            realized_profit:   float (USD)
            unrealized_profit: float (USD)
            total_cost:        float (USD)
            profit_change:     float (multiplier, e.g. 3.5 = 3.5x)
            buy_count:         int
            sell_count:        int
        }
    """
    url  = f"{BASE_URL}/vas/api/v1/token_traders/sol/{contract_address}"
    data = await _get(url, params={
        "orderby":   "realized_profit",
        "direction": "desc",
        "limit":     str(min(limit, 100)),
    })
    if not data:
        return []

    items = (data.get("data") or {}).get("traders") or data.get("data") or []
    if isinstance(items, dict):
        items = items.get("items") or []

    results = []
    for t in items[:limit]:
        mult = _safe_float(t.get("profit_change"))
        if mult is None:
            continue
        results.append({
            "wallet":            t.get("address") or t.get("maker") or "",
            "realized_profit":   _safe_float(t.get("realized_profit") or t.get("total_profit")),
            "unrealized_profit": _safe_float(t.get("unrealized_profit")),
            "total_cost":        _safe_float(t.get("total_cost") or t.get("cost")),
            "profit_change":     mult,
            "buy_count":         int(t.get("buy_tx_count_cur") or t.get("buy") or 0),
            "sell_count":        int(t.get("sell_tx_count_cur") or t.get("sell") or 0),
        })

    return results


# ── Early Buyers ──────────────────────────────────────────────────────────────

async def get_early_buyers(contract_address: str, limit: int = 30) -> list[dict]:
    """
    Fetch the first buyers of a token (reverse chronological order).
    Returns wallet addresses + entry data.
    """
    url  = f"{BASE_URL}/vas/api/v1/token_trades/sol/{contract_address}"
    data = await _get(url, params={"revert": "true", "limit": str(min(limit, 100))})
    if not data:
        return []

    items = (data.get("data") or {}).get("history") or data.get("data") or []
    if isinstance(items, dict):
        items = []

    results = []
    seen = set()
    for t in items:
        if t.get("event") != "buy":
            continue
        # Exclude developer/creator wallets
        tags = t.get("maker_token_tags") or []
        if "creator" in tags or "dev_team" in tags:
            continue
        wallet = t.get("maker") or ""
        if not wallet or wallet in seen:
            continue
        seen.add(wallet)
        results.append({
            "wallet":             wallet,
            "amount_usd":         _safe_float(t.get("amount_usd") or t.get("cost_usd")),
            "realized_profit":    _safe_float(t.get("realized_profit")),
            "unrealized_profit":  _safe_float(t.get("unrealized_profit")),
            "total_trade":        int(t.get("total_trade") or 0),
            "timestamp":          int(t.get("timestamp") or 0),
        })
        if len(results) >= limit:
            break

    return results


# ── Bundle Detector ───────────────────────────────────────────────────────────

async def get_dev_trades(contract_address: str) -> list[dict]:
    """Fetch buy transactions by the creator/dev team of a token."""
    url  = f"{BASE_URL}/defi/quotation/v1/trades/sol/{contract_address}"
    data = await _get(url, params={
        "limit":  "100",
        "maker":  "",
        "tag[]":  ["creator", "dev_team"],
    })
    if not data:
        return []

    items = (data.get("data") or {}).get("history") or []
    return [
        {
            "tx_hash":  t.get("tx_hash") or t.get("signature") or "",
            "event":    t.get("event") or "",
            "maker":    t.get("maker") or "",
            "amount":   _safe_float(t.get("amount") or 0),
        }
        for t in items
        if t.get("event") == "buy" and (t.get("tx_hash") or t.get("signature"))
    ]


async def get_token_info(contract_address: str) -> Optional[dict]:
    """Fetch token metadata including total supply."""
    url  = f"{BASE_URL}/defi/quotation/v1/tokens/sol/{contract_address}"
    data = await _get(url)
    if not data:
        return None
    return data.get("data") or data.get("token") or {}


async def decode_solana_tx(tx_hash: str) -> Optional[dict]:
    """Decode a Solana transaction via Solana.fm for bundle analysis."""
    url  = f"{SOLANA_FM_URL}/v0/transfers/{tx_hash}"
    data = await _get(url, host="solana.fm")
    return data


async def detect_bundle(contract_address: str) -> dict:
    """
    Detect if a token was bundled (coordinated multi-buy in same block by dev).

    Returns:
        {
            bundle_detected:   bool
            transactions:      int
            total_amount:      float
            pct_of_supply:     float  (0.0 – 100.0)
            tx_breakdown:      list[{tx_hash, amount, pct}]
        }
    """
    result = {
        "bundle_detected": False,
        "transactions":    0,
        "total_amount":    0.0,
        "pct_of_supply":   0.0,
        "tx_breakdown":    [],
    }

    # Get dev buys and token info in parallel
    dev_trades, token_info = await asyncio.gather(
        get_dev_trades(contract_address),
        get_token_info(contract_address),
    )

    if not dev_trades:
        return result

    total_supply = _safe_float(
        (token_info or {}).get("total_supply") or
        (token_info or {}).get("token", {}).get("total_supply")
    ) or 1_000_000_000  # pump.fun default

    # Decode each dev tx to get token transfer amounts
    tx_hashes = [t["tx_hash"] for t in dev_trades if t["tx_hash"]][:20]
    decoded   = await asyncio.gather(*[decode_solana_tx(h) for h in tx_hashes])

    amounts = []
    for tx_data in decoded:
        if not tx_data:
            continue
        transfers = tx_data.get("result") or tx_data.get("data", {}).get("transfers") or []
        for xfer in transfers:
            if xfer.get("action") == "transfer" and xfer.get("token"):
                raw = _safe_float(xfer.get("amount") or 0)
                if raw:
                    amount = raw / 1_000_000
                    amounts.append(amount)
                    break  # one token transfer per tx

    if len(amounts) > 1:
        result["bundle_detected"] = True

    total = sum(amounts)
    result["transactions"]  = len(amounts)
    result["total_amount"]  = total
    result["pct_of_supply"] = (total / total_supply * 100) if total_supply else 0
    result["tx_breakdown"]  = [
        {"amount": a, "pct": a / total_supply * 100 if total_supply else 0}
        for a in amounts
    ]

    return result


# ── Cross-Token Repeated Winners ──────────────────────────────────────────────

async def find_repeated_winners(
    contract_addresses: list[str],
    min_appearances: int = 2,
    top_n_per_token: int = 20,
) -> list[dict]:
    """
    Dragon's signature mechanic: find wallets that appear as top traders
    across MULTIPLE token contracts.

    A wallet appearing in top-performers on ≥ min_appearances different
    tokens is significantly more likely to be genuine smart money vs a
    lucky one-time trade.

    Returns list of:
        {
            wallet:      str
            appearances: int
            tokens:      list[str]  (contracts where they topped)
        }
    sorted by appearances descending.
    """
    from collections import defaultdict

    wallet_tokens: dict[str, list[str]] = defaultdict(list)

    # Fetch top traders for all contracts concurrently
    results = await asyncio.gather(*[
        get_top_traders(addr, limit=top_n_per_token)
        for addr in contract_addresses
    ], return_exceptions=True)

    for contract, traders in zip(contract_addresses, results):
        if isinstance(traders, Exception) or not traders:
            continue
        for t in traders:
            w = t.get("wallet") or ""
            if w:
                wallet_tokens[w].append(contract)

    repeated = [
        {
            "wallet":      wallet,
            "appearances": len(tokens),
            "tokens":      tokens,
        }
        for wallet, tokens in wallet_tokens.items()
        if len(tokens) >= min_appearances
    ]

    return sorted(repeated, key=lambda x: x["appearances"], reverse=True)


# ── GMGN Token Discovery ──────────────────────────────────────────────────────

async def get_new_pump_tokens(category: str = "new", limit: int = 20) -> list[dict]:
    """
    Fetch trending pump.fun tokens by category.

    category:
        "new"        — newest launches (ordered by created_timestamp)
        "completing" — tokens filling their bonding curve (by progress)
        "soaring"    — fastest market cap growth (by market_cap_5m)
        "bonded"     — graduated to DEX (real liquidity)
    """
    category_params = {
        "new":        {"orderby": "created_timestamp", "direction": "desc", "new_creation": "true"},
        "completing": {"orderby": "progress",          "direction": "desc", "pump": "true"},
        "soaring":    {"orderby": "market_cap_5m",     "direction": "desc", "soaring": "true"},
    }

    if category == "bonded":
        url    = f"{BASE_URL}/defi/quotation/v1/pairs/sol/new_pairs/1h"
        params = {
            "limit":        str(limit),
            "orderby":      "market_cap",
            "direction":    "desc",
            "launchpad":    "pump",
            "period":       "1h",
            "filters[]":    ["not_honeypot", "pump"],
        }
    else:
        url    = f"{BASE_URL}/defi/quotation/v1/rank/sol/pump/1h"
        params = dict(category_params.get(category, category_params["new"]))
        params["limit"] = str(limit)

    data = await _get(url, params=params)
    if not data:
        return []

    items = (data.get("data") or {}).get("rank") or (data.get("data") or {}).get("pairs") or []
    return items[:limit]


# ── Utilities ─────────────────────────────────────────────────────────────────

def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def format_wallet_stats(stats: dict, wallet_address: str) -> str:
    """Format a wallet's stats into a clean Telegram message."""
    addr  = wallet_address[:6] + "..." + wallet_address[-4:]
    wr    = stats.get("winrate") or 0
    p7d   = stats.get("realized_profit_7d") or 0
    p30d  = stats.get("realized_profit_30d") or 0
    total = stats.get("total_profit_pnl") or 0
    hold  = stats.get("avg_holding_period") or 0
    b7d   = stats.get("buy_7d") or 0
    b30d  = stats.get("buy_30d") or 0
    sol   = stats.get("sol_balance") or 0
    tags  = stats.get("tags") or []

    # Convert holding period seconds to readable
    if hold < 3600:
        hold_str = f"{hold/60:.0f}m"
    elif hold < 86400:
        hold_str = f"{hold/3600:.1f}h"
    else:
        hold_str = f"{hold/86400:.1f}d"

    # Win rate colour
    wr_icon = "🟢" if wr >= 0.6 else "🟡" if wr >= 0.4 else "🔴"
    # PnL colour
    p7_icon  = "📈" if p7d  >= 0 else "📉"
    p30_icon = "📈" if p30d >= 0 else "📉"

    # Tags
    tag_str = ""
    if tags:
        tag_icons = {"smart_degen": "🧠", "sniper": "🎯", "whale": "🐋", "bot": "🤖"}
        tag_str = "  ".join(tag_icons.get(t, f"#{t}") for t in tags[:4])
        tag_str = f"\n<b>Tags:</b> {tag_str}"

    # Multibaggers
    x2  = stats.get("pnl_2x_num")  or 0
    x5  = stats.get("pnl_5x_num")  or 0
    x10 = stats.get("pnl_10x_num") or 0
    bags = f"2x: {x2}  5x: {x5}  10x: {x10}" if (x2 or x5 or x10) else "—"

    return (
        f"🔍 <b>Wallet Score</b>  <code>{addr}</code>\n"
        f"{'━' * 28}\n"
        f"{wr_icon} <b>Win Rate (7d):</b>  {wr*100:.1f}%\n"
        f"{p7_icon} <b>PnL 7d:</b>         ${p7d:,.0f}\n"
        f"{p30_icon} <b>PnL 30d:</b>        ${p30d:,.0f}\n"
        f"📊 <b>All-time PnL%:</b>  {total*100:.1f}%\n"
        f"⏱ <b>Avg Hold:</b>        {hold_str}\n"
        f"🛒 <b>Buys:</b>            {b7d} (7d)  /  {b30d} (30d)\n"
        f"💰 <b>SOL Balance:</b>     {sol:.2f} SOL\n"
        f"🎰 <b>Multibaggers:</b>    {bags}"
        f"{tag_str}"
    )
