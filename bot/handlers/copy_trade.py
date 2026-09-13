"""
bot/handlers/copy_trade.py
===========================
Telegram handlers for the Copy Trading module.

Commands:
  /copytrade                — open main panel
  /copytrade_add            — add a tracked wallet
  /copytrade_remove         — interactive remove
  /copytrade_wallets        — list wallets
  /copytrade_on             — enable
  /copytrade_off            — disable
  /copytrade_settings       — open settings
  /ct_tweet                 — generate tweet recap

Callbacks use prefix: ct:*
"""

import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.keyboards.copy_trade_menu import (
    build_copy_trade_main,
    build_wallets_list,
    build_settings_menu,
    build_blacklist_menu,
    build_whitelist_menu,
    build_cancel,
    build_back_to_ct,
)
from utils.copy_trade_states import CopyTradeStates
from utils.config import settings
from utils.share_utils import bot_link as _bot_link, website_buttons as _website_buttons, share_footer as _share_footer

logger = logging.getLogger(__name__)
router = Router()

# ── Field display names ────────────────────────────────────────────────────────
_FIELD_META = {
    "fixed_amount_sol":    ("Fixed Amount",    "SOL",  float, 0.001, 100.0),
    "percentage_amount":   ("Copy %",          "%",    float, 0.1,   100.0),
    "max_buy_amount_sol":  ("Max Buy Amount",  "SOL",  float, 0.001, 100.0),
    "max_slippage":        ("Slippage",        "%",    float, 0.5,   50.0),
    "min_liquidity_usd":   ("Min Liquidity",   "USD",  float, 0.0,   1_000_000.0),
    "cooldown_seconds":    ("Cooldown",        "sec",  int,   0,     3600),
    "max_trades_per_hour": ("Max Trades/Hour", "/hr",  int,   1,     500),
    "priority_fee":        ("Priority Fee",    "SOL",  float, 0.000001, 0.01),
}


# ── Helper: build main menu text + keyboard ───────────────────────────────────

async def _render_main(user_id: int) -> tuple[str, object]:
    from services.copy_trade_service import (
        get_copy_trade_settings, get_tracked_wallets, get_copy_trade_entitlements,
    )
    s       = await get_copy_trade_settings(user_id)
    wallets = await get_tracked_wallets(user_id)
    ents    = await get_copy_trade_entitlements(user_id)

    active    = sum(1 for w in wallets if w.get("enabled"))
    mode      = s.get("copy_size_mode") or "fixed"
    size_str  = (
        f"{s.get('fixed_amount_sol', 0.05):.4f} SOL"
        if mode == "fixed"
        else f"{s.get('percentage_amount', 10):.1f}% of leader"
    )

    tier = ents.tier
    if tier == "supreme_black":
        tier_label = "🔱 SUPREME BLACK"
        tier_bar   = "▓▓▓▓▓▓▓▓▓▓ MAX TIER"
    elif tier == "supreme":
        tier_label = "👑 SUPREME"
        tier_bar   = "▓▓▓▓▓▓▓░░░ CLEARANCE: HIGH"
    else:
        tier_label = "🆓 FREE"
        tier_bar   = "▓░░░░░░░░░ CLEARANCE: BASIC"

    enabled    = s.get("enabled") and not s.get("kill_switch")
    ks_active  = bool(s.get("kill_switch"))
    power_icon = "🟢 ONLINE" if enabled else "🔴 OFFLINE"
    ks_line    = "│  KILL SW   🔴 ACTIVE — NO TRADES         │\n" if ks_active else ""

    buys_icon  = "✅" if s.get("copy_buys")  else "⬜"
    sells_icon = "✅" if s.get("copy_sells") else "⬜"

    ks_warn = "\n⛔ <b>Kill switch ACTIVE — no trades executing.</b>" if ks_active else ""
    text = (
        f"📋 <b>COPY TRADE</b>\n"
        f"<code>{tier_bar}  {tier_label}</code>\n\n"
        f"<code>{power_icon}   👛 {len(wallets)}/{ents.max_wallets} wallets  ({active} active)</code>\n"
        f"<code>📥 buys {buys_icon}  📤 sells {sells_icon}  {size_str}/trade</code>\n"
        f"<code>📐 {s.get('max_slippage', 15):.1f}% slip   ⏱ {s.get('max_trades_per_hour', 30)}/hr max</code>"
        f"{ks_warn}"
    )

    kb = build_copy_trade_main(s, len(wallets), ents)
    return text, kb


