"""
services/copy_trade_service.py
================================
CRUD layer for the Copy Trading module.

Handles:
  - Per-user copy trade settings (enabled state, sizing, risk controls)
  - Tracked wallet management (add/remove/list)
  - Token blacklist & whitelist (tier-gated)
  - Processed TX deduplication
  - Job audit trail
  - Tier-based entitlement enforcement
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

from database.sqlite_db import get_db
from utils.config import settings

logger = logging.getLogger(__name__)

# Absolute safety cap — even Supreme Black cannot exceed this
ABSOLUTE_MAX_WALLETS = 500

# ── Tier limit constants ──────────────────────────────────────────────────────

FREE_LIMITS = {
    "max_wallets":          3,
    "can_copy_sells":       False,
    "can_use_percentage":   False,
    "can_use_auto_sell":    False,
    "can_use_tp_sl":        False,
    "can_use_blacklist":    False,
    "can_use_whitelist":    False,
    "can_use_liq_filter":   False,
    "can_use_max_buy_prot": False,
    "can_use_cooldown":     False,
    "max_trades_per_hour":  30,
    "blacklist_limit":      0,
    "whitelist_limit":      0,
}

SUPREME_LIMITS = {
    "max_wallets":          20,
    "can_copy_sells":       True,
    "can_use_percentage":   True,
    "can_use_auto_sell":    False,
    "can_use_tp_sl":        False,
    "can_use_blacklist":    True,
    "can_use_whitelist":    False,
    "can_use_liq_filter":   True,
    "can_use_max_buy_prot": True,
    "can_use_cooldown":     True,
    "max_trades_per_hour":  80,
    "blacklist_limit":      50,
    "whitelist_limit":      0,
}

SUPREME_BLACK_LIMITS = {
    "max_wallets":          ABSOLUTE_MAX_WALLETS,
    "can_copy_sells":       True,
    "can_use_percentage":   True,
    "can_use_auto_sell":    True,
    "can_use_tp_sl":        True,
    "can_use_blacklist":    True,
    "can_use_whitelist":    True,
    "can_use_liq_filter":   True,
    "can_use_max_buy_prot": True,
    "can_use_cooldown":     True,
    "max_trades_per_hour":  150,
    "blacklist_limit":      9999,
    "whitelist_limit":      9999,
}


@dataclass
class CopyTradeEntitlements:
    tier:                 str
    max_wallets:          int
    can_copy_sells:       bool
    can_use_percentage:   bool
    can_use_auto_sell:    bool
    can_use_tp_sl:        bool
    can_use_blacklist:    bool
    can_use_whitelist:    bool
    can_use_liq_filter:   bool
    can_use_max_buy_prot: bool
    can_use_cooldown:     bool
    max_trades_per_hour:  int
    blacklist_limit:      int
    whitelist_limit:      int


async def get_copy_trade_entitlements(user_id: int) -> CopyTradeEntitlements:
    """Returns copy-trade entitlements based on the user's active tier."""
    from services.brainrot_token_gate import get_active_tier
    tier = await get_active_tier(user_id)
    if tier == "supreme_black":
        lims = SUPREME_BLACK_LIMITS
    elif tier == "supreme":
        lims = SUPREME_LIMITS
    else:
        lims = FREE_LIMITS
    return CopyTradeEntitlements(tier=tier, **lims)


# ── Settings Defaults ─────────────────────────────────────────────────────────

SETTINGS_DEFAULTS = {
    "enabled":              0,
    "kill_switch":          0,
    "copy_buys":            1,
    "copy_sells":           0,
    "copy_size_mode":       "fixed",   # "fixed" | "percentage"
    "fixed_amount_sol":     0.05,
    "percentage_amount":    10.0,      # % of leader's trade size
    "max_buy_amount_sol":   0.5,
    "max_slippage":         15.0,
    "min_liquidity_usd":    0.0,
    "auto_sell":            0,
    "take_profit_pct":      0.0,
    "stop_loss_pct":        0.0,
    "cooldown_seconds":     30,
    "max_trades_per_hour":  30,
    "priority_fee":         0.005,
}


# ── Settings CRUD ─────────────────────────────────────────────────────────────

