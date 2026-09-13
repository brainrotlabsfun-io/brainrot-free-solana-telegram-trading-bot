"""
services/candle_sniper_service.py
===================================
Candle Sniper settings CRUD, mode override save/restore,
candidate management, and position lifecycle.

Mode Override Design
--------------------
When Candle Sniper is ENABLED:
  - The user's current sniper_settings row is JSON-serialized and saved to
    candle_sniper_previous_config (if restore_previous_config = 1).
  - candle_sniper_settings.enabled is set to 1.
  - The CS worker begins its own discovery/scoring/execution loop.
  - The regular auto-buy worker is not modified; CS runs as an additive layer.

When Candle Sniper is DISABLED:
  - If restore_previous_config = 1, the saved sniper_settings snapshot is
    restored back to the sniper_settings table.
  - candle_sniper_settings.enabled is set to 0.
  - The CS worker stops processing for this user.

Entitlements (Candle Sniper tier limits):
  Tier          | Candidates | Max Positions | Config Access
  Free          | 3          | 1             | Basic only
  SUPREME       | 10         | 3             | Full
  SUPREME BLACK | 20         | 5             | Full + partial TP
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp

from database.sqlite_db import get_db
from utils.config import settings

logger = logging.getLogger(__name__)

_DEXSCREENER_TIMEOUT = aiohttp.ClientTimeout(total=12)

# ── Candle Sniper Entitlements ────────────────────────────────────────────────

@dataclass
class CSEntitlements:
    tier:                  str
    max_candidates:        int    # max tokens tracked simultaneously
    max_open_positions:    int    # max concurrent CS positions
    can_auto_buy:          bool
    can_trailing_stop:     bool   # trailing stop exit logic
    can_partial_tp:        bool   # partial take-profit (Supreme Black only)
    can_full_config:       bool   # access to all settings fields
    candidate_scan_limit:  int    # max candidates fetched per scan cycle


def get_cs_entitlements(tier: str) -> CSEntitlements:
    if tier == "supreme_black":
        return CSEntitlements(
            tier="supreme_black",
            max_candidates=9999,   # unlimited
            max_open_positions=9999,  # unlimited
            can_auto_buy=True,
            can_trailing_stop=True,
            can_partial_tp=True,
            can_full_config=True,
            candidate_scan_limit=200,
        )
    if tier == "supreme":
        return CSEntitlements(
            tier="supreme",
            max_candidates=50,
            max_open_positions=15,
            can_auto_buy=True,
            can_trailing_stop=True,
            can_partial_tp=False,
            can_full_config=True,
            candidate_scan_limit=100,
        )
    # Free tier
    return CSEntitlements(
        tier="free",
        max_candidates=15,
        max_open_positions=5,
        can_auto_buy=True,
        can_trailing_stop=False,
        can_partial_tp=False,
        can_full_config=False,   # basic settings only
        candidate_scan_limit=30,
    )


# ── Default Settings ──────────────────────────────────────────────────────────

_DEFAULTS = {
    "enabled":                0,
    "strategy_profile":      "balanced",
    "timeframe":             "5m",
    "scan_window":            20,
    "min_confirmations":       3,
    "confidence_threshold":   40,
    "auto_buy":                0,
    "max_open_positions":      5,
    "trade_size_sol":         0.05,
    "stop_loss_pct":         15.0,
    "take_profit_pct":       50.0,
    "trailing_stop_pct":     10.0,
    "slippage_pct":           5.0,
    "cooldown_seconds":      300,
    "max_hold_minutes":      480,
    "restore_previous_config": 1,
    "surge_enabled":         0,
    "surge_threshold_pct": 500.0,
    "surge_track_hours":    24,
}


# ── Settings CRUD ─────────────────────────────────────────────────────────────

async def get_cs_settings(user_id: int) -> dict:
    """Returns CS settings for user, creating defaults on first call."""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM candle_sniper_settings WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()

    if row is None:
        await _create_default_settings(user_id)
        return dict(_DEFAULTS, user_id=user_id)

    d = dict(row)
    # Fill any missing keys with defaults (forward-compat)
    for k, v in _DEFAULTS.items():
        d.setdefault(k, v)
    return d


async def _create_default_settings(user_id: int) -> None:
    async with get_db() as db:
        await db.execute("""
            INSERT OR IGNORE INTO candle_sniper_settings (user_id) VALUES (?)
        """, (user_id,))
        await db.commit()


async def update_cs_field(user_id: int, field: str, value) -> None:
    """Update a single CS settings field."""
    allowed = set(_DEFAULTS.keys()) - {"enabled"}  # enabled managed separately
    if field not in allowed:
        raise ValueError(f"Unknown CS settings field: {field}")

    await get_cs_settings(user_id)  # ensure row exists
    async with get_db() as db:
        await db.execute(
            f"UPDATE candle_sniper_settings SET {field} = ?, updated_at = CURRENT_TIMESTAMP "
            f"WHERE user_id = ?",
            (value, user_id),
        )
        await db.commit()
    logger.debug(f"CS field updated user={user_id} {field}={value}")


# ── Mode Enable / Disable (Override Logic) ───────────────────────────────────

async def enable_candle_sniper(user_id: int) -> None:
    """
    Activates Candle Sniper mode for the user.

    If restore_previous_config = 1 (default), the user's current sniper_settings
    row is captured and saved to candle_sniper_previous_config so it can be
    restored when CS is disabled.
    """
    cfg = await get_cs_settings(user_id)
    if cfg.get("restore_previous_config"):
        await _snapshot_sniper_settings(user_id)

    async with get_db() as db:
        await db.execute(
            "UPDATE candle_sniper_settings SET enabled = 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()
    logger.info(f"Candle Sniper ENABLED for user={user_id}")


async def disable_candle_sniper(user_id: int) -> bool:
    """
    Deactivates Candle Sniper mode.

    Returns True if previous sniper config was restored, False otherwise.
    """
    cfg = await get_cs_settings(user_id)
    restored = False

    if cfg.get("restore_previous_config"):
        restored = await _restore_sniper_settings(user_id)

    async with get_db() as db:
        await db.execute(
            "UPDATE candle_sniper_settings SET enabled = 0, updated_at = CURRENT_TIMESTAMP "
            "WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()
    logger.info(f"Candle Sniper DISABLED for user={user_id} (config_restored={restored})")
    return restored


async def toggle_candle_sniper(user_id: int) -> bool:
    """Toggle CS on/off. Returns new enabled state."""
    cfg = await get_cs_settings(user_id)
    if cfg.get("enabled"):
        await disable_candle_sniper(user_id)
        return False
    else:
        await enable_candle_sniper(user_id)
        return True


async def _snapshot_sniper_settings(user_id: int) -> None:
    """Capture current sniper_settings to candle_sniper_previous_config."""
    try:
        async with get_db() as db:
            async with db.execute(
                "SELECT * FROM sniper_settings WHERE user_id = ?", (user_id,)
            ) as cur:
                row = await cur.fetchone()

        if row is None:
            return  # no settings to save

        snapshot = json.dumps(dict(row))
        async with get_db() as db:
            await db.execute("""
                INSERT INTO candle_sniper_previous_config (user_id, settings_json, saved_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    settings_json = excluded.settings_json,
                    saved_at      = CURRENT_TIMESTAMP
            """, (user_id, snapshot))
            await db.commit()
        logger.debug(f"Sniper config snapshot saved for user={user_id}")
    except Exception as exc:
        logger.warning(f"Failed to snapshot sniper settings for user={user_id}: {exc}")


async def _restore_sniper_settings(user_id: int) -> bool:
    """Restore sniper_settings from candle_sniper_previous_config snapshot."""
    try:
        async with get_db() as db:
            async with db.execute(
                "SELECT settings_json FROM candle_sniper_previous_config WHERE user_id = ?",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()

        if not row or not row["settings_json"]:
            return False

        data = json.loads(row["settings_json"])
        # Restore writable fields only (skip id, user_id, created_at)
        writable = [
            "min_liquidity", "min_volume", "min_buys", "max_token_age_minutes",
            "max_risk_level", "default_buy_size", "default_slippage",
            "strict_mode", "auto_filter_enabled", "prioritize_fresh_launches",
            "prioritize_liquidity_strength", "instant_alert_on_match", "preferred_platform",
        ]
        updates = {k: data[k] for k in writable if k in data}
        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [user_id]
            async with get_db() as db:
                await db.execute(
                    f"UPDATE sniper_settings SET {set_clause} WHERE user_id = ?",
                    values,
                )
                await db.commit()
        logger.info(f"Sniper config restored for user={user_id}")
        return True
    except Exception as exc:
        logger.warning(f"Failed to restore sniper settings for user={user_id}: {exc}")
        return False


# ── Candidate Management ──────────────────────────────────────────────────────

async def upsert_candidate(token: dict, profile: str, score_result: dict) -> int:
    """
    Insert or update a scored candidate in the candle_sniper_candidates table.
    Returns the candidate id.
    """
    import json as _json
    equations_json = _json.dumps(score_result.get("equations", []))

    async with get_db() as db:
        # Check if already exists and active
        async with db.execute(
            "SELECT id FROM candle_sniper_candidates "
            "WHERE token_address = ? AND status = 'active'",
            (token["address"],),
        ) as cur:
            existing = await cur.fetchone()

        if existing:
            await db.execute("""
                UPDATE candle_sniper_candidates
                SET composite_score = ?, equations_passed = ?,
                    equations_json = ?, liquidity_usd = ?,
                    volume_h1 = ?, buy_ratio_h1 = ?,
                    age_minutes = ?, strategy_profile = ?,
                    expires_at = datetime('now', '+2 hours')
                WHERE id = ?
            """, (
                score_result["composite_score"],
                score_result["equations_passed"],
                equations_json,
                token.get("liquidity_usd", 0),
                token.get("volume_h1", 0),
                _buy_ratio(token),
                token.get("age_minutes", 0),
                profile,
                existing["id"],
            ))
            await db.commit()
            return existing["id"]

        await db.execute("""
            INSERT INTO candle_sniper_candidates
                (token_address, token_name, token_symbol, composite_score,
                 equations_passed, equations_json, liquidity_usd,
                 volume_h1, buy_ratio_h1, age_minutes, strategy_profile,
                 expires_at, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now','+2 hours'),'active')
        """, (
            token["address"],
            token.get("name", ""),
            token.get("symbol", ""),
            score_result["composite_score"],
            score_result["equations_passed"],
            equations_json,
            token.get("liquidity_usd", 0),
            token.get("volume_h1", 0),
            _buy_ratio(token),
            token.get("age_minutes", 0),
            profile,
        ))
        await db.commit()
        async with db.execute("SELECT last_insert_rowid() AS id") as cur:
            row = await cur.fetchone()
        return row["id"] if row else 0


async def get_top_candidates(profile: str, limit: int = 10) -> list[dict]:
    """Returns top active scored candidates for a given strategy profile."""
    async with get_db() as db:
        async with db.execute("""
            SELECT * FROM candle_sniper_candidates
            WHERE status = 'active'
              AND (strategy_profile = ? OR strategy_profile IS NULL)
              AND (expires_at IS NULL OR expires_at > datetime('now'))
            ORDER BY composite_score DESC
            LIMIT ?
        """, (profile, limit)) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def expire_old_candidates() -> int:
    """Mark expired candidates as expired. Returns count expired."""
    async with get_db() as db:
        await db.execute("""
            UPDATE candle_sniper_candidates
            SET status = 'expired'
            WHERE status = 'active' AND expires_at < datetime('now')
        """)
        await db.commit()
        async with db.execute("SELECT changes() AS n") as cur:
            row = await cur.fetchone()
    return row["n"] if row else 0


async def mark_candidate_traded(token_address: str) -> None:
    async with get_db() as db:
        await db.execute("""
            UPDATE candle_sniper_candidates
            SET status = 'traded'
            WHERE token_address = ? AND status = 'active'
        """, (token_address,))
        await db.commit()


# ── Position Management ───────────────────────────────────────────────────────

async def open_cs_position(
    user_id: int,
    token_address: str,
    entry_price_sol: float,
    tx_signature: str,
    trade_size_sol: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    trailing_stop_pct: float,
    max_duration_minutes: int = 120,
    candidate_id: Optional[int] = None,
) -> int:
    """Log a new Candle Sniper position. Returns position id."""
    async with get_db() as db:
        await db.execute("""
            INSERT INTO candle_sniper_positions
                (user_id, token_address, candidate_id, entry_price_sol,
                 current_price_sol, highest_price_sol, trade_size_sol,
                 stop_loss_pct, take_profit_pct, trailing_stop_pct,
                 tx_signature, status, max_duration_minutes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,'open',?)
        """, (
            user_id, token_address, candidate_id,
            entry_price_sol, entry_price_sol, entry_price_sol,
            trade_size_sol, stop_loss_pct, take_profit_pct,
            trailing_stop_pct, tx_signature, max_duration_minutes,
        ))
        await db.commit()
        async with db.execute("SELECT last_insert_rowid() AS id") as cur:
            row = await cur.fetchone()
    return row["id"] if row else 0


async def get_cs_open_positions(user_id: int) -> list[dict]:
    async with get_db() as db:
        async with db.execute("""
            SELECT * FROM candle_sniper_positions
            WHERE user_id = ? AND status = 'open'
            ORDER BY opened_at DESC
        """, (user_id,)) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_all_open_cs_positions() -> list[dict]:
    """For the worker: all open CS positions across all users."""
    async with get_db() as db:
        async with db.execute("""
            SELECT p.*, s.trailing_stop_pct, s.stop_loss_pct, s.take_profit_pct
            FROM candle_sniper_positions p
            JOIN candle_sniper_settings s ON s.user_id = p.user_id
            WHERE p.status = 'open'
        """) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def update_cs_position_price(position_id: int, current_price: float) -> None:
    async with get_db() as db:
        await db.execute("""
            UPDATE candle_sniper_positions
            SET current_price_sol = ?,
                highest_price_sol = MAX(highest_price_sol, ?),
                trailing_active = CASE
                    -- Activate trailing stop once price is up (trailing_stop_pct + 5)% from entry.
                    -- e.g. 10% trailing → activates at +15% gain; 20% trailing → +25%.
                    -- This lets winners run past TP rather than capping at a fixed target.
                    WHEN ? > entry_price_sol * (1 + (trailing_stop_pct + 5.0) / 100.0)
                    THEN 1 ELSE trailing_active END
            WHERE id = ?
        """, (current_price, current_price, current_price, position_id))
        await db.commit()


async def close_cs_position(position_id: int, reason: str) -> None:
    async with get_db() as db:
        await db.execute("""
            UPDATE candle_sniper_positions
            SET status = 'closed', exit_reason = ?, closed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (reason, position_id))
        await db.commit()
    logger.info(f"CS position {position_id} closed: {reason}")


async def count_open_cs_positions(user_id: int) -> int:
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) AS n FROM candle_sniper_positions "
            "WHERE user_id = ? AND status = 'open'",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
    return row["n"] if row else 0


