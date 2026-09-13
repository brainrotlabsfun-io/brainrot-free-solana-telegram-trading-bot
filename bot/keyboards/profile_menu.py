"""
bot/keyboards/profile_menu.py
==============================
Inline keyboards for the Profile page.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def build_profile_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💳 WALLET",    callback_data="sniper:wallet"),
        InlineKeyboardButton(text="📊 POSITIONS", callback_data="sniper:positions"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ BACK", callback_data="menu:back"),
    )
    return builder.as_markup()