async def get_copy_trade_settings(user_id: int) -> dict:
    """Fetch copy trade settings; inserts defaults if the row doesn't exist."""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM copy_trade_settings WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()

    if row is None:
        await _insert_default_settings(user_id)
        return dict(SETTINGS_DEFAULTS) | {"user_id": user_id}

    result = dict(SETTINGS_DEFAULTS)
    result.update({k: row[k] for k in row.keys() if k in result or k == "user_id"})
    return result


async def _insert_default_settings(user_id: int) -> None:
    async with get_db() as db:
        await db.execute("""
            INSERT OR IGNORE INTO copy_trade_settings (user_id)
            VALUES (?)
        """, (user_id,))
        await db.commit()


async def update_copy_trade_field(user_id: int, field: str, value) -> None:
    """Update a single field in copy_trade_settings."""
    allowed = set(SETTINGS_DEFAULTS.keys())
    if field not in allowed:
        raise ValueError(f"Invalid copy trade setting field: {field}")
    async with get_db() as db:
        await db.execute(f"""
            INSERT INTO copy_trade_settings (user_id, {field}, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                {field}     = excluded.{field},
                updated_at  = CURRENT_TIMESTAMP
        """, (user_id, value))
        await db.commit()


async def toggle_copy_trade(user_id: int) -> bool:
    """Toggle copy trading enabled state. Returns new state."""
    s = await get_copy_trade_settings(user_id)
    new_state = 0 if s.get("enabled") else 1
    await update_copy_trade_field(user_id, "enabled", new_state)
    return bool(new_state)


async def toggle_kill_switch(user_id: int) -> bool:
    """Toggle kill switch. Returns new state."""
    s = await get_copy_trade_settings(user_id)
    new_state = 0 if s.get("kill_switch") else 1
    await update_copy_trade_field(user_id, "kill_switch", new_state)
    return bool(new_state)


# ── Wallet Management ─────────────────────────────────────────────────────────

def _is_valid_solana_address(address: str) -> bool:
    """Basic Solana base58 address validation (32–44 chars, base58 charset)."""
    import re
    return bool(re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$', address.strip()))


async def add_tracked_wallet(
    user_id: int,
    wallet_address: str,
    label: str = "",
) -> tuple[bool, str]:
    """
    Add a wallet to the user's copy-trade tracking list.
    Returns (success, error_message).
    """
    wallet_address = wallet_address.strip()
    if not _is_valid_solana_address(wallet_address):
        return False, "Invalid Solana wallet address."

    ents = await get_copy_trade_entitlements(user_id)
    current = await get_tracked_wallets(user_id)

    if len(current) >= ents.max_wallets:
        return False, (
            f"Wallet limit reached ({ents.max_wallets} for {ents.tier.replace('_', ' ').title()} tier). "
            f"Upgrade to add more."
        )

    try:
        async with get_db() as db:
            await db.execute("""
                INSERT INTO copy_trade_wallets (user_id, wallet_address, label, enabled)
                VALUES (?, ?, ?, 1)
            """, (user_id, wallet_address, label[:64]))
            await db.commit()
        return True, ""
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return False, "That wallet is already in your tracking list."
        logger.error(f"add_tracked_wallet error user={user_id}: {e}")
        return False, "Database error — please try again."


async def remove_tracked_wallet(user_id: int, wallet_id: int) -> bool:
    """Remove a wallet by its row ID. Returns True on success."""
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM copy_trade_wallets WHERE id = ? AND user_id = ?",
            (wallet_id, user_id)
        )
        await db.commit()
        return cur.rowcount > 0