async def get_users_with_cs_autobuy() -> list[dict]:
    """Returns all users who have CS enabled AND auto_buy=1."""
    async with get_db() as db:
        async with db.execute("""
            SELECT cs.*, ha.tier
            FROM candle_sniper_settings cs
            LEFT JOIN holder_access ha ON ha.user_id = cs.user_id AND ha.active = 1
            WHERE cs.enabled = 1 AND cs.auto_buy = 1
        """) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ── Extended Token Data Fetch ─────────────────────────────────────────────────

async def fetch_cs_token_data(token_address: str) -> Optional[dict]:
    """
    Fetches extended DexScreener data including price-change fields needed
    by the 9 quant equations. Returns None on failure or if token is not on Solana.
    """
    url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
    try:
        async with aiohttp.ClientSession(timeout=_DEXSCREENER_TIMEOUT) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        pairs = data.get("pairs") or []
        sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
        if not sol_pairs:
            return None

        pair = max(sol_pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))
        return _parse_extended_pair(pair, token_address)
    except Exception as exc:
        logger.debug(f"fetch_cs_token_data({token_address[:8]}): {exc}")
        return None


# ── Watchlist Management ──────────────────────────────────────────────────────

async def get_user_watchlist(user_id: int) -> list[dict]:
    """Returns user's custom watchlist token additions."""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM candle_sniper_watchlist WHERE user_id = ? ORDER BY added_at DESC",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def add_watchlist_token(user_id: int, token_address: str,
                               symbol: str = "", name: str = "") -> bool:
    """Add a token to user's custom watchlist. Returns False if already exists."""
    try:
        async with get_db() as db:
            await db.execute("""
                INSERT INTO candle_sniper_watchlist
                    (user_id, token_address, token_symbol, token_name)
                VALUES (?, ?, ?, ?)
            """, (user_id, token_address, symbol, name))
            await db.commit()
        logger.info(f"CS watchlist add user={user_id} token={token_address[:8]} ({symbol})")
        return True
    except Exception:
        return False  # UNIQUE constraint = already exists