# ── Commands ───────────────────────────────────────────────────────────────────

@router.message(Command("copytrade"))
async def cmd_copytrade(message: Message, state: FSMContext):
    await state.clear()
    text, kb = await _render_main(message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.message(Command("copytrade_on"))
async def cmd_ct_on(message: Message):
    from services.copy_trade_service import update_copy_trade_field
    await update_copy_trade_field(message.from_user.id, "enabled", 1)
    await message.answer("✅ Copy trading <b>enabled</b>.")


@router.message(Command("copytrade_off"))
async def cmd_ct_off(message: Message):
    from services.copy_trade_service import update_copy_trade_field
    await update_copy_trade_field(message.from_user.id, "enabled", 0)
    await message.answer("🔴 Copy trading <b>disabled</b>.")


@router.message(Command("copytrade_add"))
async def cmd_ct_add(message: Message, state: FSMContext):
    await state.set_state(CopyTradeStates.waiting_for_wallet_address)
    await message.answer(
        "📋 <b>Add Tracked Wallet</b>\n\n"
        "Send the Solana wallet address you want to copy trade:",
        reply_markup=build_cancel(),
    )


@router.message(Command("copytrade_remove"))
async def cmd_ct_remove(message: Message):
    from services.copy_trade_service import get_tracked_wallets
    wallets = await get_tracked_wallets(message.from_user.id)
    if not wallets:
        await message.answer("You have no tracked wallets.")
        return
    from services.copy_trade_service import get_copy_trade_entitlements
    ents = await get_copy_trade_entitlements(message.from_user.id)
    kb   = build_wallets_list(wallets, ents)
    await message.answer("Tap 🗑 next to a wallet to remove it:", reply_markup=kb)


@router.message(Command("copytrade_wallets"))
async def cmd_ct_wallets(message: Message):
    from services.copy_trade_service import get_tracked_wallets, get_copy_trade_entitlements
    wallets = await get_tracked_wallets(message.from_user.id)
    ents    = await get_copy_trade_entitlements(message.from_user.id)
    if not wallets:
        await message.answer(
            "No wallets tracked yet. Use /copytrade_add to add one.",
            reply_markup=build_back_to_ct(),
        )
        return
    kb = build_wallets_list(wallets, ents)
    await message.answer(
        f"👛 <b>Tracked Wallets</b> ({len(wallets)}/{ents.max_wallets})\n"
        f"Tap an address to toggle, 🗑 to remove.",
        reply_markup=kb,
    )


@router.message(Command("copytrade_settings"))
async def cmd_ct_settings(message: Message):
    from services.copy_trade_service import get_copy_trade_settings, get_copy_trade_entitlements
    s    = await get_copy_trade_settings(message.from_user.id)
    ents = await get_copy_trade_entitlements(message.from_user.id)
    kb   = build_settings_menu(s, ents)
    await message.answer("⚙️ <b>Copy Trade Settings</b>", reply_markup=kb)


# ── Callbacks: Main Panel ─────────────────────────────────────────────────────

@router.callback_query(F.data == "ct:main")
async def cb_ct_main(call: CallbackQuery, state: FSMContext):
    import asyncio
    from aiogram.exceptions import TelegramBadRequest as _TBR
    await state.clear()
    try:
        boot = await call.message.edit_text(
            "<code>█░░░░░░░░░ COPY TRADE TERMINAL BOOT...</code>", parse_mode="HTML"
        )
        await asyncio.sleep(0.38)
        await boot.edit_text(
            "<code>████░░░░░░ LOADING POSITIONS...</code>", parse_mode="HTML"
        )
        await asyncio.sleep(0.38)
        await boot.edit_text(
            "<code>██████████ SYSTEMS ONLINE ⚡</code>", parse_mode="HTML"
        )
        await asyncio.sleep(0.28)
    except _TBR:
        pass
    text, kb = await _render_main(call.from_user.id)
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "ct:toggle")
async def cb_ct_toggle(call: CallbackQuery):
    from services.copy_trade_service import toggle_copy_trade
    new_state = await toggle_copy_trade(call.from_user.id)
    text, kb  = await _render_main(call.from_user.id)
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer("✅ Enabled" if new_state else "🔴 Disabled")


