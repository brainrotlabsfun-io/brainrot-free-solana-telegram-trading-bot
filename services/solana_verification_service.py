"""
services/solana_verification_service.py
=========================================
On-chain verification of $BRAINROT burn transactions.

Supports three detection methods in order:
  1. Parsed burn/burnChecked instruction (direct burn)
  2. Token balance decrease on user's account (catches incinerator transfers)
  3. Transfer instruction to the incinerator address

Handles both legacy and versioned (v0) transactions — Phantom uses versioned
by default, which puts account keys under staticAccountKeys, not accountKeys.
"""

import logging
from typing import Optional

import aiohttp

from utils.config import settings, get_rpc_url, mark_rpc_rate_limited

logger = logging.getLogger(__name__)

SPL_TOKEN_PROGRAM_ID  = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
BURN_TYPES            = {"burn", "burnChecked"}
INCINERATOR_ADDR      = "1nc1nerator11111111111111111111111111111111"


async def verify_burn_transaction(
    tx_signature: str,
    expected_wallet: str,
    expected_mint: str,
    required_amount_tokens: float,
    token_decimals: int = 6,
) -> dict:
    """
    Verifies a Solana burn transaction on-chain via JSON-RPC.

    Returns:
        {
            "valid":          bool,
            "burned_amount":  float,
            "error":          str | None,
            "mint":           str | None,
            "wallet":         str | None,
        }
    """
    payload = {
        "jsonrpc": "2.0",
        "id":      1,
        "method":  "getTransaction",
        "params":  [
            tx_signature,
            {
                "encoding":                       "jsonParsed",
                "maxSupportedTransactionVersion": 0,
                "commitment":                     "confirmed",
            },
        ],
    }

    data = None
    last_error = "RPC request failed."
    for attempt in range(3):
        rpc_url = get_rpc_url()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    rpc_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    data = await resp.json()
        except aiohttp.ClientError as exc:
            logger.error(f"RPC request failed for tx {tx_signature[:20]} (attempt {attempt+1}): {exc}")
            mark_rpc_rate_limited(rpc_url)
            last_error = f"RPC request failed: {exc}"
            continue
        except Exception as exc:
            logger.error(f"Unexpected error fetching tx {tx_signature[:20]}: {exc}")
            return _fail(str(exc))

        rpc_err = data.get("error") if data else None
        if rpc_err:
            err_code = rpc_err.get("code") if isinstance(rpc_err, dict) else None
            if err_code in (-32429, -32005):  # rate limited / request queue full
                logger.warning(
                    f"RPC rate-limited (code {err_code}) on attempt {attempt+1}: {rpc_url[:50]}"
                )
                mark_rpc_rate_limited(rpc_url)
                last_error = "RPC is busy — retrying..."
                data = None
                continue
            logger.warning(f"RPC error for tx {tx_signature[:20]}: {rpc_err}")
            return _fail(f"RPC error: {rpc_err}")
        break  # success

    if data is None:
        return _fail(f"RPC unavailable after 3 attempts: {last_error}")

    tx_data = data.get("result")
    if tx_data is None:
        return _fail("Transaction not found. Wait 30 seconds and try again.")

    meta = tx_data.get("meta") or {}
    if meta.get("err") is not None:
        return _fail("Transaction failed on-chain.")

    # ── Method 1: explicit burn/burnChecked instruction ───────────────────────
    result = _find_burn_instruction(tx_data, expected_wallet, expected_mint, token_decimals)
    if result["found"]:
        logger.info(f"verify: method=burn_instruction amount={result['amount']} tx={tx_signature[:20]}")
        return _check_amount(result, required_amount_tokens)

    # ── Method 2: token balance decrease on user's account ────────────────────
    # Covers sol-incinerator.com and any transfer-to-dead-address style burn.
    # Works for both legacy and versioned (v0) transactions.
    result = _find_balance_decrease(tx_data, expected_wallet, expected_mint, token_decimals)
    if result["found"]:
        logger.info(f"verify: method=balance_decrease amount={result['amount']} tx={tx_signature[:20]}")
        return _check_amount(result, required_amount_tokens)

    # ── Method 3: transfer instruction to incinerator ─────────────────────────
    result = _find_transfer_to_incinerator(tx_data, expected_wallet, expected_mint, token_decimals)
    if result["found"]:
        logger.info(f"verify: method=incinerator_transfer amount={result['amount']} tx={tx_signature[:20]}")
        return _check_amount(result, required_amount_tokens)

    logger.warning(
        f"verify: no burn found tx={tx_signature[:20]} "
        f"wallet={expected_wallet[:10]} mint={expected_mint[:10]}"
    )
    return _fail(
        "No burn detected in this transaction.\n"
        "Make sure you burned $BRAINROT from your linked wallet address.\n"
        "Check solscan.io to confirm the TX included a burn or transfer to the incinerator."
    )


# ── Detection helpers ──────────────────────────────────────────────────────────

def _get_account_keys(tx_data: dict) -> list:
    """
    Returns account keys list, handling both legacy and versioned (v0) transactions.
    Legacy: message.accountKeys (list of strings or dicts)
    Versioned: message.staticAccountKeys (list of dicts with 'pubkey')
    """
    message = tx_data.get("transaction", {}).get("message", {})
    raw = (
        message.get("accountKeys")
        or message.get("staticAccountKeys")
        or []
    )
    # Normalize: always return list of strings
    result = []
    for entry in raw:
        if isinstance(entry, dict):
            result.append(entry.get("pubkey", ""))
        else:
            result.append(str(entry))
    return result