async def remove_watchlist_token(user_id: int, token_address: str) -> bool:
    """Remove a token from user's custom watchlist. Returns True if removed."""
    async with get_db() as db:
        await db.execute(
            "DELETE FROM candle_sniper_watchlist WHERE user_id = ? AND token_address = ?",
            (user_id, token_address),
        )
        await db.commit()
        async with db.execute("SELECT changes() AS n") as cur:
            row = await cur.fetchone()
    removed = (row["n"] if row else 0) > 0
    if removed:
        logger.info(f"CS watchlist remove user={user_id} token={token_address[:8]}")
    return removed


# ── Discovery ─────────────────────────────────────────────────────────────────

_PUMPFUN_API     = "https://frontend-api.pump.fun/coins"
_DEXSCREENER_BOOSTS_URL = "https://api.dexscreener.com/token-boosts/latest/v1"
_PUMPFUN_TIMEOUT = aiohttp.ClientTimeout(total=15)
_DEXSCREEN_SEM   = asyncio.Semaphore(5)  # max 5 concurrent DexScreener fetches

# Minimum market cap for pump.fun movers to avoid microscopic tokens (in SOL-equiv USD)
_PUMPFUN_MOVERS_MIN_MCAP_USD = 30_000   # ~$30k — filters out pre-traction noise