async def toggle_tracked_wallet(user_id: int, wallet_id: int) -> Optional[bool]:
    """Toggle a wallet's enabled state. Returns new state or None if not found."""
    async with get_db() as db:
        async with db.execute(
            "SELECT enabled FROM copy_trade_wallets WHERE id = ? AND user_id = ?",
            (wallet_id, user_id)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        new_state = 0 if row["enabled"] else 1
        await db.execute(
            "UPDATE copy_trade_wallets SET enabled = ? WHERE id = ? AND user_id = ?",
            (new_state, wallet_id, user_id)
        )
        await db.commit()
    return bool(new_state)


async def get_tracked_wallets(user_id: int) -> list[dict]:
    """Return all tracked wallets for a user."""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM copy_trade_wallets WHERE user_id = ? ORDER BY created_at ASC",
            (user_id,)
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_all_active_tracked_wallets() -> list[dict]:
    """
    Return all unique wallet addresses being actively tracked by at least one
    enabled user. Used by the worker to build its monitoring set.
    """
    async with get_db() as db:
        async with db.execute("""
            SELECT DISTINCT ctw.wallet_address
            FROM copy_trade_wallets ctw
            JOIN copy_trade_settings cts ON ctw.user_id = cts.user_id
            WHERE ctw.enabled = 1
              AND cts.enabled = 1
              AND cts.kill_switch = 0
        """) as cur:
            rows = await cur.fetchall()
    return [r["wallet_address"] for r in rows]


async def get_users_tracking_wallet(wallet_address: str) -> list[dict]:
    """
    Return all user settings rows for users actively tracking a given wallet.
    Joined with copy_trade_settings for immediate use in the worker.
    """
    async with get_db() as db:
        async with db.execute("""
            SELECT ctw.user_id, ctw.id AS wallet_row_id, ctw.label,
                   cts.enabled, cts.kill_switch, cts.copy_buys, cts.copy_sells,
                   cts.copy_size_mode, cts.fixed_amount_sol, cts.percentage_amount,
                   cts.max_buy_amount_sol, cts.max_slippage, cts.min_liquidity_usd,
                   cts.auto_sell, cts.take_profit_pct, cts.stop_loss_pct,
                   cts.cooldown_seconds, cts.max_trades_per_hour, cts.priority_fee
            FROM copy_trade_wallets ctw
            JOIN copy_trade_settings cts ON ctw.user_id = cts.user_id
            WHERE ctw.wallet_address = ?
              AND ctw.enabled        = 1
              AND cts.enabled        = 1
              AND cts.kill_switch    = 0
        """, (wallet_address,)) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ── Token Blacklist ───────────────────────────────────────────────────────────

async def add_to_token_blacklist(user_id: int, token_address: str) -> tuple[bool, str]:
    ents = await get_copy_trade_entitlements(user_id)
    if not ents.can_use_blacklist:
        return False, "Token blacklist requires SUPREME or higher."

    token_address = token_address.strip()
    if not _is_valid_solana_address(token_address):
        return False, "Invalid token address."

    current = await get_token_blacklist(user_id)
    if len(current) >= ents.blacklist_limit:
        return False, f"Blacklist full ({ents.blacklist_limit} max for your tier)."

    try:
        async with get_db() as db:
            await db.execute(
                "INSERT INTO copy_trade_token_blacklist (user_id, token_address) VALUES (?, ?)",
                (user_id, token_address)
            )
            await db.commit()
        return True, ""
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return False, "Token already blacklisted."
        return False, "Database error."


async def remove_from_token_blacklist(user_id: int, entry_id: int) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM copy_trade_token_blacklist WHERE id = ? AND user_id = ?",
            (entry_id, user_id)
        )
        await db.commit()
    return cur.rowcount > 0


async def get_token_blacklist(user_id: int) -> list[dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM copy_trade_token_blacklist WHERE user_id = ? ORDER BY added_at DESC",
            (user_id,)
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_blacklisted_addresses(user_id: int) -> set[str]:
    entries = await get_token_blacklist(user_id)
    return {e["token_address"] for e in entries}


# ── Token Whitelist ───────────────────────────────────────────────────────────

async def add_to_token_whitelist(user_id: int, token_address: str) -> tuple[bool, str]:
    ents = await get_copy_trade_entitlements(user_id)
    if not ents.can_use_whitelist:
        return False, "Token whitelist requires SUPREME BLACK."

    token_address = token_address.strip()
    if not _is_valid_solana_address(token_address):
        return False, "Invalid token address."

    current = await get_token_whitelist(user_id)
    if len(current) >= ents.whitelist_limit:
        return False, f"Whitelist full ({ents.whitelist_limit} max)."

    try:
        async with get_db() as db:
            await db.execute(
                "INSERT INTO copy_trade_token_whitelist (user_id, token_address) VALUES (?, ?)",
                (user_id, token_address)
            )
            await db.commit()
        return True, ""
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return False, "Token already whitelisted."
        return False, "Database error."


async def remove_from_token_whitelist(user_id: int, entry_id: int) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM copy_trade_token_whitelist WHERE id = ? AND user_id = ?",
            (entry_id, user_id)
        )
        await db.commit()
    return cur.rowcount > 0


