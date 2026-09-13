"""
bot/keyboards/copy_trade_menu.py
=================================
All inline keyboards for the Copy Trading module.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.keyboards.share_templates import COPY_TRADE_SHARE_URL


def build_copy_trade_main(s: dict, wallet_count: int, ents) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    enabled_icon  = "🟢 ON"     if s.get("enabled")      else "🔴 OFF"
    kill_icon     = "🔴 ACTIVE" if s.get("kill_switch")  else "⬜ OFF"

    builder.row(
        InlineKeyboardButton(text=f"POWER: {enabled_icon}",        callback_data="ct:toggle"),
        InlineKeyboardButton(text=f"KILL SWITCH: {kill_icon}",     callback_data="ct:kill"),
    )
    builder.row(
        InlineKeyboardButton(
            text=f"👛 TRACKED WALLETS ({wallet_count}/{ents.max_wallets})",
            callback_data="ct:wallets",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="⚙️  SETTINGS",          callback_data="ct:settings"),
        InlineKeyboardButton(text="📊  LIVE STATUS",        callback_data="ct:status"),
    )
    builder.row(
        InlineKeyboardButton(text="📋  TRADE HISTORY",      callback_data="ct:history"),
        InlineKeyboardButton(text="🐦  SHARE ON X",         url=COPY_TRADE_SHARE_URL),
    )

    if ents.can_use_blacklist or ents.can_use_whitelist:
        row = []
        if ents.can_use_blacklist:
            row.append(InlineKeyboardButton(text="🚫 BLACKLIST", callback_data="ct:blacklist"))
        if ents.can_use_whitelist:
            row.append(InlineKeyboardButton(text="✅ WHITELIST", callback_data="ct:whitelist"))
        builder.row(*row)

    builder.row(
        InlineKeyboardButton(text="👑 SUPREME ACCESS",        callback_data="supreme:main"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️  BACK",              callback_data="menu:back"),
    )
    return builder.as_markup()


def build_wallets_list(wallets: list[dict], ents) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for w in wallets[:20]:
        addr    = w["wallet_address"]
        short   = addr[:6] + "..." + addr[-4:]
        label   = w.get("label") or ""
        display = f"{short} ({label})" if label else short
        icon    = "🟢" if w.get("enabled") else "⏸"
        builder.row(
            InlineKeyboardButton(
                text=f"{icon} {display}",
                callback_data=f"ct:wallet_toggle:{w['id']}",
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=f"ct:wallet_rm:{w['id']}",
            ),
        )

    builder.row(
        InlineKeyboardButton(text="➕ ADD WALLET", callback_data="ct:wallet_add"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️  BACK", callback_data="ct:main"),
    )
    return builder.as_markup()


def build_settings_menu(s: dict, ents) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    buys_icon  = "✅" if s.get("copy_buys")  else "⬜"
    sells_icon = "✅" if s.get("copy_sells") else "⬜"
    builder.row(
        InlineKeyboardButton(text=f"{buys_icon} COPY BUYS",  callback_data="ct:toggle_buys"),
        InlineKeyboardButton(
            text=f"{sells_icon} COPY SELLS",
            callback_data="ct:toggle_sells" if ents.can_copy_sells else "ct:noop_sells",
        ),
    )

    mode   = s.get("copy_size_mode") or "fixed"
    f_icon = "✅" if mode == "fixed"      else "⬜"
    p_icon = "✅" if mode == "percentage" else "⬜"
    builder.row(
        InlineKeyboardButton(text=f"{f_icon} FIXED SIZE",  callback_data="ct:mode:fixed"),
        InlineKeyboardButton(
            text=f"{p_icon} % SIZE",
            callback_data="ct:mode:percentage" if ents.can_use_percentage else "ct:noop_pct",
        ),
    )

    if mode == "fixed":
        builder.row(
            InlineKeyboardButton(
                text=f"💰 FIXED AMOUNT: {s.get('fixed_amount_sol', 0.05):.4f} SOL",
                callback_data="ct:set:fixed_amount_sol",
            ),
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text=f"📐 COPY %: {s.get('percentage_amount', 10):.1f}%",
                callback_data="ct:set:percentage_amount",
            ),
        )

    if ents.can_use_max_buy_prot:
        builder.row(
            InlineKeyboardButton(
                text=f"🛑 MAX BUY: {s.get('max_buy_amount_sol', 0.5):.4f} SOL",
                callback_data="ct:set:max_buy_amount_sol",
            ),
        )

    builder.row(
        InlineKeyboardButton(
            text=f"📐 SLIPPAGE: {s.get('max_slippage', 15):.1f}%",
            callback_data="ct:set:max_slippage",
        ),
        InlineKeyboardButton(
            text="⚡ PRIORITY FEE",
            callback_data="ct:set:priority_fee",
        ),
    )

    if ents.can_use_liq_filter:
        builder.row(
            InlineKeyboardButton(
                text=f"💧 MIN LIQUIDITY: ${s.get('min_liquidity_usd', 0):.0f}",
                callback_data="ct:set:min_liquidity_usd",
            ),
        )

    if ents.can_use_cooldown:
        builder.row(
            InlineKeyboardButton(
                text=f"⏳ COOLDOWN: {s.get('cooldown_seconds', 30)}S",
                callback_data="ct:set:cooldown_seconds",
            ),
            InlineKeyboardButton(
                text=f"⏱ MAX/HOUR: {s.get('max_trades_per_hour', 30)}",
                callback_data="ct:set:max_trades_per_hour",
            ),
        )

    builder.row(
        InlineKeyboardButton(text="⬅️  BACK", callback_data="ct:main"),
    )
    return builder.as_markup()


def build_blacklist_menu(entries: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for e in entries[:20]:
        addr  = e["token_address"]
        short = addr[:6] + "..." + addr[-4:]
        builder.row(
            InlineKeyboardButton(
                text=f"🗑 {short}",
                callback_data=f"ct:bl_rm:{e['id']}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="➕ ADD TOKEN", callback_data="ct:bl_add"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️  BACK", callback_data="ct:main"),
    )
    return builder.as_markup()


def build_whitelist_menu(entries: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for e in entries[:20]:
        addr  = e["token_address"]
        short = addr[:6] + "..." + addr[-4:]
        builder.row(
            InlineKeyboardButton(
                text=f"✅ {short}",
                callback_data=f"ct:wl_rm:{e['id']}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="➕ ADD TOKEN", callback_data="ct:wl_add"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️  BACK", callback_data="ct:main"),
    )
    return builder.as_markup()


def build_cancel() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ CANCEL", callback_data="ct:cancel_fsm"))
    return builder.as_markup()


def build_back_to_ct() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️  BACK TO COPY TRADE", callback_data="ct:main"))
    return builder.as_markup()