async def discover_candidates(user_id: Optional[int] = None) -> list[dict]:
    """
    Multi-source discovery:
      1. DexScreener boosts  — tokens teams are actively promoting
      2. pump.fun movers     — top tokens by recent trading activity (the
                               "movers" view: sort=last_reply / last_trade)
      3. pump.fun top mcap   — fallback when both above return nothing
      4. User's custom watchlist — always appended

    Returns extended token dicts sorted by volume_h1 descending.
    """
    token_entries: list[tuple[str, str, str]] = []  # (address, symbol, name)
    seen: set[str] = set()

    # ── Source 1: DexScreener boosts ─────────────────────────────────────────
    boosts_task   = _fetch_dexscreener_boosts(seen)
    # ── Source 2: pump.fun movers (runs concurrently with boosts) ────────────
    movers_task   = _pumpfun_movers(seen)

    boosts_entries, movers_entries = await asyncio.gather(
        boosts_task, movers_task, return_exceptions=True
    )

    if isinstance(boosts_entries, list):
        token_entries.extend(boosts_entries)
        seen.update(addr for addr, _, _ in boosts_entries)

    if isinstance(movers_entries, list):
        for entry in movers_entries:
            if entry[0] not in seen:
                seen.add(entry[0])
                token_entries.append(entry)

    # ── Source 3: pump.fun top by market cap (only if both above empty) ──────
    if not token_entries:
        token_entries = await _pumpfun_fallback(seen)

    # ── Source 4: User's custom watchlist ─────────────────────────────────────
    if user_id is not None:
        custom = await get_user_watchlist(user_id)
        for entry in custom:
            addr = entry["token_address"]
            if addr and addr not in seen:
                seen.add(addr)
                token_entries.append((
                    addr,
                    entry.get("token_symbol", ""),
                    entry.get("token_name", ""),
                ))

    if not token_entries:
        logger.info("CS discovery: no tokens to score")
        return []

    # ── Fetch pair data concurrently ──────────────────────────────────────────
    async def _fetch(addr: str, sym: str, name: str) -> Optional[dict]:
        async with _DEXSCREEN_SEM:
            try:
                token = await fetch_cs_token_data(addr)
                if token:
                    if not token.get("symbol") or token["symbol"] == "???":
                        token["symbol"] = sym or "???"
                    if not token.get("name") or token["name"] == "Unknown":
                        token["name"] = name or sym or "Unknown"
                return token
            except Exception as exc:
                logger.debug(f"CS fetch {addr[:8]}: {exc}")
                return None

    tasks = [_fetch(addr, sym, name) for addr, sym, name in token_entries]
    raw   = await asyncio.gather(*tasks, return_exceptions=True)

    results = [t for t in raw if isinstance(t, dict)]
    results.sort(key=lambda t: t.get("volume_h1") or 0, reverse=True)
    logger.info(
        f"CS discovery: {len(token_entries)} tokens fetched → {len(results)} with market data"
    )
    return results