async def get_token_whitelist(user_id: int) -> list[dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM copy_trade_token_whitelist WHERE user_id = ? ORDER BY added_at DESC",
            (user_id,)
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_whitelisted_addresses(user_id: int) -> set[str]:
    entries = await get_token_whitelist(user_id)
    return {e["token_address"] for e in entries}


# ── Duplicate TX Protection ───────────────────────────────────────────────────

async def is_tx_processed(tx_signature: str, user_id: int) -> bool:
    """Return True if this TX has already been processed for this user."""
    async with get_db() as db:
        async with db.execute(
            "SELECT 1 FROM processed_copy_txs WHERE tx_signature = ? AND user_id = ?",
            (tx_signature, user_id)
        ) as cur:
            return await cur.fetchone() is not None


async def mark_tx_processed(
    tx_signature: str,
    user_id: int,
    wallet_address: str,
    token_mint: str,
    direction: str,
) -> None:
    async with get_db() as db:
        await db.execute("""
            INSERT OR IGNORE INTO processed_copy_txs
                (tx_signature, user_id, wallet_address, token_mint, direction)
            VALUES (?, ?, ?, ?, ?)
        """, (tx_signature, user_id, wallet_address, token_mint, direction))
        await db.commit()


# ── Rate Limiting ─────────────────────────────────────────────────────────────

async def count_copy_trades_last_hour(user_id: int) -> int:
    """Count copy trade jobs executed in the last 60 minutes."""
    async with get_db() as db:
        async with db.execute("""
            SELECT COUNT(*) FROM copy_trade_jobs
            WHERE user_id  = ?
              AND status   IN ('executed', 'queued')
              AND created_at >= datetime('now', '-1 hour')
        """, (user_id,)) as cur:
            row = await cur.fetchone()
    return row[0] if row else 0


async def get_last_trade_time(user_id: int) -> float:
    """Return the unix timestamp of the most recent copy trade job, or 0."""
    async with get_db() as db:
        async with db.execute("""
            SELECT created_at FROM copy_trade_jobs
            WHERE user_id = ? AND status IN ('executed', 'queued')
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,)) as cur:
            row = await cur.fetchone()
    if not row:
        return 0.0
    import datetime as dt
    try:
        ts = dt.datetime.fromisoformat(str(row["created_at"]).replace(" ", "T"))
        return ts.timestamp()
    except Exception:
        return 0.0


# ── Job Logging ───────────────────────────────────────────────────────────────

async def log_copy_trade_job(
    user_id: int,
    followed_wallet: str,
    token_address: str,
    direction: str,
    leader_amount_sol: float = 0.0,
    copy_amount_sol: float = 0.0,
    source_tx_signature: str = "",
) -> int:
    """Create a copy_trade_jobs row. Returns the job ID."""
    async with get_db() as db:
        cur = await db.execute("""
            INSERT INTO copy_trade_jobs
                (user_id, followed_wallet, token_address, direction,
                 leader_amount_sol, copy_amount_sol, source_tx_signature, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'queued')
        """, (user_id, followed_wallet, token_address, direction,
              leader_amount_sol, copy_amount_sol, source_tx_signature))
        job_id = cur.lastrowid
        await db.commit()
    return job_id


async def update_copy_trade_job(
    job_id: int,
    status: str,
    tx_signature: str = "",
    skip_reason: str = "",
) -> None:
    async with get_db() as db:
        await db.execute("""
            UPDATE copy_trade_jobs
            SET status = ?, tx_signature = ?, skip_reason = ?,
                executed_at = CASE WHEN ? IN ('executed','failed','skipped')
                              THEN CURRENT_TIMESTAMP ELSE executed_at END
            WHERE id = ?
        """, (status, tx_signature, skip_reason, status, job_id))
        await db.commit()


async def get_copy_trade_jobs(user_id: int, limit: int = 20) -> list[dict]:
    async with get_db() as db:
        async with db.execute("""
            SELECT * FROM copy_trade_jobs
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_id, limit)) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ── Tweet Generator ───────────────────────────────────────────────────────────

