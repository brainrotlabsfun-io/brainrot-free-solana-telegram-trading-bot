"""
services/auto_exit_service.py
==============================
Supreme Black Auto-Exit Manager — core service layer.

Responsibilities:
  - System preset seeding
  - Per-user auto-exit settings CRUD
  - Exit preset CRUD (system + user)
  - Position state registration and updates
  - Trigger evaluation (TP / SL / trailing stop / time exit)
  - Sell execution coordination with idempotency guards
  - Event logging
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from database.sqlite_db import get_db
from utils.config import settings

logger = logging.getLogger(__name__)

# ── Re-entry tracking ──────────────────────────────────────────────────────────
# In-memory counter: (user_id, token_address) → number of re-entries this session.
# Resets on bot restart, which is fine — session-scoped re-entry limits.
MAX_REENTRIES = 2
_reentry_counts: dict[tuple[int, str], int] = {}

# ── System preset definitions ──────────────────────────────────────────────────

# ── Preset calibration notes ───────────────────────────────────────────────────
# Target: profitable at ~33% win rate on Solana memecoins.
# Math: EV = WinRate × AvgWin - (1-WinRate) × AvgLoss > 0
# At 33% WR: need AvgWin > 2× AvgLoss.
#
# Key mechanic: taking 60%+ at TP1 means TP1 hit → trade is profitable regardless
# of what the remainder does. Break-even after TP1 prevents the remainder from
# turning a winner into a loser. SL only bites on the 67% of trades that never
# hit TP1 at all — and those are capped at the SL %.
#
# EV estimate for Quick Flip at 33% WR:
#   Winner: avg +30% on capital (TP1 + some TP2/trailing) = +0.015 SOL on 0.05
#   Loser:  avg -12% on capital                           = -0.006 SOL on 0.05
#   EV = 0.33×0.015 - 0.67×0.006 = 0.00495 - 0.00402 = +$0.001 per trade
#   Positive even at 33% — scales with position size and trade frequency.
# ──────────────────────────────────────────────────────────────────────────────

SYSTEM_PRESETS = [
    {
        # DEFAULT for most users. Captures fast pumps, break-even protects remainder.
        # EV-positive from ~30% win rate. Best for new pump.fun launches.
        "name":                "⚡ Quick Flip",
        "description":         "Take 60% at +20%, break-even locks remainder. Out in 8 min. Profitable at 30%+ WR.",
        "is_system":           1,
        "tp1_pct":             20.0,  "tp1_sell_pct":  60.0,
        "tp2_pct":             50.0,  "tp2_sell_pct":  25.0,
        "tp3_pct":             100.0, "tp3_sell_pct":  10.0,
        "moon_bag_pct":        5.0,
        "sl_pct":              -12.0,
        "trailing_stop_pct":   8.0,
        "trailing_after_tp":   1,
        "break_even_after_tp": 1,
        "max_hold_minutes":    8,
    },
    {
        # Holds longer, rides momentum. Better for high-conviction tokens.
        "name":                "🏃 Balanced Runner",
        "description":         "40% at +25%, ride to +80%. Trailing stop protects gains. 20 min hold.",
        "is_system":           1,
        "tp1_pct":             25.0,  "tp1_sell_pct":  40.0,
        "tp2_pct":             80.0,  "tp2_sell_pct":  35.0,
        "tp3_pct":             150.0, "tp3_sell_pct":  20.0,
        "moon_bag_pct":        5.0,
        "sl_pct":              -15.0,
        "trailing_stop_pct":   12.0,
        "trailing_after_tp":   1,
        "break_even_after_tp": 1,
        "max_hold_minutes":    20,
    },
    {
        # Most conservative. Take 70% of capital off at first sign of profit.
        # Lowest risk of all presets — small wins, very small losses.
        "name":                "🛡️ Fast Risk-Off",
        "description":         "Take 70% at +15% gain. Exit everything by 5 min. Capital protection first.",
        "is_system":           1,
        "tp1_pct":             15.0,  "tp1_sell_pct":  70.0,
        "tp2_pct":             35.0,  "tp2_sell_pct":  20.0,
        "tp3_pct":             60.0,  "tp3_sell_pct":  8.0,
        "moon_bag_pct":        2.0,
        "sl_pct":              -8.0,
        "trailing_stop_pct":   5.0,
        "trailing_after_tp":   1,
        "break_even_after_tp": 1,
        "max_hold_minutes":    5,
    },

    # ── Degen Fire strategy-matched exit presets ───────────────────────────────

    {
        # Ultra-fast scalp. 75% out at +10%. For micro-caps that spike and dump.
        "name":                "🔬 Degen Scalp",
        "description":         "75% out at +10%, rest trailing. Exit in 3 min. Best for micro-caps.",
        "is_system":           1,
        "tp1_pct":             10.0,  "tp1_sell_pct":  75.0,
        "tp2_pct":             25.0,  "tp2_sell_pct":  18.0,
        "tp3_pct":             50.0,  "tp3_sell_pct":  6.0,
        "moon_bag_pct":        1.0,
        "sl_pct":              -7.0,
        "trailing_stop_pct":   4.0,
        "trailing_after_tp":   1,
        "break_even_after_tp": 1,
        "max_hold_minutes":    3,
    },
    {
        # Rides volume spikes. Medium risk, medium hold time.
        "name":                "📈 Spike Rider",
        "description":         "50% at +25%, trails the spike. Exits by 20 min. Good for volume-spike tokens.",
        "is_system":           1,
        "tp1_pct":             25.0,  "tp1_sell_pct":  50.0,
        "tp2_pct":             60.0,  "tp2_sell_pct":  30.0,
        "tp3_pct":             100.0, "tp3_sell_pct":  15.0,
        "moon_bag_pct":        5.0,
        "sl_pct":              -15.0,
        "trailing_stop_pct":   10.0,
        "trailing_after_tp":   1,
        "break_even_after_tp": 1,
        "max_hold_minutes":    20,
    },
    {
        # DEX graduate tokens have more sustained momentum — can hold longer.
        "name":                "🎓 Grad Runner",
        "description":         "35% at +30%, ride DEX listing rally to +150%. 35 min hold.",
        "is_system":           1,
        "tp1_pct":             30.0,  "tp1_sell_pct":  35.0,
        "tp2_pct":             80.0,  "tp2_sell_pct":  30.0,
        "tp3_pct":             150.0, "tp3_sell_pct":  25.0,
        "moon_bag_pct":        10.0,
        "sl_pct":              -18.0,
        "trailing_stop_pct":   12.0,
        "trailing_after_tp":   2,
        "break_even_after_tp": 1,
        "max_hold_minutes":    35,
    },
    {
        # Panic-wave entries that reverse hard. Get in, grab 10%, leave.
        "name":                "😱 Panic Flip",
        "description":         "80% out at +10%, gone in 4 min. For panic-wave plays that reverse fast.",
        "is_system":           1,
        "tp1_pct":             10.0,  "tp1_sell_pct":  80.0,
        "tp2_pct":             22.0,  "tp2_sell_pct":  15.0,
        "tp3_pct":             40.0,  "tp3_sell_pct":  4.0,
        "moon_bag_pct":        1.0,
        "sl_pct":              -7.0,
        "trailing_stop_pct":   4.0,
        "trailing_after_tp":   1,
        "break_even_after_tp": 1,
        "max_hold_minutes":    4,
    },
]

# ── System preset seeding ──────────────────────────────────────────────────────

async def seed_system_presets() -> None:
    """Insert system presets if they don't already exist. Called on startup.
    Also applies any value migrations to existing system preset rows."""
    async with get_db() as db:
        for p in SYSTEM_PRESETS:
            async with db.execute(
                "SELECT id FROM exit_presets WHERE is_system = 1 AND name = ?", (p["name"],)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                await db.execute("""
                    INSERT INTO exit_presets
                        (user_id, name, description, is_system,
                         tp1_pct, tp1_sell_pct, tp2_pct, tp2_sell_pct,
                         tp3_pct, tp3_sell_pct, moon_bag_pct, sl_pct,
                         trailing_stop_pct, trailing_after_tp,
                         break_even_after_tp, max_hold_minutes)
                    VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    p["name"], p["description"], p["is_system"],
                    p.get("tp1_pct"), p.get("tp1_sell_pct"),
                    p.get("tp2_pct"), p.get("tp2_sell_pct"),
                    p.get("tp3_pct"), p.get("tp3_sell_pct"),
                    p.get("moon_bag_pct", 0),
                    p.get("sl_pct"),
                    p.get("trailing_stop_pct"),
                    p.get("trailing_after_tp", 1),
                    p.get("break_even_after_tp", 1),
                    p.get("max_hold_minutes"),
                ))
            else:
                # Sync existing system preset values to match the current definition
                await db.execute("""
                    UPDATE exit_presets SET
                        description        = ?,
                        tp1_pct            = ?, tp1_sell_pct = ?,
                        tp2_pct            = ?, tp2_sell_pct = ?,
                        tp3_pct            = ?, tp3_sell_pct = ?,
                        moon_bag_pct       = ?, sl_pct        = ?,
                        trailing_stop_pct  = ?, trailing_after_tp   = ?,
                        break_even_after_tp= ?, max_hold_minutes     = ?
                    WHERE is_system = 1 AND name = ?
                """, (
                    p["description"],
                    p.get("tp1_pct"), p.get("tp1_sell_pct"),
                    p.get("tp2_pct"), p.get("tp2_sell_pct"),
                    p.get("tp3_pct"), p.get("tp3_sell_pct"),
                    p.get("moon_bag_pct", 0), p.get("sl_pct"),
                    p.get("trailing_stop_pct"), p.get("trailing_after_tp", 1),
                    p.get("break_even_after_tp", 1), p.get("max_hold_minutes"),
                    p["name"],
                ))
        await db.commit()
    logger.info("System exit presets seeded.")