async def _fetch_dexscreener_boosts(seen: set[str]) -> list[tuple[str, str, str]]:
    """Fetch DexScreener boosted Solana tokens sorted by boost amount."""
    entries: list[tuple[str, str, str]] = []
    try:
        async with aiohttp.ClientSession(timeout=_DEXSCREENER_TIMEOUT) as session:
            async with session.get(_DEXSCREENER_BOOSTS_URL) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    boosts = data if isinstance(data, list) else []
                    sol_boosts = [b for b in boosts if b.get("chainId") == "solana"]
                    sol_boosts.sort(key=lambda b: b.get("totalAmount", 0), reverse=True)
                    for boost in sol_boosts[:50]:
                        addr = (boost.get("tokenAddress") or "").strip()
                        if addr and addr not in seen:
                            entries.append((addr, "", ""))
                    logger.debug(f"CS boosts: {len(entries)} Solana tokens")
                else:
                    logger.warning(f"DexScreener boosts API status {resp.status}")
    except Exception as exc:
        logger.warning(f"DexScreener boosts fetch failed: {exc}")
    return entries


async def _pumpfun_movers(
    seen: set[str],
    limit: int = 40,
    min_mcap_usd: float = _PUMPFUN_MOVERS_MIN_MCAP_USD,
) -> list[tuple[str, str, str]]:
    """
    Fetch pump.fun "movers" — tokens with the most recent trading activity.

    Queries the pump.fun frontend API twice (last_trade_timestamp + market_cap
    sort) to mirror what users see in the movers table.  Includes both bonding-
    curve and graduated tokens as long as they meet the minimum market cap.
    """
    entries: list[tuple[str, str, str]] = []
    local_seen: set[str] = set()

    # Two passes: recent activity + top market-cap movers
    sort_modes = [
        ("last_reply",            "DESC"),   # most recently active/traded
        ("market_cap",            "DESC"),   # highest mcap trending
    ]

    async with aiohttp.ClientSession(timeout=_PUMPFUN_TIMEOUT) as session:
        for sort_key, order in sort_modes:
            try:
                params = {
                    "limit":        limit,
                    "offset":       0,
                    "sort":         sort_key,
                    "order":        order,
                    "includeNsfw":  "false",
                }
                async with session.get(
                    _PUMPFUN_API, params=params,
                    headers={"Accept": "application/json"}
                ) as resp:
                    if resp.status != 200:
                        logger.debug(f"pump.fun movers ({sort_key}) status {resp.status}")
                        continue
                    data = await resp.json(content_type=None)
                    coins = data if isinstance(data, list) else []

                for coin in coins:
                    mint = (coin.get("mint") or "").strip()
                    if not mint or mint in seen or mint in local_seen:
                        continue
                    # Market cap filter — skip micro-cap dust
                    mcap = float(coin.get("usd_market_cap") or coin.get("market_cap") or 0)
                    if mcap < min_mcap_usd:
                        continue
                    local_seen.add(mint)
                    entries.append((mint, coin.get("symbol", "???"), coin.get("name", "")))

            except Exception as exc:
                logger.debug(f"pump.fun movers ({sort_key}) failed: {exc}")

    if entries:
        logger.debug(f"CS pump.fun movers: {len(entries)} tokens (mcap ≥ ${min_mcap_usd:,.0f})")
    return entries