async def generate_copy_trade_tweet(user_id: int, period_hours: int = 24) -> str:
    """
    Build a ready-to-post tweet summarising copy trading activity.

    Pulls all executed jobs in the last `period_hours` hours, computes:
      - Total trades (buys + sells)
      - Total SOL volume deployed
      - Unique wallets followed
      - Unique tokens traded
      - Success rate (executed vs failed)
      - Most-copied wallet (shortened)
      - Most-traded token (shortened)

    Returns the tweet as a plain string the user can copy-paste directly.
    Twitter limit is 280 chars — we keep it under that.
    """
    async with get_db() as db:
        async with db.execute("""
            SELECT direction, copy_amount_sol, followed_wallet, token_address,
                   status, created_at
            FROM copy_trade_jobs
            WHERE user_id   = ?
              AND status    IN ('executed', 'failed')
              AND created_at >= datetime('now', ?)
            ORDER BY created_at DESC
        """, (user_id, f"-{period_hours} hours")) as cur:
            rows = await cur.fetchall()

    if not rows:
        return (
            "No copy trades in the last "
            f"{period_hours}h to report yet. "
            f"Start copy trading with {settings.BRAND_HANDLE} 🧠"
        )

    jobs = [dict(r) for r in rows]

    executed = [j for j in jobs if j["status"] == "executed"]
    failed   = [j for j in jobs if j["status"] == "failed"]
    buys     = [j for j in executed if j["direction"] == "buy"]
    sells    = [j for j in executed if j["direction"] == "sell"]

    total_sol = sum(j.get("copy_amount_sol") or 0 for j in executed)
    success_rate = (len(executed) / len(jobs) * 100) if jobs else 0

    # Most-copied wallet
    from collections import Counter
    wallet_counts = Counter(j["followed_wallet"] for j in executed)
    top_wallet    = wallet_counts.most_common(1)
    top_wallet_str = ""
    if top_wallet:
        w = top_wallet[0][0]
        top_wallet_str = w[:4] + "…" + w[-4:]

    # Most-traded token
    token_counts = Counter(j["token_address"] for j in executed)
    top_token    = token_counts.most_common(1)
    top_token_str = ""
    if top_token:
        t = top_token[0][0]
        top_token_str = t[:4] + "…" + t[-4:]

    unique_wallets = len(set(j["followed_wallet"] for j in executed))
    unique_tokens  = len(set(j["token_address"]   for j in executed))

    period_label = f"{period_hours}h" if period_hours < 24 else (
        "24h" if period_hours == 24 else f"{period_hours // 24}d"
    )

    # Build tweet — keep it punchy and under 280 chars
    lines = [
        f"📋 Copy Trade Recap ({period_label}) | {settings.BRAND_HANDLE}",
        "",
        f"✅ {len(executed)} trades executed  ❌ {len(failed)} failed",
        f"🟢 {len(buys)} buys  🔴 {len(sells)} sells",
        f"💰 {total_sol:.3f} SOL deployed",
        f"🎯 {success_rate:.0f}% success rate",
        f"👛 {unique_wallets} wallet{'s' if unique_wallets != 1 else ''} followed  "
        f"🪙 {unique_tokens} token{'s' if unique_tokens != 1 else ''} traded",
    ]

    if top_wallet_str:
        lines.append(f"🔥 Top wallet: {top_wallet_str}")
    if top_token_str:
        lines.append(f"🏆 Top token: {top_token_str}")

    lines += ["", "#Solana #CopyTrading #BRAINROT #DeFi #Memecoin #SolanaTrading"]

    tweet = "\n".join(lines)

    # Hard trim to 280 chars if needed (shouldn't normally be hit)
    if len(tweet) > 280:
        tweet = tweet[:277] + "..."

    return tweet
