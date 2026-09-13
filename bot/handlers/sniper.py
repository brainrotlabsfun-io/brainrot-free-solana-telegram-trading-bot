"""
bot/handlers/sniper.py
=======================
Full Sniper Tool handler.

Sections:
  A.  Main menu
  B.  Analyze Token (FSM)
  C.  Sniper Settings (view + per-field edit FSM + toggles)
  D.  Presets (list, view, create FSM, apply, delete)
  E.  Watch Targets (list, add FSM, remove, feed shortcuts)
  F.  Blacklist (list, add FSM, remove, feed shortcuts)
  G.  Trade Preview (manual + from feed)
  H.  Live Launch Feed (fetch + display + per-card actions)
  I.  Smart Alerts (toggle + view)
  J.  Auto-Buy (settings + toggles + field edit FSM)
  K.  Wallet (view + add/change FSM)
  L.  Positions (list + close)
  N.  FSM cancel + admin sniper commands
"""

import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton

from bot.keyboards.sniper_menu import (
    build_sniper_menu,
    build_back_to_sniper,
    build_token_actions,
    build_settings_menu,
    build_presets_list,
    build_preset_actions,
    build_share_menu,
    build_watch_list,
    build_watch_targets_main,
    build_watch_target_detail,
    build_blacklist_menu,
    build_feed_nav,
    build_feed_card_actions,
    build_autobuy_menu,
    build_liq_sniper_menu,
    build_cancel_sniper,
)
from services.sniper_service import (
    is_valid_solana_address,
    analyze_token_for_user,
    get_feed_for_user,
    format_token_card,
    cache_address,
    get_cached_address,
)
from services.sniper_settings_service import get_settings, update_setting, apply_preset_to_settings
from services.sniper_presets_service import (
    get_presets, get_preset, count_presets,
    create_preset_from_settings, delete_preset,
    get_presets_with_pnl, get_preset_pnl,
    BUILTIN_TEMPLATES,
)
from services.sniper_watch_service import (
    get_watch_targets, count_watch_targets,
    add_watch_target, remove_watch_target,
    get_watch_target_by_id, update_watch_target_field,
)
from services.sniper_blacklist_service import (
    get_blacklist, count_blacklist,
    add_to_blacklist, remove_from_blacklist,
)
from services.sniper_alert_service import get_alert_settings, toggle_alerts
from utils.share_utils import bot_link as _bot_link, website_buttons as _website_buttons, share_footer as _share_footer
from services.auto_buy_service import (
    get_auto_buy_settings, update_auto_buy_field,
    toggle_auto_buy, toggle_kill_switch,
)
from services.wallet_service import get_wallet, set_wallet, get_sol_balance
from services.positions_service import get_positions, close_position, get_recent_transactions
from utils.sniper_states import (
    AnalyzeTokenState, AddWatchTargetState, AddBlacklistState,
    AddWalletState, EditSettingState, CreatePresetState,
    ConfigAutoBuyState, TradePreviewState,
)
from utils.states import WithdrawState
from utils.admin import is_admin

router = Router()
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _short(address: str) -> str:
    return address[:6] + "..." + address[-4:] if len(address) > 10 else address


def _fmt_analysis(result: dict) -> str:
    t     = result["token"]
    score = result["score"]
    risks = result.get("risk_notes", [])
    prem  = result.get("premium_notes")

    age   = t.get("age_minutes")
    age_s = f"{age}m" if age is not None else "?"

    risk_block = ("\n\n⚠️ <b>Risk Notes:</b>\n" + "\n".join(f"• {r}" for r in risks)) if risks else ""

    # Extra analysis notes, when the scorer produced any
    if prem:
        extra_block = f"\n\n🔬 <b>Analysis:</b>\n{prem}"
    else:
        extra_block = ""

    return (
        f"🔍 <b>Token Analysis</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Name:</b>   {t.get('name','?')}  (<b>{t.get('symbol','?')}</b>)\n"
        f"<b>Address:</b> <code>{t.get('address','')}</code>\n"
        f"<b>Price:</b>  ${t.get('price_usd', 0):.8f}\n"
        f"<b>Liquidity:</b> ${t.get('liquidity_usd', 0):,.0f}\n"
        f"<b>Volume 1h:</b> ${t.get('volume_h1', 0):,.0f}\n"
        f"<b>Buys 1h:</b>  {t.get('buys_h1', 0)}  |  <b>Sells 1h:</b> {t.get('sells_h1', 0)}\n"
        f"<b>Age:</b> {age_s}\n"
        f"<b>DEX:</b> {t.get('dex','?')}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>BRAINROT Sniper Score: {score}/100</b>\n"
        f"{result['rating']}\n\n"
        f"<i>{result.get('summary','')}</i>"
        f"{risk_block}{extra_block}\n\n"
    )


def _fmt_settings(s: dict) -> str:
    sm  = "✅" if s.get("strict_mode") else "⬜"
    af  = "✅" if s.get("auto_filter_enabled") else "⬜"
    fl  = "✅" if s.get("prioritize_fresh_launches") else "⬜"
    ls  = "✅" if s.get("prioritize_liquidity_strength") else "⬜"
    ia  = "✅" if s.get("instant_alert_on_match") else "⬜"

    plat_labels = {"auto": "🔄 Auto", "jupiter": "🪐 Jupiter", "pumpfun": "🔥 PumpFun"}
    plat = plat_labels.get(s.get("preferred_platform", "auto"), "🔄 Auto")

    base = (
        f"⚙️ <b>Sniper Settings</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔀 Platform:         {plat}\n"
        f"💧 Min Liquidity:    ${s.get('min_liquidity',0):,.0f}\n"
        f"📊 Min Volume:       ${s.get('min_volume',0):,.0f}\n"
        f"🛒 Min Buys:         {s.get('min_buys',0)}\n"
        f"⏱ Max Token Age:    {s.get('max_token_age_minutes',0)}m\n"
        f"⚠️ Max Risk Level:   {s.get('max_risk_level',0)}/5\n"
        f"💰 Default Buy:     {s.get('default_buy_size',0)} SOL\n"
        f"📐 Slippage:         {s.get('default_slippage',0)}%\n"
        f"{sm} Strict Mode\n"
    )
    base += (
        f"\n{af} Auto Filter    {fl} Fresh Priority\n"
        f"{ls} Liq Strength   {ia} Instant Alert\n"
    )
    return base


# ══════════════════════════════════════════════════════════════════════════════
# A. MAIN MENU
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "sniper:main")
async def cb_sniper_main(callback: CallbackQuery) -> None:
    import asyncio
    from database.sqlite_db import get_db as _get_db_local
    from services.bot_wallet_service import get_or_create_bot_wallet as _get_wallet_local, get_sol_balance as _get_sol_balance_local

    user_id = callback.from_user.id

    # Boot animation
    try:
        boot = await callback.message.edit_text(
            "<code>█░░░░░░░░░ BRAINROT SNIPER BOOTING...</code>",
            parse_mode="HTML",
        )
        await asyncio.sleep(0.38)
        await boot.edit_text(
            "<code>████░░░░░░ LOADING MISSION DATA...</code>",
            parse_mode="HTML",
        )
        await asyncio.sleep(0.38)
        await boot.edit_text(
            "<code>██████████ SYSTEMS ONLINE ⚡</code>",
            parse_mode="HTML",
        )
        await asyncio.sleep(0.30)
    except TelegramBadRequest:
        pass


    # ── Pull dashboard stats ───────────────────────────────────────────────────
    try:
        async with _get_db_local() as db:
            # Total buys executed
            async with db.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount_sol),0) FROM auto_buy_jobs "
                "WHERE user_id = ? AND status = 'executed'",
                (user_id,)
            ) as cur:
                row = await cur.fetchone()
                total_buys     = row[0] if row else 0
                total_spent    = float(row[1]) if row else 0.0

            # Open positions
            async with db.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount_sol),0) FROM tracked_positions "
                "WHERE user_id = ? AND status = 'open'",
                (user_id,)
            ) as cur:
                row = await cur.fetchone()
                open_positions = row[0] if row else 0
                open_spent     = float(row[1]) if row else 0.0

            # Closed positions — estimate P&L from sell_executions
            async with db.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount_sol_est),0) FROM sell_executions "
                "WHERE user_id = ? AND status = 'confirmed'",
                (user_id,)
            ) as cur:
                row = await cur.fetchone()
                total_sells    = row[0] if row else 0
                total_returned = float(row[1]) if row else 0.0

    except Exception:
        total_buys = total_spent = open_positions = open_spent = 0
        total_sells = total_returned = 0

    # ── Wallet balance ─────────────────────────────────────────────────────────
    bal_str = "—"
    try:
        w = await _get_wallet_local(user_id)
        if w and w.get("wallet_address"):
            bal = await _get_sol_balance_local(w["wallet_address"])
            bal_str = f"{bal:.4f} SOL" if bal is not None else "RPC ERR"
    except Exception:
        pass

    # ── P&L calc ──────────────────────────────────────────────────────────────
    # crude estimate: returned - spent on closed positions
    closed_spent = max(0.0, total_spent - open_spent)
    pnl_sol      = total_returned - closed_spent
    pnl_sign     = "+" if pnl_sol >= 0 else ""
    pnl_icon     = "📈" if pnl_sol >= 0 else "📉"

    # ── Balance bar ───────────────────────────────────────────────────────────
    try:
        bal_num = float(bal_str.replace(" SOL","")) if bal_str != "—" else 0
        bar_fill = min(10, int(bal_num / 0.5 * 10)) if bal_num > 0 else 0
        bal_bar  = "▓" * bar_fill + "░" * (10 - bar_fill)
    except Exception:
        bal_bar = "░" * 10

    status_line = "All systems armed."

    text = (
        f"🎯 <b>BRAINROT SNIPER</b>\n"
        f"<code>💳 {bal_bar}  {bal_str}</code>\n"
        f"<code>🎯 {total_buys} bought  📂 {open_positions} open  💸 {total_sells} sells</code>\n"
        f"<code>{pnl_icon} P&L est  {pnl_sign}{pnl_sol:.4f} SOL</code>\n\n"
        f"<i>{status_line}</i>"
    )

    try:
        await callback.message.edit_text(
            text,
            reply_markup=build_sniper_menu(),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


# ══════════════════════════════════════════════════════════════════════════════
# B. ANALYZE TOKEN
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "sniper:analyze")
async def cb_analyze_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AnalyzeTokenState.waiting_address)
    await callback.message.answer(
        "🔍 <b>Analyze Token</b>\n\n"
        "Paste the Solana token contract address:\n"
        "<i>Must be a valid base58 Solana address (32–44 characters)</i>",
        reply_markup=build_cancel_sniper(),
    )
    await callback.answer()


@router.message(AnalyzeTokenState.waiting_address)
async def fsm_analyze_address(message: Message, state: FSMContext) -> None:
    address = message.text.strip()
    if not is_valid_solana_address(address):
        await message.answer(
            "❌ Invalid Solana address. Please check and try again.",
            reply_markup=build_cancel_sniper(),
        )
        return

    await state.clear()
    status_msg = await message.answer("⏳ Fetching token data...")

    result = await analyze_token_for_user(message.from_user.id, address)

    if "error" in result:
        await status_msg.edit_text(f"❌ {result['error']}")
        return

    cache_key = cache_address(address)
    await status_msg.edit_text(
        text=_fmt_analysis(result),
        reply_markup=build_token_actions(address, cache_key),
    )