async def _pumpfun_fallback(seen: set[str], limit: int = 30) -> list[tuple[str, str, str]]:
    """Last-resort fallback: top pump.fun tokens by market cap (graduated only)."""
    entries: list[tuple[str, str, str]] = []
    try:
        params = {"limit": limit, "offset": 0, "sort": "market_cap",
                  "order": "DESC", "includeNsfw": "false"}
        async with aiohttp.ClientSession(timeout=_PUMPFUN_TIMEOUT) as session:
            async with session.get(_PUMPFUN_API, params=params,
                                   headers={"Accept": "application/json"}) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    coins = data if isinstance(data, list) else []
                    for coin in coins:
                        mint = (coin.get("mint") or "").strip()
                        if not mint or mint in seen:
                            continue
                        is_graduated = coin.get("complete", False) or bool(coin.get("raydium_pool", ""))
                        if not is_graduated:
                            continue
                        seen.add(mint)
                        entries.append((mint, coin.get("symbol", "???"), coin.get("name", "")))
                    logger.debug(f"CS pumpfun fallback: {len(entries)} tokens")
                else:
                    logger.debug(f"pump.fun fallback API status {resp.status}")
    except Exception as exc:
        logger.debug(f"pump.fun fallback failed: {exc}")
    return entries


# kept for backward compat — now delegates to discover_candidates
async def discover_pumpfun_candidates(
    limit: int = 50,
    min_market_cap_usd: float = 50_000,
    graduated_only: bool = False,
    user_id: Optional[int] = None,
) -> list[dict]:
    """Deprecated: now delegates to discover_candidates()."""
    return await discover_candidates(user_id=user_id)