@router.callback_query(F.data == "ct:kill")
async def cb_ct_kill(call: CallbackQuery):
    from services.copy_trade_service import toggle_kill_switch
    new_state = await toggle_kill_switch(call.from_user.id)
    text, kb  = await _render_main(call.from_user.id)
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer("🔴 Kill switch ACTIVE" if new_state else "✅ Kill switch off")


# ── Callbacks: Wallets ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "ct:wallets")
async def cb_ct_wallets(call: CallbackQuery):
    from services.copy_trade_service import get_tracked_wallets, get_copy_trade_entitlements
    user_id = call.from_user.id
    wallets = await get_tracked_wallets(user_id)
    ents    = await get_copy_trade_entitlements(user_id)
    kb      = build_wallets_list(wallets, ents)
    count   = len(wallets)
    await call.message.edit_text(
        f"👛 <b>Tracked Wallets</b> ({count}/{ents.max_wallets})\n\n"
        f"Tap address row to pause/resume. Tap 🗑 to remove.",
        reply_markup=kb,
    )
    await call.answer()


@router.callback_query(F.data == "ct:wallet_add")
async def cb_ct_wallet_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(CopyTradeStates.waiting_for_wallet_address)
    await call.message.edit_text(
        "📋 <b>Add Tracked Wallet</b>\n\n"
        "Send the Solana wallet address to copy trade.\n"
        "<i>Example: 9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin</i>",
        reply_markup=build_cancel(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("ct:wallet_toggle:"))
async def cb_ct_wallet_toggle(call: CallbackQuery):
    from services.copy_trade_service import (
        toggle_tracked_wallet, get_tracked_wallets, get_copy_trade_entitlements
    )
    wallet_id = int(call.data.split(":")[2])
    new_state = await toggle_tracked_wallet(call.from_user.id, wallet_id)
    if new_state is None:
        await call.answer("Wallet not found.", show_alert=True)
        return
    wallets = await get_tracked_wallets(call.from_user.id)
    ents    = await get_copy_trade_entitlements(call.from_user.id)
    kb      = build_wallets_list(wallets, ents)
    await call.message.edit_reply_markup(reply_markup=kb)
    await call.answer("🟢 Enabled" if new_state else "⏸ Paused")


@router.callback_query(F.data.startswith("ct:wallet_rm:"))
async def cb_ct_wallet_rm(call: CallbackQuery):
    from services.copy_trade_service import (
        remove_tracked_wallet, get_tracked_wallets, get_copy_trade_entitlements
    )
    wallet_id = int(call.data.split(":")[2])
    removed   = await remove_tracked_wallet(call.from_user.id, wallet_id)
    if not removed:
        await call.answer("Wallet not found.", show_alert=True)
        return
    wallets = await get_tracked_wallets(call.from_user.id)
    ents    = await get_copy_trade_entitlements(call.from_user.id)
    kb      = build_wallets_list(wallets, ents)
    await call.message.edit_text(
        f"👛 <b>Tracked Wallets</b> ({len(wallets)}/{ents.max_wallets})\n\n"
        f"Wallet removed.",
        reply_markup=kb,
    )
    await call.answer("🗑 Removed")


# ── FSM: Add Wallet ────────────────────────────────────────────────────────────

@router.message(CopyTradeStates.waiting_for_wallet_address)
async def fsm_wallet_address(message: Message, state: FSMContext):
    address = message.text.strip() if message.text else ""
    from services.copy_trade_service import add_tracked_wallet
    # Quick format validation before asking for label
    import re
    if not re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$', address):
        await message.answer(
            "❌ Invalid Solana address. Please send a valid base58 wallet address.",
            reply_markup=build_cancel(),
        )
        return

    await state.update_data(wallet_address=address)
    await state.set_state(CopyTradeStates.waiting_for_wallet_label)
    await message.answer(
        f"✅ Address: <code>{address}</code>\n\n"
        f"Send a label/nickname for this wallet (or skip with a dash <code>-</code>):",
        reply_markup=build_cancel(),
    )


@router.message(CopyTradeStates.waiting_for_wallet_label)
async def fsm_wallet_label(message: Message, state: FSMContext):
    label = message.text.strip() if message.text else ""
    if label == "-":
        label = ""
    data    = await state.get_data()
    address = data.get("wallet_address", "")
    await state.clear()

    from services.copy_trade_service import add_tracked_wallet
    ok, err = await add_tracked_wallet(message.from_user.id, address, label)

    if ok:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="⬅️  Done — Back to Copy Trade", callback_data="ct:main"))
        await state.set_state(CopyTradeStates.waiting_for_wallet_address)
        await message.answer(
            f"✅ <b>Wallet added!</b>\n"
            f"<code>{address[:6]}...{address[-4:]}</code>  —  {label or '(no label)'}\n\n"
            f"Send the next wallet address to add another,\n"
            f"or tap Done when finished.",
            reply_markup=kb.as_markup(),
        )
    else:
        await message.answer(
            f"❌ <b>Failed to add wallet</b>\n{err}",
            reply_markup=build_back_to_ct(),
        )


