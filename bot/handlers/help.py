"""
bot/handlers/help.py
====================
Handles the /help command.
Shows all available commands with short descriptions.
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    from bot.handlers.callbacks import _build_help_menu
    text = (
        "❓ <b>Help &amp; FAQ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Select a topic below to get answers:"
    )
    await message.answer(text, reply_markup=_build_help_menu())
