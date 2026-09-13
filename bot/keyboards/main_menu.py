"""
bot/keyboards/main_menu.py
==========================
Defines the main inline keyboard for the bot menu.
Add new buttons here as new modules are built.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from utils.config import settings


def build_main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    # ── Row 1: New user onboarding + Wallet ───────────────────────────────────
    builder.row(
        InlineKeyboardButton(text="🆕 NEW USERS / INFO",      callback_data="menu:new_users"),
        InlineKeyboardButton(text="💼 WALLET",                callback_data="menu:wallet"),
    )
    # ── Row 3: Sniper Tool (full width) ───────────────────────────────────────
    builder.row(
        InlineKeyboardButton(text="🎯  SNIPER TOOL",          callback_data="sniper:main"),
    )
    # ── Row 4: Copy Trade (full width) ────────────────────────────────────────
    builder.row(
        InlineKeyboardButton(text="📋  COPY TRADE",           callback_data="ct:main"),
    )
    # ── Row 5: Candle Sniper (full width) ─────────────────────────────────────
    builder.row(
        InlineKeyboardButton(text="🕯️  CANDLE SNIPER",        callback_data="cs:main"),
    )
    # ── Row 6: Portfolio Viewer Guide ─────────────────────────────────────────
    builder.row(
        InlineKeyboardButton(text="📈  VIEW MY PORTFOLIO  📉",  callback_data="menu:portfolio_guide"),
    )
    # ── Row 7: Profile ────────────────────────────────────────────────────────
    builder.row(
        InlineKeyboardButton(text="👤  PROFILE",              callback_data="profile:main"),
    )
    # ── Row 8: Raid Center + Raid Hub ─────────────────────────────────────────
    builder.row(
        InlineKeyboardButton(text="⚔️  RAID CENTER",          callback_data="raid:main"),
        InlineKeyboardButton(text="🚀  RAID HUB",             callback_data="hub:main"),
    )
    # ── Row 9: User Tutorial ──────────────────────────────────────────────────
    builder.row(
        InlineKeyboardButton(text="📚  USER TUTORIAL",        callback_data="tut:hub"),
    )
    # ── Row 10: Help ──────────────────────────────────────────────────────────
    builder.row(
        InlineKeyboardButton(text="❗  HELP  ❗",              callback_data="menu:help"),
    )
    # ── Row 11: Community links ────────────────────────────────────────────────
    # Each link is optional — set DISCORD_URL / TWITTER_URL / WEBSITE_URL in .env.
    # Buttons for unset links are simply omitted, and the row is skipped entirely
    # if none are configured.
    community = [
        ("💬 Discord", settings.DISCORD_URL),
        ("🐦 Twitter", settings.TWITTER_URL),
        ("🌐 Website", settings.WEBSITE_URL),
    ]
    community_buttons = [
        InlineKeyboardButton(text=label, url=url)
        for label, url in community
        if url
    ]
    if community_buttons:
        builder.row(*community_buttons)

    return builder.as_markup()


def build_watchlist_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🪙 TOKENS",       callback_data="wl:tokens"),
        InlineKeyboardButton(text="👛 WALLETS",      callback_data="wl:wallets"),
    )
    builder.row(
        InlineKeyboardButton(text="👨‍💻 DEV RADAR",    callback_data="wl:dev_radar"),
        InlineKeyboardButton(text="📢 TEMPLATES",    callback_data="wl:templates"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️  BACK",        callback_data="menu:back"),
    )
    return builder.as_markup()


def build_back_button() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅️  Back to Menu", callback_data="menu:back")
    )
    return builder.as_markup()