# ── Callbacks: Settings ────────────────────────────────────────────────────────

@router.callback_query(F.data == "ct:settings")
async def cb_ct_settings(call: CallbackQuery):
    from services.copy_trade_service import get_copy_trade_settings, get_copy_trade_entitlements
    s    = await get_copy_trade_settings(call.from_user.id)
    ents = await get_copy_trade_entitlements(call.from_user.id)
    kb   = build_settings_menu(s, ents)
    await call.message.edit_text("⚙️ <b>Copy Trade Settings</b>", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "ct:toggle_buys")
async def cb_toggle_buys(call: CallbackQuery):
    from services.copy_trade_service import get_copy_trade_settings, update_copy_trade_field, get_copy_trade_entitlements
    s = await get_copy_trade_settings(call.from_user.id)
    await update_copy_trade_field(call.from_user.id, "copy_buys", 0 if s.get("copy_buys") else 1)
    s    = await get_copy_trade_settings(call.from_user.id)
    ents = await get_copy_trade_entitlements(call.from_user.id)
    await call.message.edit_reply_markup(reply_markup=build_settings_menu(s, ents))
    await call.answer()


@router.callback_query(F.data == "ct:toggle_sells")
async def cb_toggle_sells(call: CallbackQuery):
    from services.copy_trade_service import (
        get_copy_trade_settings, update_copy_trade_field, get_copy_trade_entitlements
    )
    ents = await get_copy_trade_entitlements(call.from_user.id)
    if not ents.can_copy_sells:
        await call.answer("🔒 Copy sells requires SUPREME or higher.", show_alert=True)
        return
    s = await get_copy_trade_settings(call.from_user.id)
    await update_copy_trade_field(call.from_user.id, "copy_sells", 0 if s.get("copy_sells") else 1)
    s = await get_copy_trade_settings(call.from_user.id)
    await call.message.edit_reply_markup(reply_markup=build_settings_menu(s, ents))
    await call.answer()


@router.callback_query(F.data.startswith("ct:mode:"))
async def cb_ct_mode(call: CallbackQuery):
    from services.copy_trade_service import (
        update_copy_trade_field, get_copy_trade_settings, get_copy_trade_entitlements
    )
    mode = call.data.split(":")[2]
    ents = await get_copy_trade_entitlements(call.from_user.id)
    if mode == "percentage" and not ents.can_use_percentage:
        await call.answer("🔒 Percentage sizing requires SUPREME or higher.", show_alert=True)
        return
    await update_copy_trade_field(call.from_user.id, "copy_size_mode", mode)
    s = await get_copy_trade_settings(call.from_user.id)
    await call.message.edit_reply_markup(reply_markup=build_settings_menu(s, ents))
    await call.answer(f"Mode set to {mode}")


@router.callback_query(F.data.startswith("ct:set:"))
async def cb_ct_set_field(call: CallbackQuery, state: FSMContext):
    field = call.data.split(":")[2]
    if field not in _FIELD_META:
        await call.answer("Unknown field.", show_alert=True)
        return

    name, unit, typ, mn, mx = _FIELD_META[field]
    await state.set_state(CopyTradeStates.waiting_for_field_value)
    await state.update_data(field=field, field_type=typ.__name__, min_val=mn, max_val=mx)

    from services.copy_trade_service import get_copy_trade_settings
    s = await get_copy_trade_settings(call.from_user.id)
    current = s.get(field, "—")

    await call.message.edit_text(
        f"⚙️ <b>Set {name}</b>\n\n"
        f"Current: <b>{current} {unit}</b>\n"
        f"Range: {mn} – {mx} {unit}\n\n"
        f"Send a new value:",
        reply_markup=build_cancel(),
    )
    await call.answer()


