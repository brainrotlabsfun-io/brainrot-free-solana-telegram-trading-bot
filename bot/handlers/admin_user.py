"""
bot/handlers/admin_user.py
===========================
User utility and admin lookup commands.

Commands:
  /myid                 — show your own Telegram user ID (anyone can use)
  /adminuser <user_id>  — admin: wallet and account summary for a user
"""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from database.sqlite_db import get_db
from utils.admin import is_admin
from services.wallet_service import get_wallet

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("myid"))
async def cmd_myid(message: Message) -> None:
    """Anyone can use this to find their Telegram user ID."""
    uid  = message.from_user.id
    name = message.from_user.username or message.from_user.first_name
    await message.answer(
        f"👤 <b>Your Telegram ID</b>\n\n"
        f"<code>{uid}</code>\n\n"
        f"Name: {name}\n\n"
        f"<i>Add this to ADMIN_IDS in .env to give yourself admin access.</i>",
        parse_mode="HTML",
    )


@router.message(Command("adminuser"))
async def cmd_adminuser(message: Message) -> None:
    """Admin: show a summary for a user ID."""
    if not is_admin(message.from_user.id):
        return

    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: /adminuser &lt;user_id&gt;")
        return

    uid    = int(parts[1])
    wallet = await get_wallet(uid)

    async with get_db() as db:
        async with db.execute(
            "SELECT username, first_name, created_at FROM users WHERE telegram_user_id = ?",
            (uid,),
        ) as cur:
            user_row = await cur.fetchone()
        async with db.execute(
            "SELECT wallet_address, created_at FROM bot_wallets WHERE user_id = ?",
            (uid,),
        ) as cur:
            bot_wallet = await cur.fetchone()

    if user_row is None and wallet is None and bot_wallet is None:
        await message.answer(f"No record found for user {uid}.")
        return

    name    = (user_row["username"] or user_row["first_name"]) if user_row else "—"
    joined  = user_row["created_at"] if user_row else "—"
    linked  = wallet["wallet_address"] if wallet else "—"
    bot_w   = bot_wallet["wallet_address"] if bot_wallet else "—"

    await message.answer(
        f"👤 <b>User {uid}</b>\n\n"
        f"<b>Name:</b> {name}\n"
        f"<b>Joined:</b> {joined}\n\n"
        f"<b>Linked Wallet:</b> <code>{linked}</code>\n"
        f"<b>Bot Wallet:</b> <code>{bot_w}</code>",
        parse_mode="HTML",
    )