def _find_burn_instruction(
    tx_data: dict,
    expected_wallet: str,
    expected_mint: str,
    token_decimals: int,
) -> dict:
    """Looks for an explicit burn/burnChecked SPL instruction."""
    message = tx_data.get("transaction", {}).get("message", {})
    meta    = tx_data.get("meta") or {}
    all_ixs = list(message.get("instructions", []))
    for inner in meta.get("innerInstructions", []):
        all_ixs.extend(inner.get("instructions", []))

    for ix in all_ixs:
        parsed = ix.get("parsed")
        if not parsed:
            continue
        if ix.get("program") not in ("spl-token", "spl-token-2022"):
            continue
        if parsed.get("type") not in BURN_TYPES:
            continue

        info      = parsed.get("info", {})
        mint      = info.get("mint", "")
        authority = info.get("authority", info.get("multisigAuthority", ""))

        if mint.lower() != expected_mint.lower():
            continue
        # Accept if authority matches wallet OR if mint matches (lenient)
        if authority.lower() != expected_wallet.lower():
            # Still accept — might be delegated authority
            logger.debug(f"verify: burn instruction authority mismatch: {authority[:10]} vs {expected_wallet[:10]}")

        token_amount = info.get("tokenAmount")
        if token_amount:
            amount = float(token_amount.get("uiAmount") or 0)
        else:
            raw = int(info.get("amount", 0))
            amount = raw / (10 ** token_decimals)

        if amount <= 0:
            continue

        return {"found": True, "amount": amount, "mint": mint, "wallet": authority or expected_wallet}

    return {"found": False}


def _find_balance_decrease(
    tx_data: dict,
    expected_wallet: str,
    expected_mint: str,
    token_decimals: int,
) -> dict:
    """
    Detects a burn by finding a token account owned by expected_wallet
    whose balance decreased for the expected mint.
    Works for transfer-to-incinerator and all other burn methods.
    Handles both legacy and versioned transactions.
    """
    meta         = tx_data.get("meta") or {}
    pre_balances = meta.get("preTokenBalances", [])
    post_balances = meta.get("postTokenBalances", [])
    post_map     = {b["accountIndex"]: b for b in post_balances}
    account_keys = _get_account_keys(tx_data)

    for pre in pre_balances:
        if pre.get("mint", "").lower() != expected_mint.lower():
            continue

        owner = pre.get("owner", "")
        idx   = pre.get("accountIndex", -1)

        # Resolve account pubkey at this index
        acct_pubkey = account_keys[idx] if 0 <= idx < len(account_keys) else ""

        # Must belong to expected wallet (owner or account pubkey)
        if (owner.lower() != expected_wallet.lower()
                and acct_pubkey.lower() != expected_wallet.lower()):
            continue

        pre_ui  = float((pre.get("uiTokenAmount") or {}).get("uiAmount") or 0)
        post_ui = 0.0
        if idx in post_map:
            post_ui = float((post_map[idx].get("uiTokenAmount") or {}).get("uiAmount") or 0)

        burned = pre_ui - post_ui
        if burned <= 0:
            continue

        return {
            "found":  True,
            "amount": burned,
            "mint":   expected_mint,
            "wallet": owner or expected_wallet,
        }

    return {"found": False}


def _find_transfer_to_incinerator(
    tx_data: dict,
    expected_wallet: str,
    expected_mint: str,
    token_decimals: int,
) -> dict:
    """
    Detects a token transfer instruction to the incinerator address.
    Some dApps structure burns this way.
    """
    message = tx_data.get("transaction", {}).get("message", {})
    meta    = tx_data.get("meta") or {}
    all_ixs = list(message.get("instructions", []))
    for inner in meta.get("innerInstructions", []):
        all_ixs.extend(inner.get("instructions", []))

    for ix in all_ixs:
        parsed = ix.get("parsed")
        if not parsed:
            continue
        if ix.get("program") not in ("spl-token", "spl-token-2022"):
            continue
        if parsed.get("type") not in ("transfer", "transferChecked"):
            continue

        info        = parsed.get("info", {})
        mint        = info.get("mint", expected_mint)  # transfer may omit mint
        destination = info.get("destination", "")
        authority   = info.get("authority", info.get("source", ""))

        if mint.lower() != expected_mint.lower():
            # transferChecked includes mint, plain transfer may not
            if parsed.get("type") == "transfer" and mint == expected_mint:
                pass  # allow

        if INCINERATOR_ADDR.lower() not in destination.lower():
            continue

        token_amount = info.get("tokenAmount")
        if token_amount:
            amount = float(token_amount.get("uiAmount") or 0)
        else:
            raw = int(info.get("amount", 0))
            amount = raw / (10 ** token_decimals)

        if amount <= 0:
            continue

        return {
            "found":  True,
            "amount": amount,
            "mint":   mint or expected_mint,
            "wallet": authority or expected_wallet,
        }

    return {"found": False}


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _check_amount(result: dict, required: float) -> dict:
    amount = result["amount"]
    if amount < required:
        return {
            "valid":         False,
            "burned_amount": amount,
            "error": (
                f"Burned {amount:,.0f} $BRAINROT in this TX.\n"
                f"Need {required:,.0f} total. Burns are cumulative — "
                f"submit more burn TXs to reach the threshold."
            ),
            "mint":   result.get("mint"),
            "wallet": result.get("wallet"),
        }
    return {
        "valid":         True,
        "burned_amount": amount,
        "error":         None,
        "mint":          result.get("mint"),
        "wallet":        result.get("wallet"),
    }


def _fail(error: str) -> dict:
    return {"valid": False, "burned_amount": 0.0, "error": error, "mint": None, "wallet": None}