@router.message(CopyTradeStates.waiting_for_field_value)
async def fsm_field_value(message: Message, state: FSMContext):
    data  = await state.get_data()
    field = data.get("field", "")
    typ   = float if data.get("field_type") == "float" else int
    mn    = data.get("min_val", 0)
    mx    = data.get("max_val", 9999)

    try:
        value = typ(message.text.strip())
    except (ValueError, TypeError):
        name, unit = _FIELD_META[field][0], _FIELD_META[field][1]
        await message.answer(
            f"❌ Invalid value — send a single number.\n"
            f"Range: <b>{mn} – {mx} {unit}</b>",
            reply_markup=build_cancel(),
        )
        return

    if not (mn <= value <= mx):
        name, unit = _FIELD_META[field][0], _FIELD_META[field][1]
        await message.answer(
            f"❌ Out of range. Must be between <b>{mn}</b> and <b>{mx} {unit}</b>.",
            reply_markup=build_cancel(),
        )
        return

    await state.clear()
    from services.copy_trade_service import update_copy_trade_field, get_copy_trade_settings, get_copy_trade_entitlements
    await update_copy_trade_field(message.from_user.id, field, value)
    s    = await get_copy_trade_settings(message.from_user.id)
    ents = await get_copy_trade_entitlements(message.from_user.id)
    name = _FIELD_META[field][0]
    unit = _FIELD_META[field][1]
    await message.answer(
        f"✅ <b>{name}</b> set to <b>{value} {unit}</b>",
        reply_markup=build_settings_menu(s, ents),
    )


# ── Callbacks: Blacklist ───────────────────────────────────────────────────────

@router.callback_query(F.data == "ct:blacklist")
async def cb_ct_blacklist(call: CallbackQuery):
    from services.copy_trade_service import get_token_blacklist, get_copy_trade_entitlements
    ents = await get_copy_trade_entitlements(call.from_user.id)
    if not ents.can_use_blacklist:
        await call.answer("🔒 Token blacklist requires SUPREME or higher.", show_alert=True)
        return
    entries = await get_token_blacklist(call.from_user.id)
    kb = build_blacklist_menu(entries)
    await call.message.edit_text(
        f"🚫 <b>Token Blacklist</b> ({len(entries)}/{ents.blacklist_limit})\n\n"
        f"Tokens here will never be copy traded.",
        reply_markup=kb,
    )
    await call.answer()


@router.callback_query(F.data == "ct:bl_add")
async def cb_ct_bl_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(CopyTradeStates.waiting_for_bl_token)
    await call.message.edit_text(
        "🚫 <b>Blacklist Token</b>\n\nSend the token mint address to blacklist:",
        reply_markup=build_cancel(),
    )
    await call.answer()


@router.message(CopyTradeStates.waiting_for_bl_token)
async def fsm_bl_token(message: Message, state: FSMContext):
    await state.clear()
    from services.copy_trade_service import add_to_token_blacklist, get_token_blacklist, get_copy_trade_entitlements
    ok, err = await add_to_token_blacklist(message.from_user.id, message.text.strip() if message.text else "")
    if ok:
        entries = await get_token_blacklist(message.from_user.id)
        await message.answer(
            f"✅ Token blacklisted.",
            reply_markup=build_blacklist_menu(entries),
        )
    else:
        await message.answer(f"❌ {err}", reply_markup=build_back_to_ct())


@router.callback_query(F.data.startswith("ct:bl_rm:"))
async def cb_ct_bl_rm(call: CallbackQuery):
    from services.copy_trade_service import (
        remove_from_token_blacklist, get_token_blacklist, get_copy_trade_entitlements
    )
    entry_id = int(call.data.split(":")[2])
    await remove_from_token_blacklist(call.from_user.id, entry_id)
    entries = await get_token_blacklist(call.from_user.id)
    ents    = await get_copy_trade_entitlements(call.from_user.id)
    await call.message.edit_text(
        f"🚫 <b>Token Blacklist</b> ({len(entries)}/{ents.blacklist_limit})",
        reply_markup=build_blacklist_menu(entries),
    )
    await call.answer("🗑 Removed")


# ── Callbacks: Whitelist ───────────────────────────────────────────────────────

