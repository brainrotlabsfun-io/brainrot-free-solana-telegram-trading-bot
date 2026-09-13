"""
services/watch_alert_worker.py
================================
Background worker — checks prices of watched tokens every 2 minutes.
Fires a DM alert with quick buy button when drop or pump threshold is hit.

Price source: DexScreener API (no key required).
Alert cooldown: 30 minutes per token per user (prevents spam).
"""

import asyncio
import logging
from datetime import datetime, timedelta

import aiohttp
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.sniper_watch_service import (
    get_all_alert_targets,
    update_last_price,
    set_last_alerted,
)
from database.sqlite_db import get_db

logger = logging.getLogger(__name__)

_running = False
DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"
ALERT_COOLDOWN_MINUTES = 30
POLL_INTERVAL_SECONDS  = 120  # 2 minutes


def stop() -> None:
    global _running
    _running = False


async def start(bot: Bot) -> None:
    global _running
    _running = True
    logger.info("Watch alert worker started.")
    while _running:
        try:
            await _check_all(bot)
        except Exception as e:
            logger.error(f"watch_alert_worker error: {e}", exc_info=True)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
    logger.info("Watch alert worker stopped.")


async def _fetch_price_sol(token_address: str) -> float | None:
    """Fetch the current price in SOL via DexScreener. Returns None on failure."""
    url = DEXSCREENER_URL.format(token_address)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                data = await resp.json()
                pairs = data.get("pairs") or []
                # Prefer a SOL-paired pool
                for pair in pairs:
                    if pair.get("quoteToken", {}).get("symbol") == "SOL":
                        price = float(pair.get("priceNative") or 0)
                        if price > 0:
                            return price
                # Fallback: any pair, convert USD → SOL using rough estimate
                if pairs:
                    price_usd = float(pairs[0].get("priceUsd") or 0)
                    sol_usd   = await _fetch_sol_usd()
                    if price_usd > 0 and sol_usd > 0:
                        return price_usd / sol_usd
    except Exception as e:
        logger.debug(f"watch_alert: price fetch for {token_address[:10]} failed: {e}")
    return None


async def _fetch_sol_usd() -> float:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                data = await resp.json()
                return float(data["solana"]["usd"])
    except Exception:
        return 130.0  # fallback estimate


async def _is_on_cooldown(row_id: int) -> bool:
    async with get_db() as db:
        async with db.execute(
            "SELECT last_alerted_at FROM sniper_watch_targets WHERE id = ?", (row_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row or not row["last_alerted_at"]:
        return False
    try:
        last = datetime.fromisoformat(str(row["last_alerted_at"]).replace(" ", "T"))
        return datetime.utcnow() - last < timedelta(minutes=ALERT_COOLDOWN_MINUTES)
    except Exception:
        return False


def _build_quick_buy_kb(token_address: str, buy_sol: float) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text=f"⚡ Quick Buy {buy_sol:.4f} SOL",
        callback_data=f"sniper:quick_buy:{token_address}:{buy_sol}",
    ))
    b.row(InlineKeyboardButton(
        text="🔍 Analyze Token",
        callback_data=f"sniper:analyze_addr:{token_address}",
    ))
    return b.as_markup()


async def _check_all(bot: Bot) -> None:
    targets = await get_all_alert_targets()
    if not targets:
        return

    for t in targets:
        try:
            await _check_one(bot, t)
        except Exception as e:
            logger.debug(f"watch_alert: error checking {t.get('token_address', '?')[:10]}: {e}")
        # Small delay between RPC calls to avoid rate limits
        await asyncio.sleep(0.5)


async def _check_one(bot: Bot, t: dict) -> None:
    row_id    = t["id"]
    user_id   = t["user_id"]
    addr      = t["token_address"]
    entry_sol = float(t.get("entry_price_sol") or 0)
    drop_pct  = float(t.get("alert_drop_pct")  or 20.0)
    pump_pct  = float(t.get("alert_pump_pct")  or 100.0)
    buy_sol   = float(t.get("quick_buy_sol")   or 0.05)
    sym       = t.get("token_symbol") or addr[:6] + "..." + addr[-4:]

    current_sol = await _fetch_price_sol(addr)
    if current_sol is None or current_sol <= 0:
        return

    await update_last_price(row_id, current_sol)

    # On first add, set entry price
    if entry_sol <= 0:
        async with get_db() as db:
            await db.execute(
                "UPDATE sniper_watch_targets SET entry_price_sol = ? WHERE id = ?",
                (current_sol, row_id),
            )
            await db.commit()
        return  # nothing to compare on first check

    change_pct = (current_sol - entry_sol) / entry_sol * 100

    fired = False
    if change_pct <= -drop_pct:
        fired = True
        direction = "DROP"
        icon = "📉"
        alert_msg = (
            f"📉 <b>WATCH ALERT — PRICE DROP</b>\n\n"
            f"<code>┌─ {sym[:26]:<26}─┐\n"
            f"│  ENTRY   {entry_sol:.8f} SOL       │\n"
            f"│  NOW     {current_sol:.8f} SOL       │\n"
            f"│  CHANGE  ↓{abs(change_pct):.1f}%                   │\n"
            f"│  THRESHOLD  ↓{drop_pct:.0f}%                │\n"
            f"└{'─'*34}┘</code>\n\n"
            f"Token dropped past your alert threshold.\n"
            f"Tap below to act quickly."
        )
    elif change_pct >= pump_pct:
        fired = True
        direction = "PUMP"
        icon = "📈"
        alert_msg = (
            f"📈 <b>WATCH ALERT — PRICE PUMP</b>\n\n"
            f"<code>┌─ {sym[:26]:<26}─┐\n"
            f"│  ENTRY   {entry_sol:.8f} SOL       │\n"
            f"│  NOW     {current_sol:.8f} SOL       │\n"
            f"│  CHANGE  ↑{change_pct:.1f}%                   │\n"
            f"│  THRESHOLD  ↑{pump_pct:.0f}%                │\n"
            f"└{'─'*34}┘</code>\n\n"
            f"Token pumped past your alert threshold.\n"
            f"Tap below to act quickly."
        )
    else:
        return

    if await _is_on_cooldown(row_id):
        return

    try:
        await bot.send_message(
            user_id,
            alert_msg,
            reply_markup=_build_quick_buy_kb(addr, buy_sol),
            parse_mode="HTML",
        )
        await set_last_alerted(row_id)
        logger.info(
            f"watch_alert: fired {direction} alert for user {user_id} "
            f"token {addr[:10]} ({change_pct:+.1f}%)"
        )
    except Exception as e:
        logger.warning(f"watch_alert: could not notify user {user_id}: {e}")