# ══════════════════════════════════════════════════════════════════════════════
# C. SNIPER SETTINGS
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "sniper:settings")
async def cb_settings(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    s       = await get_settings(user_id)
    await callback.message.edit_text(
        text=_fmt_settings(s),
        reply_markup=build_settings_menu(s),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sniper:set:"))
async def cb_set_field_start(callback: CallbackQuery, state: FSMContext) -> None:
    field = callback.data.split("sniper:set:")[-1]
    labels = {
        "min_liquidity":         "Min Liquidity (USD)",
        "min_volume":            "Min Volume (USD)",
        "min_buys":              "Min Buys (integer)",
        "max_token_age_minutes": "Max Token Age (minutes)",
        "max_risk_level":        "Max Risk Level (1-5)",
        "default_buy_size":      "Default Buy Size (SOL)",
        "default_slippage":      "Default Slippage (%)",
    }
    label = labels.get(field, field)
    await state.set_state(EditSettingState.waiting_value)
    await state.update_data(field=field)
    await callback.message.answer(
        f"✏️ Enter new value for <b>{label}</b>:",
        reply_markup=build_cancel_sniper(),
    )
    await callback.answer()


# (settings value handler merged below with auto-buy handler to avoid duplicate registration)


@router.callback_query(F.data.startswith("sniper:platform:"))
async def cb_set_platform(callback: CallbackQuery) -> None:
    user_id  = callback.from_user.id
    platform = callback.data.split("sniper:platform:")[-1]
    if platform not in ("auto", "jupiter", "pumpfun"):
        await callback.answer("Unknown platform.", show_alert=True)
        return
    await update_setting(user_id, "preferred_platform", platform)
    labels = {"auto": "🔄 Auto (smart routing)", "jupiter": "🪐 Jupiter only", "pumpfun": "🔥 PumpFun only"}
    s_new = await get_settings(user_id)
    await callback.message.edit_reply_markup(reply_markup=build_settings_menu(s_new))
    await callback.answer(f"Platform set to {labels[platform]}")


@router.callback_query(F.data.startswith("sniper:toggle:"))
async def cb_toggle_setting(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    field   = callback.data.split("sniper:toggle:")[-1]

    advanced_fields = {
        "auto_filter_enabled", "prioritize_fresh_launches",
        "prioritize_liquidity_strength", "auto_hide_weak_metadata",
        "auto_hide_low_momentum", "instant_alert_on_match", "premium_ranking_boost",
    }
    s = await get_settings(user_id)
    new_val = 0 if s.get(field) else 1
    await update_setting(user_id, field, new_val)

    s_new = await get_settings(user_id)
    await callback.message.edit_reply_markup(
        reply_markup=build_settings_menu(s_new)
    )
    await callback.answer(f"{'On' if new_val else 'Off'}")


# ══════════════════════════════════════════════════════════════════════════════
# D. PRESETS
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "sniper:presets")
async def cb_presets(callback: CallbackQuery) -> None:
    user_id    = callback.from_user.id
    presets    = await get_presets_with_pnl(user_id)   # sorted by P&L desc

    # Built-in starter templates at the bottom (unranked — no trade history)
    display = presets[:]
    for t in BUILTIN_TEMPLATES:
        display.append({"id": f"tpl_{t['name']}", "name": t['name'], "total_pnl": None})

    slots_used = len(presets)

    # Build ranking rows
    rank_lines = ""
    if presets:
        rank_lines = "<code>"
        for i, p in enumerate(presets, 1):
            pnl     = p.get("total_pnl", 0.0) or 0.0
            trades  = p.get("trades", 0) or 0
            wr      = p.get("win_rate", 0.0) or 0.0
            sign    = "+" if pnl >= 0 else ""
            medal   = ["🥇","🥈","🥉"].pop(0) if i <= 3 else f"#{i}"
            pname   = p["name"].upper()[:18]
            rank_lines += f"{str(medal):<3} {pname:<18} {sign}{pnl:.4f} SOL  {trades}T  {wr:.0f}%WR\n"
        rank_lines += "</code>"
    else:
        rank_lines = "<i>No presets yet — save one to start tracking P&L.</i>"

    await callback.message.edit_text(
        text=(
            f"<code>╔══════════════════════════════╗\n"
            f"║  ⬛  CONFIG VAULT  //  PRESETS ║\n"
            f"╚══════════════════════════════╝</code>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
            f"<b>// PERFORMANCE RANKING</b>\n"
            f"{rank_lines}\n"
            f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n"
            f"<i>Tap a preset to load, edit, or share it.</i>"
        ),
        reply_markup=build_presets_list(display),
    )
    await callback.answer()


@router.callback_query(F.data == "sniper:share_menu")
async def cb_share_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "🌐 <b>SHARE TO COMMUNITY</b>\n"
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
        "Choose a platform to share on.\n"
        "Each link opens pre-filled and ready to post.\n\n"
        "<code>#BRAINROTONCHAINBOT</code> — use the hashtag\n"
        "so the community can find each other's trades,\n"
        "presets, and strategies across all platforms.\n\n"
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>",
        reply_markup=build_share_menu(),
    )
    await callback.answer()


def _fmt_sniper_preset(p: dict, pnl_stats: dict = None, tag: str = "") -> str:
    """Full hacker-style display for a sniper (buy filter) preset."""
    flag = lambda v: "ON " if v else "OFF"
    strat = (p.get("strategy_mode") or "none").upper()
    plat  = (p.get("preferred_platform") or "auto").upper()
    risk  = p.get("max_risk_level", 3)
    risk_label = {1: "LOW", 2: "MEDIUM-LOW", 3: "MEDIUM", 4: "HIGH", 5: "DEGEN"}.get(risk, str(risk))

    lines = (
        f"<code>━━━━  ENTRY FILTERS  ━━━━━━━━━━\n"
        f"MIN LIQ    ${p.get('min_liquidity', 0):>9,.0f}\n"
        f"MIN VOL    ${p.get('min_volume', 0):>9,.0f}\n"
        f"MIN BUYS   {p.get('min_buys', 0):>10}\n"
        f"MAX AGE    {p.get('max_token_age_minutes', 0):>8}m\n"
        f"RISK LVL   {risk_label:>10}\n"
        f"━━━━  EXECUTION  ━━━━━━━━━━━━━━\n"
        f"BUY SIZE   {p.get('default_buy_size', 0):>8} SOL\n"
        f"SLIPPAGE   {p.get('default_slippage', 0):>8.1f}%\n"
        f"PLATFORM   {plat:>10}\n"
        f"STRATEGY   {strat:>10}\n"
        f"━━━━  FILTERS  ━━━━━━━━━━━━━━━━\n"
        f"STRICT MODE        {flag(p.get('strict_mode')):>3}\n"
        f"AUTO FILTER        {flag(p.get('auto_filter_enabled')):>3}\n"
        f"FRESH LAUNCH PRIO  {flag(p.get('prioritize_fresh_launches')):>3}\n"
        f"LIQ STRENGTH PRIO  {flag(p.get('prioritize_liquidity_strength')):>3}\n"
        f"HIDE WEAK META     {flag(p.get('auto_hide_weak_metadata')):>3}\n"
        f"HIDE LOW MOMENTUM  {flag(p.get('auto_hide_low_momentum')):>3}\n"
        f"INSTANT ALERT      {flag(p.get('instant_alert_on_match')):>3}\n"
        f"RANKING BOOST      {flag(p.get('premium_ranking_boost')):>3}\n"
    )

    if pnl_stats and pnl_stats.get("trades", 0) > 0:
        pnl    = pnl_stats["total_pnl"]
        trades = pnl_stats["trades"]
        wins   = pnl_stats["wins"]
        losses = pnl_stats["losses"]
        wr     = pnl_stats["win_rate"]
        sign   = "+" if pnl >= 0 else ""
        lines += (
            f"━━━━  P&L HISTORY  ━━━━━━━━━━━━\n"
            f"TOTAL P&L  {sign}{pnl:.5f} SOL\n"
            f"TRADES     {trades:>10}\n"
            f"WINS       {wins:>10}\n"
            f"LOSSES     {losses:>10}\n"
            f"WIN RATE   {wr:>9.1f}%\n"
        )
    else:
        lines += "━━━━  P&L HISTORY  ━━━━━━━━━━━━\nNO TRADES YET FOR THIS PRESET\n"

    lines += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>"
    name  = p.get("name", "PRESET").upper()
    badge = f"  <i>[{tag}]</i>" if tag else ""
    return f"⬛ <b>PRESET  //  {name[:24]}</b>{badge}\n{lines}"


@router.callback_query(F.data.startswith("sniper:preset_view:"))
async def cb_preset_view(callback: CallbackQuery) -> None:
    raw     = callback.data.split("sniper:preset_view:")[-1]
    user_id = callback.from_user.id

    # Built-in template (no P&L — not user-created)
    if raw.startswith("tpl_"):
        name = raw[4:]
        tpl  = next((t for t in BUILTIN_TEMPLATES if t["name"] == name), None)
        if tpl:
            await callback.message.edit_text(
                text=_fmt_sniper_preset(tpl, tag="BUILT-IN TEMPLATE"),
                reply_markup=build_preset_actions(raw, is_template=True),
            )
        await callback.answer()
        return

    preset = await get_preset(int(raw), user_id)
    if not preset:
        await callback.answer("Preset not found.", show_alert=True)
        return

    pnl_stats = await get_preset_pnl(user_id, preset["id"])
    await callback.message.edit_text(
        text=_fmt_sniper_preset(preset, pnl_stats),
        reply_markup=build_preset_actions(preset["id"]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sniper:preset_apply:"))
async def cb_preset_apply(callback: CallbackQuery) -> None:
    raw     = callback.data.split("sniper:preset_apply:")[-1]
    user_id = callback.from_user.id

    if raw.startswith("tpl_"):
        name   = raw[4:]
        preset = next((t for t in BUILTIN_TEMPLATES if t["name"] == name), None)
    else:
        preset = await get_preset(int(raw), user_id)

    if not preset:
        await callback.answer("Preset not found.", show_alert=True)
        return

    await apply_preset_to_settings(user_id, preset)

    # Also apply auto_buy_settings fields — these are NOT in sniper_settings table
    # so apply_preset_to_settings misses them entirely, breaking preset load
    from services.auto_buy_service import update_auto_buy_field as _ab_update
    _AB_FIELDS = [
        "score_threshold", "max_buy_size_sol", "slippage",
        "max_buys_per_hour", "cooldown_seconds", "priority_fee", "min_initial_buy_sol",
    ]
    for _f in _AB_FIELDS:
        if _f in preset:
            await _ab_update(user_id, _f, preset[_f])

    pname = preset.get("name", "PRESET")
    await callback.answer("Preset applied.")
    await callback.message.edit_text(
        f"⬛ <b>PRESET  //  APPLIED</b>\n"
        f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"LOADED {pname.upper()[:24]}\n"
        f"STATUS settings overwritten\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>",
        reply_markup=build_back_to_sniper(),
    )


@router.callback_query(F.data.startswith("sniper:preset_del:"))
async def cb_preset_delete(callback: CallbackQuery) -> None:
    raw     = callback.data.split("sniper:preset_del:")[-1]
    user_id = callback.from_user.id
    if raw.startswith("tpl_"):
        await callback.answer("Built-in templates cannot be deleted.", show_alert=True)
        return
    success = await delete_preset(int(raw), user_id)
    if success:
        await callback.answer("Preset deleted.")
        await callback.message.edit_text(
            "⬛ <b>PRESET  //  DELETED</b>\n"
            "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "STATUS  preset removed\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>",
            reply_markup=build_back_to_sniper(),
        )
    else:
        await callback.answer("Not found.", show_alert=True)


_TWITTER_HASHTAG_URL = "https://x.com/hashtag/BRAINROTALPHABOTPRESET"

@router.callback_query(F.data.startswith("sniper:preset_share:"))
async def cb_preset_share(callback: CallbackQuery) -> None:
    from urllib.parse import quote
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    from services.auto_exit_service import get_preset as get_exit_preset

    raw     = callback.data.split("sniper:preset_share:")[-1]
    user_id = callback.from_user.id
    preset  = await get_preset(int(raw), user_id)
    if not preset:
        await callback.answer("Preset not found.", show_alert=True)
        return

    # Fetch user's active exit preset for exit strategy info
    exit_p    = None
    exit_name = "custom"
    try:
        from database.sqlite_db import get_db
        async with get_db() as db:
            async with db.execute(
                "SELECT selected_preset_id FROM auto_exit_settings WHERE user_id = ?",
                (user_id,)
            ) as cur:
                row = await cur.fetchone()
        if row and row[0]:
            exit_p    = await get_exit_preset(row[0])
            exit_name = exit_p["name"] if exit_p else "custom"
    except Exception:
        pass

    pnl_stats = await get_preset_pnl(user_id, preset["id"])
    pnl    = pnl_stats.get("total_pnl", 0.0) or 0.0
    trades = pnl_stats.get("trades", 0) or 0
    wins   = pnl_stats.get("wins", 0) or 0
    losses = pnl_stats.get("losses", 0) or 0
    wr     = pnl_stats.get("win_rate", 0.0) or 0.0
    sign   = "+" if pnl >= 0 else ""
    pname  = preset["name"]
    strat  = (preset.get("strategy_mode") or "none").upper()

    # Exit info lines (only if we have an exit preset)
    if exit_p:
        tp1_pct  = exit_p.get("tp1_pct") or 0
        tp1_sell = exit_p.get("tp1_sell_pct") or 0
        tp2_pct  = exit_p.get("tp2_pct") or 0
        sl_pct   = exit_p.get("sl_pct") or 0
        trail    = exit_p.get("trailing_stop_pct") or 0
        hold     = exit_p.get("max_hold_minutes") or 0
        exit_line = (
            f"EXIT: {exit_name}\n"
            f"TP1: +{tp1_pct:.0f}% sell {tp1_sell:.0f}% | "
            f"TP2: +{tp2_pct:.0f}% | "
            f"SL: {sl_pct:.0f}% | "
            f"TRAIL: {trail:.0f}% | "
            f"HOLD: {hold}m\n"
        )
    else:
        exit_line = f"EXIT: {exit_name}\n"

    # ── Tweet (Twitter threads would allow more — single tweet stays under 280) ──
    tweet = (
        f"#BRAINROTALPHABOTPRESET\n"
        f"PRESET: {pname}\n"
        f"P&L: {sign}{pnl:.4f} SOL | {trades}T | {wr:.0f}%WR ({wins}W/{losses}L)\n"
        f"ENTRY: LIQ ${preset.get('min_liquidity',0):,.0f} | "
        f"VOL ${preset.get('min_volume',0):,.0f} | "
        f"BUYS {preset.get('min_buys',0)} | "
        f"AGE {preset.get('max_token_age_minutes',0)}m\n"
        f"BUY: {preset.get('default_buy_size',0)} SOL | "
        f"SLIP {preset.get('default_slippage',0):.0f}% | "
        f"STRAT {strat}\n"
        + exit_line +
        f"Drop your results 👇 #Solana #crypto"
    )

    # Trim to 280 chars if needed, keeping hashtag intact
    if len(tweet) > 280:
        tweet = tweet[:277] + "..."

    tweet_url  = f"https://x.com/intent/tweet?text={quote(tweet)}"
    tg_url     = f"https://t.me/share/url?url={quote(_bot_link(), safe='')}&text={quote(tweet)}"
    reddit_url = f"https://www.reddit.com/submit?title={quote(f'$BRAINROT Preset: {pname}', safe='')}&text={quote(tweet, safe='')}"

    # ── Preview shown inside the bot ─────────────────────────────────────────
    preview_exit = ""
    if exit_p:
        preview_exit = (
            f"EXIT PRESET  {exit_name}\n"
            f"TP1  +{tp1_pct:.0f}% → sell {tp1_sell:.0f}%\n"
            f"TP2  +{tp2_pct:.0f}%\n"
            f"SL   {sl_pct:.0f}%\n"
            f"TRAIL {trail:.0f}%  HOLD {hold}m\n"
        )

    confirm = (
        f"<code>╔══════════════════════════════╗\n"
        f"║  🌐  SHARE PRESET  //  {pname[:16]:<16}║\n"
        f"╚══════════════════════════════╝\n"
        f"━━━━━━  PERFORMANCE  ━━━━━━━━━━\n"
        f"P&L     {sign}{pnl:.5f} SOL\n"
        f"TRADES  {trades}  |  WR {wr:.0f}%  ({wins}W / {losses}L)\n"
        f"━━━━━━  ENTRY  ━━━━━━━━━━━━━━━━\n"
        f"LIQ    ${preset.get('min_liquidity',0):>9,.0f}\n"
        f"VOL    ${preset.get('min_volume',0):>9,.0f}\n"
        f"BUYS   {preset.get('min_buys',0):>10}\n"
        f"AGE    {preset.get('max_token_age_minutes',0):>8}m\n"
        f"SIZE   {preset.get('default_buy_size',0):>8} SOL\n"
        f"SLIP   {preset.get('default_slippage',0):>8.0f}%\n"
        f"STRAT  {strat:>10}\n"
        + (f"━━━━━━  EXIT  ━━━━━━━━━━━━━━━━━\n{preview_exit}" if preview_exit else "")
        + f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
        f"Pick a platform to share your preset.\n"
        f"Use <code>#BRAINROTONCHAINBOT</code> so the community\n"
        f"can find your strategy and give feedback."
    )

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🐦 POST ON X",         url=tweet_url),
        InlineKeyboardButton(text="✈️ TELEGRAM",           url=tg_url),
    )
    kb.row(
        InlineKeyboardButton(text="🟠 REDDIT",             url=reddit_url),
        InlineKeyboardButton(text="# COMMUNITY HASHTAG",  url=_TWITTER_HASHTAG_URL),
    )
    kb.row(InlineKeyboardButton(text="⬅️  BACK TO PRESET", callback_data=f"sniper:preset_view:{raw}"))
    await callback.message.edit_text(confirm, reply_markup=kb.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "sniper:preset_create")
async def cb_preset_create_start(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    count   = await count_presets(user_id)


    await state.set_state(CreatePresetState.waiting_name)
    await callback.message.answer(
        "⬛ <b>PRESET  //  CREATE NEW</b>\n"
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "ACTION  snapshot current settings\n"
        "INPUT   enter preset name below\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        "<i>Type a name (2–32 chars) and send:</i>",
        reply_markup=build_cancel_sniper(),
    )
    await callback.answer()


@router.message(CreatePresetState.waiting_name)
async def fsm_preset_name(message: Message, state: FSMContext) -> None:
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    name = message.text.strip()
    if len(name) < 2:
        await message.answer(
            "⬛ <b>PRESET  //  ERROR</b>\n"
            "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "ERR  name too short (min 2 chars)\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>",
            reply_markup=build_cancel_sniper(),
        )
        return
    if len(name) > 32:
        name = name[:32]

    data    = await state.get_data()
    source  = data.get("save_source", "sniper")
    await state.clear()
    user_id = message.from_user.id
    try:
        s = await get_settings(user_id)
        # If saving from auto-buy page, merge auto-buy settings into the snapshot
        if source == "autobuy":
            ab = await get_auto_buy_settings(user_id)
            s.update({k: ab[k] for k in (
                "score_threshold", "max_buy_size_sol", "slippage",
                "max_buys_per_hour", "cooldown_seconds", "priority_fee",
                "min_initial_buy_sol",
            ) if k in ab})
        pid = await create_preset_from_settings(user_id, name, s)
        kb  = InlineKeyboardBuilder()
        back_cb = "sniper:autobuy" if source == "autobuy" else "sniper:presets"
        kb.row(InlineKeyboardButton(text="📂 MY SAVED PRESETS", callback_data="sniper:ab_load_presets" if source == "autobuy" else "sniper:presets"))
        kb.row(InlineKeyboardButton(text="⬅️  BACK", callback_data=back_cb))
        await message.answer(
            f"💾 <b>PRESET SAVED</b>\n"
            f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"NAME   {name.upper()[:24]}\n"
            f"ID     #{pid}\n"
            f"STATUS all auto-buy settings stored\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>",
            reply_markup=kb.as_markup(),
        )
    except Exception as e:
        logger.error(f"fsm_preset_name error: {e}", exc_info=True)
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="⬅️  BACK TO PRESETS", callback_data="sniper:presets"))
        await message.answer(
            "⬛ <b>PRESET  //  SAVE FAILED</b>\n"
            "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "ERR  could not save preset\n"
            "     please try again\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>",
            reply_markup=kb.as_markup(),
        )


# ══════════════════════════════════════════════════════════════════════════════
# E. WATCH TARGETS
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "sniper:watch")
async def cb_watch(callback: CallbackQuery) -> None:
    import asyncio
    user_id = callback.from_user.id
    targets = await get_watch_targets(user_id)
    count   = len(targets)

    # Boot animation
    msg = await callback.message.edit_text(
        "<code>█░░░░░░░░░ LOADING WATCH TARGETS...</code>",
        parse_mode="HTML",
    )
    await asyncio.sleep(0.4)
    await msg.edit_text(
        "<code>██████░░░░ SCANNING ALERTS...</code>",
        parse_mode="HTML",
    )
    await asyncio.sleep(0.35)

    active_alerts = sum(1 for t in targets if t.get("alert_enabled", 1))

    text = (
        "╔══════════════════════════════╗\n"
        "║   👁 <b>WATCH TARGETS</b>           ║\n"
        "╚══════════════════════════════╝\n\n"
        f"<code>┌─ STATUS ─────────────────────────┐\n"
        f"│  WATCHING   {count:<3} tokens              │\n"
        f"│  ALERTS ON  {active_alerts:<3} tokens             │\n"
        f"└──────────────────────────────────┘</code>\n\n"
        "<code>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</code>\n"
        "Add a token CA → set drop/pump alert %\n"
        "→ get notified + quick buy button in DM.\n"
        "<code>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</code>\n\n"
        "<i>Tap a token to configure its alert settings.</i>"
    )

    await msg.edit_text(
        text,
        reply_markup=build_watch_targets_main(targets),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sniper:wt_detail:"))
async def cb_wt_detail(callback: CallbackQuery) -> None:
    row_id  = int(callback.data.split(":")[-1])
    user_id = callback.from_user.id
    t = await get_watch_target_by_id(row_id, user_id)
    if not t:
        await callback.answer("Watch target not found.", show_alert=True)
        return

    addr       = t["token_address"]
    short      = addr[:6] + "..." + addr[-4:]
    sym        = t.get("token_symbol") or short
    drop_pct   = t.get("alert_drop_pct")  or 20.0
    pump_pct   = t.get("alert_pump_pct")  or 100.0
    buy_sol    = t.get("quick_buy_sol")   or 0.05
    entry      = float(t.get("entry_price_sol") or 0)
    last       = float(t.get("last_price_sol")  or 0)
    alert_icon = "🔔 ON" if t.get("alert_enabled", 1) else "🔕 OFF"

    change_line = ""
    if entry > 0 and last > 0:
        pct = (last - entry) / entry * 100
        sign = "+" if pct >= 0 else ""
        change_line = f"│  CHANGE   {sign}{pct:.1f}% from entry      │\n"

    text = (
        "╔══════════════════════════════╗\n"
        f"║   👁 <b>WATCH TARGET</b>            ║\n"
        "╚══════════════════════════════╝\n\n"
        f"<code>┌─ TOKEN ──────────────────────────┐\n"
        f"│  {sym[:26]:<26}  │\n"
        f"│  {short:<34}│\n"
        f"└──────────────────────────────────┘\n\n"
        f"┌─ ALERT SETTINGS ─────────────────┐\n"
        f"│  ALERTS    {alert_icon:<22}│\n"
        f"│  DROP AT   ↓{drop_pct:.0f}%{'':<21}│\n"
        f"│  PUMP AT   ↑{pump_pct:.0f}%{'':<21}│\n"
        f"│  QUICK BUY {buy_sol:.4f} SOL             │\n"
        + change_line +
        f"└──────────────────────────────────┘</code>\n\n"
        f"<i>Configure alerts below. You'll get a DM with\n"
        f"a quick buy button when the threshold is hit.</i>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=build_watch_target_detail(t),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sniper:wt_toggle:"))
