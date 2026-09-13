"""
bot/keyboards/raid_menu.py
==========================
All inline keyboards used by the Raid Center module.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def build_raid_menu() -> InlineKeyboardMarkup:
    """Main Raid Center menu keyboard."""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="⚔️  ACTIVE RAID",     callback_data="raid:active"),
    )
    builder.row(
        InlineKeyboardButton(text="🏆  LEADERBOARD",     callback_data="raid:leaderboard"),
        InlineKeyboardButton(text="📊  MY RAID STATS",   callback_data="raid:stats"),
    )
    builder.row(
        InlineKeyboardButton(text="📋  RAID RULES",      callback_data="raid:rules"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️  BACK",            callback_data="menu:back"),
    )

    return builder.as_markup()


def build_raid_action_menu(raid_id: int, target_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="🔗  OPEN RAID LINK", url=target_url),
    )
    builder.row(
        InlineKeyboardButton(
            text="✅  MARK COMPLETED",
            callback_data=f"raid:complete:{raid_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️  BACK", callback_data="raid:main"),
    )

    return builder.as_markup()


def build_back_to_raid_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅️  BACK TO RAID CENTER", callback_data="raid:main")
    )
    return builder.as_markup()