def _parse_extended_pair(pair: dict, override_address: str = "") -> Optional[dict]:
    """Parse a raw DexScreener pair into extended CS token data."""
    from datetime import datetime, timezone
    try:
        base   = pair.get("baseToken") or {}
        liq    = pair.get("liquidity") or {}
        vol    = pair.get("volume") or {}
        txns   = pair.get("txns") or {}
        h1     = txns.get("h1") or {}
        h24    = txns.get("h24") or {}
        m5     = txns.get("m5") or {}
        pc     = pair.get("priceChange") or {}

        created_ms = pair.get("pairCreatedAt")
        if created_ms:
            now_ms     = datetime.now(timezone.utc).timestamp() * 1000
            age_minutes = max(0, int((now_ms - created_ms) / 60_000))
        else:
            age_minutes = None

        address = override_address or base.get("address", "")
        if not address:
            return None

        return {
            "address":          address,
            "name":             base.get("name", "Unknown"),
            "symbol":           base.get("symbol", "???"),
            "price_usd":        float(pair.get("priceUsd") or 0),
            "liquidity_usd":    float(liq.get("usd") or 0),
            "volume_h24":       float(vol.get("h24") or 0),
            "volume_h1":        float(vol.get("h1") or 0),
            "volume_m5":        float(vol.get("m5") or 0),
            "buys_h1":          int(h1.get("buys", 0)),
            "sells_h1":         int(h1.get("sells", 0)),
            "buys_h24":         int(h24.get("buys", 0)),
            "sells_h24":        int(h24.get("sells", 0)),
            "buys_m5":          int(m5.get("buys", 0)),
            "sells_m5":         int(m5.get("sells", 0)),
            "age_minutes":      age_minutes,
            "dex":              pair.get("dexId", "unknown"),
            "pair_address":     pair.get("pairAddress", ""),
            "price_change_m5":  float(pc.get("m5") or 0),
            "price_change_h1":  float(pc.get("h1") or 0),
            "price_change_h6":  float(pc.get("h6") or 0),
            "price_change_h24": float(pc.get("h24") or 0),
            "market_cap":       float(pair.get("marketCap") or pair.get("fdv") or 0),
            "source":           "dexscreener",
        }
    except Exception:
        return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _buy_ratio(token: dict) -> float:
    b = int(token.get("buys_h1") or 0)
    s = int(token.get("sells_h1") or 0)
    total = b + s
    return round(b / total, 4) if total > 0 else 0.0


