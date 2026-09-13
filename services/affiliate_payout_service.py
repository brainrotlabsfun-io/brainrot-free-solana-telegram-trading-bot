"""
services/affiliate_payout_service.py
======================================
Sends SOL commission payouts from the payment wallet to affiliate wallets.

Uses the PAYMENT_WALLET_PRIVATE_KEY from .env to sign a simple SOL transfer
(SystemProgram.transfer) — no Jupiter swap needed, just lamports from A to B.

Called automatically by affiliate_payment_worker after a qualifying payment
is confirmed and a commission entry is created.

Security:
  - Private key is read from env at call time, never stored in memory long-term
  - Never logs key bytes
  - Payout is skipped (not crashed) if key is missing — admin can pay manually
"""

import base64
import logging
import os
from typing import Optional

import aiohttp

from utils.config import get_rpc_url, mark_rpc_rate_limited

logger = logging.getLogger(__name__)

COMMISSION_PCT     = 0.21   # 21% of incoming SOL
MIN_PAYOUT_SOL     = 0.000001
PRIORITY_FEE_LAMPORTS = 5000


def _get_payment_keypair():
    """
    Load the payment wallet keypair from PAYMENT_WALLET_PRIVATE_KEY env var.
    Supports base58-encoded private keys (64-byte keypair).
    Returns a solders Keypair or None if not configured.
    """
    raw = os.getenv("PAYMENT_WALLET_PRIVATE_KEY", "").strip()
    if not raw:
        logger.warning("affiliate_payout: PAYMENT_WALLET_PRIVATE_KEY not set — skipping auto-payout")
        return None
    try:
        from solders.keypair import Keypair
        # Try base58 decode first (most common format from Phantom/CLI export)
        import base58
        key_bytes = base58.b58decode(raw)
        return Keypair.from_bytes(key_bytes)
    except Exception:
        try:
            # Fallback: raw bytes as list (Solana CLI JSON format)
            import json
            key_bytes = bytes(json.loads(raw))
            from solders.keypair import Keypair
            return Keypair.from_bytes(key_bytes)
        except Exception as e:
            logger.error(f"affiliate_payout: failed to load keypair: {e}")
            return None


async def _get_latest_blockhash() -> Optional[str]:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getLatestBlockhash",
        "params": [{"commitment": "confirmed"}],
    }
    for attempt in range(3):
        rpc_url = get_rpc_url()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    rpc_url, json=body,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 429:
                        mark_rpc_rate_limited(rpc_url)
                        continue
                    data = await resp.json()
                    return data["result"]["value"]["blockhash"]
        except Exception as e:
            logger.warning(f"affiliate_payout: getLatestBlockhash failed: {e}")
    return None


async def _send_raw_transaction(signed_bytes: bytes) -> Optional[str]:
    encoded = base64.b64encode(signed_bytes).decode()
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sendTransaction",
        "params": [encoded, {
            "encoding":            "base64",
            "skipPreflight":       False,
            "maxRetries":          8,
            "preflightCommitment": "processed",
        }],
    }
    for attempt in range(3):
        rpc_url = get_rpc_url()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    rpc_url, json=body,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 429:
                        mark_rpc_rate_limited(rpc_url)
                        continue
                    data = await resp.json()
                    if "error" in data:
                        logger.warning(f"affiliate_payout: sendTransaction error: {data['error']}")
                        return None
                    return data.get("result")
        except Exception as e:
            logger.error(f"affiliate_payout: sendTransaction exception: {e}")
    return None


async def send_sol_commission(
    to_address: str,
    amount_sol: float,
) -> Optional[str]:
    """
    Sends `amount_sol` SOL from the payment wallet to `to_address`.
    Returns the transaction signature on success, None on failure.

    Builds a SystemProgram.transfer instruction using solders.
    """
    if amount_sol < MIN_PAYOUT_SOL:
        logger.warning(f"affiliate_payout: amount {amount_sol} SOL below minimum, skip")
        return None

    keypair = _get_payment_keypair()
    if not keypair:
        return None

    blockhash = await _get_latest_blockhash()
    if not blockhash:
        logger.error("affiliate_payout: could not get blockhash")
        return None

    try:
        from solders.keypair import Keypair
        from solders.pubkey import Pubkey
        from solders.hash import Hash
        from solders.transaction import Transaction
        from solders.system_program import transfer, TransferParams
        from solders.message import Message
        from solders.compute_budget import set_compute_unit_price, set_compute_unit_limit

        lamports = int(amount_sol * 1_000_000_000)
        to_pubkey = Pubkey.from_string(to_address)

        # Priority fee — ensures the payout lands quickly even during congestion.
        # set_compute_unit_price takes micro-lamports per compute unit.
        # set_compute_unit_limit caps the CU budget (simple transfer needs ~200).
        priority_ix = set_compute_unit_price(PRIORITY_FEE_LAMPORTS)
        cu_limit_ix = set_compute_unit_limit(200)

        transfer_ix = transfer(TransferParams(
            from_pubkey = keypair.pubkey(),
            to_pubkey   = to_pubkey,
            lamports    = lamports,
        ))

        msg = Message.new_with_blockhash(
            [priority_ix, cu_limit_ix, transfer_ix],
            keypair.pubkey(),
            Hash.from_string(blockhash),
        )
        tx      = Transaction([keypair], msg, Hash.from_string(blockhash))
        tx_bytes = bytes(tx)

        sig = await _send_raw_transaction(tx_bytes)
        if sig:
            logger.info(
                f"affiliate_payout: sent {amount_sol:.6f} SOL to {to_address[:10]}... "
                f"tx={sig[:16]}..."
            )
        return sig

    except Exception as e:
        logger.error(f"affiliate_payout: failed to build/send transfer: {e}")
        return None


async def pay_commission(
    affiliate_wallet: str,
    amount_sol_received: float,
    commission_id: int,
) -> Optional[str]:
    """
    Calculates 21% of `amount_sol_received` and sends it to `affiliate_wallet`.
    Updates commission_ledger with the payout tx hash on success.
    Returns the tx signature or None.
    """
    from services.affiliate_service import mark_commission_paid

    payout_sol = round(amount_sol_received * COMMISSION_PCT, 9)
    logger.info(
        f"affiliate_payout: paying commission #{commission_id} "
        f"{payout_sol:.6f} SOL to {affiliate_wallet[:10]}..."
    )

    sig = await send_sol_commission(affiliate_wallet, payout_sol)
    if sig:
        await mark_commission_paid(commission_id, sig)
        logger.info(f"affiliate_payout: commission #{commission_id} marked paid tx={sig[:16]}...")
    else:
        logger.warning(f"affiliate_payout: payout failed for commission #{commission_id} — will need manual payout")

    return sig
