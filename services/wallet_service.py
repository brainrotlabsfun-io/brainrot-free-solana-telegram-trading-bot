"""
services/wallet_service.py
============================
Manages trading wallets linked to users.
SOL balance fetching: stub — replace with Solana RPC call when ready.

Real implementation:
    from solana.rpc.async_api import AsyncClient
    async with AsyncClient("https://api.mainnet-beta.solana.com") as client:
        resp = await client.get_balance(PublicKey(wallet_address))
        sol = resp.value / 1_000_000_000
"""

import logging
from typing import Optional

from database.sqlite_db import get_db

logger = logging.getLogger(__name__)

LAMPORTS_PER_SOL = 1_000_000_000


async def get_wallet(user_id: int) -> Optional[dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM trading_wallets WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def set_wallet(user_id: int, wallet_address: str) -> None:
    async with get_db() as db:
        # Primary trading wallet (used by sniper)
        await db.execute("""
            INSERT INTO trading_wallets (user_id, wallet_address)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                wallet_address = ?,
                updated_at     = CURRENT_TIMESTAMP
        """, (user_id, wallet_address, wallet_address))
        # wallet_links — linked external wallet
        await db.execute("""
            INSERT INTO wallet_links (user_id, wallet_address)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                wallet_address = ?,
                updated_at     = CURRENT_TIMESTAMP
        """, (user_id, wallet_address, wallet_address))
        await db.commit()
    logger.info(f"Wallet set for user {user_id}: {wallet_address[:8]}...")


async def remove_wallet(user_id: int) -> None:
    async with get_db() as db:
        await db.execute("DELETE FROM trading_wallets WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM wallet_links WHERE user_id = ?", (user_id,))
        await db.commit()


async def get_sol_balance(wallet_address: str) -> Optional[float]:
    """
    Returns SOL balance for a wallet address.
    STUB — replace with real Solana RPC call.
    Returns None if unavailable.
    """
    # TODO: Implement real RPC call
    # from solana.rpc.async_api import AsyncClient
    # from solana.publickey import PublicKey
    # async with AsyncClient("https://api.mainnet-beta.solana.com") as client:
    #     resp = await client.get_balance(PublicKey(wallet_address))
    #     if resp.value is not None:
    #         return resp.value / LAMPORTS_PER_SOL
    return None


async def has_sufficient_balance(user_id: int, required_sol: float) -> tuple[bool, str]:
    """
    Checks if linked wallet has enough SOL for a trade.
    Returns (ok, message).
    """
    wallet = await get_wallet(user_id)
    if not wallet:
        return False, "No wallet linked. Add your wallet first."

    balance = await get_sol_balance(wallet["wallet_address"])
    if balance is None:
        return True, "Balance check unavailable — proceed manually."  # non-blocking for now

    if balance < required_sol:
        return False, f"Insufficient balance: {balance:.4f} SOL available, {required_sol:.4f} SOL required."

    return True, f"Balance OK: {balance:.4f} SOL"
