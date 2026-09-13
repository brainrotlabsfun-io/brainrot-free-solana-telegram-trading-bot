"""
bot/handlers/menu.py
====================
Handles the /menu command.
Sends the main inline keyboard menu.
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards.main_menu import build_main_menu

router = Router()

MENU_TEXT = (
    "📋 <b>Main Menu</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "Select a module below to get started.\n"
    "<i>Inactive modules will show a coming soon message.</i>"
)


@router.message(Command("menu"))
async def handle_menu(message: Message) -> None:
    await message.answer(
        text=MENU_TEXT,
        reply_markup=build_main_menu(),
    )
