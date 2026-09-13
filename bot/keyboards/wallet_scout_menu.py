"""
bot/keyboards/wallet_scout_menu.py
====================================
Keyboards for the Wallet Scout module.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.keyboards.share_templates import WALLET_SCOUT_SHARE_URL


def build_wallet_scout_main(is_supreme: bool, is_black: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🧠 DRAGON PRESETS",        callback_data="ws:presets"),
    )
    builder.row(
        InlineKeyboardButton(text="🔍 SCORE A WALLET",        callback_data="ws:score"),
        InlineKeyboardButton(text="🏆 TOP TRADERS PER TOKEN", callback_data="ws:toptraders"),
    )
    builder.row(
        InlineKeyboardButton(text="⏱ EARLY BUYERS",           callback_data="ws:earlybuyers"),
        InlineKeyboardButton(text="💣 BUNDLE DETECTOR",        callback_data="ws:bundle"),
    )
    if is_supreme or is_black:
        builder.row(
            InlineKeyboardButton(
                text="🔁 CROSS-TOKEN WINNERS" + (" 🖤" if is_black else ""),
                callback_data="ws:repeated",
            ),
        )
    builder.row(
        InlineKeyboardButton(text="🌊 GMGN TOKEN FEED",        callback_data="ws:feed"),
    )
    builder.row(
        InlineKeyboardButton(text="🐦  SHARE ON X / TWITTER",   url=WALLET_SCOUT_SHARE_URL),
    )
    builder.row(
        InlineKeyboardButton(text="👑 SUPREME ACCESS",            callback_data="supreme:main"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️  BACK",                  callback_data="menu:back"),
    )
    return builder.as_markup()


def build_presets_main(summaries: dict, user_subs: list[str]) -> InlineKeyboardMarkup:
    from services.wallet_discovery_worker import PRESET_LABELS
    builder = InlineKeyboardBuilder()
    for key, label in PRESET_LABELS.items():
        info   = summaries.get(key) or {}
        count  = info.get("count", 0)
        subbed = "✅ " if key in user_subs else ""
        builder.row(
            InlineKeyboardButton(
                text=f"{subbed}{label.upper()}  ({count} WALLETS)",
                callback_data=f"ws:preset_view:{key}",
            ),
        )
    builder.row(
        InlineKeyboardButton(text="🔄 FORCE REFRESH",   callback_data="ws:preset_run"),
        InlineKeyboardButton(text="⬅️  BACK",           callback_data="ws:main"),
    )
    return builder.as_markup()


def build_preset_detail(
    preset_key: str, wallets: list[dict], is_subscribed: bool
) -> InlineKeyboardMarkup:
    from services.wallet_discovery_worker import PRESET_LABELS
    builder = InlineKeyboardBuilder()
    label = PRESET_LABELS.get(preset_key, preset_key)
    if is_subscribed:
        builder.row(
            InlineKeyboardButton(
                text=f"❌ UNSUBSCRIBE FROM {label.upper()}",
                callback_data=f"ws:preset_unsub:{preset_key}",
            ),
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text=f"✅ SUBSCRIBE TO {label.upper()}",
                callback_data=f"ws:preset_sub:{preset_key}",
            ),
        )
    if wallets:
        builder.row(
            InlineKeyboardButton(
                text="📊 SCORE #1 WALLET",
                callback_data=f"ws:score_addr:{wallets[0]['wallet_address'][:44]}",
            ),
            InlineKeyboardButton(
                text="📋 ADD #1 TO COPY TRADE",
                callback_data=f"ws:add_to_ct:{wallets[0]['wallet_address'][:44]}",
            ),
        )
    builder.row(
        InlineKeyboardButton(text="⬅️  BACK TO PRESETS", callback_data="ws:presets"),
    )
    return builder.as_markup()


def build_back_to_scout() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️  BACK TO SCOUT", callback_data="ws:main"))
    return builder.as_markup()


def build_cancel_scout() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ CANCEL", callback_data="ws:cancel_fsm"))
    return builder.as_markup()


def build_wallet_score_actions(wallet_address: str) -> InlineKeyboardMarkup:
    """Actions after scoring a wallet — quick-add to copy trade."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📋 ADD TO COPY TRADE",
            callback_data=f"ws:add_to_ct:{wallet_address[:44]}",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="🔍 SCORE ANOTHER", callback_data="ws:score"),
        InlineKeyboardButton(text="⬅️  BACK",         callback_data="ws:main"),
    )
    return builder.as_markup()


def build_top_traders_actions(wallets: list[str]) -> InlineKeyboardMarkup:
    """After showing top traders — bulk score or add best to copy trade."""
    builder = InlineKeyboardBuilder()
    if wallets:
        builder.row(
            InlineKeyboardButton(
                text="📊 SCORE TOP WALLET",
                callback_data=f"ws:score_addr:{wallets[0][:44]}",
            ),
        )
        builder.row(
            InlineKeyboardButton(
                text="📋 ADD #1 TO COPY TRADE",
                callback_data=f"ws:add_to_ct:{wallets[0][:44]}",
            ),
        )
    builder.row(
        InlineKeyboardButton(text="🏆 ANOTHER TOKEN", callback_data="ws:toptraders"),
        InlineKeyboardButton(text="⬅️  BACK",         callback_data="ws:main"),
    )
    return builder.as_markup()


def build_feed_category() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🆕 NEW LAUNCHES",   callback_data="ws:feed:new"),
        InlineKeyboardButton(text="📈 COMPLETING",     callback_data="ws:feed:completing"),
    )
    builder.row(
        InlineKeyboardButton(text="🚀 SOARING",        callback_data="ws:feed:soaring"),
        InlineKeyboardButton(text="🎓 BONDED (DEX)",   callback_data="ws:feed:bonded"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️  BACK",          callback_data="ws:main"),
    )
    return builder.as_markup()


def build_repeated_winners_actions(wallets: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if wallets:
        builder.row(
            InlineKeyboardButton(
                text="📊 SCORE #1 WINNER",
                callback_data=f"ws:score_addr:{wallets[0][:44]}",
            ),
            InlineKeyboardButton(
                text="📋 ADD #1 TO COPY TRADE",
                callback_data=f"ws:add_to_ct:{wallets[0][:44]}",
            ),
        )
    builder.row(
        InlineKeyboardButton(text="🔁 RUN AGAIN",    callback_data="ws:repeated"),
        InlineKeyboardButton(text="⬅️  BACK",        callback_data="ws:main"),
    )
    return builder.as_markup()
