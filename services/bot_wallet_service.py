"""
services/bot_wallet_service.py
================================
Per-user bot-managed hot wallets.

Flow:
  1. Bot generates a Solana keypair for the user on first access.
  2. Private key is AES-256 encrypted (Fernet) before storage in bot_wallets table.
  3. User deposits SOL to their bot wallet address.
  4. Bot signs trades automatically using the decrypted keypair.

Security notes:
  - WALLET_ENCRYPTION_KEY must be kept secret — if lost, private keys cannot be decrypted.
  - Never log or display private key bytes.
  - Users should only deposit amounts they are willing to trade actively.
"""

import base64
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from database.sqlite_db import get_db
from utils.config import settings, get_rpc_url

logger = logging.getLogger(__name__)

# WSOL mint (used as input for SOL → token swaps)
SOL_MINT = "So11111111111111111111111111111111111111112"


def _fernet() -> Fernet:
    key = settings.WALLET_ENCRYPTION_KEY.encode()
    return Fernet(key)


async def get_or_create_bot_wallet(user_id: int) -> dict:
    """
    Returns the user's bot wallet (address + encrypted key).
    Creates one on first call.
    """
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM bot_wallets WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()

    if row:
        return dict(row)

    return await _create_bot_wallet(user_id)


async def _create_bot_wallet(user_id: int) -> dict:
    try:
        from solders.keypair import Keypair
    except ImportError:
        raise RuntimeError(
            "solders is required for bot wallet generation. "
            "Run: pip install solders"
        )

    kp            = Keypair()
    address       = str(kp.pubkey())
    privkey_bytes = bytes(kp)                                    # 64 bytes
    encrypted_key = _fernet().encrypt(privkey_bytes).decode()    # store as str

    async with get_db() as db:
        await db.execute("""
            INSERT OR IGNORE INTO bot_wallets (user_id, wallet_address, encrypted_private_key)
            VALUES (?, ?, ?)
        """, (user_id, address, encrypted_key))
        await db.commit()
        async with db.execute(
            "SELECT * FROM bot_wallets WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()

    logger.info(f"Bot wallet created for user {user_id}: {address[:8]}...")
    return dict(row)


async def get_bot_wallet_address(user_id: int) -> Optional[str]:
    row = await get_or_create_bot_wallet(user_id)
    return row["wallet_address"] if row else None


def get_keypair(encrypted_key: str):
    """Decrypt and return a solders Keypair. Never log the result."""
    try:
        from solders.keypair import Keypair
    except ImportError:
        raise RuntimeError("solders is required. Run: pip install solders")

    privkey_bytes = _fernet().decrypt(encrypted_key.encode())
    return Keypair.from_bytes(privkey_bytes)


async def get_sol_balance(address: str) -> Optional[float]:
    """Returns SOL balance in SOL via Solana JSON-RPC. Returns None on error."""
    import aiohttp
    import asyncio
    from utils.config import get_rpc_url, mark_rpc_rate_limited
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [address, {"commitment": "confirmed"}],
    }
    for attempt in range(4):
        rpc_url = get_rpc_url()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    rpc_url,
                    json=body,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 429:
                        mark_rpc_rate_limited(rpc_url)
                        continue  # immediately try next RPC
                    data = await resp.json(content_type=None)
                    if "error" in data:
                        err = data["error"]
                        if isinstance(err, dict) and err.get("code") == 429:
                            mark_rpc_rate_limited(rpc_url)
                            continue  # immediately try next RPC
                        logger.warning(f"getBalance RPC error for {address[:8]}: {err}")
                        return None
                    result = data.get("result")
                    if result is None:
                        return None
                    lamports = result.get("value") if isinstance(result, dict) else result
                    if lamports is None:
                        return None
                    return int(lamports) / 1_000_000_000
        except Exception as e:
            logger.warning(f"getBalance failed for {address[:8]}: {e}")
            if attempt < 3:
                await asyncio.sleep(0.5)
    logger.warning(f"getBalance failed after retries for {address[:8]}")
    return None


async def get_latest_blockhash() -> Optional[str]:
    """Fetches the latest blockhash from the RPC."""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                get_rpc_url(),
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getLatestBlockhash",
                    "params": [{"commitment": "confirmed"}],
                },
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json(content_type=None)
                return data["result"]["value"]["blockhash"]
    except Exception as e:
        logger.warning(f"getLatestBlockhash failed: {e}")
        return None


async def withdraw_sol(
    user_id: int,
    to_address: str,
    amount_sol: float,
) -> dict:
    """
    Sends SOL from the user's bot wallet to an external address.
    Returns {"success": bool, "signature": str|None, "error": str|None}
    """
    import aiohttp
    from solders.pubkey import Pubkey
    from solders.system_program import transfer, TransferParams
    from solders.transaction import Transaction
    from solders.message import Message
    from solders.hash import Hash

    NETWORK_FEE_SOL = 0.000005  # ~5000 lamports safety buffer

    row = await get_or_create_bot_wallet(user_id)
    if not row:
        return {"success": False, "signature": None, "error": "Bot wallet not found."}

    address = row["wallet_address"]
    keypair = get_keypair(row["encrypted_private_key"])

    balance = await get_sol_balance(address)
    if balance is None:
        return {"success": False, "signature": None, "error": "Could not fetch balance."}

    max_send = balance - NETWORK_FEE_SOL
    if amount_sol > max_send:
        return {
            "success": False,
            "signature": None,
            "error": f"Insufficient balance. Available to withdraw: {max_send:.6f} SOL (balance {balance:.6f} − fee reserve {NETWORK_FEE_SOL}).",
        }

    blockhash_str = await get_latest_blockhash()
    if not blockhash_str:
        return {"success": False, "signature": None, "error": "Could not fetch blockhash from RPC."}

    try:
        lamports = int(amount_sol * 1_000_000_000)
        ix = transfer(TransferParams(
            from_pubkey = keypair.pubkey(),
            to_pubkey   = Pubkey.from_string(to_address),
            lamports    = lamports,
        ))
        msg = Message.new_with_blockhash([ix], keypair.pubkey(), Hash.from_string(blockhash_str))
        tx  = Transaction([keypair], msg, Hash.from_string(blockhash_str))
        raw = bytes(tx)
    except Exception as e:
        logger.error(f"withdraw_sol build tx failed: {e}")
        return {"success": False, "signature": None, "error": f"Failed to build transaction: {e}"}

    # Send
    import base64
    encoded = base64.b64encode(raw).decode()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                get_rpc_url(),
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendTransaction",
                    "params": [encoded, {"encoding": "base64", "skipPreflight": False, "maxRetries": 5}],
                },
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json(content_type=None)
                if "error" in data:
                    return {"success": False, "signature": None, "error": str(data["error"])}
                sig = data.get("result")
                logger.info(f"Withdrawal {amount_sol} SOL → {to_address[:8]}... tx={sig}")
                return {"success": True, "signature": sig, "error": None}
    except Exception as e:
        logger.error(f"withdraw_sol sendTransaction failed: {e}")
        return {"success": False, "signature": None, "error": str(e)}


async def delete_bot_wallet(user_id: int) -> None:
    """Permanently deletes the bot wallet record. Funds are unrecoverable if any remain."""
    async with get_db() as db:
        await db.execute("DELETE FROM bot_wallets WHERE user_id = ?", (user_id,))
        await db.commit()
    logger.warning(f"Bot wallet deleted for user {user_id}")