@router.callback_query(F.data == "ct:whitelist")
async def cb_ct_whitelist(call: CallbackQuery):
    from services.copy_trade_service import get_token_whitelist, get_copy_trade_entitlements
    ents = await get_copy_trade_entitlements(call.from_user.id)
    if not ents.can_use_whitelist:
        await call.answer("🔒 Whitelist requires SUPREME BLACK.", show_alert=True)
        return
    entries = await get_token_whitelist(call.from_user.id)
    await call.message.edit_text(
        f"✅ <b>Token Whitelist</b> ({len(entries)} tokens)\n\n"
        f"When non-empty, only whitelisted tokens will be copy traded.",
        reply_markup=build_whitelist_menu(entries),
    )
    await call.answer()


@router.callback_query(F.data == "ct:wl_add")
async def cb_ct_wl_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(CopyTradeStates.waiting_for_wl_token)
    await call.message.edit_text(
        "✅ <b>Whitelist Token</b>\n\nSend the token mint address to whitelist:",
        reply_markup=build_cancel(),
    )
    await call.answer()


@router.message(CopyTradeStates.waiting_for_wl_token)
async def fsm_wl_token(message: Message, state: FSMContext):
    await state.clear()
    from services.copy_trade_service import add_to_token_whitelist, get_token_whitelist
    ok, err = await add_to_token_whitelist(message.from_user.id, message.text.strip() if message.text else "")
    if ok:
        entries = await get_token_whitelist(message.from_user.id)
        await message.answer("✅ Token whitelisted.", reply_markup=build_whitelist_menu(entries))
    else:
        await message.answer(f"❌ {err}", reply_markup=build_back_to_ct())


@router.callback_query(F.data.startswith("ct:wl_rm:"))
async def cb_ct_wl_rm(call: CallbackQuery):
    from services.copy_trade_service import remove_from_token_whitelist, get_token_whitelist
    entry_id = int(call.data.split(":")[2])
    await remove_from_token_whitelist(call.from_user.id, entry_id)
    entries = await get_token_whitelist(call.from_user.id)
    await call.message.edit_text(
        f"✅ <b>Token Whitelist</b> ({len(entries)} tokens)",
        reply_markup=build_whitelist_menu(entries),
    )
    await call.answer("🗑 Removed")


# ── Status Panel ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "ct:status")
async def cb_ct_status(call: CallbackQuery):
    from services.copy_trade_worker import get_stats
    from services.copy_trade_service import get_copy_trade_jobs
    import time as _time

    stats = get_stats()
    jobs  = await get_copy_trade_jobs(call.from_user.id, limit=5)

    scan_age = "—"
    if stats.get("last_scan_ts"):
        age = int(_time.time() - stats["last_scan_ts"])
        scan_age = f"{age}s ago"

    last_trade = "—"
    if stats.get("last_trade_ts"):
        age = int(_time.time() - stats["last_trade_ts"])
        last_trade = f"{age}s ago  ({stats.get('last_trade_symbol', '')})"

    recent_text = ""
    for j in jobs:
        status_icon = {"executed": "✅", "failed": "❌", "skipped": "⏭", "queued": "⏳"}.get(
            j.get("status"), "?"
        )
        token = j.get("token_address") or "?"
        tx    = j.get("tx_signature") or ""
        token_link = f'<a href="https://solscan.io/token/{token}">{token[:8]}...{token[-4:]}</a>'
        tx_link    = (f' · <a href="https://solscan.io/tx/{tx}">TX</a>' if tx else "")
        recent_text += (
            f"  {status_icon} {j.get('direction', '?').upper()} "
            f"{token_link} "
            f"{j.get('copy_amount_sol', 0):.4f} SOL{tx_link}\n"
        )

    text = (
        f"📊 <b>Copy Trade Live Status</b>\n"
        f"{'━' * 30}\n\n"
        f"<b>Last scan:</b> {scan_age}\n"
        f"<b>Wallets monitored:</b> {stats.get('wallets_monitored', 0)}\n"
        f"<b>Scans completed:</b> {stats.get('scans_completed', 0)}\n"
        f"<b>Swaps detected:</b>  {stats.get('swaps_detected', 0)}\n\n"
        f"<b>✅ Trades executed:</b>  {stats.get('trades_executed', 0)}\n"
        f"<b>⏭ Trades skipped:</b>   {stats.get('trades_skipped', 0)}\n"
        f"<b>❌ Trades failed:</b>    {stats.get('trades_failed', 0)}\n"
        f"<b>🕐 Last trade:</b>       {last_trade}\n"
    )
    if recent_text:
        text += f"\n<b>Recent jobs:</b>\n{recent_text}"

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔄 Refresh",  callback_data="ct:status"))
    builder.row(InlineKeyboardButton(text="📣 Share Results", callback_data="ct:share"))
    builder.row(InlineKeyboardButton(text="⬅️  Back",    callback_data="ct:main"))
    await call.message.edit_text(text, reply_markup=builder.as_markup(), disable_web_page_preview=True)
    await call.answer()