# ── Surge Detection ────────────────────────────────────────────────────────────

async def record_cs_price(token: dict, track_hours: int = 24) -> None:
    """
    Save the first-seen price of a token for surge tracking.
    Uses INSERT OR IGNORE so only the FIRST price is ever stored per token.
    """
    addr   = token.get("address") or token.get("token_address") or ""
    symbol = token.get("symbol") or token.get("token_symbol") or ""
    price  = float(token.get("price_usd") or 0.0)
    mcap   = float(token.get("market_cap") or token.get("market_cap_usd") or 0.0)
    if not addr or price <= 0:
        return
    async with get_db() as db:
        await db.execute("""
            INSERT OR IGNORE INTO cs_price_history
                (token_address, token_symbol, price_usd, market_cap_usd, expires_at)
            VALUES (?, ?, ?, ?, datetime('now', ?))
        """, (addr, symbol, price, mcap, f"+{track_hours} hours"))
        await db.commit()


async def get_surge_candidates(min_age_minutes: int = 10) -> list[dict]:
    """
    Return all tracked tokens that were recorded at least min_age_minutes ago
    and haven't yet triggered a surge alert — with their baseline price.
    """
    async with get_db() as db:
        async with db.execute("""
            SELECT token_address, token_symbol, price_usd, market_cap_usd, recorded_at
            FROM cs_price_history
            WHERE expires_at > datetime('now')
              AND alerted    = 0
              AND recorded_at <= datetime('now', ?)
        """, (f"-{min_age_minutes} minutes",)) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def mark_surge_alerted(token_address: str) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE cs_price_history SET alerted = 1 WHERE token_address = ?",
            (token_address,)
        )
        await db.commit()


async def cleanup_expired_price_history() -> None:
    async with get_db() as db:
        await db.execute("DELETE FROM cs_price_history WHERE expires_at <= datetime('now')")
        await db.commit()


async def get_global_surge_candidates(min_age_minutes: int = 10) -> list[dict]:
    """
    Return all tracked tokens that haven't yet fired the global 5000% broadcast alert.
    Ignores the per-user `alerted` flag — this runs independently.
    """
    async with get_db() as db:
        async with db.execute("""
            SELECT token_address, token_symbol, price_usd, market_cap_usd, recorded_at
            FROM cs_price_history
            WHERE expires_at       > datetime('now')
              AND global_alerted   = 0
              AND recorded_at     <= datetime('now', ?)
        """, (f"-{min_age_minutes} minutes",)) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def mark_global_alerted(token_address: str) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE cs_price_history SET global_alerted = 1 WHERE token_address = ?",
            (token_address,)
        )
        await db.commit()


async def get_all_cs_users() -> list[int]:
    """Return user_ids of everyone who has any CS settings row (active or not)."""
    async with get_db() as db:
        async with db.execute("SELECT user_id FROM candle_sniper_settings") as cur:
            rows = await cur.fetchall()
    return [r["user_id"] for r in rows]


async def get_users_with_surge_enabled() -> list[dict]:
    """Return all users who have surge detection enabled and CS active."""
    async with get_db() as db:
        async with db.execute("""
            SELECT user_id, surge_threshold_pct, surge_track_hours,
                   trade_size_sol, slippage_pct, strategy_profile
            FROM candle_sniper_settings
            WHERE enabled        = 1
              AND surge_enabled  = 1
        """) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]
