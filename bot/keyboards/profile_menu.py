"""
bot/keyboards/profile_menu.py
==============================
Inline keyboards for the Profile and Badges pages.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def build_profile_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🏅 MY BADGES",       callback_data="profile:badges"),
        InlineKeyboardButton(text="👑 SUPREME ACCESS",  callback_data="supreme:main"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ BACK", callback_data="menu:back"),
    )
    return builder.as_markup()


def build_badges_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👤 MY PROFILE",     callback_data="profile:main"),
        InlineKeyboardButton(text="👑 SUPREME ACCESS", callback_data="supreme:main"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ BACK", callback_data="menu:back"),
    )
    return builder.as_markup()
