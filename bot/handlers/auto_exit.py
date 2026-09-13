"""
bot/handlers/auto_exit.py
==========================
Supreme Black Auto-Exit Manager — Telegram handler.

Sections:
  A. Main menu
  B. System preset viewer (blurred for non-Black users)
  C. User preset manager (clone / apply / delete)
  D. Active position viewer + per-position controls
  E. Settings (slippage, priority fee, notifications)
  F. FSM flows (clone name input, settings edits)
  G. Manual sell
  H. Upgrade CTA
"""

import asyncio
import logging

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.keyboards.auto_exit_menu import (
    build_auto_exit_main,
    build_sys_presets,
    build_preset_view,
    build_user_presets,
    build_ae_positions,
    build_pos_detail,
    build_ae_settings,
    build_ae_cancel,
    build_back_to_ae,
    BLUR,
)

logger = logging.getLogger(__name__)
router = Router()


# ── FSM States ─────────────────────────────────────────────────────────────────

class AEState(StatesGroup):
    clone_name  = State()   # waiting for user to name a cloned preset
    edit_field  = State()   # waiting for a settings value


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _is_black(user_id: int) -> bool:
    from services.brainrot_token_gate import is_supreme_black
    return await is_supreme_black(user_id)


def _bar(pct: float, width: int = 12) -> str:
    """ASCII progress bar — pct is 0-100."""
    filled = int(round(pct / 100 * width))
    filled = max(0, min(width, filled))
    return "▓" * filled + "░" * (width - filled)


def _fmt_preset(p: dict, is_black: bool) -> str:
    """Format a preset for display — terminal/hacker style. Blur values if not Supreme Black."""
    def v(val, fmt=".0f"):
        if val is None:
            return "—"
        return f"{val:{fmt}}" if is_black else BLUR

    name = p["name"]
    desc = p.get("description") or ""
    lines = [
        f"╔{'═' * 30}╗",
        f"║  {name:<28}║",
        f"╚{'═' * 30}╝",
    ]
    if desc:
        lines.append(f"\n<i>{desc}</i>")
    lines.append("")

    # Take-profit ladder
    tp_rows = []
    for n in (1, 2, 3):
        pct  = p.get(f"tp{n}_pct")
        sell = p.get(f"tp{n}_sell_pct")
        if pct is not None:
            tp_rows.append(f"  TP{n}  +{v(pct):>6}%  →  SELL {v(sell):>4}%")
    if tp_rows:
        lines.append("<code>TAKE-PROFIT LADDER\n" + "\n".join(tp_rows) + "</code>")

    rows = []
    if p.get("sl_pct") is not None:
        rows.append(f"  STOP-LOSS       {v(p['sl_pct']):>8}%")
    if p.get("trailing_stop_pct") is not None:
        tat = p.get("trailing_after_tp", 1)
        rows.append(f"  TRAILING STOP   {v(p['trailing_stop_pct']):>8}%  after TP{tat if is_black else BLUR}")
    bep = p.get("break_even_after_tp")
    if bep:
        rows.append(f"  BREAK-EVEN      after TP{bep if is_black else BLUR}")
    if p.get("moon_bag_pct"):
        rows.append(f"  MOON BAG        {v(p['moon_bag_pct']):>8}%")
    if p.get("max_hold_minutes"):
        rows.append(f"  MAX HOLD        {v(p['max_hold_minutes']):>6} min")
    if rows:
        lines.append("<code>RISK CONTROLS\n" + "\n".join(rows) + "</code>")

    if not is_black:
        lines.append(
            "\n🖤 <b>Preset values locked — Supreme Black only</b>\n"
            "<i>Upgrade to view, clone, and apply Black presets.</i>"
        )
    return "\n".join(lines)