# ── Share Results ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ct:share"))
async def cb_ct_share(call: CallbackQuery):
    from services.copy_trade_service import generate_copy_trade_tweet
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    from urllib.parse import quote

    parts = call.data.split(":")
    try:
        period_hours = int(parts[2])
    except (IndexError, ValueError):
        period_hours = 24

    period_label = "24h" if period_hours == 24 else ("72h" if period_hours == 72 else "7d")
    bot_link     = _bot_link()

    tweet = await generate_copy_trade_tweet(call.from_user.id, period_hours)

    tg_post = (
        f"📋 $BRAINROT Alpha Bot — Copy Trade Recap ({period_label})\n\n"
        f"{tweet}\n\n"
        f"👇 Try it yourself:\n{bot_link}"
    )

    tiktok_ig = (
        f"📋 Copy trading on Solana with $BRAINROT Alpha Bot\n\n"
        f"{tweet}\n\n"
        f"#Solana #CopyTrading #BRAINROT #Crypto #DeFi #Memecoin #SolanaTrading {settings.SHARE_HASHTAG}"
    )

    x_url  = f"https://x.com/intent/tweet?text={quote(tweet)}"
    tg_url = f"https://t.me/share/url?url={quote(bot_link)}&text={quote(tg_post)}"
    reddit_url = (
        f"https://www.reddit.com/submit"
        f"?title={quote(f'$BRAINROT Copy Trade Recap ({period_label})')}"
        f"&text={quote(tweet)}"
    )

    _BRAINROT_CA   = settings.BRAINROT_MINT
    _INCINERATOR   = "1nc1nerator11111111111111111111111111111111"

    # Tracked wallets as individual tap-to-copy lines
    from services.copy_trade_service import get_tracked_wallets
    wallets = await get_tracked_wallets(call.from_user.id)
    wallet_lines = ""
    for w in wallets:
        addr  = w.get("wallet_address", "")
        label = w.get("label") or ""
        tag   = f"  <i>{label}</i>" if label else ""
        wallet_lines += f"{tag}\n<pre>{addr}</pre>\n" if tag else f"<pre>{addr}</pre>\n"

    text = (
        f"📣 <b>Share Your Copy Trade Results — {period_label}</b>\n"
        f"{'━' * 30}\n\n"
        + (f"<b>Tracked wallets:</b>\n{wallet_lines}\n" if wallet_lines else "")
        + f"<b>$BRAINROT CA:</b>\n"
        f"<pre>{_BRAINROT_CA}</pre>\n"
        f"<b>Burn address:</b>\n"
        f"<pre>{_INCINERATOR}</pre>\n\n"
        f"<b>Post content (tap to copy):</b>\n"
        f"{'─' * 30}\n\n"
        f"<code>{tweet}</code>\n\n"
        f"{'─' * 30}\n\n"
        f"<b>TikTok / Instagram caption:</b>\n"
        f"<code>{tiktok_ig}</code>\n\n"
        f"{'─' * 30}\n"
        f"🔗 Follow <a href=\"{settings.TWITTER_URL}\">{settings.BRAND_HANDLE}</a> on X\n"
        f"<i>Timeframe:</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="𝕏  Post to X",        url=x_url),
        InlineKeyboardButton(text="✈️ Share on Telegram", url=tg_url),
    )
    builder.row(
        InlineKeyboardButton(text="🔴 Share on Reddit",  url=reddit_url),
        *_website_buttons(),
    )
    builder.row(
        InlineKeyboardButton(text="24h", callback_data="ct:share:24"),
        InlineKeyboardButton(text="72h", callback_data="ct:share:72"),
        InlineKeyboardButton(text="7d",  callback_data="ct:share:168"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="ct:status"))
    await call.message.edit_text(text, reply_markup=builder.as_markup(), disable_web_page_preview=True)
    await call.answer()


