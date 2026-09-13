"""
bot/keyboards/supreme_menu.py
==============================
Inline keyboards for the SUPREME Access and burn activation pages.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def build_supreme_black_info() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔥 PATH 1 — BURN",              callback_data="supreme:burn_instructions"),
        InlineKeyboardButton(text="⬛ PATH 2 — PAY SOL",           callback_data="af:signup:start"),
    )
    builder.row(
        InlineKeyboardButton(text="👑 MY SUPREME STATUS",           callback_data="supreme:main"),
        InlineKeyboardButton(text="🧠 ALPHA NETWORK",               callback_data="af:main"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ BACK TO MENU", callback_data="menu:back"),
    )
    return builder.as_markup()


def build_supreme_access(wallet_linked: bool, is_supreme: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if not wallet_linked:
        # No wallet yet — show link button + both pathways explained
        builder.row(
            InlineKeyboardButton(text="🔗 LINK WALLET", callback_data="supreme:link_wallet"),
        )
        if not is_supreme:
            builder.row(
                InlineKeyboardButton(
                    text="⚡ BUY TRIAL ACCESS (0.05 SOL / 12H)",
                    callback_data="sp:main",
                ),
            )
    else:
        # Wallet linked — show BOTH upgrade pathways side by side
        builder.row(
            InlineKeyboardButton(text="🔗 CHANGE WALLET", callback_data="supreme:link_wallet"),
        )
        if not is_supreme:
            # PATH 1: Burn
            builder.row(
                InlineKeyboardButton(
                    text="🔥 PATH 1 — BURN $BRAINROT",
                    callback_data="supreme:burn_instructions",
                ),
            )
            # PATH 2: SOL payment via Alpha Network
            builder.row(
                InlineKeyboardButton(
                    text="⬛ PATH 2 — PAY $100 SOL",
                    callback_data="af:signup:start",
                ),
            )
            builder.row(
                InlineKeyboardButton(
                    text="⚡ BUY TRIAL ACCESS (0.05 SOL / 12H)",
                    callback_data="sp:main",
                ),
            )
        builder.row(
            InlineKeyboardButton(text="📥 SUBMIT BURN TX", callback_data="supreme:submit_tx"),
            InlineKeyboardButton(text="🔄 CHECK STATUS",   callback_data="supreme:check"),
        )

    builder.row(
        InlineKeyboardButton(text="🔱 SUPREME BLACK INFO", callback_data="supreme:black_info"),
        InlineKeyboardButton(text="🧠 ALPHA NETWORK",      callback_data="af:main"),
    )
    builder.row(
        InlineKeyboardButton(text="👤 MY PROFILE", callback_data="profile:main"),
        InlineKeyboardButton(text="🏅 MY BADGES",  callback_data="profile:badges"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ BACK", callback_data="menu:back"),
    )
    return builder.as_markup()


def build_submit_tx_cancel() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ CANCEL", callback_data="supreme:main"),
    )
    return builder.as_markup()


def build_back_to_supreme() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅️ BACK TO SUPREME", callback_data="supreme:main"),
    )
    return builder.as_markup()


def build_activation_result(success: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if success:
        builder.row(
            InlineKeyboardButton(text="🏅 VIEW MY BADGES", callback_data="profile:badges"),
            InlineKeyboardButton(text="👤 MY PROFILE",     callback_data="profile:main"),
        )
    else:
        builder.row(
            InlineKeyboardButton(text="📥 TRY AGAIN",    callback_data="supreme:submit_tx"),
            InlineKeyboardButton(text="🔄 CHECK STATUS", callback_data="supreme:check"),
        )
    builder.row(
        InlineKeyboardButton(text="⬅️ BACK", callback_data="supreme:main"),
    )
    return builder.as_markup()
