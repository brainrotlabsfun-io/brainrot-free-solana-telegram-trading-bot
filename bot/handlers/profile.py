"""
bot/handlers/profile.py
========================
User profile page.

Callbacks:
  profile:main — wallet, points, and trading activity summary
"""

import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.keyboards.profile_menu import build_profile_menu
from services.points_service import get_user_points, get_user_rank
from services.positions_service import get_positions, get_recent_transactions
from services.wallet_service import get_wallet
from services.bot_wallet_service import get_bot_wallet_address, get_sol_balance

logger = logging.getLogger(__name__)
router = Router()


def _short(addr: str | None) -> str:
    if not addr:
        return "—"
    return addr[:6] + "..." + addr[-4:] if len(addr) > 10 else addr


@router.callback_query(F.data == "profile:main")
async def cb_profile_main(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    user    = callback.from_user

    linked   = await get_wallet(user_id)
    linked_a = linked["wallet_address"] if linked else None

    bot_addr = await get_bot_wallet_address(user_id)
    balance  = await get_sol_balance(bot_addr) if bot_addr else None
    bal_s    = f"{balance:.4f} SOL" if balance is not None else "—"

    points = await get_user_points(user_id)
    rank   = await get_user_rank(user_id)
    rank_s = f"#{rank}" if rank else "unranked"

    positions = await get_positions(user_id)
    recent    = await get_recent_transactions(user_id, limit=100)

    text = (
        f"👤 <b>My Profile</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Username:</b>       @{user.username or user.first_name}\n\n"
        f"<b>Bot Wallet:</b>     <code>{_short(bot_addr)}</code>\n"
        f"<b>Balance:</b>        {bal_s}\n"
        f"<b>Linked Wallet:</b>  <code>{_short(linked_a)}</code>\n\n"
        f"<b>Open Positions:</b> {len(positions)}\n"
        f"<b>Transactions:</b>   {len(recent)}\n\n"
        f"<b>Raid Points:</b>    {points:,}  ({rank_s})\n"
    )

    await callback.message.edit_text(text, reply_markup=build_profile_menu())
    await callback.answer()