# ── Auto-exit settings ─────────────────────────────────────────────────────────

async def get_auto_exit_settings(user_id: int) -> dict:
    async with get_db() as db:
        # Explicitly set updated_at=NULL on first insert so the worker can detect
        # "never configured by user" vs "user explicitly disabled".
        await db.execute(
            "INSERT OR IGNORE INTO auto_exit_settings (user_id, updated_at) VALUES (?, NULL)",
            (user_id,),
        )
        await db.commit()
        async with db.execute(
            "SELECT * FROM auto_exit_settings WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else {"user_id": user_id, "enabled": 0, "live_mode": 1,
                                   "selected_preset_id": None, "notifications_enabled": 1,
                                   "custom_slippage": 15.0, "custom_priority_fee": 0.005}


async def update_auto_exit_field(user_id: int, field: str, value) -> None:
    allowed = {"enabled", "live_mode", "selected_preset_id",
               "custom_slippage", "custom_priority_fee", "notifications_enabled"}
    if field not in allowed:
        return
    async with get_db() as db:
        await db.execute(f"""
            INSERT INTO auto_exit_settings (user_id, {field})
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                {field} = ?,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, value, value))
        await db.commit()


async def toggle_auto_exit(user_id: int) -> bool:
    """Toggle auto-exit on/off. Returns new state."""
    s = await get_auto_exit_settings(user_id)
    new = 0 if s.get("enabled") else 1
    await update_auto_exit_field(user_id, "enabled", new)
    return bool(new)


async def toggle_live_mode(user_id: int) -> bool:
    """Toggle live/paper mode. Returns True = live."""
    s = await get_auto_exit_settings(user_id)
    new = 0 if s.get("live_mode") else 1
    await update_auto_exit_field(user_id, "live_mode", new)
    return bool(new)


# ── Preset CRUD ────────────────────────────────────────────────────────────────

async def get_system_presets() -> list[dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM exit_presets WHERE is_system = 1 ORDER BY id"
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_user_presets(user_id: int) -> list[dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM exit_presets WHERE user_id = ? AND is_system = 0 ORDER BY id",
            (user_id,)
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_preset(preset_id: int) -> Optional[dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM exit_presets WHERE id = ?", (preset_id,)
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def clone_preset(preset_id: int, user_id: int, new_name: str) -> int:
    """Clone a system or user preset into the user's own collection."""
    src = await get_preset(preset_id)
    if not src:
        raise ValueError("Preset not found")
    async with get_db() as db:
        cur = await db.execute("""
            INSERT INTO exit_presets
                (user_id, name, description, is_system,
                 tp1_pct, tp1_sell_pct, tp2_pct, tp2_sell_pct,
                 tp3_pct, tp3_sell_pct, moon_bag_pct, sl_pct,
                 trailing_stop_pct, trailing_after_tp,
                 break_even_after_tp, max_hold_minutes)
            VALUES (?,?,?,0,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            user_id, new_name, src.get("description"),
            src.get("tp1_pct"), src.get("tp1_sell_pct"),
            src.get("tp2_pct"), src.get("tp2_sell_pct"),
            src.get("tp3_pct"), src.get("tp3_sell_pct"),
            src.get("moon_bag_pct", 0), src.get("sl_pct"),
            src.get("trailing_stop_pct"),
            src.get("trailing_after_tp", 1),
            src.get("break_even_after_tp", 1),
            src.get("max_hold_minutes"),
        ))
        await db.commit()
        return cur.lastrowid


async def delete_user_preset(preset_id: int, user_id: int) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM exit_presets WHERE id = ? AND user_id = ? AND is_system = 0",
            (preset_id, user_id)
        )
        await db.commit()
    return cur.rowcount > 0


# ── Position state management ──────────────────────────────────────────────────

async def register_position(
    position_id: int,
    user_id: int,
    token_address: str,
    entry_price_sol: float,
    preset_id: Optional[int] = None,
    opened_at: Optional[str] = None,
) -> None:
    """
    Register a newly opened position for watcher tracking.
    Called after a successful buy is confirmed on-chain.
    opened_at should be the actual buy confirmation time so max_hold_minutes is accurate.
    """
    from datetime import datetime, timezone
    if not opened_at:
        opened_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    async with get_db() as db:
        await db.execute("""
            INSERT OR IGNORE INTO position_state
                (position_id, user_id, token_address, entry_price_sol,
                 current_price_sol, highest_price_sol, preset_id, opened_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (position_id, user_id, token_address,
              entry_price_sol, entry_price_sol, entry_price_sol, preset_id, opened_at))
        await db.commit()
    logger.info(f"Position {position_id} registered for auto-exit watching (opened_at={opened_at}).")


async def get_active_position_states() -> list[dict]:
    """Returns all positions the watcher should monitor."""
    async with get_db() as db:
        async with db.execute("""
            SELECT ps.*, tp.amount_sol
            FROM position_state ps
            LEFT JOIN tracked_positions tp ON tp.id = ps.position_id
            WHERE ps.status IN ('watching', 'partial')
        """) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def update_position_price(
    position_id: int,
    current_price: float,
) -> None:
    """Update price fields and last_checked_at."""
    async with get_db() as db:
        await db.execute("""
            UPDATE position_state SET
                current_price_sol = ?,
                highest_price_sol = MAX(highest_price_sol, ?),
                last_checked_at   = CURRENT_TIMESTAMP,
                updated_at        = CURRENT_TIMESTAMP
            WHERE position_id = ?
        """, (current_price, current_price, position_id))
        await db.commit()


async def mark_position_closed(position_id: int) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE position_state SET status='closed', updated_at=CURRENT_TIMESTAMP "
            "WHERE position_id=?", (position_id,)
        )
        await db.commit()


async def mark_position_partial(position_id: int, qty_remaining_pct: float) -> None:
    async with get_db() as db:
        await db.execute("""
            UPDATE position_state SET
                status = 'partial',
                qty_remaining_pct = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE position_id = ?
        """, (qty_remaining_pct, position_id))
        await db.commit()


async def _set_tp_fired(position_id: int, tp_num: int) -> None:
    col = f"tp{tp_num}_fired"
    async with get_db() as db:
        await db.execute(
            f"UPDATE position_state SET {col}=1, updated_at=CURRENT_TIMESTAMP WHERE position_id=?",
            (position_id,)
        )
        await db.commit()


async def _activate_trailing(position_id: int, current_price: float) -> None:
    async with get_db() as db:
        await db.execute("""
            UPDATE position_state SET
                trailing_active   = 1,
                trailing_high_sol = ?,
                updated_at        = CURRENT_TIMESTAMP
            WHERE position_id = ?
        """, (current_price, position_id))
        await db.commit()


async def _update_trailing_high(position_id: int, price: float) -> None:
    async with get_db() as db:
        await db.execute("""
            UPDATE position_state SET
                trailing_high_sol = MAX(trailing_high_sol, ?),
                updated_at = CURRENT_TIMESTAMP
            WHERE position_id = ?
        """, (price, position_id))
        await db.commit()


async def _set_break_even(position_id: int) -> None:
    async with get_db() as db:
        await db.execute("""
            UPDATE position_state SET
                break_even_active = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE position_id = ?
        """, (position_id,))
        await db.commit()


async def _set_sl_fired(position_id: int) -> None:
    async with get_db() as db:
        await db.execute("""
            UPDATE position_state SET
                sl_fired = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE position_id = ?
        """, (position_id,))
        await db.commit()


# ── Event logging ──────────────────────────────────────────────────────────────

async def log_position_event(
    position_id: int,
    user_id: int,
    event_type: str,
    price_sol: float = 0.0,
    sell_pct: float = 0.0,
    pnl_sol: float = 0.0,
    note: str = "",
) -> None:
    async with get_db() as db:
        await db.execute("""
            INSERT INTO position_events
                (position_id, user_id, event_type, price_sol, sell_pct, pnl_sol, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (position_id, user_id, event_type, price_sol, sell_pct, pnl_sol, note))
        await db.commit()


async def get_position_events(position_id: int) -> list[dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM position_events WHERE position_id=? ORDER BY created_at DESC",
            (position_id,)
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ── Sell execution tracking ────────────────────────────────────────────────────

async def record_sell_attempt(
    position_id: int,
    user_id: int,
    token_address: str,
    sell_pct: float,
    trigger_type: str,
) -> int:
    """Creates a sell_executions row BEFORE submitting the TX. Returns its id."""
    async with get_db() as db:
        cur = await db.execute("""
            INSERT INTO sell_executions
                (position_id, user_id, token_address, sell_pct, trigger_type, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (position_id, user_id, token_address, sell_pct, trigger_type))
        await db.commit()
        return cur.lastrowid


async def update_sell_execution(exec_id: int, tx_sig: str, status: str) -> None:
    async with get_db() as db:
        await db.execute("""
            UPDATE sell_executions SET
                tx_signature = ?,
                status = ?,
                confirmed_at = CASE WHEN ? = 'confirmed' THEN CURRENT_TIMESTAMP ELSE NULL END
            WHERE id = ?
        """, (tx_sig, status, status, exec_id))
        await db.commit()


async def has_pending_sell(position_id: int, trigger_type: str) -> bool:
    """Idempotency guard — returns True if a sell for this trigger should be skipped.
    'confirmed'      = always blocks (TP already took profit — don't re-sell)
    'sent'/'pending' = block if recent (< 3 min) to avoid double-submit
    'failed'         = block for 2 min cooldown to prevent retry spam every 8s
    """
    async with get_db() as db:
        async with db.execute("""
            SELECT id FROM sell_executions
            WHERE position_id = ? AND trigger_type = ?
              AND (
                status = 'confirmed'
                OR (status IN ('pending', 'sent')
                    AND created_at >= datetime('now', '-3 minutes'))
                OR (status = 'failed'
                    AND created_at >= datetime('now', '-2 minutes'))
              )
        """, (position_id, trigger_type)) as cur:
            row = await cur.fetchone()
    return row is not None


async def _is_first_failure(position_id: int, trigger_type: str) -> bool:
    """Returns True if this is the first failed attempt for this trigger (notify once only)."""
    async with get_db() as db:
        async with db.execute("""
            SELECT COUNT(*) FROM sell_executions
            WHERE position_id = ? AND trigger_type = ? AND status = 'failed'
        """, (position_id, trigger_type)) as cur:
            row = await cur.fetchone()
    return (row[0] if row else 0) <= 1


async def clear_stale_pending_sells(max_age_minutes: int = 5) -> int:
    """
    Called on worker startup. Marks 'pending' AND 'sent' sell records older than
    max_age_minutes as 'failed' so they don't permanently block re-fires.
    'sent' records that survive a bot restart never get confirmed by _confirm_sell_tx
    (the background task was killed) and would block sells indefinitely.
    """
    async with get_db() as db:
        cur = await db.execute("""
            UPDATE sell_executions
            SET status = 'failed'
            WHERE status IN ('pending', 'sent')
              AND created_at <= datetime('now', ? || ' minutes')
        """, (f"-{max_age_minutes}",))
        await db.commit()
        cleaned = cur.rowcount
    if cleaned:
        logger.warning(f"Cleared {cleaned} stale pending/sent sell record(s) on startup.")
    return cleaned


async def _maybe_reenter(
    pos_id: int,
    user_id: int,
    token: str,
    bot,
    notify: bool,
) -> None:
    """
    After a confirmed profitable full-close, re-enter the same token if:
      - Re-entry count for (user_id, token) < MAX_REENTRIES
      - Current price is still above the original entry price (token still moving up)
      - User has auto-buy enabled (live_mode respected via execute_buy)

    Uses the user's auto-buy settings for amount/slippage/priority fee.
    """
    key = (user_id, token)
    count = _reentry_counts.get(key, 0)
    if count >= MAX_REENTRIES:
        logger.info(f"[{pos_id}] Re-entry skipped: max {MAX_REENTRIES} reentries reached for {token[:8]}")
        return

    # Get original entry price from closed position
    try:
        async with get_db() as db:
            async with db.execute(
                "SELECT entry_price_sol FROM position_state WHERE position_id = ?", (pos_id,)
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return
        entry_price = float(row["entry_price_sol"] or 0)
    except Exception as e:
        logger.warning(f"[{pos_id}] Re-entry: could not fetch entry price: {e}")
        return

    # Fetch current price
    try:
        from services.token_data_provider import get_token_price_in_sol
        current_price = await get_token_price_in_sol(token)
    except Exception as e:
        logger.warning(f"[{pos_id}] Re-entry: price fetch failed for {token[:8]}: {e}")
        return

    if not current_price or current_price <= 0:
        logger.debug(f"[{pos_id}] Re-entry skipped: no current price for {token[:8]}")
        return

    # Only re-enter if token is still above entry (still in profit territory)
    if entry_price > 0 and current_price <= entry_price:
        logger.info(
            f"[{pos_id}] Re-entry skipped: price {current_price:.10f} <= entry {entry_price:.10f} "
            f"({token[:8]}) — momentum gone"
        )
        return

    # Load auto-buy settings for this user
    try:
        from services.auto_buy_service import get_auto_buy_settings
        ab = await get_auto_buy_settings(user_id)
    except Exception as e:
        logger.warning(f"[{pos_id}] Re-entry: could not load auto-buy settings: {e}")
        return

    amount_sol   = float(ab.get("max_buy_size_sol") or 0.05)
    slippage     = float(ab.get("slippage") or 15.0)
    priority_fee = float(ab.get("priority_fee") or 0.006)
    preset_id    = ab.get("liq_exit_preset_id")

    logger.info(
        f"[{pos_id}] Re-entry #{count + 1}/{MAX_REENTRIES} for {token[:8]} — "
        f"{amount_sol} SOL @ current {current_price:.10f} (entry was {entry_price:.10f})"
    )

    # Execute the buy
    try:
        from services.solana_execution_service import execute_buy
        result = await execute_buy(
            user_id          = user_id,
            token_address    = token,
            amount_sol       = amount_sol,
            slippage_pct     = slippage,
            priority_fee_sol = priority_fee,
            exit_preset_id   = preset_id,
        )
    except Exception as e:
        logger.error(f"[{pos_id}] Re-entry execute_buy raised: {e}", exc_info=True)
        return

    if result["success"]:
        _reentry_counts[key] = count + 1
        sig = result["signature"]
        logger.info(f"[{pos_id}] Re-entry TX broadcast: {sig[:12]} (#{count + 1})")
        if notify:
            try:
                reentry_num = count + 1
                await bot.send_message(
                    user_id,
                    f"🔄 <b>Auto Re-Entry #{reentry_num}</b>\n\n"
                    f"<b>Token:</b> <code>{token}</code>\n"
                    f"<b>Amount:</b> {amount_sol} SOL\n"
                    f"<b>Price:</b> <code>{current_price:.10f} SOL</code>\n"
                    f"<b>TX:</b> <code>{sig}</code>\n\n"
                    f"<i>Re-entered after profitable exit — {MAX_REENTRIES - reentry_num} re-entry slot(s) remaining.</i>",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            except Exception as e:
                logger.warning(f"Re-entry notify failed user={user_id}: {e}")
    else:
        logger.warning(f"[{pos_id}] Re-entry buy failed: {result.get('error')}")
        if notify:
            try:
                await bot.send_message(
                    user_id,
                    f"⚠️ <b>Auto Re-Entry Failed</b>\n\n"
                    f"<b>Token:</b> <code>{token}</code>\n"
                    f"<b>Reason:</b> {result.get('error', 'Unknown')}\n\n"
                    f"<i>Re-entry attempt did not execute.</i>",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            except Exception:
                pass


async def _confirm_sell_tx(
    exec_id: int,
    sig: str,
    pos_id: int,
    user_id: int,
    token: str,
    trigger_type: str,
    new_qty: float,
    moon_bag: float,
    bot,
    notify: bool,
    pre_sell_qty: float = 100.0,
) -> None:
    """
    Background task: polls for on-chain confirmation of a sell TX.
    - Confirmed  → update sell_execution to 'confirmed'
    - Failed/timeout → update to 'failed', reopen position so the trigger
      can re-fire on the next worker cycle.
    """
    from services.solana_execution_service import confirm_transaction
    result = await confirm_transaction(sig)
    status = result["status"]

    if status == "confirmed":
        await update_sell_execution(exec_id, sig, "confirmed")
        logger.info(f"[{pos_id}] {trigger_type} sell confirmed on-chain: {sig[:12]}")
        # ── Re-entry logic ────────────────────────────────────────────────────
        # Only attempt re-entry on a full close (new_qty sold down to/below moon_bag)
        # that was triggered by a profit exit (TP or max_hold — not a stop-loss).
        is_full_close   = new_qty <= moon_bag
        is_profit_exit  = trigger_type not in ("sl",)
        if is_full_close and is_profit_exit:
            await _maybe_reenter(pos_id, user_id, token, bot, notify)
        return

    # TX failed or timed out — revert position state so the trigger can fire again
    reason = "on-chain error" if status == "failed" else "timeout (network congestion)"
    logger.warning(f"[{pos_id}] {trigger_type} sell {status}: {sig[:12]} — reverting position state")
    await update_sell_execution(exec_id, sig, "failed")

    # Restore position so the watcher can re-evaluate next cycle.
    # Use pre_sell_qty (qty before this sell fired) so partial-position accounting
    # stays correct (Bug 3 fix). Also reset sl_fired if this was an SL TX so the
    # stop-loss can re-fire on the next cycle (Bug 4 fix).
    async with get_db() as db:
        await db.execute("""
            UPDATE position_state
            SET status             = 'watching',
                qty_remaining_pct  = ?,
                sl_fired           = CASE WHEN ? = 'sl' THEN 0 ELSE sl_fired END,
                updated_at         = CURRENT_TIMESTAMP
            WHERE position_id = ? AND status IN ('closed', 'partial')
        """, (pre_sell_qty, trigger_type, pos_id))
        await db.commit()

    if notify:
        try:
            await bot.send_message(
                user_id,
                f"⚠️ <b>Auto-Exit sell did NOT confirm</b>\n\n"
                f"<b>Token:</b> <code>{token}</code>\n"
                f"<b>Trigger:</b> {trigger_type}\n"
                f"<b>TX:</b> <code>{sig}</code>\n"
                f"<b>Reason:</b> {reason}\n\n"
                f"<i>Position re-opened — will retry on next price check.</i>",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.warning(f"_confirm_sell_tx notify failed user={user_id}: {e}")


# ── Core trigger evaluator ─────────────────────────────────────────────────────

async def evaluate_and_fire(
    ps: dict,          # position_state row
    preset: dict,      # exit_presets row
    settings_row: dict,# auto_exit_settings row
    bot,               # aiogram Bot instance for notifications
) -> None:
    """
    Evaluates all exit rules for one position in deterministic order and fires
    the first applicable trigger. Idempotent — safe to call repeatedly.

    Evaluation order:
      1. Hard stop-loss
      2. Max hold / time exit
      3. Take-profit ladder (TP1 → TP2 → TP3)
      4. Break-even activation (side-effect of TP fire, not a sell)
      5. Trailing stop
    """
    from services.solana_execution_service import execute_sell

    pos_id       = ps["position_id"]
    user_id      = ps["user_id"]
    token        = ps["token_address"]
    entry        = float(ps["entry_price_sol"] or 0)
    current      = float(ps["current_price_sol"] or 0)
    highest      = float(ps["highest_price_sol"] or 0)
    qty_rem      = float(ps["qty_remaining_pct"] or 100.0)
    opened_at    = ps.get("opened_at") or ""

    # Minimum value filter: estimate current SOL value of the position.
    # If < 0.003 SOL it's not worth the transaction fee — close silently.
    MIN_VALUE_SOL = 0.003
    amount_sol = float(ps.get("amount_sol") or 0)
    if amount_sol > 0:
        if entry > 0 and current > 0:
            est_value = amount_sol * (current / entry) * (qty_rem / 100)
        else:
            est_value = amount_sol * (qty_rem / 100)
        if 0 < est_value < MIN_VALUE_SOL:
            await mark_position_closed(pos_id)
            async with get_db() as _db:
                await _db.execute(
                    "UPDATE tracked_positions SET status='closed', closed_at=CURRENT_TIMESTAMP WHERE id=?",
                    (pos_id,)
                )
                await _db.commit()
            logger.info(f"[{pos_id}] Value ~{est_value:.5f} SOL < {MIN_VALUE_SOL} SOL minimum — closed silently")
            return
    live_mode    = bool(settings_row.get("live_mode", 1))
    slippage     = float(settings_row.get("custom_slippage") or 15.0)
    # Priority fee: use auto-exit setting if explicitly configured (> default floor),
    # otherwise fall back to the user's sniper priority fee setting.
    ae_priority  = float(settings_row.get("custom_priority_fee") or 0)
    if ae_priority < 0.003:
        # AE setting is at factory default — fall back to the user's auto-buy priority fee
        # (this is where users typically configure their .006 preference)
        try:
            from services.auto_buy_service import get_auto_buy_settings as _get_ab
            ab_s = await _get_ab(user_id)
            ae_priority = float(ab_s.get("priority_fee") or 0.003)
        except Exception:
            ae_priority = 0.003   # safe minimum that lands on Solana reliably
    priority_fee = max(ae_priority, 0.003)  # never go below 0.003 SOL for sells
    notify       = bool(settings_row.get("notifications_enabled", 1))
    moon_bag     = float(preset.get("moon_bag_pct") or 0)
    MAX_HOLD_SELL_ATTEMPTS = 5   # give up after this many failed sell TXs (stops fee bleed)

    if current <= 0:
        # No price data. If max_hold is configured AND the position has been open
        # longer than max_hold + 5 minutes, attempt a blind 100% sell.
        # This handles tokens where the price API has no data (dead / illiquid tokens)
        # but the position was bought with real SOL and needs to be exited.
        _max_hold = preset.get("max_hold_minutes")
        if _max_hold and opened_at:
            try:
                _opened_dt = datetime.fromisoformat(str(opened_at).strip().replace(" ", "T"))
                if _opened_dt.tzinfo is None:
                    _opened_dt = _opened_dt.replace(tzinfo=timezone.utc)
                _age_min = (datetime.now(timezone.utc) - _opened_dt).total_seconds() / 60
                if _age_min >= float(_max_hold) + 5:
                    # Blind sell — past max hold, no price.
                    # Same failure cap as the priced path: give up after 5 failed
                    # attempts to stop priority-fee bleed on dead tokens.
                    async with get_db() as _bchk:
                        async with _bchk.execute(
                            "SELECT COUNT(*) FROM sell_executions "
                            "WHERE position_id=? AND trigger_type='max_hold' AND status='failed'",
                            (pos_id,)
                        ) as _bcur:
                            _brow = await _bcur.fetchone()
                            _bfail_count = _brow[0] if _brow else 0
                    if _bfail_count >= MAX_HOLD_SELL_ATTEMPTS:
                        await mark_position_closed(pos_id)
                        async with get_db() as _db:
                            await _db.execute(
                                "UPDATE tracked_positions SET status='closed',"
                                "closed_at=CURRENT_TIMESTAMP WHERE id=?", (pos_id,)
                            )
                            await _db.commit()
                        logger.warning(
                            f"[{pos_id}] blind max_hold: {_bfail_count} failed attempts "
                            "— closing silently to stop fee bleed"
                        )
                        return
                    logger.info(
                        f"[{pos_id}] No price data after {_age_min:.0f}m "
                        f"(max_hold={_max_hold}m) — attempting blind sell"
                    )
                    if not await has_pending_sell(pos_id, "max_hold"):
                        _exec_id = await record_sell_attempt(
                            pos_id, user_id, token, qty_rem, "max_hold"
                        )
                        try:
                            _result = await execute_sell(
                                user_id=user_id,
                                token_address=token,
                                sell_pct=100.0,
                                slippage_pct=slippage,
                                priority_fee_sol=priority_fee,
                            )
                            if _result["success"]:
                                _sig = _result["signature"]
                                await update_sell_execution(_exec_id, _sig, "sent")
                                await mark_position_closed(pos_id)
                                async with get_db() as _db:
                                    await _db.execute(
                                        "UPDATE tracked_positions SET status='closed',"
                                        "closed_at=CURRENT_TIMESTAMP WHERE id=?", (pos_id,)
                                    )
                                    await _db.commit()
                                if notify:
                                    try:
                                        await bot.send_message(
                                            user_id,
                                            f"⬛ <b>AUTO-EXIT  //  TIME  EXIT</b>\n"
                                            f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                            f"HELD   {_age_min:.0f} min  [no price data]\n"
                                            f"SOLD   100%\n"
                                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
                                            f"📋 CA <i>(tap to copy)</i>\n"
                                            f"<code>{token}</code>\n\n"
                                            f"🔗 TX <i>(tap to copy)</i>\n"
                                            f"<code>{_sig}</code>\n"
                                            f'<a href="https://solscan.io/tx/{_sig}">↗ Solscan</a>  '
                                            f'<a href="https://pump.fun/{token}">↗ Pump.fun</a>',
                                            parse_mode="HTML",
                                        )
                                    except Exception:
                                        pass
                                logger.info(f"[{pos_id}] Blind sell sent: {_sig[:12]}")
                            elif _result.get("error") in ("dust", "No token balance found in bot wallet."):
                                # No real balance — close silently
                                await update_sell_execution(_exec_id, "DUST", "closed")
                                await mark_position_closed(pos_id)
                                async with get_db() as _db:
                                    await _db.execute(
                                        "UPDATE tracked_positions SET status='closed',"
                                        "closed_at=CURRENT_TIMESTAMP WHERE id=?", (pos_id,)
                                    )
                                    await _db.commit()
                                logger.info(f"[{pos_id}] Blind sell: no balance — closed silently")
                            else:
                                await update_sell_execution(_exec_id, "", "failed")
                                _err = _result.get("error", "")
                                logger.warning(f"[{pos_id}] Blind sell failed: {_err}")
                                # Only notify on first failure
                                if notify and await _is_first_failure(pos_id, "max_hold"):
                                    await _notify_error(bot, user_id, token, "max_hold", _err)
                        except Exception as _exc:
                            await update_sell_execution(_exec_id, "", "failed")
                            logger.error(f"[{pos_id}] Blind sell exception: {_exc}")
            except Exception as _te:
                logger.debug(f"[{pos_id}] blind sell time parse: {_te}")
        return  # no price data — skip normal trigger evaluation

    if entry <= 0 and current > 0:
        # Entry price was 0 at buy time (token wasn't indexed yet).
        # Backfill it now using the first live price we have.
        # This means P&L starts from this price, not the true buy price —
        # but it's far better than the position being permanently un-evaluatable.
        async with get_db() as db:
            await db.execute(
                "UPDATE position_state SET entry_price_sol = ?, highest_price_sol = ? "
                "WHERE position_id = ? AND entry_price_sol <= 0",
                (current, current, pos_id),
            )
            await db.commit()
        logger.info(f"[{pos_id}] Entry price backfilled to {current:.10f} SOL (was 0)")
        return  # re-evaluate on the next cycle with the correct entry price

    change_pct = (current - entry) / entry * 100

    async def _fire_sell(sell_pct_of_original: float, trigger_type: str, label: str) -> bool:
        """
        Execute a sell for sell_pct_of_original% of the original position.
        Returns True if the sell was successfully broadcast (not necessarily confirmed).
        """
        if await has_pending_sell(pos_id, trigger_type):
            logger.debug(f"[{pos_id}] {trigger_type} already in flight — skipping")
            return False

        # Convert sell_pct_of_original to actual % of current balance
        if qty_rem <= 0:
            return False
        actual_pct = min(sell_pct_of_original / qty_rem * 100, 100.0)

        exec_id = await record_sell_attempt(pos_id, user_id, token, sell_pct_of_original, trigger_type)

        pnl_sol  = (current - entry) * (sell_pct_of_original / 100)  # rough estimate
        note_str = f"{label} @ {current:.8f} SOL ({change_pct:+.1f}%)"
        logger.info(f"[{pos_id}] Firing {trigger_type}: {note_str} live={live_mode}")

        if not live_mode:
            # Paper mode — log and notify only, no on-chain tx
            await update_sell_execution(exec_id, "PAPER_MODE", "paper")
            await log_position_event(pos_id, user_id, trigger_type, current, sell_pct_of_original, pnl_sol, note_str + " [PAPER]")
            new_qty = max(0.0, qty_rem - sell_pct_of_original)
            if new_qty <= moon_bag:
                await mark_position_closed(pos_id)
            else:
                await mark_position_partial(pos_id, new_qty)
            if notify:
                await _notify(bot, user_id, token, trigger_type, label, current, entry,
                              sell_pct_of_original, pnl_sol, new_qty, paper=True)
            return True

        # Live mode — execute on-chain
        try:
            result = await execute_sell(
                user_id          = user_id,
                token_address    = token,
                sell_pct         = actual_pct,
                slippage_pct     = slippage,
                priority_fee_sol = priority_fee,
            )
        except Exception as exc:
            # Any uncaught exception (network, RPC down, etc.) → mark failed so
            # has_pending_sell doesn't permanently block this trigger.
            logger.error(f"[{pos_id}] execute_sell raised for {trigger_type}: {exc}", exc_info=True)
            await update_sell_execution(exec_id, "", "failed")
            if notify:
                await _notify_error(bot, user_id, token, trigger_type, f"Execution exception: {exc}")
            return False

        if result["success"]:
            sig = result["signature"]
            # Mark as "sent" not "confirmed" — the RPC accepted the TX but it
            # is not yet finalized on-chain.  The background task below updates
            # the record to "confirmed" or reverts to "failed" after polling.
            await update_sell_execution(exec_id, sig, "sent")
            await log_position_event(pos_id, user_id, trigger_type, current, sell_pct_of_original, pnl_sol, note_str)
            new_qty = max(0.0, qty_rem - sell_pct_of_original)
            if new_qty <= moon_bag:
                await mark_position_closed(pos_id)
                from database.sqlite_db import get_db as _db
                async with _db() as db:
                    await db.execute(
                        "UPDATE tracked_positions SET status='closed', closed_at=CURRENT_TIMESTAMP WHERE id=?",
                        (pos_id,)
                    )
                    await db.commit()
            else:
                await mark_position_partial(pos_id, new_qty)
            if notify:
                await _notify(bot, user_id, token, trigger_type, label, current, entry,
                              sell_pct_of_original, pnl_sol, new_qty, sig=sig)
            # Background: poll confirmation and handle on-chain failure
            asyncio.create_task(_confirm_sell_tx(
                exec_id, sig, pos_id, user_id, token, trigger_type, new_qty, moon_bag, bot, notify,
                pre_sell_qty=qty_rem,
            ))
            return True
        else:
            err = result.get("error", "")
            if err in ("dust", "No token balance found in bot wallet."):
                # No real balance — close silently, no user notification
                await update_sell_execution(exec_id, "DUST", "closed")
                await mark_position_closed(pos_id)
                async with get_db() as _db:
                    await _db.execute(
                        "UPDATE tracked_positions SET status='closed', closed_at=CURRENT_TIMESTAMP WHERE id=?",
                        (pos_id,)
                    )
                    await _db.commit()
                logger.info(f"[{pos_id}] No balance — position closed silently")
                return True
            await update_sell_execution(exec_id, "", "failed")
            logger.warning(f"[{pos_id}] {trigger_type} sell failed: {err}")
            # Only notify user on the FIRST failure — not every 8-second retry
            if notify and await _is_first_failure(pos_id, trigger_type):
                await _notify_error(bot, user_id, token, trigger_type, err)
            return False

    # ── 1. Hard stop-loss ──────────────────────────────────────────────────────
    sl_pct = preset.get("sl_pct")
    if sl_pct is not None and not ps.get("sl_fired"):
        # Break-even: if active, effective SL is the entry price (0% down)
        effective_sl_pct = 0.0 if ps.get("break_even_active") else float(sl_pct)
        if change_pct <= effective_sl_pct:
            sl_label = "Break-even exit" if ps.get("break_even_active") else f"Stop-loss ({sl_pct:.0f}%)"
            # Mark sl_fired AFTER _fire_sell confirms the TX was broadcast (not before).
            # Setting it before means a failed quote/sign/RPC call permanently disables
            # SL with no sell ever executed — Bug 1 fix.
            fired = await _fire_sell(qty_rem, "sl", sl_label)
            if fired:
                await _set_sl_fired(pos_id)
            return

    # ── 2. Max hold / time exit ────────────────────────────────────────────────
    max_hold = preset.get("max_hold_minutes")
    if max_hold and opened_at:
        try:
            # SQLite stores CURRENT_TIMESTAMP as "2025-03-15 10:30:00" (space-separated).
            # datetime.fromisoformat() only handles the "T"-separated ISO format before Python 3.11.
            # Replace space with "T" so it works on all Python versions.
            opened_dt = datetime.fromisoformat(str(opened_at).strip().replace(" ", "T"))
            if opened_dt.tzinfo is None:
                opened_dt = opened_dt.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - opened_dt).total_seconds() / 60
            if age_min >= max_hold:
                sell_amt = max(0.0, qty_rem - moon_bag)
                if sell_amt > 0:
                    # Bug 2 fix: cap retries to stop bleeding SOL on priority fees for
                    # illiquid/dead tokens whose sells keep failing on-chain.
                    # After MAX_HOLD_SELL_ATTEMPTS failures, close the DB record silently.
                    async with get_db() as _chk:
                        async with _chk.execute(
                            "SELECT COUNT(*) FROM sell_executions "
                            "WHERE position_id=? AND trigger_type='max_hold' AND status='failed'",
                            (pos_id,)
                        ) as _cur:
                            _row = await _cur.fetchone()
                            _fail_count = _row[0] if _row else 0
                    if _fail_count >= MAX_HOLD_SELL_ATTEMPTS:
                        await mark_position_closed(pos_id)
                        async with get_db() as _db:
                            await _db.execute(
                                "UPDATE tracked_positions SET status='closed',"
                                "closed_at=CURRENT_TIMESTAMP WHERE id=?",
                                (pos_id,)
                            )
                            await _db.commit()
                        logger.warning(
                            f"[{pos_id}] max_hold: {_fail_count} failed sell attempts — "
                            "closing silently to stop fee bleed (token likely illiquid)"
                        )
                        if notify:
                            try:
                                await bot.send_message(
                                    user_id,
                                    f"⬛ <b>AUTO-EXIT  //  ABANDONED</b>\n"
                                    f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                    f"HELD   {age_min:.0f} min\n"
                                    f"FAILS  {_fail_count} sell attempts\n"
                                    f"STATUS Closed — token illiquid/dead\n"
                                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
                                    f"📋 CA <i>(tap to copy)</i>\n"
                                    f"<code>{token}</code>\n\n"
                                    f"<i>No further sell attempts — token had no liquidity.</i>",
                                    parse_mode="HTML",
                                )
                            except Exception:
                                pass
                        return
                    await _fire_sell(sell_amt, "max_hold", f"Max hold {max_hold}m reached")
                else:
                    await mark_position_closed(pos_id)
                return
        except Exception as e:
            logger.warning(f"[{pos_id}] max_hold time parse error: {e} opened_at={opened_at!r}")

    # ── 3. Take-profit ladder ──────────────────────────────────────────────────
    for tp_num in (1, 2, 3):
        if ps.get(f"tp{tp_num}_fired"):
            continue
        tp_pct  = preset.get(f"tp{tp_num}_pct")
        tp_sell = preset.get(f"tp{tp_num}_sell_pct")
        if tp_pct is None or tp_sell is None:
            continue
        if change_pct >= float(tp_pct):
            await _set_tp_fired(pos_id, tp_num)
            fired = await _fire_sell(tp_sell, f"tp{tp_num}", f"TP{tp_num} +{tp_pct:.0f}%")
            if fired:
                # ── 4. Break-even activation ─────────────────────────────────
                bep = preset.get("break_even_after_tp", 1)
                if tp_num >= (bep or 1) and not ps.get("break_even_active"):
                    await _set_break_even(pos_id)
                # ── Trailing stop activation ──────────────────────────────────
                tat = preset.get("trailing_after_tp", 1)
                if tp_num >= (tat or 1) and not ps.get("trailing_active"):
                    await _activate_trailing(pos_id, current)
            return  # one trigger per cycle

    # ── 5. Trailing stop ───────────────────────────────────────────────────────
    if ps.get("trailing_active"):
        trailing_pct  = preset.get("trailing_stop_pct")
        trailing_high = float(ps.get("trailing_high_sol") or current)
        await _update_trailing_high(pos_id, current)

        if trailing_pct and trailing_high > 0:
            stop_price = trailing_high * (1 - float(trailing_pct) / 100)
            if current <= stop_price:
                sell_amt = max(0.0, qty_rem - moon_bag)
                if sell_amt > 0:
                    await _fire_sell(sell_amt, "trailing", f"Trailing stop ({trailing_pct:.0f}%)")
                else:
                    await mark_position_closed(pos_id)
                return


# ── Telegram notifications ─────────────────────────────────────────────────────

_TRIGGER_LABELS = {
    "sl":             "STOP-LOSS",
    "tp1":            "TP1  HIT",
    "tp2":            "TP2  HIT",
    "tp3":            "TP3  HIT",
    "max_hold":       "TIME  EXIT",
    "trailing_stop":  "TRAILING  STOP",
    "moon_bag":       "MOON  BAG  KEPT",
}


async def _notify(
    bot, user_id: int, token: str, trigger: str, label: str,
    current: float, entry: float, sell_pct: float, pnl_sol: float,
    qty_remaining: float, sig: str = "", paper: bool = False,
) -> None:
    from utils.share_utils import build_share_markup
    pct_chg  = (current - entry) / entry * 100 if entry > 0 else 0
    pnl_sign = "+" if pnl_sol >= 0 else ""
    chg_sign = "+" if pct_chg >= 0 else ""
    trig_label = _TRIGGER_LABELS.get(trigger, trigger.upper())
    mode_tag   = "PAPER" if paper else "LIVE"
    text = (
        f"⬛ <b>AUTO-EXIT  //  {trig_label}</b>  <i>[{mode_tag}]</i>\n"
        f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"ENTRY  {entry:.8f} SOL\n"
        f"EXIT   {current:.8f} SOL  {chg_sign}{pct_chg:.1f}%\n"
        f"SOLD   {sell_pct:.0f}%  ▸  REM {qty_remaining:.0f}%\n"
        f"P&L    {pnl_sign}{pnl_sol:.5f} SOL\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
        f"📋 CA <i>(tap to copy)</i>\n"
        f"<code>{token}</code>\n\n"
        + (
            f"🔗 TX <i>(tap to copy)</i>\n"
            f"<code>{sig}</code>\n"
            f'<a href="https://solscan.io/tx/{sig}">↗ Solscan</a>  '
            f'<a href="https://pump.fun/{token}">↗ Pump.fun</a>'
            if sig else
            f'<a href="https://pump.fun/{token}">↗ Pump.fun</a>'
        )
    )
    # Build share text
    _tok_short = token[:6] + "…"
    _chg_str   = f"{chg_sign}{pct_chg:.1f}%"
    if pct_chg >= 0:
        _share_text = (
            f"✅ Auto-exit {_chg_str} on {_tok_short} via {settings.BRAND_HANDLE} 🚀\n"
            f"{trig_label} triggered — profit secured 🎯\n"
            f"#brainrotonchain"
        )
    else:
        _share_text = (
            f"⬛ Auto-exit {trig_label} on {_tok_short} via {settings.BRAND_HANDLE}\n"
            f"Risk managed {_chg_str} 🛡️\n"
            f"#brainrotonchain"
        )
    try:
        await bot.send_message(user_id, text, parse_mode="HTML",
                               disable_web_page_preview=True,
                               reply_markup=build_share_markup(_share_text))
    except Exception as e:
        logger.warning(f"Auto-exit notify failed user={user_id}: {e}")


async def _notify_error(bot, user_id: int, token: str, trigger: str, error: str) -> None:
    trig_label = _TRIGGER_LABELS.get(trigger, trigger.upper())
    try:
        await bot.send_message(
            user_id,
            f"⬛ <b>AUTO-EXIT  //  ERR</b>\n"
            f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"TRIG   {trig_label}\n"
            f"ERR    {error[:120]}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
            f"📋 CA <i>(tap to copy)</i>\n"
            f"<code>{token}</code>",
            parse_mode="HTML",
        )
    except Exception:
        pass