def _fmt_position_state(ps: dict, is_black: bool) -> str:
    token    = ps["token_address"]
    entry    = float(ps.get("entry_price_sol") or 0)
    current  = float(ps.get("current_price_sol") or 0)
    highest  = float(ps.get("highest_price_sol") or 0)
    qty_rem  = float(ps.get("qty_remaining_pct") or 100)
    status   = ps.get("status", "?").upper()

    change_pct = (current - entry) / entry * 100 if entry > 0 else 0
    unrealised = (current - entry) * (qty_rem / 100) if entry > 0 else 0
    sign   = "+" if change_pct >= 0 else ""
    arrow  = "▲" if change_pct >= 0 else "▼"
    short  = token[:6] + "..." + token[-4:]

    pnl_bar = _bar(min(100, max(0, change_pct)), 10)

    flags = []
    if ps.get("tp1_fired"): flags.append("TP1✅")
    if ps.get("tp2_fired"): flags.append("TP2✅")
    if ps.get("tp3_fired"): flags.append("TP3✅")
    if ps.get("trailing_active"): flags.append("TRAIL")
    if ps.get("break_even_active"): flags.append("BE")

    flag_str = "  ".join(flags) if flags else "—"

    return (
        f"<code>TOKEN   {short}\n"
        f"STATUS  {status}\n"
        f"ENTRY   {entry:.8f} SOL\n"
        f"NOW     {current:.8f} SOL\n"
        f"HIGH    {highest:.8f} SOL\n"
        f"PnL     {pnl_bar} {sign}{change_pct:.1f}%\n"
        f"QTY REM {qty_rem:.0f}%\n"
        f"UNREAL  {unrealised:+.5f} SOL\n"
        f"FLAGS   {flag_str}</code>"
    )