# ── Trade History ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "ct:history")
async def cb_ct_history(call: CallbackQuery):
    from services.copy_trade_service import get_copy_trade_jobs
    jobs = await get_copy_trade_jobs(call.from_user.id, limit=15)

    if not jobs:
        text = "📋 <b>Trade History</b>\n\nNo copy trades executed yet."
    else:
        text = "📋 <b>Trade History</b> (last 15)\n\n"
        for j in jobs:
            status_icon = {"executed": "✅", "failed": "❌", "skipped": "⏭", "queued": "⏳"}.get(
                j.get("status"), "?"
            )
            dir_icon   = "🟢" if j.get("direction") == "buy" else "🔴"
            token      = j.get("token_address") or ""
            wallet     = j.get("followed_wallet") or ""
            tx         = j.get("tx_signature") or ""
            size       = j.get("copy_amount_sol") or 0
            reason     = j.get("skip_reason") or ""
            token_link  = f'<a href="https://solscan.io/token/{token}">{token[:8]}...{token[-4:]}</a>' if token else "?"
            wallet_link = f'<a href="https://solscan.io/account/{wallet}">{wallet[:6]}...{wallet[-4:]}</a>' if wallet else "?"
            tx_link     = f' <a href="https://solscan.io/tx/{tx}">↗</a>' if tx else ""
            text += (
                f"{status_icon} {dir_icon} {token_link}  "
                f"{size:.4f} SOL  {wallet_link}{tx_link}\n"
            )
            if reason:
                text += f"   ↳ {reason}\n"

    await call.message.edit_text(text, reply_markup=build_back_to_ct())
    await call.answer()


# ── Tweet Recap ───────────────────────────────────────────────────────────────

@router.message(Command("ct_tweet"))
async def cmd_ct_tweet(message: Message):
    await _send_tweet_recap(message.from_user.id, message)


@router.callback_query(F.data == "ct:tweet")
async def cb_ct_tweet(call: CallbackQuery):
    await call.answer()
    await _send_tweet_recap(call.from_user.id, call.message, edit=False)


@router.callback_query(F.data.startswith("ct:tweet:"))
async def cb_ct_tweet_period(call: CallbackQuery):
    """Handle period selector: ct:tweet:24 / ct:tweet:72 / ct:tweet:168"""
    try:
        hours = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        hours = 24
    await call.answer()
    await _send_tweet_recap(call.from_user.id, call.message, edit=False, period_hours=hours)


async def _send_tweet_recap(user_id: int, message, edit: bool = False, period_hours: int = 24):
    from services.copy_trade_service import generate_copy_trade_tweet
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    tweet = await generate_copy_trade_tweet(user_id, period_hours)

    # Period selector buttons
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="24h",  callback_data="ct:tweet:24"),
        InlineKeyboardButton(text="72h",  callback_data="ct:tweet:72"),
        InlineKeyboardButton(text="7d",   callback_data="ct:tweet:168"),
    )
    builder.row(InlineKeyboardButton(text="⬅️  Back", callback_data="ct:main"))
    kb = builder.as_markup()

    period_label = (
        "24h" if period_hours == 24
        else "72h" if period_hours == 72
        else "7d"
    )

    header = (
        f"🐦 <b>Tweet Recap — {period_label}</b>\n\n"
        f"Copy the text below and paste it into X/Twitter:\n"
        f"{'─' * 30}\n\n"
        f"<code>{tweet}</code>\n\n"
        f"{'─' * 30}\n"
        f"<i>Tap a period above to change the timeframe.</i>"
    )

    if edit:
        await message.edit_text(header, reply_markup=kb)
    else:
        await message.answer(header, reply_markup=kb)


# ── Noop guards (locked features) ─────────────────────────────────────────────

@router.callback_query(F.data.in_({"ct:noop_sells", "ct:noop_pct"}))
async def cb_noop(call: CallbackQuery):
    msgs = {
        "ct:noop_sells": "🔒 Copy sells requires SUPREME or higher.",
        "ct:noop_pct":   "🔒 Percentage sizing requires SUPREME or higher.",
    }
    await call.answer(msgs.get(call.data, "🔒 Requires upgrade."), show_alert=True)


# ── FSM cancel ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "ct:cancel_fsm")
async def cb_cancel_fsm(call: CallbackQuery, state: FSMContext):
    await state.clear()
    text, kb = await _render_main(call.from_user.id)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer("Cancelled")