async def cb_wt_toggle(callback: CallbackQuery) -> None:
    row_id  = int(callback.data.split(":")[-1])
    user_id = callback.from_user.id
    t = await get_watch_target_by_id(row_id, user_id)
    if not t:
        await callback.answer("Not found.", show_alert=True)
        return
    new_val = 0 if t.get("alert_enabled", 1) else 1
    await update_watch_target_field(row_id, user_id, "alert_enabled", new_val)
    await callback.answer("🔔 Alerts ON" if new_val else "🔕 Alerts OFF", show_alert=False)
    # Refresh detail
    t["alert_enabled"] = new_val
    await cb_wt_detail.__wrapped__(callback) if hasattr(cb_wt_detail, "__wrapped__") else None
    # Re-fetch and re-render
    updated = await get_watch_target_by_id(row_id, user_id)
    if updated:
        callback.data = f"sniper:wt_detail:{row_id}"
        await cb_wt_detail(callback)


@router.callback_query(F.data.startswith("sniper:wt_set_drop:"))
async def cb_wt_set_drop(callback: CallbackQuery, state: FSMContext) -> None:
    row_id = int(callback.data.split(":")[-1])
    await state.set_state("WatchTargetSetDrop")
    await state.update_data(wt_row_id=row_id)
    await callback.message.edit_text(
        "📉 <b>Set Drop Alert %</b>\n\n"
        "Enter the % drop that triggers an alert.\n"
        "Example: <code>20</code> = alert when price drops 20%.\n\n"
        "Reply with a number (1–90):",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sniper:wt_set_pump:"))
async def cb_wt_set_pump(callback: CallbackQuery, state: FSMContext) -> None:
    row_id = int(callback.data.split(":")[-1])
    await state.set_state("WatchTargetSetPump")
    await state.update_data(wt_row_id=row_id)
    await callback.message.edit_text(
        "📈 <b>Set Pump Alert %</b>\n\n"
        "Enter the % pump that triggers an alert.\n"
        "Example: <code>100</code> = alert when price 2x.\n\n"
        "Reply with a number (10–10000):",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sniper:wt_set_buy:"))
async def cb_wt_set_buy(callback: CallbackQuery, state: FSMContext) -> None:
    row_id = int(callback.data.split(":")[-1])
    await state.set_state("WatchTargetSetBuy")
    await state.update_data(wt_row_id=row_id)
    await callback.message.edit_text(
        "💰 <b>Set Quick Buy Amount</b>\n\n"
        "Enter SOL amount for the quick buy button in alerts.\n"
        "Example: <code>0.05</code>\n\n"
        "Reply with an amount (0.001–5):",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(StateFilter("WatchTargetSetDrop"))
async def fsm_wt_drop(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    row_id = data.get("wt_row_id")
    try:
        val = float(message.text.strip().replace("%", ""))
        if not 1 <= val <= 90:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Enter a number between 1 and 90.", parse_mode="HTML")
        return
    await state.clear()
    ok = await update_watch_target_field(row_id, message.from_user.id, "alert_drop_pct", val)
    await message.answer(
        f"✅ Drop alert set to <b>↓{val:.0f}%</b>",
        parse_mode="HTML",
    )


@router.message(StateFilter("WatchTargetSetPump"))
async def fsm_wt_pump(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    row_id = data.get("wt_row_id")
    try:
        val = float(message.text.strip().replace("%", ""))
        if not 10 <= val <= 10000:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Enter a number between 10 and 10000.", parse_mode="HTML")
        return
    await state.clear()
    await update_watch_target_field(row_id, message.from_user.id, "alert_pump_pct", val)
    await message.answer(
        f"✅ Pump alert set to <b>↑{val:.0f}%</b>",
        parse_mode="HTML",
    )


@router.message(StateFilter("WatchTargetSetBuy"))
async def fsm_wt_buy(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    row_id = data.get("wt_row_id")
    try:
        val = float(message.text.strip())
        if not 0.001 <= val <= 5:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Enter a SOL amount between 0.001 and 5.", parse_mode="HTML")
        return
    await state.clear()
    await update_watch_target_field(row_id, message.from_user.id, "quick_buy_sol", val)
    await message.answer(
        f"✅ Quick buy set to <b>{val:.4f} SOL</b>",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "sniper:watch_add_manual")
async def cb_watch_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    count   = await count_watch_targets(user_id)


    await state.set_state(AddWatchTargetState.waiting_address)
    await callback.message.answer(
        "👁 Enter the token address to watch:",
        reply_markup=build_cancel_sniper(),
    )
    await callback.answer()


# Watch add from feed/analysis shortcuts
@router.callback_query(F.data.startswith("sniper:watch_add:"))
async def cb_watch_add_cached(callback: CallbackQuery) -> None:
    key     = callback.data.split("sniper:watch_add:")[-1]
    address = get_cached_address(key)
    if not address:
        await callback.answer("Token reference expired. Re-analyze to add.", show_alert=True)
        return
    user_id = callback.from_user.id
    count   = await count_watch_targets(user_id)
    ok, msg = await add_watch_target(user_id, address)
    await callback.answer(msg, show_alert=not ok)


@router.message(AddWatchTargetState.waiting_address)
async def fsm_watch_address(message: Message, state: FSMContext) -> None:
    address = message.text.strip()
    if not is_valid_solana_address(address):
        await message.answer("❌ Invalid address.", reply_markup=build_cancel_sniper())
        return
    await state.clear()
    ok, msg = await add_watch_target(message.from_user.id, address)
    await message.answer(f"{'✅' if ok else '❌'} {msg}")


@router.callback_query(F.data.startswith("sniper:watch_rm:"))
async def cb_watch_remove(callback: CallbackQuery) -> None:
    row_id = int(callback.data.split("sniper:watch_rm:")[-1])
    ok     = await remove_watch_target(row_id, callback.from_user.id)
    if ok:
        targets = await get_watch_targets(callback.from_user.id)
        await callback.message.edit_text(
            f"👁 <b>Watch Targets</b>\n"
            f"Saved: {len(targets)}",
            reply_markup=build_watch_list(targets),
        )
    await callback.answer("Removed." if ok else "Not found.")


# ══════════════════════════════════════════════════════════════════════════════
# F. BLACKLIST
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "sniper:blacklist")
async def cb_blacklist(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    entries = await get_blacklist(user_id)
    await callback.message.edit_text(
        text=(
            f"🚫 <b>Blacklist</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Blacklisted: {len(entries)}\n\n"
            f"<i>Tap a token to remove it. These tokens are hidden from your feed.</i>"
        ),
        reply_markup=build_blacklist_menu(entries),
    )
    await callback.answer()


@router.callback_query(F.data == "sniper:bl_add_manual")
async def cb_bl_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    count   = await count_blacklist(user_id)
    await state.set_state(AddBlacklistState.waiting_address)
    await callback.message.answer("🚫 Enter token address to blacklist:", reply_markup=build_cancel_sniper())
    await callback.answer()


@router.callback_query(F.data.startswith("sniper:bl_add:"))
async def cb_bl_add_cached(callback: CallbackQuery) -> None:
    key     = callback.data.split("sniper:bl_add:")[-1]
    address = get_cached_address(key)
    if not address:
        await callback.answer("Reference expired.", show_alert=True)
        return
    user_id = callback.from_user.id
    count   = await count_blacklist(user_id)
    ok, msg = await add_to_blacklist(user_id, address)
    await callback.answer(msg, show_alert=not ok)


@router.message(AddBlacklistState.waiting_address)
async def fsm_bl_address(message: Message, state: FSMContext) -> None:
    address = message.text.strip()
    if not is_valid_solana_address(address):
        await message.answer("❌ Invalid address.", reply_markup=build_cancel_sniper())
        return
    await state.update_data(bl_address=address)
    await state.set_state(AddBlacklistState.waiting_label)
    await message.answer(
        "📝 Enter a name/label for this token (e.g. <code>FARTCOIN</code>), or type <code>skip</code>:",
        parse_mode="HTML",
        reply_markup=build_cancel_sniper(),
    )


@router.message(AddBlacklistState.waiting_label)
async def fsm_bl_label(message: Message, state: FSMContext) -> None:
    raw   = message.text.strip()
    label = "" if raw.lower() == "skip" else raw
    data  = await state.get_data()
    address = data.get("bl_address", "")
    await state.clear()
    ok, msg = await add_to_blacklist(message.from_user.id, address, label)
    await message.answer(f"{'✅' if ok else '❌'} {msg}")


@router.callback_query(F.data.startswith("sniper:bl_rm:"))
async def cb_bl_remove(callback: CallbackQuery) -> None:
    row_id  = int(callback.data.split("sniper:bl_rm:")[-1])
    ok      = await remove_from_blacklist(row_id, callback.from_user.id)
    entries = await get_blacklist(callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=build_blacklist_menu(entries))
    await callback.answer("Removed." if ok else "Not found.")


@router.callback_query(F.data == "sniper:dup_creators")
async def cb_dup_creators(callback: CallbackQuery) -> None:
    """Show deployers who have launched multiple tokens with similar names this session."""
    from services.auto_buy_worker import get_duplicate_creators
    from services.sniper_blacklist_service import add_creator_to_blacklist, get_creator_blacklist
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    user_id  = callback.from_user.id
    dupes    = get_duplicate_creators(min_launches=2)
    bl       = await get_creator_blacklist(user_id)
    bl_addrs = {e["creator_address"] for e in bl}

    b = InlineKeyboardBuilder()
    if not dupes:
        text = (
            "🔍 <b>Duplicate Creators</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<i>No duplicate deployers detected this session.\n"
            "Creators who launch 2+ tokens with similar names will appear here.</i>"
        )
    else:
        lines = ["🔍 <b>Duplicate Creators</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
        for d in dupes[:15]:
            addr    = d["creator"]
            short   = addr[:6] + "..." + addr[-4:]
            blocked = "🚫 " if addr in bl_addrs else ""
            names   = ", ".join(d["names"][:3])
            lines.append(f"{blocked}<code>{short}</code>  {d['count']} tokens\n  <i>{names}</i>")
            if addr not in bl_addrs:
                b.row(InlineKeyboardButton(
                    text=f"🚫 Block {short}",
                    callback_data=f"sniper:bl_creator:{addr}",
                ))
        text = "\n".join(lines)

    b.row(InlineKeyboardButton(text="🔄 Refresh", callback_data="sniper:dup_creators"))
    b.row(InlineKeyboardButton(text="📋 Creator Blacklist", callback_data="sniper:creator_bl_list"))
    b.row(InlineKeyboardButton(text="⬅️  Back", callback_data="sniper:blacklist"))
    try:
        await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("sniper:bl_creator:"))
async def cb_bl_creator(callback: CallbackQuery) -> None:
    from services.sniper_blacklist_service import add_creator_to_blacklist
    user_id        = callback.from_user.id
    creator_addr   = callback.data.split("sniper:bl_creator:")[-1]
    ok, msg        = await add_creator_to_blacklist(user_id, creator_addr, note="flagged duplicate deployer")
    await callback.answer(f"{'✅' if ok else '⚠️'} {msg}", show_alert=True)
    await cb_dup_creators(callback)


@router.callback_query(F.data == "sniper:creator_bl_list")
async def cb_creator_bl_list(callback: CallbackQuery) -> None:
    from services.sniper_blacklist_service import get_creator_blacklist, remove_creator_from_blacklist
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    user_id = callback.from_user.id
    bl      = await get_creator_blacklist(user_id)

    b = InlineKeyboardBuilder()
    if not bl:
        text = (
            "🚫 <b>Creator Blacklist</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<i>No creators blacklisted yet.\n"
            "Block deployers from the Duplicate Creators page.</i>"
        )
    else:
        lines = ["🚫 <b>Creator Blacklist</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
        for e in bl:
            addr  = e["creator_address"]
            short = addr[:6] + "..." + addr[-4:]
            note  = e.get("note") or ""
            lines.append(f"<code>{short}</code>  <i>{note}</i>")
            b.row(InlineKeyboardButton(
                text=f"❌ Remove {short}",
                callback_data=f"sniper:rm_creator:{e['id']}",
            ))
        text = "\n".join(lines)

    b.row(InlineKeyboardButton(text="⬅️  Back", callback_data="sniper:dup_creators"))
    try:
        await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("sniper:rm_creator:"))
async def cb_rm_creator(callback: CallbackQuery) -> None:
    from services.sniper_blacklist_service import remove_creator_from_blacklist
    row_id = int(callback.data.split("sniper:rm_creator:")[-1])
    ok     = await remove_creator_from_blacklist(row_id, callback.from_user.id)
    await callback.answer("Removed." if ok else "Not found.")
    await cb_creator_bl_list(callback)


# ══════════════════════════════════════════════════════════════════════════════
# G. TRADE PREVIEW
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "sniper:preview")
async def cb_preview_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TradePreviewState.waiting_address)
    await callback.message.answer(
        "📋 <b>Trade Preview</b>\n\nPaste the token address to preview a trade:",
        reply_markup=build_cancel_sniper(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sniper:preview_token:"))
async def cb_preview_cached(callback: CallbackQuery) -> None:
    key     = callback.data.split("sniper:preview_token:")[-1]
    address = get_cached_address(key)
    if not address:
        await callback.answer("Reference expired. Re-analyze token.", show_alert=True)
        return
    await _show_trade_preview(callback.from_user.id, address, callback.message)
    await callback.answer()


@router.message(TradePreviewState.waiting_address)
async def fsm_preview_address(message: Message, state: FSMContext) -> None:
    address = message.text.strip()
    if not is_valid_solana_address(address):
        await message.answer("❌ Invalid address.", reply_markup=build_cancel_sniper())
        return
    await state.clear()
    await _show_trade_preview(message.from_user.id, address, message)


async def _show_trade_preview(user_id: int, address: str, msg_or_cb) -> None:
    settings = await get_settings(user_id)
    result   = await analyze_token_for_user(user_id, address)

    if "error" in result:
        text = f"❌ {result['error']}"
    else:
        t      = result["token"]
        score  = result["score"]
        risks  = result.get("risk_notes", [])
        risk_s = "\n".join(f"⚠️ {r}" for r in risks) if risks else "None"
        text   = (
            f"📋 <b>Trade Preview</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>Token:</b> {t.get('symbol','?')} — {t.get('name','?')}\n"
            f"<code>{address}</code>\n\n"
            f"<b>Buy Size:</b>  {settings.get('default_buy_size', 0.05)} SOL\n"
            f"<b>Slippage:</b>  {settings.get('default_slippage', 15)}%\n"
            f"<b>Liquidity:</b> ${t.get('liquidity_usd',0):,.0f}\n"
            f"<b>Volume 1h:</b> ${t.get('volume_h1',0):,.0f}\n"
            f"<b>Score:</b>    {score}/100 — {result['rating']}\n\n"
            f"<b>Risk Notes:</b>\n{risk_s}\n\n"
            f"<i>⚠️ This is a preview only. No transaction has been sent.</i>"
        )

    from aiogram.types import Message as TgMessage
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    cache_key = cache_address(address)
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ Buy Now",       callback_data=f"sniper:buy_confirm:{cache_key}"),
        InlineKeyboardButton(text="⬅️ Back",          callback_data="sniper:main"),
    )

    if isinstance(msg_or_cb, TgMessage):
        await msg_or_cb.answer(text, reply_markup=b.as_markup())
    else:
        await msg_or_cb.edit_text(text, reply_markup=b.as_markup(), disable_web_page_preview=True)


@router.callback_query(F.data.startswith("sniper:buy_confirm:"))
async def cb_buy_confirm(callback: CallbackQuery) -> None:
    from services.solana_execution_service import execute_buy
    from services.bot_wallet_service import get_or_create_bot_wallet, get_sol_balance as _bal

    user_id   = callback.from_user.id
    cache_key = callback.data.split("sniper:buy_confirm:")[-1]
    address   = get_cached_address(cache_key)
    if not address:
        await callback.answer("Reference expired. Re-analyze the token.", show_alert=True)
        return

    s        = await get_settings(user_id)
    buy_size = float(s.get("default_buy_size") or 0.05)
    slippage = float(s.get("default_slippage") or 15.0)

    # Check bot wallet balance
    try:
        row     = await get_or_create_bot_wallet(user_id)
        balance = await _bal(row["wallet_address"])
    except RuntimeError as e:
        await callback.answer(str(e), show_alert=True)
        return

    if balance is None or balance < buy_size + 0.001:
        bal_s = f"{balance:.5f}" if balance is not None else "unknown"
        await callback.answer(
            f"Insufficient SOL. Wallet has {bal_s} SOL, need {buy_size + 0.001:.5f}.",
            show_alert=True,
        )
        return

    await callback.answer("⏳ Executing trade…")
    wait_msg = await callback.message.answer(
        f"⏳ Sending buy order…\n"
        f"Token: <code>{address}</code>\n"
        f"Size: {buy_size} SOL  |  Slippage: {slippage}%"
    )

    platform = s.get("preferred_platform") or "auto"
    result = await execute_buy(
        user_id       = user_id,
        token_address = address,
        amount_sol    = buy_size,
        slippage_pct  = slippage,
        platform      = platform,
    )

    if result["success"]:
        sig      = result["signature"]
        platform_used = result.get("platform_used", "Unknown")
        await wait_msg.edit_text(
            f"✅ <b>Buy Submitted!</b>\n\n"
            f"<b>Token:</b> <code>{address}</code>\n"
            f"<b>Size:</b> {buy_size} SOL\n"
            f"<b>Platform:</b> {platform_used}\n"
            f"<b>TX:</b> <code>{sig}</code>\n\n"
            f"<a href='https://solscan.io/tx/{sig}'>View on Solscan</a>\n\n"
            f"<i>Confirming on-chain — position will appear in Positions once confirmed.</i>",
            reply_markup=build_back_to_sniper(),
            disable_web_page_preview=True,
        )
    else:
        await wait_msg.edit_text(
            f"❌ <b>Trade Failed</b>\n\n"
            f"<b>Reason:</b> {result['error']}",
            reply_markup=build_back_to_sniper(),
        )


# ══════════════════════════════════════════════════════════════════════════════
# H. LIVE LAUNCH FEED
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "sniper:feed")
async def cb_live_feed(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id

    wait_msg = await callback.message.answer("📡 Fetching live launches...")

    feed_data = await get_feed_for_user(user_id)
    candidates = feed_data["candidates"]

    if not candidates:
        await wait_msg.edit_text(
            "📡 <b>Live Launch Feed</b>\n\nNo candidates matching your current settings.\n"
            "Try loosening your filters in Settings.",
            reply_markup=build_feed_nav(False),
        )
        await callback.answer()
        return

    header = (
        f"📡 <b>Live Launch Feed</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Showing {len(candidates)} ranked candidates \n"
    )
    await wait_msg.edit_text(header + "\n<i>Use buttons below each card to act.</i>")

    for i, token in enumerate(candidates[:10], 1):
        key  = cache_address(token.get("address", ""))
        card = format_token_card(token, i)
        await callback.message.answer(card, reply_markup=build_feed_card_actions(key))

    await callback.message.answer(
        f"{'─'*28}\n📡 End of feed — {len(candidates)} candidates shown.",
        reply_markup=build_feed_nav(True),
    )
    await callback.answer()


# Feed card quick actions
@router.callback_query(F.data.startswith("sniper:fa:"))
async def cb_feed_analyze(callback: CallbackQuery, state: FSMContext) -> None:
    key     = callback.data.split("sniper:fa:")[-1]
    address = get_cached_address(key)
    if not address:
        await callback.answer("Reference expired.", show_alert=True)
        return
    status = await callback.message.answer("⏳ Analyzing...")
    result = await analyze_token_for_user(callback.from_user.id, address)
    if "error" in result:
        await status.edit_text(f"❌ {result['error']}", reply_markup=build_back_to_sniper())
    else:
        new_key = cache_address(address)
        await status.edit_text(_fmt_analysis(result), reply_markup=build_token_actions(address, new_key))
    await callback.answer()


@router.callback_query(F.data.startswith("sniper:fp:"))
async def cb_feed_preview(callback: CallbackQuery) -> None:
    key     = callback.data.split("sniper:fp:")[-1]
    address = get_cached_address(key)
    if not address:
        await callback.answer("Reference expired.", show_alert=True)
        return
    await _show_trade_preview(callback.from_user.id, address, callback.message)
    await callback.answer()


@router.callback_query(F.data.startswith("sniper:fw:"))
async def cb_feed_watch(callback: CallbackQuery) -> None:
    key     = callback.data.split("sniper:fw:")[-1]
    address = get_cached_address(key)
    if not address:
        await callback.answer("Reference expired.", show_alert=True)
        return
    ok, msg = await add_watch_target(callback.from_user.id, address)
    await callback.answer(msg, show_alert=not ok)


@router.callback_query(F.data.startswith("sniper:fb:"))
async def cb_feed_blacklist(callback: CallbackQuery) -> None:
    key     = callback.data.split("sniper:fb:")[-1]
    address = get_cached_address(key)
    if not address:
        await callback.answer("Reference expired.", show_alert=True)
        return
    ok, msg = await add_to_blacklist(callback.from_user.id, address)
    await callback.answer(msg, show_alert=not ok)


# ══════════════════════════════════════════════════════════════════════════════
# I. SMART ALERTS
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "sniper:alerts")
async def cb_alerts(callback: CallbackQuery) -> None:
    user_id   = callback.from_user.id
    alert_cfg = await get_alert_settings(user_id)
    enabled   = bool(alert_cfg.get("enabled"))

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    toggle_label = "🔔 Disable Alerts" if enabled else "🔕 Enable Alerts"
    b.row(InlineKeyboardButton(text=toggle_label, callback_data="sniper:alert_toggle"))
    b.row(InlineKeyboardButton(text="⬅️  Back", callback_data="sniper:main"))

    basic_check  = "✅"
    smart_check  = "✅"
    adv_check    = "✅"

    await callback.message.edit_text(
        text=(
            f"🔔 <b>Smart Alerts</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Status: {'🟢 Enabled' if enabled else '🔴 Disabled'}\n\n"
            f"{basic_check} Basic Alerts\n"
            f"{smart_check} Settings-Match Alerts\n"
            f"{adv_check}  Watch Target Alerts\n"
            f"{smart_check} Ranked Candidate Alerts\n\n"
        ),
        reply_markup=b.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "sniper:alert_toggle")
async def cb_alert_toggle(callback: CallbackQuery) -> None:
    new_state = await toggle_alerts(callback.from_user.id)
    await callback.answer(f"Alerts {'enabled' if new_state else 'disabled'}.")
    await cb_alerts(callback)


# ══════════════════════════════════════════════════════════════════════════════
# J. AUTO-BUY
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "sniper:autobuy")
async def cb_autobuy(callback: CallbackQuery) -> None:
    import asyncio
    from services.bot_wallet_service import get_or_create_bot_wallet, get_sol_balance as _bal

    user_id = callback.from_user.id

    # Boot sequence
    frames = [
        "<code>▓░░░░░░░░░  BOOTING ENGINE...</code>",
        "<code>▓▓▓▓░░░░░░  LOADING CONFIG...</code>",
        "<code>▓▓▓▓▓▓▓░░░  CHECKING WALLET...</code>",
    ]
    for frame in frames:
        try:
            await callback.message.edit_text(frame, parse_mode="HTML")
        except TelegramBadRequest:
            pass
        await asyncio.sleep(0.38)

    s    = await get_auto_buy_settings(user_id)

    # Wallet + balance
    try:
        row    = await get_or_create_bot_wallet(user_id)
        w_addr = row["wallet_address"]
        bal    = await _bal(w_addr)
        bal_f  = float(bal) if bal is not None else 0.0
        w_short_s = w_addr[:6] + "…" + w_addr[-4:]
    except Exception:
        w_addr    = ""
        w_short_s = "unavailable"
        bal_f     = 0.0

    bal_bar   = ("▓" * min(12, int(bal_f / 0.5 * 12))) + ("░" * max(0, 12 - min(12, int(bal_f / 0.5 * 12))))
    bal_s     = f"{bal_f:.5f} SOL"
    bal_warn  = "  ⚠️ LOW" if bal_f < 0.05 else ""

    # State
    enabled   = bool(s.get("enabled"))
    kill      = bool(s.get("kill_switch"))
    power_s   = "ONLINE  ✅" if (enabled and not kill) else ("KILL SW ⛔" if kill else "OFFLINE ❌")

    # Settings
    threshold  = int(s.get("score_threshold") or 30)
    buy_size   = float(s.get("max_buy_size_sol") or 0.05)
    max_hour   = int(s.get("max_buys_per_hour") or 3)
    slippage   = float(s.get("slippage") or 15.0)
    pfee       = float(s.get("priority_fee") or 0.005)
    cooldown   = int(s.get("cooldown_seconds") or 60)
    wallet_floor  = float(s.get("min_wallet_balance_sol") or 0.05)
    daily_limit   = float(s.get("daily_spend_limit_sol") or 0.0)
    min_mcap      = float(s.get("min_market_cap_usd") or 0.0)
    max_mcap      = float(s.get("max_market_cap_usd") or 0.0)

    cap_size   = "∞"
    cap_hour   = "∞"

    thresh_warn = "  ⚠️ VERY LOW — raise to 20+" if threshold < 5 else (
                  "  ⚠️ LOW" if threshold < 15 else "")

    text = (
        f"<code>"
        f"╔══════════════════════════════╗\n"
        f"║  🤖 AUTO-BUY ENGINE          ║\n"
        f"╚══════════════════════════════╝\n"
        f"POWER    {power_s}\n"
        f"WALLET   {w_short_s}\n"
        f"BALANCE  {bal_bar} {bal_s}{bal_warn}\n"
        f"──────────────────────────────\n"
        f"BUY SIZE  {buy_size} SOL   (cap {cap_size} SOL)\n"
        f"MAX/HOUR  {max_hour}         (cap {cap_hour})\n"
        f"SCORE ≥   {threshold}/100{thresh_warn}\n"
        f"SLIP      {slippage}%\n"
        f"PRIORITY  {pfee} SOL\n"
        f"COOLDOWN  {cooldown}s\n"
        f"FLOOR     {wallet_floor} SOL  (auto-stop)\n"
        f"DAILY LIM  {'OFF' if daily_limit == 0 else f'{daily_limit} SOL/24h'}\n"
        f"MCAP      {'OFF' if min_mcap == 0 else f'${min_mcap:,.0f}'} – {'∞' if max_mcap == 0 else f'${max_mcap:,.0f}'}\n"
        f"──────────────────────────────\n"
        f"FEED     PUMPPORTAL WEBSOCKET\n"
        f"SCAN     every 6 seconds\n"
        f"──────────────────────────────\n"
        f"HOW IT WORKS:\n"
        f"  Bot streams every new pump.fun\n"
        f"  launch in real-time. Each token\n"
        f"  is scored. If score ≥ threshold,\n"
        f"  token passes blacklist + balance\n"
        f"  checks, then auto-buys instantly.\n"
        f"  You get a Telegram alert per buy.\n"
        f"──────────────────────────────\n"
        f"QUICK PRESETS load all settings\n"
        f"at once. Fine-tune below them.\n"
        f"</code>"
    )

    kb = build_autobuy_menu(s)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "sniper:ab_toggle")
async def cb_ab_toggle(callback: CallbackQuery) -> None:
    import asyncio
    import services.auto_buy_worker as _worker
    user_id = callback.from_user.id
    new     = await toggle_auto_buy(user_id)
    if new:
        # Clear seen buffer so recent tokens are re-evaluated immediately
        _worker.reset_seen()
        await callback.answer("▶️ Auto-Buy ONLINE — scanning feed now. Kill switch cleared.", show_alert=True)
    else:
        await callback.answer(
            "⏹ Auto-Buy STOPPED.\n\nAny trade already mid-execution will still complete, "
            "but no new buys will be placed.",
            show_alert=True,
        )
    # Force a neutral frame so the page refresh always has a visible diff to edit
    try:
        await callback.message.edit_text(
            "<code>▓░░░░░░░░░  APPLYING...</code>", parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass
    await asyncio.sleep(0.3)
    await cb_autobuy(callback)


@router.callback_query(F.data == "sniper:ab_kill")
async def cb_ab_kill(callback: CallbackQuery) -> None:
    import asyncio
    new = await toggle_kill_switch(callback.from_user.id)
    await callback.answer(
        f"⛔ KILL SWITCH {'ARMED — all buys blocked' if new else 'CLEARED — buys allowed'}.",
        show_alert=True,
    )
    try:
        await callback.message.edit_text(
            "<code>▓░░░░░░░░░  APPLYING...</code>", parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass
    await asyncio.sleep(0.3)
    await cb_autobuy(callback)


@router.callback_query(F.data == "sniper:noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.in_({"sniper:ab_status", "sniper:ab_status_refresh"}))
async def cb_ab_status(callback: CallbackQuery) -> None:
    """Live scan status panel — shows session counters, filter breakdown, last activity."""
    import time as _time
    from urllib.parse import quote
    import services.auto_buy_worker as _worker
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    stats    = _worker.get_stats()
    running  = _worker._running

    def _ago(ts: float) -> str:
        if not ts:
            return "never"
        secs = int(_time.time() - ts)
        if secs < 60:   return f"{secs}s ago"
        if secs < 3600: return f"{secs // 60}m ago"
        return f"{secs // 3600}h ago"

    engine_s    = "🟢 SCANNING" if running else "🔴 OFFLINE"
    scan_age    = _ago(stats["last_scan_ts"])
    buy_age     = _ago(stats["last_buy_ts"])

    total_filtered = (
        stats["token_bl_blocked"] +
        stats["creator_bl_blocked"] +
        stats["creator_dupes_blocked"] +
        stats["name_dupes_blocked"] +
        stats["low_score_blocked"]
    )

    last_seen = stats["last_token_seen"] or "—"
    last_buy  = stats["last_buy_symbol"] or "—"

    # Filter rate bar — what % of tokens got blocked
    total_seen = max(1, stats["tokens_evaluated"])
    block_rate = int(total_filtered / total_seen * 10)
    block_bar  = "▓" * min(10, block_rate) + "░" * max(0, 10 - block_rate)

    # Buy success rate bar
    total_attempts = max(1, stats["buys_executed"] + stats["buys_failed"])
    success_rate   = int(stats["buys_executed"] / total_attempts * 10)
    success_bar    = "▓" * min(10, success_rate) + "░" * max(0, 10 - success_rate)

    text = (
        f"<code>"
        f"╔══════════════════════════════╗\n"
        f"║  📡 LIVE SCAN STATUS         ║\n"
        f"╚══════════════════════════════╝\n"
        f"ENGINE   {engine_s}\n"
        f"SCANS    #{stats['scans_completed']:,}   LAST {scan_age}\n"
        f"LAST TOK {last_seen}\n"
        f"──────────────────────────────\n"
        f"TOKENS EVALUATED  {stats['tokens_evaluated']:,}\n"
        f"──────────────────────────────\n"
        f"SPAM FILTER  {block_bar} {total_filtered:,} blocked\n"
        f"  DUPE NAME+WALLET  {stats['name_dupes_blocked']:>6}\n"
        f"  SERIAL DEPLOYER   {stats['creator_dupes_blocked']:>6}\n"
        f"  CREATOR BLACKLIST {stats['creator_bl_blocked']:>6}\n"
        f"  TOKEN BLACKLIST   {stats['token_bl_blocked']:>6}\n"
        f"  BELOW THRESHOLD   {stats['low_score_blocked']:>6}\n"
        f"  LOW BALANCE SKIP  {stats['low_balance_blocked']:>6}\n"
        f"──────────────────────────────\n"
        f"BUYS  {success_bar}  ✅{stats['buys_executed']} ❌{stats['buys_failed']}\n"
        f"LAST BUY  {buy_age}  [{last_buy}]\n"
        f"──────────────────────────────\n"
        f"Stats reset on each engine start\n"
        f"</code>"
    )

    # ── Share copy ────────────────────────────────────────────────────────────
    # Concise tweet — Twitter caps at 280 chars; this lands ~260
    tweet = (
        f"🤖 My $BRAINROT Alpha Bot just filtered {total_filtered:,} spam tokens "
        f"& executed {stats['buys_executed']} auto-buys this session!\n\n"
        f"📡 {stats['tokens_evaluated']:,} tokens scanned\n"
        f"✅ {stats['buys_executed']} buys | ❌ {stats['buys_failed']} failed\n\n"
        f"The smartest meme coin sniper on Telegram ⚡\n"
        f"{_bot_link()}\n\n"
        f"{_share_footer()}"
    )

    # Telegram forward share text (slightly fuller)
    tg_share = (
        f"🤖 $BRAINROT Alpha Bot — Live Auto-Sniper\n\n"
        f"📊 Session Stats:\n"
        f"  📡 Tokens scanned: {stats['tokens_evaluated']:,}\n"
        f"  🔍 Spam filtered:  {total_filtered:,}\n"
        f"  ✅ Buys executed:  {stats['buys_executed']}\n\n"
        f"The smartest meme coin sniper on Telegram — "
        f"go check it out 👇\n\n"
        f"{_share_footer()}"
    )
    bot_link = _bot_link()

    twitter_url  = f"https://x.com/intent/tweet?text={quote(tweet)}"
    telegram_url = f"https://t.me/share/url?url={quote(bot_link)}&text={quote(tg_share)}"
    reddit_url   = (
        f"https://www.reddit.com/submit"
        f"?title={quote('$BRAINROT Alpha Bot — AI Meme Coin Sniper on Telegram')}"
        f"&url={quote(bot_link)}"
    )

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔄 Refresh", callback_data="sniper:ab_status_refresh"))
    b.row(
        InlineKeyboardButton(text="𝕏  Share on X",        url=twitter_url),
        InlineKeyboardButton(text="✈️ Share on Telegram", url=telegram_url),
    )
    b.row(
        InlineKeyboardButton(text="🔴 Share on Reddit",   url=reddit_url),
        *_website_buttons(),
    )
    b.row(InlineKeyboardButton(text="⬅️  Back", callback_data="sniper:autobuy"))
    try:
        await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("sniper:ab_preset:"))
async def cb_ab_preset(callback: CallbackQuery) -> None:
    from utils.trade_presets import TRADE_PRESETS
    from services.sniper_settings_service import DEFAULTS as SNIPER_DEFAULTS

    key     = callback.data.split("sniper:ab_preset:")[-1]
    preset  = TRADE_PRESETS.get(key)
    if not preset:
        await callback.answer("Unknown preset.", show_alert=True)
        return

    user_id = callback.from_user.id

    # Apply sniper_settings fields
    sniper_fields = set(SNIPER_DEFAULTS.keys())
    for field, val in preset.items():
        if field in sniper_fields:
            await update_setting(user_id, field, val)

    # Apply auto_buy_settings fields
    ab_fields = {"score_threshold", "max_buy_size_sol", "slippage",
                 "max_buys_per_hour", "cooldown_seconds", "priority_fee"}
    for field in ab_fields:
        if field in preset:
            val = preset[field]
            if field == "max_buy_size_sol":
                val = float(val)
            if field == "max_buys_per_hour":
                val = int(val)
            await update_auto_buy_field(user_id, field, val)

    # Pause auto-buy and clear the seen buffer so the worker starts fresh
    # with the new preset settings. User must re-enable manually.
    await update_auto_buy_field(user_id, "enabled", 0)
    import services.auto_buy_worker as _worker
    _worker.reset_seen()

    await callback.answer(f"✅ {preset['label']} applied! Press ▶️ Power to start.", show_alert=True)
    # Refresh the auto-buy page
    await cb_autobuy(callback)


@router.callback_query(F.data == "sniper:ab_save_preset")
async def cb_ab_save_preset(callback: CallbackQuery, state: FSMContext) -> None:
    """Save current auto-buy settings as a named preset."""
    from utils.sniper_states import CreatePresetState
    await state.set_state(CreatePresetState.waiting_name)
    await state.update_data(save_source="autobuy")
    from bot.keyboards.sniper_menu import build_cancel_sniper
    await callback.message.answer(
        "💾 <b>SAVE PRESET</b>\n\nEnter a name for this preset:",
        parse_mode="HTML",
        reply_markup=build_cancel_sniper(),
    )
    await callback.answer()


@router.callback_query(F.data == "sniper:ab_load_presets")
async def cb_ab_load_presets(callback: CallbackQuery) -> None:
    """Show user's saved presets with load buttons, directly from the auto-buy page."""
    from services.sniper_presets_service import get_presets_with_pnl
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    user_id = callback.from_user.id
    presets = await get_presets_with_pnl(user_id)

    builder = InlineKeyboardBuilder()
    if not presets:
        text = "📂 <b>MY SAVED PRESETS</b>\n\nNo saved presets yet. Use <b>💾 SAVE CURRENT SETTINGS</b> to create one."
    else:
        lines = ["📂 <b>MY SAVED PRESETS</b>\n"]
        for p in presets:
            pnl   = p.get("total_pnl", 0.0)
            wr    = p.get("win_rate", 0.0)
            trades = p.get("trades", 0)
            pnl_s = f"{pnl:+.4f} SOL" if trades else "no trades yet"
            wr_s  = f"  {wr:.0f}% WR" if trades else ""
            lines.append(f"• <b>{p['name']}</b>  {pnl_s}{wr_s}")
            builder.row(
                InlineKeyboardButton(text=f"▶️ {p['name']}", callback_data=f"sniper:preset_load:{p['id']}"),
                InlineKeyboardButton(text="🗑",               callback_data=f"sniper:preset_del:{p['id']}"),
            )
        text = "\n".join(lines)

    builder.row(InlineKeyboardButton(text="⬅️ BACK", callback_data="sniper:autobuy"))
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("sniper:abset:"))
async def cb_abset_field(callback: CallbackQuery, state: FSMContext) -> None:
    field  = callback.data.split("sniper:abset:")[-1]
    labels = {
        "max_buy_size_sol":       "Max Buy Size (SOL)",
        "max_buys_per_hour":      "Max Buys Per Hour",
        "score_threshold":        "Score Threshold (1-100)",
        "slippage":               "Slippage (%)",
        "priority_fee":           "Priority Fee (SOL)",
        "cooldown_seconds":       "Cooldown (seconds)",
        "min_wallet_balance_sol": "Wallet Floor — Auto-Stop (SOL)\nBot will halt and kill-switch when balance drops to this.\nSet 0 to disable.",
        "daily_spend_limit_sol":  "Daily Spend Limit (SOL)\nMax SOL the bot can spend in a 24h rolling window.\nSet 0 to disable.",
        "min_market_cap_usd":     "Minimum Market Cap (USD)\nOnly buy tokens with market cap ABOVE this.\nExample: 50000 = $50K minimum.\nSet 0 to disable.",
        "max_market_cap_usd":     "Maximum Market Cap (USD)\nOnly buy tokens with market cap BELOW this.\nExample: 500000 = $500K maximum.\nSet 0 to disable.",
    }
    await state.set_state(EditSettingState.waiting_value)
    await state.update_data(field=f"__ab__{field}")
    await callback.message.answer(
        f"✏️ Enter new value for <b>{labels.get(field, field)}</b>:",
        reply_markup=build_cancel_sniper(),
    )
    await callback.answer()


@router.message(EditSettingState.waiting_value)
async def fsm_edit_setting_or_ab(message: Message, state: FSMContext) -> None:
    """Single handler for both sniper settings edits and auto-buy field edits."""
    data  = await state.get_data()
    field = data.get("field", "")
    raw   = message.text.strip() if message.text else ""

    # ── Expired session (bot was restarted, MemoryStorage wiped) ─────────────
    if not field:
        await state.clear()
        await message.answer(
            "⚠️ Session expired. Please tap the setting button again.",
            reply_markup=build_back_to_sniper(),
        )
        return

    # ── Auto-buy field (prefixed with __ab__) ─────────────────────────────────
    if field.startswith("__ab__"):
        real_field = field[6:]
        ab_int_fields = {"max_buys_per_hour", "cooldown_seconds"}
        try:
            value = int(raw) if real_field in ab_int_fields else float(raw)
        except ValueError:
            await message.answer("❌ Invalid number.", reply_markup=build_cancel_sniper())
            return
        await state.clear()
        await update_auto_buy_field(message.from_user.id, real_field, value)
        import services.auto_buy_worker as _worker
        _worker.reset_seen()
        # Send a minimal confirm then immediately re-render the auto-buy engine page
        await message.answer(f"✅ <b>{real_field}</b> → <code>{value}</code>", parse_mode="HTML")
        # Fake a callback to re-render the engine page in-place
        class _FakeCallback:
            message      = message
            from_user    = message.from_user
            data         = "sniper:autobuy"
            async def answer(self, *a, **kw): pass
        await cb_autobuy(_FakeCallback())
        return

    # ── Regular sniper settings field ─────────────────────────────────────────
    int_fields   = {"min_buys", "max_token_age_minutes", "max_risk_level"}
    float_fields = {"min_liquidity", "min_volume", "default_buy_size", "default_slippage"}
    error        = None
    value        = None

    try:
        if field in int_fields:
            value = int(raw)
            if field == "max_risk_level" and not (1 <= value <= 5):
                error = "Risk level must be 1–5."
            elif value < 0:
                error = "Value must be >= 0."
        elif field in float_fields:
            value = float(raw)
            if value < 0:
                error = "Value must be >= 0."
            if field == "default_slippage" and not (0.1 <= value <= 50):
                error = "Slippage must be 0.1–50%."
            if field == "default_buy_size" and value <= 0:
                error = "Buy size must be > 0."
        else:
            error = f"Unknown field '{field}'. Please tap the setting button again."
    except ValueError:
        error = "Please enter a valid number."

    if error:
        await message.answer(f"❌ {error}", reply_markup=build_cancel_sniper())
        return

    await state.clear()
    await update_setting(message.from_user.id, field, value)
    await message.answer(
        f"✅ <b>{field}</b> updated to <code>{value}</code>",
        reply_markup=build_back_to_sniper(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# J2. LIQUIDITY SNIPER
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "sniper:liq_sniper")
async def cb_liq_sniper(callback: CallbackQuery) -> None:
    from services.auto_buy_service import get_auto_buy_settings
    from services.auto_exit_service import get_preset
    ab_s = await get_auto_buy_settings(callback.from_user.id)
    min_buy  = float(ab_s.get("min_initial_buy_sol") or 0)
    active   = bool(ab_s.get("enabled")) and min_buy > 0
    ks       = bool(ab_s.get("kill_switch"))

    # Resolve exit preset name
    exit_preset_name = "None — tap to set"
    liq_exit_id = ab_s.get("liq_exit_preset_id")
    if liq_exit_id:
        p = await get_preset(int(liq_exit_id))
        if p:
            exit_preset_name = p["name"]

    status_line = "🟢 ACTIVE" if active and not ks else ("🔴 KILL SWITCH" if ks else "🔴 OFF")
    text = (
        f"⬛️ <b>Liquidity Sniper</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Status:</b>         {status_line}\n"
        f"<b>Min Initial Buy:</b> {min_buy} SOL\n"
        f"<b>Buy Size:</b>       {ab_s.get('max_buy_size_sol', 0.05)} SOL\n"
        f"<b>Priority Fee:</b>   {ab_s.get('priority_fee', 0.001)} SOL\n"
        f"<b>Slippage:</b>       {ab_s.get('slippage', 25.0)}%\n"
        f"<b>Exit Preset:</b>    {exit_preset_name}\n"
        f"<b>Platform:</b>       PumpFun (bonding curve)\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>How it works:</b>\n"
        f"• Monitors every new pump.fun launch in real-time\n"
        f"• Skips tokens where initial buy &lt; {min_buy} SOL\n"
        f"• Executes via high-priority PumpFun bonding curve tx\n"
        f"• Auto-Exit applies your exit preset on every confirmed buy\n\n"
        f"<i>Set exit preset → Apply Optimal Settings → Power ON</i>"
    )
    try:
        await callback.message.edit_text(
            text, reply_markup=build_liq_sniper_menu(ab_s, exit_preset_name)
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "sniper:liq_power")
async def cb_liq_power(callback: CallbackQuery) -> None:
    from services.auto_buy_service import get_auto_buy_settings, toggle_auto_buy
    ab_s = await get_auto_buy_settings(callback.from_user.id)
    min_buy = float(ab_s.get("min_initial_buy_sol") or 0)
    if min_buy <= 0 and not ab_s.get("enabled"):
        await callback.answer(
            "⚠️ Min Initial Buy is 0 — tap 'Apply Optimal Settings' first.",
            show_alert=True,
        )
        return
    new = await toggle_auto_buy(callback.from_user.id)
    import services.auto_buy_worker as _worker
    if new:
        _worker.reset_seen()
        await callback.answer("⬛️ Liquidity Sniper ▶️ STARTED", show_alert=True)
    else:
        _worker.reset_seen()
        await callback.answer("⬛️ Liquidity Sniper ⏹ STOPPED — seen buffer cleared.", show_alert=True)
    await cb_liq_sniper(callback)


@router.callback_query(F.data == "sniper:liq_activate")
async def cb_liq_activate(callback: CallbackQuery) -> None:
    """Apply the recommended Liquidity Sniper preset and pause for user to review."""
    from utils.trade_presets import TRADE_PRESETS
    from services.sniper_settings_service import DEFAULTS as SNIPER_DEFAULTS
    preset  = TRADE_PRESETS["liq_sniper"]
    user_id = callback.from_user.id

    # Apply sniper_settings fields
    sniper_fields = set(SNIPER_DEFAULTS.keys())
    for field, val in preset.items():
        if field in sniper_fields:
            await update_setting(user_id, field, val)

    # Apply auto_buy_settings fields
    ab_fields = {"score_threshold", "max_buy_size_sol", "slippage",
                 "max_buys_per_hour", "cooldown_seconds", "priority_fee",
                 "min_initial_buy_sol"}
    for field in ab_fields:
        if field in preset:
            await update_auto_buy_field(user_id, field, preset[field])

    # Disable auto-buy — user must press Power to start
    await update_auto_buy_field(user_id, "enabled", 0)
    import services.auto_buy_worker as _worker
    _worker.reset_seen()

    await callback.answer(
        "⬛️ Liquidity Sniper configured!\n"
        "Filter: 0.24 SOL initial buy\nPress Power to start.",
        show_alert=True,
    )
    await cb_liq_sniper(callback)


@router.callback_query(F.data == "sniper:liq_exit_preset")
async def cb_liq_exit_preset(callback: CallbackQuery) -> None:
    """Let user pick which exit preset the Liquidity Sniper will auto-apply."""
    from services.auto_exit_service import get_system_presets, get_user_presets, get_auto_exit_settings
    from services.auto_buy_service import get_auto_buy_settings, update_auto_buy_field
    import asyncio
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    sys_p, user_p, ab_s = await asyncio.gather(
        get_system_presets(),
        get_user_presets(callback.from_user.id),
        get_auto_buy_settings(callback.from_user.id),
    )
    current_id = ab_s.get("liq_exit_preset_id")
    all_p = sys_p + user_p
    b = InlineKeyboardBuilder()
    for p in all_p:
        tick = "✅ " if p["id"] == current_id else ""
        icon = "⭐" if p.get("is_system") else "📂"
        b.row(InlineKeyboardButton(
            text=f"{tick}{icon} {p['name']}",
            callback_data=f"sniper:liq_set_exit:{p['id']}",
        ))
    b.row(InlineKeyboardButton(text="⬅️  Back", callback_data="sniper:liq_sniper"))
    try:
        await callback.message.edit_text(
            "🚪 <b>Liquidity Sniper — Exit Preset</b>\n\n"
            "Choose the preset that auto-applies to every position the Liquidity Sniper opens.\n"
            "<i>Quick Flip = 2x take profit. Balanced = staged exits. Risk-Off = tight stop.</i>",
            reply_markup=b.as_markup(),
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("sniper:liq_set_exit:"))
async def cb_liq_set_exit(callback: CallbackQuery) -> None:
    from services.auto_buy_service import update_auto_buy_field
    from services.auto_exit_service import get_preset
    preset_id = int(callback.data.split("sniper:liq_set_exit:")[-1])
    await update_auto_buy_field(callback.from_user.id, "liq_exit_preset_id", preset_id)
    # Reset power — settings changed
    await update_auto_buy_field(callback.from_user.id, "enabled", 0)
    import services.auto_buy_worker as _worker
    _worker.reset_seen()
    p = await get_preset(preset_id)
    name = p["name"] if p else f"#{preset_id}"
    await callback.answer(f"✅ Exit preset set to: {name}\nPress Power to restart.", show_alert=True)
    await cb_liq_sniper(callback)


@router.callback_query(F.data == "sniper:liq_holdings")
async def cb_liq_holdings(callback: CallbackQuery) -> None:
    from services.auto_buy_service import get_liq_sniper_jobs
    jobs = await get_liq_sniper_jobs(callback.from_user.id, limit=25)

    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    if not jobs:
        text = (
            "📊 <b>Liquidity Sniper Holdings</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<i>No positions yet. Power on the Liquidity Sniper to start buying.</i>"
        )
    else:
        lines = ["📊 <b>Liquidity Sniper Holdings</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
        status_icons = {
            "queued":   "⏳",
            "executed": "✅",
            "failed":   "❌",
            "cancelled":"🚫",
        }
        for j in jobs:
            addr  = j["token_address"]
            short = addr[:6] + "..." + addr[-4:]
            icon  = status_icons.get(j["status"], "❓")
            ts    = str(j["created_at"])[:16] if j["created_at"] else "—"
            lines.append(
                f"{icon} <code>{short}</code>  {j['amount_sol']} SOL  "
                f"score={j['score']}  <i>{ts}</i>"
            )
        text = "\n".join(lines)

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔄 Refresh", callback_data="sniper:liq_holdings"))
    b.row(InlineKeyboardButton(text="⬅️  Back", callback_data="sniper:liq_sniper"))
    try:
        await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        pass
    await callback.answer()


# ══════════════════════════════════════════════════════════════════════════════
# K. WALLET
# ══════════════════════════════════════════════════════════════════════════════

async def _get_token_holdings(addr: str) -> list[dict]:
    """Fetch all SPL token accounts with non-zero balance for this wallet."""
    import aiohttp
    from utils.config import get_rpc_url
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                get_rpc_url(),
                json={
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getTokenAccountsByOwner",
                    "params": [
                        addr,
                        {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                        {"encoding": "jsonParsed"},
                    ],
                },
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json(content_type=None)
                accounts = data.get("result", {}).get("value", [])
                holdings = []
                for acct in accounts:
                    info = acct["account"]["data"]["parsed"]["info"]
                    ui   = float(info["tokenAmount"].get("uiAmount") or 0)
                    if ui > 0:
                        holdings.append({
                            "mint":   info["mint"],
                            "amount": ui,
                            "decimals": info["tokenAmount"].get("decimals", 0),
                        })
                return holdings
    except Exception:
        return []


async def _wallet_text_and_kb(user_id: int, show_key: bool = False):
    """Build wallet page text + keyboard. Shared by cb_wallet, cb_wallet_refresh, export, hide."""
    from services.bot_wallet_service import get_or_create_bot_wallet, get_sol_balance as _bal, get_keypair
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="⟳  REFRESH",       callback_data="sniper:wallet_refresh"),
        InlineKeyboardButton(text="▲  WITHDRAW SOL",  callback_data="sniper:withdraw"),
    )
    if show_key:
        b.row(InlineKeyboardButton(text="▣  HIDE  SECRET  KEY", callback_data="sniper:wallet_hide_key"))
    else:
        b.row(InlineKeyboardButton(text="▢  REVEAL  SECRET  KEY", callback_data="sniper:wallet_export"))
    b.row(InlineKeyboardButton(text="←  BACK", callback_data="sniper:main"))

    # Wallet row — always needed
    row  = await get_or_create_bot_wallet(user_id)
    addr = row["wallet_address"]

    # Balance — degraded on error, never blocks key
    try:
        balance = await _bal(addr)
        bal_s   = f"{balance:.6f} SOL" if balance is not None else "ERR  rpc timeout"
    except Exception:
        bal_s = "ERR  rpc timeout"

    # Holdings — empty on error
    try:
        holdings = await _get_token_holdings(addr)
    except Exception:
        holdings = []

    if holdings:
        token_lines = []
        for h in holdings[:10]:
            mint_short = h["mint"][:6] + ".." + h["mint"][-4:]
            amt   = h["amount"]
            amt_s = f"{amt:,.0f}" if amt >= 1 else f"{amt:.6f}"
            token_lines.append(f"  {mint_short}  {amt_s}")
        if len(holdings) > 10:
            token_lines.append(f"  ...+{len(holdings)-10} more")
        holdings_section = (
            f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"HOLDINGS  ({len(holdings)})\n"
            + "\n".join(token_lines) + "\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        )
    else:
        holdings_section = ""

    # Key block — fetched independently so balance/holdings errors never block it
    if show_key:
        privkey_b58 = str(get_keypair(row["encrypted_private_key"]))
        key_line = (
            f"<code>KEY </code>  <tg-spoiler><code>{privkey_b58}</code></tg-spoiler>\n"
            f"<i>⚠️ Never share — Phantom: Settings → Add Wallet → Import Key</i>\n"
        )
    else:
        key_line = ""

    addr_short = addr[:6] + ".." + addr[-4:]
    text = (
        f"⬛ <b>BOT  WALLET  //  SOLANA</b>\n"
        f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"BAL    {bal_s}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        f"<code>ADDR</code>  <tg-spoiler><code>{addr}</code></tg-spoiler>\n"
        f"<a href='https://solscan.io/account/{addr}'>↗ {addr_short} on Solscan</a>\n"
        f"{key_line}"
        f"{holdings_section}"
        f"<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"[1] tap ADDR to reveal + copy\n"
        f"[2] fund from any Solana wallet\n"
        f"[3] bot auto-signs all trades\n"
        f"[4] reveal KEY → import to Phantom\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>"
    )
    return text, b.as_markup()


@router.callback_query(F.data == "sniper:wallet")
async def cb_wallet(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    text, kb = await _wallet_text_and_kb(user_id)
    try:
        await callback.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except TelegramBadRequest:
        pass  # message unchanged — already showing latest
    await callback.answer()


@router.callback_query(F.data == "sniper:wallet_refresh")
async def cb_wallet_refresh(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    text, kb = await _wallet_text_and_kb(user_id)
    try:
        await callback.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
        await callback.answer("✅ Balance refreshed.")
    except TelegramBadRequest:
        await callback.answer("Balance unchanged.")


# ── Withdraw flow ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "sniper:withdraw")
async def cb_withdraw_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(WithdrawState.waiting_address)
    await callback.message.answer(
        "💸 <b>Withdraw SOL</b>\n\n"
        "Step 1 of 2 — Enter the <b>destination wallet address</b>\n"
        "<i>This is where your SOL will be sent.</i>",
        reply_markup=build_cancel_sniper(),
    )
    await callback.answer()


@router.message(WithdrawState.waiting_address)
async def fsm_withdraw_address(message: Message, state: FSMContext) -> None:
    address = message.text.strip() if message.text else ""
    if not is_valid_solana_address(address):
        await message.answer(
            "❌ Invalid Solana address. Please enter a valid base58 public key.",
            reply_markup=build_cancel_sniper(),
        )
        return
    await state.update_data(to_address=address)
    await state.set_state(WithdrawState.waiting_amount)

    from services.bot_wallet_service import get_or_create_bot_wallet, get_sol_balance as _bal
    row     = await get_or_create_bot_wallet(message.from_user.id)
    balance = await _bal(row["wallet_address"]) or 0.0

    await message.answer(
        f"💸 <b>Withdraw SOL</b>\n\n"
        f"Step 2 of 2 — Enter the <b>amount in SOL</b> to send\n\n"
        f"<b>Destination:</b> <code>{address}</code>\n"
        f"<b>Available balance:</b> {balance:.6f} SOL\n"
        f"<i>(0.000005 SOL kept for network fee)</i>\n\n"
        f"Type the amount, e.g. <code>0.5</code>\n"
        f"Type <code>all</code> to withdraw everything.",
        reply_markup=build_cancel_sniper(),
    )


@router.message(WithdrawState.waiting_amount)
async def fsm_withdraw_amount(message: Message, state: FSMContext) -> None:
    from services.bot_wallet_service import (
        get_or_create_bot_wallet, get_sol_balance as _bal, withdraw_sol
    )
    raw = message.text.strip().lower() if message.text else ""
    data = await state.get_data()
    to_address = data.get("to_address", "")

    row     = await get_or_create_bot_wallet(message.from_user.id)
    balance = await _bal(row["wallet_address"]) or 0.0
    FEE     = 0.000005

    if raw == "all":
        amount = max(0.0, balance - FEE)
    else:
        try:
            amount = float(raw)
        except ValueError:
            await message.answer("❌ Enter a number or 'all'.", reply_markup=build_cancel_sniper())
            return

    if amount <= 0:
        await message.answer("❌ Amount must be greater than 0.", reply_markup=build_cancel_sniper())
        return
    if amount > balance - FEE:
        await message.answer(
            f"❌ Insufficient balance.\n"
            f"Available: {max(0.0, balance - FEE):.6f} SOL",
            reply_markup=build_cancel_sniper(),
        )
        return

    await state.clear()
    wait = await message.answer(f"⏳ Sending {amount:.6f} SOL…")

    result = await withdraw_sol(message.from_user.id, to_address, amount)

    if result["success"]:
        sig = result["signature"]
        await wait.edit_text(
            f"✅ <b>Withdrawal sent!</b>\n\n"
            f"<b>Amount:</b> {amount:.6f} SOL\n"
            f"<b>To:</b> <code>{to_address}</code>\n"
            f"<b>TX:</b> <code>{sig}</code>\n\n"
            f"<a href='https://solscan.io/tx/{sig}'>View on Solscan</a>",
            reply_markup=build_back_to_sniper(),
            disable_web_page_preview=True,
        )
    else:
        await wait.edit_text(
            f"❌ <b>Withdrawal failed</b>\n\n{result['error']}",
            reply_markup=build_back_to_sniper(),
        )


@router.callback_query(F.data == "sniper:wallet_remove")
async def cb_wallet_remove(callback: CallbackQuery) -> None:
    await callback.answer("Bot wallets cannot be deleted — funds may be inside. Use Withdraw to move funds.", show_alert=True)




@router.callback_query(F.data == "sniper:wallet_export")
async def cb_wallet_export(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    try:
        text, kb = await _wallet_text_and_kb(user_id, show_key=True)
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest:
        pass  # already showing key or message unchanged
    except Exception as _e:
        import logging as _log
        _log.getLogger(__name__).error(f"wallet_export uid={user_id}: {_e}", exc_info=True)
    finally:
        try:
            await callback.answer()
        except Exception:
            pass


@router.callback_query(F.data == "sniper:wallet_hide_key")
async def cb_wallet_hide_key(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    try:
        text, kb = await _wallet_text_and_kb(user_id, show_key=False)
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest:
        pass  # message unchanged
    finally:
        try:
            await callback.answer()
        except Exception:
            pass




@router.message(AddWalletState.waiting_address)
async def fsm_wallet_address(message: Message, state: FSMContext) -> None:
    address = message.text.strip()
    if not is_valid_solana_address(address):
        await message.answer("❌ Invalid Solana address.", reply_markup=build_cancel_sniper())
        return
    await state.clear()
    await set_wallet(message.from_user.id, address)
    await message.answer(f"✅ Wallet linked: <code>{address}</code>")


# ══════════════════════════════════════════════════════════════════════════════
# L. POSITIONS
# ══════════════════════════════════════════════════════════════════════════════

def _pnl_bar(pct: float, width: int = 10) -> str:
    """Compact ASCII P&L bar. Positive = filled from left, negative = empty."""
    if pct >= 0:
        filled = min(width, int(pct / 100 * width * 2))  # scale so 50% = half bar
        return "▓" * filled + "░" * (width - filled)
    else:
        empty = min(width, int(abs(pct) / 100 * width * 2))
        return "▒" * empty + "░" * (width - empty)  # ▒ = losing territory


async def _load_jobs(user_id: int, limit: int = 30, offset: int = 0) -> list[dict]:
    """
    Load active positions from position_state (the auto-exit watcher's source of truth).
    Only returns positions the watcher is actively monitoring (watching / partial).
    """
    from database.sqlite_db import get_db
    async with get_db() as db:
        async with db.execute(
            """
            SELECT ps.position_id,
                   ps.token_address,
                   ps.entry_price_sol,
                   ps.current_price_sol,
                   ps.qty_remaining_pct,
                   ps.status,
                   tp.amount_sol  AS total_spent,
                   tp.token_symbol,
                   tp.opened_at   AS last_bought
            FROM   position_state ps
            LEFT JOIN tracked_positions tp ON tp.id = ps.position_id
            WHERE  ps.user_id = ? AND ps.status IN ('watching', 'partial')
            ORDER  BY tp.opened_at DESC
            LIMIT  ? OFFSET ?
            """,
            (user_id, limit, offset),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def _count_jobs(user_id: int) -> int:
    """Active positions currently being watched by the auto-exit watcher."""
    from database.sqlite_db import get_db
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM position_state WHERE user_id = ? AND status IN ('watching', 'partial')",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else 0


async def _enrich_open(jobs: list[dict], wallet_addr: str | None) -> list[dict]:
    """
    Enrich positions with live balance check.
    Prices come from position_state (auto-exit watcher updates every 8s).
    Skips positions where wallet balance is confirmed 0.
    """
    import asyncio
    from services.solana_execution_service import get_token_balance

    enriched = []
    for j in jobs:
        mint         = j["token_address"]
        spent        = float(j["total_spent"] or 0)
        entry_price  = float(j["entry_price_sol"] or 0)
        current_price = float(j["current_price_sol"] or entry_price or 0)
        qty_remaining = float(j["qty_remaining_pct"] or 100)
        raw_symbol    = j.get("token_symbol") or ""
        symbol        = raw_symbol[:12] if raw_symbol and not raw_symbol.startswith(mint[:6]) else (mint[:6] + "…" + mint[-4:])

        balance: float | None = None
        if wallet_addr:
            try:
                balance = await get_token_balance(wallet_addr, mint)
            except Exception:
                pass

        # Skip positions where wallet confirms 0 balance (already sold/rugged)
        if balance is not None and balance == 0:
            continue

        enriched.append({
            "position_id":  j["position_id"],
            "mint":         mint,
            "symbol":       symbol,
            "spent":        spent,
            "balance":      balance,
            "price_sol":    current_price,
            "entry_price":  entry_price,
            "qty_remaining": qty_remaining,
            "last_bought":  str(j["last_bought"] or "")[:16],
        })
        await asyncio.sleep(0.15)

    return enriched


@router.callback_query(F.data == "sniper:positions")
async def cb_positions(callback: CallbackQuery) -> None:
    """Open positions — terminal aesthetic, manual sell buttons, separate history link."""
    import asyncio
    from services.bot_wallet_service import get_or_create_bot_wallet
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    user_id = callback.from_user.id

    # Boot flash
    try:
        await callback.message.edit_text(
            "<code>▓▓░░░░░░░░  SCANNING WALLET...</code>", parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass

    jobs = await _load_jobs(user_id)

    try:
        wallet_row  = await get_or_create_bot_wallet(user_id)
        wallet_addr = wallet_row["wallet_address"]
        w_short     = wallet_addr[:6] + "…" + wallet_addr[-4:]
    except Exception:
        wallet_addr = None
        w_short     = "unavailable"

    if not jobs:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🔄 Refresh", callback_data="sniper:positions"))
        b.row(InlineKeyboardButton(text="⬅️  Back",   callback_data="sniper:main"))
        try:
            await callback.message.edit_text(
                "<code>╔══════════════════════════════╗\n"
                "║   📡 OPEN POSITIONS          ║\n"
                "╚══════════════════════════════╝\n\n"
                "NO POSITIONS FOUND\n"
                "──────────────────────────────\n"
                "Positions appear here after\n"
                "a confirmed auto-buy trade.</code>",
                reply_markup=b.as_markup(),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await callback.answer()
        return

    open_pos = await _enrich_open(jobs, wallet_addr)
    closed_count = len(jobs) - len(open_pos)

    # ── Build position cards ──────────────────────────────────────────────────
    def _fmt_open(e: dict) -> str:
        mint         = e["mint"]
        short        = mint[:6] + "…" + mint[-4:]
        spent        = e["spent"]
        balance      = e["balance"]
        price_sol    = e["price_sol"]
        entry_price  = e["entry_price"]
        qty_rem      = e["qty_remaining"]
        sym          = e["symbol"].upper()
        ts           = e["last_bought"][:10] if e["last_bought"] else "—"
        status_tag   = "PARTIAL" if qty_rem < 99 else "WATCHING"

        if entry_price > 0 and price_sol > 0:
            # PnL from entry→current price on remaining qty
            pnl_pct  = (price_sol / entry_price - 1) * 100
            pnl_sol  = spent * (qty_rem / 100) * (price_sol / entry_price - 1)
            sign     = "+" if pnl_sol >= 0 else ""
            bar      = _pnl_bar(pnl_pct)
            pnl_line = f"PnL  {bar} {sign}{pnl_pct:.1f}%  ({sign}{pnl_sol:.5f})"
        elif balance is None:
            pnl_line = "PnL  ░░░░░░░░░░  RPC TIMEOUT"
        else:
            pnl_line = "PnL  ░░░░░░░░░░  PRICE PENDING"

        bal_str = f"{balance:,.0f}" if balance is not None and balance >= 1 else (
            f"{balance:.4f}" if balance is not None else "···"
        )
        qty_str = f"{qty_rem:.0f}% rem" if qty_rem < 99 else "100%"

        return (
            f"<code>┌─ {status_tag}  {sym[:18]}\n"
            f"│ CA     {short}\n"
            f"│ SPENT  {spent:.5f} SOL  [{qty_str}]\n"
            f"│ {pnl_line[:38]}\n"
            f"│ ENTRY  {entry_price:.8f}  →  {price_sol:.8f}\n"
            f"│ BAL    {bal_str}\n"
            f"└ {ts}</code>"
        )

    # ── Portfolio summary ─────────────────────────────────────────────────────
    total_spent = sum(e["spent"] for e in open_pos)
    total_pnl   = sum(
        e["spent"] * (e["qty_remaining"] / 100) * (e["price_sol"] / e["entry_price"] - 1)
        for e in open_pos
        if e["entry_price"] > 0 and e["price_sol"] > 0
    )
    if total_spent > 0:
        sign    = "+" if total_pnl >= 0 else ""
        net_pct = (total_pnl / total_spent * 100) if total_spent > 0 else 0
        summary = (
            f"<code>╔══════════════════════════════╗\n"
            f"║  PORTFOLIO  [{len(open_pos)} OPEN]        ║\n"
            f"║  IN:  {total_spent:.4f} SOL{'':<14}║\n"
            f"║  PnL: {sign}{total_pnl:.5f} SOL  ({sign}{net_pct:.1f}%){'':<2}║\n"
            f"╚══════════════════════════════╝</code>\n\n"
        )
    else:
        summary = ""

    # ── Manual sell instructions ──────────────────────────────────────────────
    how_to = (
        "<code>──────────────────────────────\n"
        "HOW TO CLOSE A POSITION:\n"
        "  Tap ❌ Sell [TOKEN] below.\n"
        "  Bot executes 100% market sell.\n\n"
        "WANT AUTOMATIC EXITS?\n"
        "  Open Auto-Exit Manager →\n"
        "  pick a preset → enable power.\n"
        "  Bot then handles TP/SL/time\n"
        "  exits without you touching it.\n"
        "──────────────────────────────</code>"
    )

    # ── Assemble text ─────────────────────────────────────────────────────────
    header = (
        f"<code>╔══════════════════════════════╗\n"
        f"║   📡 OPEN POSITIONS          ║\n"
        f"╚══════════════════════════════╝\n"
        f"WALLET  {w_short}\n"
        f"OPEN    {len(open_pos)}  CLOSED {closed_count} (see history)\n"
        f"──────────────────────────────</code>\n\n"
    )

    if not open_pos:
        cards = "<code>No open positions — all closed or sold.</code>\n\n"
    else:
        cards = "\n\n".join(_fmt_open(e) for e in open_pos) + "\n\n"

    text = header + summary + cards + how_to

    # ── Keyboard ──────────────────────────────────────────────────────────────
    b = InlineKeyboardBuilder()
    if len(open_pos) > 1:
        b.row(InlineKeyboardButton(
            text=f"🔴 CLOSE ALL {len(open_pos)} POSITIONS",
            callback_data="sniper:pos_sell_all",
        ))
    for e in open_pos:
        b.row(InlineKeyboardButton(
            text=f"❌ Sell {e['symbol'].upper()}",
            callback_data=f"sniper:pos_sell:{e['mint']}",
        ))
    b.row(
        InlineKeyboardButton(text="🔄 Refresh",       callback_data="sniper:positions"),
        InlineKeyboardButton(text="📜 Trade History", callback_data="sniper:positions_closed"),
    )
    b.row(InlineKeyboardButton(text="⬅️  Back", callback_data="sniper:main"))

    try:
        await callback.message.edit_text(
            text, reply_markup=b.as_markup(), disable_web_page_preview=True, parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("sniper:positions_closed"))
async def cb_positions_closed(callback: CallbackQuery) -> None:
    """
    Trade History — paginated, instant DB-only read, no RPC calls.
    Page size: 50.
    Callback data: sniper:positions_closed  (page 0)
                   sniper:positions_closed:N  (page N)
    """
    import asyncio
    import re
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    user_id = callback.from_user.id

    # Parse page number from callback_data
    m = re.search(r":(\d+)$", callback.data)
    page = int(m.group(1)) if m else 0

    page_size = 50

    # Boot animation only on the first page open (not on prev/next taps)
    if page == 0:
        frames = [
            "<code>▓░░░░░░░░░  CONNECTING TO DB...</code>",
            "<code>▓▓▓▓░░░░░░  FETCHING BUY LOGS...</code>",
            "<code>▓▓▓▓▓▓▓░░░  COMPILING HISTORY...</code>",
        ]
        for frame in frames:
            try:
                await callback.message.edit_text(frame, parse_mode="HTML")
            except TelegramBadRequest:
                pass
            await asyncio.sleep(0.38)

    offset    = page * page_size
    jobs      = await _load_jobs(user_id, limit=page_size, offset=offset)
    total     = await _count_jobs(user_id)
    total_pages = max(1, -(-total // page_size))  # ceiling division

    b = InlineKeyboardBuilder()

    if not jobs and page == 0:
        b.row(InlineKeyboardButton(text="⬅️  Back to Positions", callback_data="sniper:positions"))
        try:
            await callback.message.edit_text(
                "<code>╔══════════════════════════════╗\n"
                "║   📜 TRADE HISTORY           ║\n"
                "╚══════════════════════════════╝\n\n"
                "No trade history yet.\n"
                "Executed buys appear here.</code>",
                reply_markup=b.as_markup(),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await callback.answer()
        return

    def _fmt_entry(j: dict) -> str:
        mint  = j["token_address"]
        short = mint[:6] + "…" + mint[-4:]
        spent = float(j["total_spent"] or 0)
        count = int(j.get("buy_count") or 1)
        ts    = str(j["last_bought"] or "")[:16]
        buys  = f"{count}x buy" if count == 1 else f"{count}x buys"
        return (
            f"<code>┌─ {short} ──────────────────┐\n"
            f"│ SPENT   {spent:.5f} SOL  [{buys:<8}]│\n"
            f"│ ENTERED {ts:<22}│\n"
            f"└{'─'*32}┘</code>"
        )

    cards          = "\n".join(_fmt_entry(j) for j in jobs)
    page_deployed  = sum(float(j["total_spent"] or 0) for j in jobs)

    text = (
        f"<code>╔══════════════════════════════╗\n"
        f"║   📜 TRADE HISTORY           ║\n"
        f"╚══════════════════════════════╝\n"
        f"PAGE     {page + 1} of {total_pages}  ({total} total)\n"
        f"SHOWING  {offset + 1}–{min(offset + page_size, total)}\n"
        f"DEPLOYED {page_deployed:.4f} SOL this page\n"
        f"──────────────────────────────</code>\n\n"
        + cards
    )

    # Pagination buttons
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text=f"◀ Prev {page_size}",
            callback_data=f"sniper:positions_closed:{page - 1}",
        ))
    if (page + 1) < total_pages:
        nav.append(InlineKeyboardButton(
            text=f"Next {page_size} ▶",
            callback_data=f"sniper:positions_closed:{page + 1}",
        ))
    if nav:
        b.row(*nav)

    b.row(InlineKeyboardButton(text="⬅️  Back to Positions", callback_data="sniper:positions"))

    try:
        await callback.message.edit_text(
            text, reply_markup=b.as_markup(), disable_web_page_preview=True, parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("sniper:pos_sell:"))
async def cb_pos_sell(callback: CallbackQuery) -> None:
    from services.solana_execution_service import execute_sell, get_token_balance
    from services.auto_buy_service import get_auto_buy_settings
    from services.bot_wallet_service import get_or_create_bot_wallet
    from services.auto_exit_service import mark_position_closed
    from database.sqlite_db import get_db

    user_id       = callback.from_user.id
    token_address = callback.data.split("sniper:pos_sell:")[-1]

    # Guard: confirm there is actually a balance to sell before sending a TX
    try:
        row     = await get_or_create_bot_wallet(user_id)
        balance = await get_token_balance(row["wallet_address"], token_address)
        if balance is not None and balance == 0:
            await callback.answer("⚠️ No tokens held — position already closed.", show_alert=True)
            await cb_positions(callback)
            return
    except Exception:
        pass   # proceed — let execute_sell handle it if balance truly 0

    ab           = await get_auto_buy_settings(user_id)
    slippage     = float(ab.get("slippage") or 15.0)
    priority_fee = float(ab.get("priority_fee") or 0.005)

    await callback.answer("⏳ Executing sell…", show_alert=False)

    result = await execute_sell(
        user_id          = user_id,
        token_address    = token_address,
        sell_pct         = 100.0,
        slippage_pct     = slippage,
        priority_fee_sol = priority_fee,
    )

    if result.get("success"):
        sig   = result.get("signature") or ""
        short = sig[:12] + "…" if sig else "—"
        await callback.answer(f"✅ Sold!  TX: {short}", show_alert=True)
        # Close position in auto-exit watcher so it stops tracking this token
        try:
            async with get_db() as db:
                async with db.execute(
                    "SELECT position_id FROM position_state WHERE user_id=? AND token_address=? AND status IN ('watching','partial') LIMIT 1",
                    (user_id, token_address),
                ) as cur:
                    ps_row = await cur.fetchone()
            if ps_row:
                pos_id = ps_row[0]
                await mark_position_closed(pos_id)
                async with get_db() as db:
                    await db.execute(
                        "UPDATE tracked_positions SET status='closed', closed_at=CURRENT_TIMESTAMP WHERE id=?",
                        (pos_id,),
                    )
                    await db.commit()
        except Exception:
            pass
    else:
        err = result.get("error") or "Unknown error"
        await callback.answer(f"❌ Sell failed: {err[:80]}", show_alert=True)

    await cb_positions(callback)


@router.callback_query(F.data == "sniper:pos_sell_all")
async def cb_pos_sell_all(callback: CallbackQuery) -> None:
    """Close all positions the auto-exit watcher is actively tracking."""
    import asyncio
    from database.sqlite_db import get_db
    from services.solana_execution_service import execute_sell, get_token_balance
    from services.auto_buy_service import get_auto_buy_settings
    from services.bot_wallet_service import get_or_create_bot_wallet
    from services.auto_exit_service import mark_position_closed

    user_id = callback.from_user.id

    # Source of truth: position_state (same as auto-exit watcher)
    async with get_db() as db:
        async with db.execute(
            "SELECT position_id, token_address FROM position_state WHERE user_id = ? AND status IN ('watching', 'partial')",
            (user_id,),
        ) as cur:
            candidates = [(r[0], r[1]) for r in await cur.fetchall()]

    if not candidates:
        await callback.answer("No active positions found.", show_alert=True)
        return

    try:
        row         = await get_or_create_bot_wallet(user_id)
        wallet_addr = row["wallet_address"]
    except Exception:
        wallet_addr = None

    # Filter to tokens we still hold
    tokens_to_sell = []
    for pos_id, mint in candidates:
        try:
            bal = await get_token_balance(wallet_addr, mint) if wallet_addr else None
            if bal is None or bal > 0:
                tokens_to_sell.append((pos_id, mint))
        except Exception:
            tokens_to_sell.append((pos_id, mint))
        await asyncio.sleep(0.2)

    if not tokens_to_sell:
        await callback.answer("✅ All positions already closed.", show_alert=True)
        await cb_positions(callback)
        return

    ab           = await get_auto_buy_settings(user_id)
    slippage     = float(ab.get("slippage") or 15.0)
    priority_fee = float(ab.get("priority_fee") or 0.005)

    await callback.answer(f"⏳ Closing {len(tokens_to_sell)} positions…", show_alert=False)

    ok = fail = 0
    for pos_id, t in tokens_to_sell:
        try:
            result = await execute_sell(
                user_id          = user_id,
                token_address    = t,
                sell_pct         = 100.0,
                slippage_pct     = slippage,
                priority_fee_sol = priority_fee,
            )
            if result.get("success"):
                ok += 1
                # Sync position_state and tracked_positions so watcher stops tracking
                try:
                    await mark_position_closed(pos_id)
                    async with get_db() as db:
                        await db.execute(
                            "UPDATE tracked_positions SET status='closed', closed_at=CURRENT_TIMESTAMP WHERE id=?",
                            (pos_id,),
                        )
                        await db.commit()
                except Exception:
                    pass
            else:
                fail += 1
        except Exception:
            fail += 1
        await asyncio.sleep(1)

    await callback.answer(f"✅ {ok} sold  ❌ {fail} failed", show_alert=True)
    await cb_positions(callback)


# ══════════════════════════════════════════════════════════════════════════════
# N. CANCEL + ADMIN COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "sniper:cancel_fsm")
async def cb_cancel_fsm(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("❌ Cancelled.", reply_markup=build_back_to_sniper())
    await callback.answer()


@router.message(Command("kill_all_trading"))
async def cmd_kill_all_trading(message: Message) -> None:
    """Admin emergency stop — disables auto-buy for ALL users instantly."""
    if not is_admin(message.from_user.id):
        return
    from database.sqlite_db import get_db
    import services.auto_buy_worker as _worker
    _worker.stop()
    async with get_db() as db:
        await db.execute(
            "UPDATE auto_buy_settings SET enabled = 0, kill_switch = 1"
        )
        await db.commit()
    await message.answer(
        "🛑 <b>EMERGENCY STOP</b>\n\n"
        "All auto-buy disabled for all users.\n"
        "Worker stopped. Use /resume_trading to re-enable.",
        parse_mode="HTML",
    )
    logger.warning(f"EMERGENCY STOP triggered by admin {message.from_user.id}")


@router.message(Command("resume_trading"))
async def cmd_resume_trading(message: Message) -> None:
    """Admin: lift the emergency stop (clears kill_switch for all users)."""
    if not is_admin(message.from_user.id):
        return
    from database.sqlite_db import get_db
    async with get_db() as db:
        await db.execute("UPDATE auto_buy_settings SET kill_switch = 0")
        await db.commit()
    await message.answer(
        "✅ Kill switch cleared for all users.\n"
        "Users must re-enable auto-buy manually via the bot.",
    )


# settings is used by the pages above
from utils.config import settings


# ── Catch-all: plain text messages with no active sniper FSM state ────────────
# Catches the case where a user typed a value after the bot was restarted.
# With SQLiteStorage, FSM states now survive restarts — this is a last-resort
# handler for truly unexpected messages.
@router.message(F.text, ~F.text.startswith("/"), StateFilter(None))
async def sniper_stray_message(message: Message) -> None:
    await message.answer(
        "⚠️ Session expired or no input expected.\n"
        "Use the menu button to navigate the sniper tool.",
        reply_markup=build_back_to_sniper(),
    )