# ── A. Main menu ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "ae:main")
async def cb_ae_main(callback: CallbackQuery) -> None:
    from services.auto_exit_service import get_auto_exit_settings, get_preset, get_active_position_states
    user_id  = callback.from_user.id
    is_black = await _is_black(user_id)
    s        = await get_auto_exit_settings(user_id)

    # ── Boot animation ─────────────────────────────────────────────────────────
    try:
        await callback.message.edit_text(
            "<code>▓░░░░░░░░░  INITIALIZING...</code>", parse_mode="HTML"
        )
        await asyncio.sleep(0.45)
        await callback.message.edit_text(
            "<code>▓▓▓▓░░░░░░  LOADING PRESETS...</code>", parse_mode="HTML"
        )
        await asyncio.sleep(0.45)
        await callback.message.edit_text(
            "<code>▓▓▓▓▓▓▓░░░  SYNCING POSITIONS...</code>", parse_mode="HTML"
        )
        await asyncio.sleep(0.45)
    except TelegramBadRequest:
        pass

    # ── Build status readout ───────────────────────────────────────────────────
    active_ps = await get_active_position_states()
    user_ps   = [p for p in active_ps if p["user_id"] == user_id]

    preset_name = "NONE"
    preset_id   = s.get("selected_preset_id")
    if preset_id:
        p = await get_preset(int(preset_id))
        if p:
            preset_name = p["name"].upper()

    power_s  = "ACTIVE  ✅" if s.get("enabled") else "OFFLINE ❌"
    mode_s   = "🔴 LIVE " if s.get("live_mode") else "📄 PAPER"
    tier_s   = "🖤 SUPREME BLACK" if is_black else "🔒 LOCKED"

    status_block = (
        f"<code>"
        f"╔══════════════════════════════╗\n"
        f"║   🖤 AUTO-EXIT TERMINAL      ║\n"
        f"╚══════════════════════════════╝\n"
        f"TIER     {tier_s}\n"
        f"POWER    {power_s}\n"
        f"MODE     {mode_s}\n"
        f"PRESET   {preset_name[:26]}\n"
        f"WATCHING {len(user_ps)} position(s)\n"
        f"CYCLE    every 8 seconds\n"
        f"──────────────────────────────\n"
        f"</code>"
    )

    if not is_black:
        status_block += (
            "\n🖤 <b>Supreme Black Required</b>\n"
            "<i>Upgrade to unlock auto TP/SL, trailing stops, and preset cloning.</i>"
        )
    else:
        status_block += (
            "\n<i>📡 Monitoring positions automatically.\n"
            "Select a preset then enable power to activate.</i>"
        )

    try:
        await callback.message.edit_text(
            status_block, reply_markup=build_auto_exit_main(s, is_black), parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


# Power / mode toggles

@router.callback_query(F.data == "ae:toggle")
async def cb_ae_toggle(callback: CallbackQuery) -> None:
    from services.auto_exit_service import toggle_auto_exit
    if not await _is_black(callback.from_user.id):
        await callback.answer("🔒 Supreme Black required.", show_alert=True)
        return
    new = await toggle_auto_exit(callback.from_user.id)
    # Answer BEFORE editing — prevents Telegram's "loading" spinner from blocking the edit
    await callback.answer(f"Auto-Exit {'ONLINE ✅' if new else 'OFFLINE 🔴'}.", show_alert=True)
    # Force a neutral frame first so the subsequent boot animation always has a diff to edit
    try:
        await callback.message.edit_text(
            "<code>▓░░░░░░░░░  APPLYING...</code>", parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass
    await asyncio.sleep(0.3)
    await cb_ae_main(callback)


@router.callback_query(F.data == "ae:live_toggle")
async def cb_ae_live_toggle(callback: CallbackQuery) -> None:
    from services.auto_exit_service import toggle_live_mode
    if not await _is_black(callback.from_user.id):
        await callback.answer("🔒 Supreme Black required.", show_alert=True)
        return
    live = await toggle_live_mode(callback.from_user.id)
    await callback.answer(f"Mode: {'🔴 LIVE — real sells enabled' if live else '📄 PAPER — simulating only'}", show_alert=True)
    try:
        await callback.message.edit_text(
            "<code>▓░░░░░░░░░  SWITCHING MODE...</code>", parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass
    await asyncio.sleep(0.3)
    await cb_ae_main(callback)


# ── B. System (Black) presets ──────────────────────────────────────────────────

@router.callback_query(F.data == "ae:sys_presets")
async def cb_sys_presets(callback: CallbackQuery) -> None:
    from services.auto_exit_service import get_system_presets
    is_black = await _is_black(callback.from_user.id)
    presets  = await get_system_presets()
    text = (
        "<code>╔══════════════════════════════╗\n"
        "║   ⭐ BLACK PRESETS           ║\n"
        "╚══════════════════════════════╝</code>\n\n"
        + ("Select a preset to view its strategy.\n" if is_black else
           "🖤 <b>Values hidden.</b> Upgrade to Supreme Black to view and clone presets.\n")
    )
    try:
        await callback.message.edit_text(text, reply_markup=build_sys_presets(presets, is_black), parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("ae:view_preset:"))
async def cb_view_preset(callback: CallbackQuery) -> None:
    from services.auto_exit_service import get_preset
    is_black  = await _is_black(callback.from_user.id)
    preset_id = int(callback.data.split("ae:view_preset:")[-1])
    preset    = await get_preset(preset_id)
    if not preset:
        await callback.answer("Preset not found.", show_alert=True)
        return
    is_system = bool(preset.get("is_system"))
    await callback.message.edit_text(
        _fmt_preset(preset, is_black),
        reply_markup=build_preset_view(preset, is_black, is_system),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ae:apply_preset:"))
async def cb_apply_preset(callback: CallbackQuery) -> None:
    from services.auto_exit_service import update_auto_exit_field, get_preset
    if not await _is_black(callback.from_user.id):
        await callback.answer("🔒 Supreme Black required.", show_alert=True)
        return
    preset_id = int(callback.data.split("ae:apply_preset:")[-1])
    # Applying a preset implies the user wants auto-exit ON — enable it together.
    await asyncio.gather(
        update_auto_exit_field(callback.from_user.id, "selected_preset_id", preset_id),
        update_auto_exit_field(callback.from_user.id, "enabled", 1),
    )
    p = await get_preset(preset_id)
    name = p["name"] if p else f"#{preset_id}"
    await callback.answer(f"✅ {name} applied — Auto-Exit is now ACTIVE.", show_alert=True)
    await cb_ae_positions(callback)


@router.callback_query(F.data.startswith("ae:clone_preset:"))
async def cb_clone_preset_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_black(callback.from_user.id):
        await callback.answer("🔒 Supreme Black required.", show_alert=True)
        return
    preset_id = int(callback.data.split("ae:clone_preset:")[-1])
    await state.set_state(AEState.clone_name)
    await state.update_data(clone_src=preset_id)
    await callback.message.answer(
        "<code>CLONE PRESET\n──────────────\nEnter a name for your custom preset:</code>",
        reply_markup=build_ae_cancel(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AEState.clone_name)
async def fsm_clone_name(message: Message, state: FSMContext) -> None:
    from services.auto_exit_service import clone_preset
    data = await state.get_data()
    name = (message.text or "").strip()[:60]
    if not name:
        await message.answer(
            "<code>❌ Name cannot be empty.</code>",
            reply_markup=build_ae_cancel(),
            parse_mode="HTML",
        )
        return
    src_id = data.get("clone_src")
    if not src_id:
        await state.clear()
        return
    await clone_preset(src_id, message.from_user.id, name)
    await state.clear()
    await message.answer(
        f"<code>✅ PRESET CLONED\n──────────────\n{name}</code>\n\n"
        f"Apply it from <b>My Presets</b>.",
        reply_markup=build_back_to_ae(),
        parse_mode="HTML",
    )


# ── C. User presets ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "ae:presets")
async def cb_user_presets(callback: CallbackQuery) -> None:
    from services.auto_exit_service import get_user_presets
    is_black = await _is_black(callback.from_user.id)
    presets  = await get_user_presets(callback.from_user.id)
    text = (
        "<code>╔══════════════════════════════╗\n"
        "║   📂 MY PRESETS              ║\n"
        "╚══════════════════════════════╝</code>\n\n"
        + ("No custom presets yet.\nClone a Black preset to build your own strategy.\n"
           if not presets else f"{len(presets)} custom preset(s) saved.\n")
    )
    try:
        await callback.message.edit_text(text, reply_markup=build_user_presets(presets, is_black), parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("ae:del_preset:"))
async def cb_del_preset(callback: CallbackQuery) -> None:
    from services.auto_exit_service import delete_user_preset
    preset_id = int(callback.data.split("ae:del_preset:")[-1])
    ok = await delete_user_preset(preset_id, callback.from_user.id)
    await callback.answer("Preset deleted." if ok else "Not found or system preset.", show_alert=True)
    await cb_user_presets(callback)


# ── D. Active positions ────────────────────────────────────────────────────────

@router.callback_query(F.data == "ae:positions")
async def cb_ae_positions(callback: CallbackQuery) -> None:
    from services.auto_exit_service import (
        get_active_position_states, get_auto_exit_settings, get_preset
    )
    from services.auto_buy_service import get_auto_buy_settings
    from services.sniper_settings_service import get_settings as get_sniper_settings

    is_black = await _is_black(callback.from_user.id)
    user_id  = callback.from_user.id

    all_ps, ae_s, ab_s, sniper_s = await asyncio.gather(
        get_active_position_states(),
        get_auto_exit_settings(user_id),
        get_auto_buy_settings(user_id),
        get_sniper_settings(user_id),
    )
    user_ps = [p for p in all_ps if p["user_id"] == user_id]

    ab_val   = "ON " if ab_s.get("enabled") else "OFF"
    ae_val   = "ON " if ae_s.get("enabled") else "OFF"
    mode_val = "LIVE " if ae_s.get("live_mode") else "PAPER"

    score_thresh = ab_s.get("score_threshold", 65)
    min_liq      = sniper_s.get("min_liquidity", 5000)
    max_age      = sniper_s.get("max_token_age_minutes", 60)
    min_buys     = sniper_s.get("min_buys", 5)
    buy_size     = ab_s.get("max_buy_size_sol", 0.01)
    platform     = (sniper_s.get("preferred_platform") or "auto").upper()

    preset_name = "NONE — SET A PRESET"
    preset_id   = ae_s.get("selected_preset_id")
    if preset_id:
        p = await get_preset(int(preset_id))
        if p:
            preset_name = p["name"]

    quick_block = (
        f"<code>"
        f"┌─ SNIPER QUICK CONFIG ─────────┐\n"
        f"│ AUTO-BUY  [{ab_val}]  AUTO-EXIT [{ae_val}] │\n"
        f"│ MODE      [{mode_val}]              │\n"
        f"│ SCORE     ≥{score_thresh}/100                 │\n"
        f"│ LIQUIDITY ≥${min_liq:,.0f}           │\n"
        f"│ MAX-AGE   {max_age}min  BUYS ≥{min_buys}    │\n"
        f"│ BUY SIZE  {buy_size} SOL  PLAT {platform[:4]}   │\n"
        f"│ PRESET    {preset_name[:23]:<23}│\n"
        f"└───────────────────────────────┘\n"
        f"</code>"
    )

    if not user_ps:
        pos_block = (
            "\n<code>📡 WATCHED POSITIONS\n"
            "──────────────────────────────\n"
            "No active positions.\n"
            "Every confirmed auto-buy is\n"
            "automatically registered here.\n"
            "Set a preset above to activate.</code>"
        )
    else:
        lines = [f"\n<code>📡 WATCHED POSITIONS  [{len(user_ps)} active]",
                 "──────────────────────────────"]
        for ps in user_ps[:8]:
            token   = ps["token_address"]
            short   = token[:6] + "…" + token[-4:]
            entry   = float(ps.get("entry_price_sol") or 0)
            current = float(ps.get("current_price_sol") or 0)
            status  = ps.get("status", "?")
            if entry > 0 and current > 0:
                chg = (current - entry) / entry * 100
                pnl_str = f"{chg:+.1f}%"
            else:
                pnl_str = "price pending"
            lines.append(f"{short}  {pnl_str}  [{status}]")
        lines.append("</code>")
        pos_block = "\n".join(lines)

    from bot.keyboards.auto_exit_menu import build_ae_positions_full
    try:
        await callback.message.edit_text(
            quick_block + pos_block,
            reply_markup=build_ae_positions_full(user_ps, ae_s, ab_s, is_black),
            disable_web_page_preview=True,
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("ae:pos_detail:"))
async def cb_pos_detail(callback: CallbackQuery) -> None:
    from services.auto_exit_service import get_active_position_states
    is_black = await _is_black(callback.from_user.id)
    pos_id   = int(callback.data.split("ae:pos_detail:")[-1])
    all_ps   = await get_active_position_states()
    ps       = next((p for p in all_ps if p["position_id"] == pos_id), None)

    if not ps:
        await callback.answer("Position no longer active.", show_alert=True)
        return

    try:
        await callback.message.edit_text(
            f"<code>╔══════════════════════════════╗\n"
            f"║   📍 POSITION DETAIL         ║\n"
            f"╚══════════════════════════════╝</code>\n\n"
            + _fmt_position_state(ps, is_black),
            reply_markup=build_pos_detail(ps, is_black),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("ae:pos_stop:"))
async def cb_pos_stop(callback: CallbackQuery) -> None:
    from services.auto_exit_service import mark_position_closed
    if not await _is_black(callback.from_user.id):
        await callback.answer("🔒 Supreme Black required.", show_alert=True)
        return
    pos_id = int(callback.data.split("ae:pos_stop:")[-1])
    await mark_position_closed(pos_id)
    await callback.answer("⏹ Stopped watching position.", show_alert=True)
    await cb_ae_positions(callback)


@router.callback_query(F.data.startswith("ae:pos_preset:"))
async def cb_pos_preset(callback: CallbackQuery) -> None:
    """Let user pick which preset to apply to a specific position."""
    from services.auto_exit_service import get_system_presets, get_user_presets
    if not await _is_black(callback.from_user.id):
        await callback.answer("🔒 Supreme Black required.", show_alert=True)
        return
    pos_id   = int(callback.data.split("ae:pos_preset:")[-1])
    sys_p    = await get_system_presets()
    user_p   = await get_user_presets(callback.from_user.id)
    all_p    = sys_p + user_p

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    for p in all_p:
        b.row(InlineKeyboardButton(
            text=p["name"],
            callback_data=f"ae:pos_set_preset:{pos_id}:{p['id']}",
        ))
    b.row(InlineKeyboardButton(text="⬅️  Cancel", callback_data=f"ae:pos_detail:{pos_id}"))
    try:
        await callback.message.edit_text(
            "<code>SELECT PRESET FOR THIS POSITION\n──────────────────────────────</code>\n\n"
            "Choose a preset to apply to this specific position.\n"
            "This overrides your global preset for this trade only.",
            reply_markup=b.as_markup(),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("ae:pos_set_preset:"))
async def cb_pos_set_preset(callback: CallbackQuery) -> None:
    _, pos_id_s, preset_id_s = callback.data.rsplit(":", 2)
    pos_id    = int(pos_id_s)
    preset_id = int(preset_id_s)
    async with __import__("database.sqlite_db", fromlist=["get_db"]).get_db() as db:
        await db.execute(
            "UPDATE position_state SET preset_id=?, updated_at=CURRENT_TIMESTAMP WHERE position_id=?",
            (preset_id, pos_id)
        )
        await db.commit()
    await callback.answer("✅ Preset applied to this position.", show_alert=True)
    await cb_ae_positions(callback)


# ── D2. Quick preset shortcuts (positions page) ────────────────────────────────

@router.callback_query(F.data == "ae:noop")
async def cb_ae_noop(callback: CallbackQuery) -> None:
    """No-op — used for separator buttons in keyboards."""
    await callback.answer()


@router.callback_query(F.data.startswith("ae:quick_preset:"))
async def cb_quick_preset(callback: CallbackQuery) -> None:
    """Apply a system preset by index directly from the positions page."""
    from services.auto_exit_service import get_system_presets, update_auto_exit_field
    if not await _is_black(callback.from_user.id):
        await callback.answer("🔒 Supreme Black required.", show_alert=True)
        return
    idx = int(callback.data.split("ae:quick_preset:")[-1])
    presets = await get_system_presets()
    if idx >= len(presets):
        await callback.answer("Preset not found.", show_alert=True)
        return
    preset = presets[idx]
    # Selecting a quick preset activates auto-exit immediately.
    await asyncio.gather(
        update_auto_exit_field(callback.from_user.id, "selected_preset_id", preset["id"]),
        update_auto_exit_field(callback.from_user.id, "enabled", 1),
    )
    await callback.answer(f"✅ {preset['name']} active — Auto-Exit ON.", show_alert=True)
    await cb_ae_positions(callback)


@router.callback_query(F.data == "ae:pick_exit_preset")
async def cb_pick_exit_preset(callback: CallbackQuery) -> None:
    """Show all available presets so the user can pick one as the global exit preset."""
    from services.auto_exit_service import get_system_presets, get_user_presets, get_auto_exit_settings
    if not await _is_black(callback.from_user.id):
        await callback.answer("🔒 Supreme Black required.", show_alert=True)
        return

    sys_p, user_p, ae_s = await asyncio.gather(
        get_system_presets(),
        get_user_presets(callback.from_user.id),
        get_auto_exit_settings(callback.from_user.id),
    )
    current_id = ae_s.get("selected_preset_id")
    all_p = sys_p + user_p

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    for p in all_p:
        tick = "✅ " if p["id"] == current_id else ""
        icon = "⭐" if p.get("is_system") else "📂"
        b.row(InlineKeyboardButton(
            text=f"{tick}{icon} {p['name']}",
            callback_data=f"ae:apply_preset:{p['id']}",
        ))
    b.row(InlineKeyboardButton(text="⬅️  Back", callback_data="ae:positions"))
    try:
        await callback.message.edit_text(
            "<code>╔══════════════════════════════╗\n"
            "║   ⭐ SELECT EXIT PRESET      ║\n"
            "╚══════════════════════════════╝</code>\n\n"
            "Applied globally to all <b>new</b> positions.\n"
            "Override per-position from the position detail view.",
            reply_markup=b.as_markup(),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


# ── G. Manual sell ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ae:manual_sell:"))
async def cb_manual_sell(callback: CallbackQuery) -> None:
    from services.auto_exit_service import (
        get_active_position_states, get_auto_exit_settings, record_sell_attempt, update_sell_execution
    )
    from services.solana_execution_service import execute_sell

    if not await _is_black(callback.from_user.id):
        await callback.answer("🔒 Supreme Black required.", show_alert=True)
        return

    parts    = callback.data.split(":")
    pos_id   = int(parts[2])
    sell_pct = float(parts[3])
    user_id  = callback.from_user.id

    all_ps   = await get_active_position_states()
    ps       = next((p for p in all_ps if p["position_id"] == pos_id), None)
    if not ps:
        await callback.answer("Position not found.", show_alert=True)
        return

    ae_s     = await get_auto_exit_settings(user_id)
    live     = bool(ae_s.get("live_mode", 1))

    await callback.answer(f"⏳ Executing manual sell {sell_pct:.0f}%...", show_alert=True)

    exec_id = await record_sell_attempt(pos_id, user_id, ps["token_address"], sell_pct, "manual")

    if not live:
        await update_sell_execution(exec_id, "PAPER_MODE", "paper")
        await callback.message.answer(
            f"<code>📄 PAPER MODE\n──────────────\nWould sell {sell_pct:.0f}% of position.\nNo on-chain TX submitted.</code>",
            parse_mode="HTML",
        )
        return

    result = await execute_sell(
        user_id          = user_id,
        token_address    = ps["token_address"],
        sell_pct         = sell_pct,
        slippage_pct     = float(ae_s.get("custom_slippage") or 15.0),
        priority_fee_sol = float(ae_s.get("custom_priority_fee") or 0.005),
    )

    if result["success"]:
        sig = result["signature"]
        await update_sell_execution(exec_id, sig, "confirmed")
        await callback.message.answer(
            f"<code>✅ MANUAL SELL EXECUTED\n"
            f"──────────────────────\n"
            f"AMOUNT  {sell_pct:.0f}% of position\n"
            f"VIA     {result.get('platform_used','?')}\n"
            f"TX      {sig[:20]}...</code>",
            parse_mode="HTML",
        )
    else:
        await update_sell_execution(exec_id, "", "failed")
        await callback.message.answer(
            f"<code>❌ SELL FAILED\n──────────────\n{result['error'][:200]}</code>",
            parse_mode="HTML",
        )


# ── E. Settings ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "ae:settings")
async def cb_ae_settings(callback: CallbackQuery) -> None:
    from services.auto_exit_service import get_auto_exit_settings
    s = await get_auto_exit_settings(callback.from_user.id)
    notif = "ON " if s.get("notifications_enabled") else "OFF"
    text = (
        f"<code>╔══════════════════════════════╗\n"
        f"║   ⚙️  EXECUTION SETTINGS     ║\n"
        f"╚══════════════════════════════╝\n"
        f"SLIPPAGE      {s.get('custom_slippage', 15.0):.1f}%\n"
        f"PRIORITY FEE  {s.get('custom_priority_fee', 0.0001):.6f} SOL\n"
        f"NOTIFICATIONS {notif}\n"
        f"──────────────────────────────</code>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=build_ae_settings(s), parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("ae:set:"))
async def cb_ae_set_field(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_black(callback.from_user.id):
        await callback.answer("🔒 Supreme Black required.", show_alert=True)
        return
    field = callback.data.split("ae:set:")[-1]
    labels = {
        "custom_slippage":     "Slippage (%)",
        "custom_priority_fee": "Priority Fee (SOL)",
    }
    await state.set_state(AEState.edit_field)
    await state.update_data(field=field)
    await callback.message.answer(
        f"<code>EDIT: {labels.get(field, field)}\n──────────────\nEnter new value:</code>",
        reply_markup=build_ae_cancel(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "ae:toggle_notif")
async def cb_toggle_notif(callback: CallbackQuery) -> None:
    from services.auto_exit_service import get_auto_exit_settings, update_auto_exit_field
    s   = await get_auto_exit_settings(callback.from_user.id)
    new = 0 if s.get("notifications_enabled") else 1
    await update_auto_exit_field(callback.from_user.id, "notifications_enabled", new)
    await callback.answer(f"Notifications {'ON' if new else 'OFF'}.")
    await cb_ae_settings(callback)


@router.message(AEState.edit_field)
async def fsm_ae_edit_field(message: Message, state: FSMContext) -> None:
    from services.auto_exit_service import update_auto_exit_field
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    data      = await state.get_data()
    field     = data.get("field", "")
    return_to = data.get("return_to")   # set by ae:qset: / ae:qs: handlers
    raw       = (message.text or "").strip()

    if not field:
        await state.clear()
        return

    def _back_kb() -> InlineKeyboardMarkup:
        if return_to:
            b = InlineKeyboardBuilder()
            b.row(InlineKeyboardButton(text="⬅️  Back to Positions", callback_data=return_to))
            return b.as_markup()
        return build_back_to_ae()

    # ── Auto-buy field (ae:qset: path) ─────────────────────────────────────────
    if field.startswith("__ab__"):
        from services.auto_buy_service import update_auto_buy_field
        real_field    = field[6:]
        ab_int_fields = {"max_buys_per_hour", "cooldown_seconds"}
        try:
            value = int(raw) if real_field in ab_int_fields else float(raw)
        except ValueError:
            await message.answer("<code>❌ Invalid — enter a number.</code>", reply_markup=build_ae_cancel(), parse_mode="HTML")
            return
        from services.brainrot_token_gate import get_entitlements
        ents = await get_entitlements(message.from_user.id)
        if real_field == "max_buy_size_sol" and value > ents.max_buy_size_limit_sol:
            await message.answer(f"<code>❌ Tier limit is {ents.max_buy_size_limit_sol} SOL.</code>", reply_markup=build_ae_cancel(), parse_mode="HTML")
            return
        if real_field == "max_buys_per_hour" and value > ents.max_buys_per_hour_limit:
            await message.answer(f"<code>❌ Tier limit is {ents.max_buys_per_hour_limit}/hr.</code>", reply_markup=build_ae_cancel(), parse_mode="HTML")
            return
        await state.clear()
        await update_auto_buy_field(message.from_user.id, real_field, value)
        import services.auto_buy_worker as _worker
        _worker.reset_seen()
        await message.answer(
            f"<code>✅ {real_field} → {value}\nSettings updated — auto-buy continues with new values.</code>",
            reply_markup=_back_kb(), parse_mode="HTML",
        )
        return

    # ── Sniper settings field (ae:qs: path) ────────────────────────────────────
    sniper_int   = {"min_buys", "max_token_age_minutes", "max_risk_level"}
    sniper_float = {"min_liquidity", "min_volume", "default_buy_size", "default_slippage"}
    if field in sniper_int or field in sniper_float:
        from services.sniper_settings_service import update_setting
        error = None
        value = None
        try:
            if field in sniper_int:
                value = int(raw)
                if field == "max_risk_level" and not (1 <= value <= 5):
                    error = "Risk level must be 1–5."
                elif value < 0:
                    error = "Value must be ≥ 0."
            else:
                value = float(raw)
                if value < 0:
                    error = "Value must be ≥ 0."
        except ValueError:
            error = "Enter a valid number."
        if error:
            await message.answer(f"<code>❌ {error}</code>", reply_markup=build_ae_cancel(), parse_mode="HTML")
            return
        await state.clear()
        await update_setting(message.from_user.id, field, value)
        await message.answer(f"<code>✅ {field} → {value}</code>", reply_markup=_back_kb(), parse_mode="HTML")
        return

    # ── AE settings field (ae:set: path) ───────────────────────────────────────
    try:
        value = float(raw)
    except ValueError:
        await message.answer(
            "<code>❌ Invalid input — enter a number.</code>",
            reply_markup=build_ae_cancel(),
            parse_mode="HTML",
        )
        return
    await update_auto_exit_field(message.from_user.id, field, value)
    await state.clear()
    await message.answer(
        f"<code>✅ SAVED\n──────────────\n{field} = {value}</code>",
        reply_markup=_back_kb(),
        parse_mode="HTML",
    )


# ── H. Upgrade CTA ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "ae:upgrade_cta")
async def cb_upgrade_cta(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "<code>╔══════════════════════════════╗\n"
        "║   🖤 SUPREME BLACK           ║\n"
        "╚══════════════════════════════╝\n"
        "UNLOCKS:\n"
        "  ✅ Auto-Exit Manager\n"
        "  ✅ TP / SL / Trailing stops\n"
        "  ✅ Supreme Black presets\n"
        "  ✅ Per-position preset override\n"
        "  ✅ Manual sell controls\n"
        "  ✅ Paper mode simulation\n"
        "──────────────────────────────\n"
        "Contact an admin to upgrade.</code>",
        parse_mode="HTML",
    )


# ── F. FSM cancel ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "ae:cancel_fsm")
async def cb_ae_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Cancelled.")
    await cb_ae_main(callback)


# ── I. Quick-config shortcuts from positions page ─────────────────────────────
# These use ae:qset: (auto-buy fields) and ae:qs: (sniper settings fields)
# prefixes so the FSM return_to can route back to ae:positions after save.

@router.callback_query(F.data.startswith("ae:qset:"))
async def cb_ae_qset_field(callback: CallbackQuery, state: FSMContext) -> None:
    """Quick-set an auto-buy field from the positions page — returns to ae:positions."""
    from bot.keyboards.auto_exit_menu import build_ae_cancel as _cancel_kb
    field  = callback.data.split("ae:qset:")[-1]
    labels = {
        "max_buy_size_sol":  "Max Buy Size (SOL)",
        "max_buys_per_hour": "Max Buys Per Hour",
        "score_threshold":   "Score Threshold (1-100)",
        "slippage":          "Slippage (%)",
        "priority_fee":      "Priority Fee (SOL)",
        "cooldown_seconds":  "Cooldown (seconds)",
    }
    await state.set_state(AEState.edit_field)
    await state.update_data(field=f"__ab__{field}", return_to="ae:positions")
    await callback.message.answer(
        f"<code>EDIT: {labels.get(field, field)}\n──────────────\nEnter new value:</code>",
        reply_markup=_cancel_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ae:qs:"))
async def cb_ae_qs_field(callback: CallbackQuery, state: FSMContext) -> None:
    """Quick-set a sniper settings field from the positions page — returns to ae:positions."""
    from bot.keyboards.auto_exit_menu import build_ae_cancel as _cancel_kb
    field  = callback.data.split("ae:qs:")[-1]
    labels = {
        "min_liquidity":         "Min Liquidity (USD)",
        "min_volume":            "Min Volume (USD)",
        "min_buys":              "Min Buys (integer)",
        "max_token_age_minutes": "Max Token Age (minutes)",
        "max_risk_level":        "Max Risk Level (1-5)",
        "default_buy_size":      "Default Buy Size (SOL)",
        "default_slippage":      "Default Slippage (%)",
    }
    await state.set_state(AEState.edit_field)
    await state.update_data(field=field, return_to="ae:positions")
    await callback.message.answer(
        f"<code>EDIT: {labels.get(field, field)}\n──────────────\nEnter new value:</code>",
        reply_markup=_cancel_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


