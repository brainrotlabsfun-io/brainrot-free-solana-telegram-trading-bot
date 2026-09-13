"""
services/positions_service.py
===============================
Manages tracked token positions and submitted transaction logs.
Column names match the tracked_positions / submitted_transactions tables in db.py.
PnL calculation is a placeholder — replace with real on-chain price lookup.
"""

import logging
from database.sqlite_db import get_db

logger = logging.getLogger(__name__)


async def add_position(
    user_id: int,
    token_address: str,
    token_symbol: str,
    buy_price_sol: float,
    amount_sol: float,
    tx_signature: str = "",
) -> int:
    """
    Insert a new position row and return its id.
    Each buy of the same token creates a NEW row (different opened_at timestamp).
    Uses an explicit timestamp to guarantee uniqueness even within the same second.
    """
    import time as _time
    from datetime import datetime, timezone
    # Millisecond-precision timestamp ensures no UNIQUE(user_id, token_address, opened_at) collision
    opened_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.") + f"{int(_time.time() * 1000) % 1000:03d}"
    async with get_db() as db:
        cursor = await db.execute("""
            INSERT INTO tracked_positions
                (user_id, token_address, token_symbol, buy_price_sol, amount_sol,
                 tx_signature, opened_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, token_address, token_symbol, buy_price_sol, amount_sol,
              tx_signature, opened_at))
        await db.commit()
        return cursor.lastrowid


async def get_positions(user_id: int) -> list[dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM tracked_positions WHERE user_id = ? AND status = 'open' ORDER BY opened_at DESC",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def close_position(position_id: int, user_id: int) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE tracked_positions SET status = 'closed', closed_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND user_id = ?",
            (position_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def log_transaction(
    user_id: int,
    token_address: str,
    tx_signature: str,
    amount_sol: float = 0.0,
    direction: str = "buy",
    status: str = "submitted",
) -> int:
    async with get_db() as db:
        cursor = await db.execute("""
            INSERT INTO submitted_transactions
                (user_id, token_address, tx_signature, amount_sol, direction, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, token_address, tx_signature, amount_sol, direction, status))
        await db.commit()
        return cursor.lastrowid


async def get_recent_transactions(user_id: int, limit: int = 20) -> list[dict]:
    async with get_db() as db:
        async with db.execute("""
            SELECT * FROM submitted_transactions
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_id, limit)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


def calculate_pnl(entry_price: float, current_price: float, quantity: float) -> dict:
    """Stub — replace current_price with a real on-chain lookup when available."""
    if entry_price <= 0:
        return {"pnl_usd": 0.0, "pnl_pct": 0.0}
    pnl_usd = (current_price - entry_price) * quantity
    pnl_pct = ((current_price - entry_price) / entry_price) * 100
    return {"pnl_usd": pnl_usd, "pnl_pct": pnl_pct}
