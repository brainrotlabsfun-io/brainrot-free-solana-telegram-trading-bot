"""
bot/handlers/candle_sniper.py
================================
Telegram UI handler for the Candle Sniper strategy module.

Callback prefix: cs:
Command:         /candle_sniper

Menu flow:
  /candle_sniper → cs:main
    ├── cs:toggle           — enable / disable mode
    ├── cs:toggle_autobuy   — toggle auto-buy
    ├── cs:profile_menu     — strategy profile picker
    │     └── cs:set_profile:{name}
    ├── cs:settings         — settings panel
    │     └── cs:set_field:{field} → FSM: CSFieldEditState.waiting_value
    ├── cs:toggle_restore   — toggle restore-previous-config
    ├── cs:candidates       — top scored candidates
    │     └── cs:candidate_detail:{addr}
    ├── cs:positions        — open CS positions
    │     ├── cs:pos_detail:{id}
    │     └── cs:pos_close:{id}
    ├── cs:debug_prompt     — FSM: enter token address for equation debug
    └── cs:locked:*         — locked features (show upgrade prompt)
"""

import logging

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.keyboards.candle_sniper_menu import (
    build_cs_main, build_cs_profile_menu, build_cs_settings,
    build_cs_candidates, build_cs_positions, build_cs_pos_detail,
    build_cs_cancel, build_cs_back_to_main,
    build_cs_candidate_action, build_cs_confirm_buy,
    build_cs_share_menu,
)
from services.candle_sniper_service import (
    get_cs_settings, update_cs_field, enable_candle_sniper,
    disable_candle_sniper, toggle_candle_sniper, get_cs_entitlements,
    get_top_candidates, get_cs_open_positions, close_cs_position,
    fetch_cs_token_data, count_open_cs_positions,
    get_user_watchlist, add_watchlist_token, remove_watchlist_token,
)
from services.candle_sniper_engine import score_candidate, apply_profile_filters
from services.brainrot_token_gate import get_active_tier
from utils.candle_sniper_states import CSFieldEditState
from utils.config import settings
from utils.share_utils import bot_link as _bot_link, website_buttons as _website_buttons, share_footer as _share_footer

logger  = logging.getLogger(__name__)
router  = Router()

# ── Field metadata: (label, unit, type, min, max) ────────────────────────────
_FIELD_META: dict[str, tuple] = {
    "timeframe":             ("Timeframe",             "(1m/3m/5m/15m)",  str,   None, None),
    "scan_window":           ("Scan Window",           "candles",         int,   5,    100),
    "min_confirmations":     ("Min Confirmations",     "/9 equations",    int,   1,    9),
    "confidence_threshold":  ("Confidence Threshold",  "%",               int,   10,   100),
    "max_open_positions":    ("Max Open Positions",    "positions",       int,   1,    9999),
    "trade_size_sol":        ("Trade Size",            "SOL",             float, 0.001, 100.0),
    "stop_loss_pct":         ("Stop Loss",             "%",               float, 1.0,  90.0),
    "take_profit_pct":       ("Take Profit",           "%",               float, 1.0,  10000.0),
    "trailing_stop_pct":     ("Trailing Stop",         "%",               float, 1.0,  90.0),
    "slippage_pct":          ("Slippage",              "%",               float, 0.5,  50.0),
    "cooldown_seconds":      ("Cooldown",              "seconds",         int,   0,    86400),
    "surge_threshold_pct":   ("Surge Threshold",       "%",               float, 50.0, 100000.0),
    "surge_track_hours":     ("Surge Track Window",    "hours",           int,   1,    72),
    "max_hold_minutes":      ("Max Hold Time",         "minutes",         int,   30,   10080),
}
_VALID_TIMEFRAMES = {"1m", "3m", "5m", "15m"}

# ── Tier label helpers ────────────────────────────────────────────────────────

def _tier_badge(tier: str) -> str:
    return {"supreme_black": "🔱 SUPREME BLACK", "supreme": "👑 SUPREME"}.get(tier, "🆓 Free")


# ── /candle_sniper command ────────────────────────────────────────────────────

@router.message(Command("candle_sniper"), StateFilter(None))
async def cmd_candle_sniper(message: Message) -> None:
    await _send_main_menu(message, message.from_user.id)


# ── Main Menu ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "cs:main")
async def cb_cs_main(callback: CallbackQuery) -> None:
    import asyncio
    from aiogram.exceptions import TelegramBadRequest as _TBR
    try:
        boot = await callback.message.edit_text(
            "<code>█░░░░░░░░░ CANDLE SNIPER BOOTING...</code>", parse_mode="HTML"
        )
        await asyncio.sleep(0.38)
        await boot.edit_text(
            "<code>████░░░░░░ SCANNING MARKETS...</code>", parse_mode="HTML"
        )
        await asyncio.sleep(0.38)
        await boot.edit_text(
            "<code>██████████ ENGINE ONLINE ⚡</code>", parse_mode="HTML"
        )
        await asyncio.sleep(0.28)
    except _TBR:
        pass
    await callback.answer()
    await _send_main_menu(callback.message, callback.from_user.id, edit=True)


async def _send_main_menu(target, user_id: int, edit: bool = False) -> None:
    import time
    from services.candle_sniper_worker import get_stats
    cfg  = await get_cs_settings(user_id)
    tier = await get_active_tier(user_id)
    ents = get_cs_entitlements(tier)

    enabled  = bool(cfg.get("enabled"))
    auto_buy = bool(cfg.get("auto_buy"))
    profile  = cfg.get("strategy_profile", "balanced").title()

    open_count      = await count_open_cs_positions(user_id)
    max_pos_display = "∞" if ents.max_open_positions >= 9999 else str(ents.max_open_positions)

    stats   = get_stats()
    cycles  = stats.get("discovery_cycles", 0)
    scored  = stats.get("candidates_scored", 0)
    buys    = stats.get("buys_executed", 0)
    closed  = stats.get("positions_closed", 0)
    last_ts = stats.get("last_discovery_ts", 0)
    if last_ts:
        secs_ago  = int(time.time() - last_ts)
        last_scan = f"{secs_ago}s ago" if secs_ago < 120 else f"{secs_ago//60}m ago"
    else:
        last_scan = "not yet"

    if tier == "supreme_black":
        tier_label = "🔱 SUPREME BLACK"
        tier_bar   = "▓▓▓▓▓▓▓▓▓▓ CLEARANCE: MAX"
    elif tier == "supreme":
        tier_label = "👑 SUPREME"
        tier_bar   = "▓▓▓▓▓▓▓░░░ CLEARANCE: HIGH"
    else:
        tier_label = "🆓 FREE"
        tier_bar   = "▓░░░░░░░░░ CLEARANCE: BASIC"

    power_icon = "🟢 ONLINE" if enabled else "🔴 OFFLINE"
    ab_icon    = "🤖 ON"     if auto_buy else "⏸ OFF"

    hint = ""
    if not enabled:
        hint = "\n<i>Tap <b>Enable</b> → turn on Auto-Buy → bot trades every 60s.</i>"
    elif not auto_buy:
        hint = "\n<i>Auto-Buy is OFF — enable it below to start executing trades.</i>"

    text = (
        f"🕯️ <b>CANDLE SNIPER</b>\n"
        f"<code>{tier_bar}  {tier_label}</code>\n\n"
        f"<code>{power_icon}   {ab_icon}   {profile}</code>\n"
        f"<code>📂 {open_count}/{max_pos_display} open   💰 {cfg.get('trade_size_sol', 0.05):.4f} SOL   TP+{cfg.get('take_profit_pct',50):.0f}% SL-{cfg.get('stop_loss_pct',15):.0f}%</code>\n"
        f"<code>🔄 {cycles} scans  🎯 {scored} scored  ✅ {buys} bought  ⏱ {last_scan}</code>"
        f"{hint}"
    )

    markup = build_cs_main(cfg, tier, ents)
    try:
        if edit:
            await target.edit_text(text, reply_markup=markup, parse_mode="HTML")
        else:
            await target.answer(text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        if edit:
            await target.answer(text, reply_markup=markup, parse_mode="HTML")


# ── Community Share Menu ──────────────────────────────────────────────────────

@router.callback_query(F.data == "cs:share_menu")
async def cb_cs_share_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "<code>╔══════════════════════════════╗\n"
        "║  🌐  SHARE  //  COMMUNITY    ║\n"
        "╚══════════════════════════════╝</code>\n\n"
        "Share your Candle Sniper activity with the community.\n"
        "Each link opens pre-filled and ready to post.\n\n"
        "Use <code>#BRAINROTONCHAINBOT</code> to connect with other\n"
        "traders — share your settings, profile, and results.\n"
        "The community builds the meta together.\n\n"
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>",
        reply_markup=build_cs_share_menu(),
    )
    await callback.answer()


# ── Toggle Enable / Disable ───────────────────────────────────────────────────

@router.callback_query(F.data == "cs:toggle")
async def cb_cs_toggle(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    new_state = await toggle_candle_sniper(user_id)
    cfg  = await get_cs_settings(user_id)
    tier = await get_active_tier(user_id)
    ents = get_cs_entitlements(tier)

    if new_state:
        note = "\n\n<i>Your previous sniper config has been saved and will be restored when you disable CS mode.</i>"
    else:
        note = "\n\n<i>Candle Sniper disabled. Previous sniper config restored (if enabled).</i>"

    await callback.answer("Candle Sniper " + ("enabled ✅" if new_state else "disabled ⛔"))

    status  = "🟢 ACTIVE" if new_state else "⚪ Inactive"
    profile = cfg.get("strategy_profile", "balanced").title()
    text = (
        f"🕯️ <b>Candle Sniper</b>  {_tier_badge(tier)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Status:</b> {status}\n"
        f"<b>Profile:</b> {profile}"
        f"{note}"
    )
    await callback.message.edit_text(text, reply_markup=build_cs_main(cfg, tier, ents),
                                     parse_mode="HTML")


# ── Toggle Auto-Buy ───────────────────────────────────────────────────────────

@router.callback_query(F.data == "cs:toggle_autobuy")
async def cb_toggle_autobuy(callback: CallbackQuery) -> None:
    user_id  = callback.from_user.id
    cfg      = await get_cs_settings(user_id)
    new_val  = 0 if cfg.get("auto_buy") else 1
    await update_cs_field(user_id, "auto_buy", new_val)
    await callback.answer(f"Auto-Buy {'enabled' if new_val else 'disabled'}")
    await cb_cs_main(callback)


# ── Toggle Restore ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "cs:toggle_restore")
async def cb_toggle_restore(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    cfg     = await get_cs_settings(user_id)
    new_val = 0 if cfg.get("restore_previous_config") else 1
    await update_cs_field(user_id, "restore_previous_config", new_val)
    await callback.answer(f"Restore on disable: {'ON' if new_val else 'OFF'}")
    await _edit_settings_menu(callback)


# ── Toggle Surge Detector ─────────────────────────────────────────────────────

@router.callback_query(F.data == "cs:toggle_surge")
async def cb_toggle_surge(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    cfg     = await get_cs_settings(user_id)
    new_val = 0 if cfg.get("surge_enabled") else 1
    await update_cs_field(user_id, "surge_enabled", new_val)
    if new_val:
        await callback.answer("🚀 Surge Detector ON — tracking tokens for price surges")
    else:
        await callback.answer("Surge Detector OFF")
    await _edit_settings_menu(callback)


# ── Strategy Profile ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "cs:profile_menu")
async def cb_cs_profile_menu(callback: CallbackQuery) -> None:
    cfg = await get_cs_settings(callback.from_user.id)
    await callback.answer()
    await callback.message.edit_text(
        "📊 <b>Strategy Profile</b>\n\n"
        "Choose how aggressive the Candle Sniper should be:\n\n"
        "🔵 <b>Safe</b> — Blue chip only ($50M+ mcap). Textbook setups, 65% confidence\n"
        "🛡️ <b>Conservative</b> — Established tokens ($2M+ mcap). Strong signal, 52%\n"
        "⚖️ <b>Balanced</b> — Default ($500k+ mcap). Good mix of opportunity vs risk, 38%\n"
        "⚡ <b>Active</b> — Mid-range ($200k+ mcap). More trades, more noise, 28%\n"
        "🔥 <b>Aggressive</b> — Emerging ($75k+ mcap). Early signals, higher risk, 16%\n"
        "💀 <b>Degen</b> — Micro-cap ($20k+ mcap). Max trades, max risk, 8%",
        reply_markup=build_cs_profile_menu(cfg.get("strategy_profile", "balanced")),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("cs:set_profile:"))
async def cb_cs_set_profile(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    profile = callback.data.split(":")[-1]
    if profile not in {"safe", "conservative", "balanced", "active", "aggressive", "degen"}:
        await callback.answer("Invalid profile", show_alert=True)
        return

    await update_cs_field(user_id, "strategy_profile", profile)

    # Apply profile defaults for confirmations and threshold
    from services.candle_sniper_engine import STRATEGY_PROFILES
    prof_cfg = STRATEGY_PROFILES[profile]
    await update_cs_field(user_id, "min_confirmations",    prof_cfg["min_confirmations"])
    await update_cs_field(user_id, "confidence_threshold", prof_cfg["confidence_threshold"])

    await callback.answer(f"Profile set to {profile.title()} ✅")
    await cb_cs_main(callback)


# ── Settings Panel ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "cs:settings")
async def cb_cs_settings(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await _edit_settings_menu(callback)


async def _edit_settings_menu(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    cfg     = await get_cs_settings(user_id)
    tier    = await get_active_tier(user_id)
    ents    = get_cs_entitlements(tier)

    text = (
        f"⚙️ <b>Candle Sniper Settings</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Profile: <b>{cfg.get('strategy_profile','balanced').title()}</b>\n"
        f"Timeframe: <b>{cfg.get('timeframe','5m')}</b>  "
        f"Scan Window: <b>{cfg.get('scan_window',20)} candles</b>\n"
        f"Min Confirmations: <b>{cfg.get('min_confirmations',5)}/9</b>  "
        f"Confidence: <b>{cfg.get('confidence_threshold',55)}%</b>\n"
        f"Trade Size: <b>{cfg.get('trade_size_sol',0.05)} SOL</b>  "
        f"Max Positions: <b>{cfg.get('max_open_positions',3)}</b>\n"
        f"Stop Loss: <b>{cfg.get('stop_loss_pct',15)}%</b>  "
        f"Take Profit: <b>{cfg.get('take_profit_pct',50)}%</b>\n"
        f"Slippage: <b>{cfg.get('slippage_pct',5)}%</b>  "
        f"Trailing Stop: <b>{cfg.get('trailing_stop_pct',10)}%</b>\n"
        f"Cooldown: <b>{cfg.get('cooldown_seconds',300)}s</b>  "
        f"Max Hold: <b>{cfg.get('max_hold_minutes',480)}m</b>\n\n"
        f"<i>Tap a field to edit it.</i>"
    )
    try:
        await callback.message.edit_text(
            text, reply_markup=build_cs_settings(cfg, ents), parse_mode="HTML"
        )
    except Exception:
        pass


# ── Settings Field Edit (FSM) ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("cs:set_field:"))
async def cb_cs_set_field(callback: CallbackQuery, state: FSMContext) -> None:
    field = callback.data.split(":")[-1]
    if field not in _FIELD_META:
        await callback.answer("Unknown field", show_alert=True)
        return

    user_id = callback.from_user.id
    tier    = await get_active_tier(user_id)
    ents    = get_cs_entitlements(tier)

    # Gate trailing stop on SUPREME
    if field == "trailing_stop_pct" and not ents.can_trailing_stop:
        await callback.answer("👑 Trailing Stop requires SUPREME tier", show_alert=True)
        return

    label, unit, typ, mn, mx = _FIELD_META[field]
    await state.set_state(CSFieldEditState.waiting_value)
    await state.update_data(field=field, label=label, unit=unit,
                            typ=typ.__name__, mn=mn, mx=mx)

    cfg     = await get_cs_settings(user_id)
    current = cfg.get(field, "—")

    if field == "timeframe":
        prompt = f"⏱ <b>{label}</b>\nValid values: 1m, 3m, 5m, 15m\nCurrent: <b>{current}</b>"
    elif mn is not None and mx is not None:
        prompt = f"⚙️ <b>{label}</b>\nRange: <b>{mn} – {mx} {unit}</b>\nCurrent: <b>{current}</b>"
    else:
        prompt = f"⚙️ <b>{label}</b> ({unit})\nCurrent: <b>{current}</b>"

    await callback.answer()
    await callback.message.edit_text(
        prompt + "\n\nSend the new value:", reply_markup=build_cs_cancel(), parse_mode="HTML"
    )


async def _handle_field_edit(message: Message, state: FSMContext) -> None:
    """Handle a field value submission (extracted so debug handler can delegate here)."""
    data  = await state.get_data()
    field = data.get("field")
    label = data.get("label", field)
    unit  = data.get("unit", "")
    mn    = data.get("mn")
    mx    = data.get("mx")
    typ_name = data.get("typ", "str")
    user_id  = message.from_user.id

    raw = message.text.strip() if message.text else ""

    if field == "timeframe":
        if raw not in _VALID_TIMEFRAMES:
            await message.answer(
                "❌ Invalid timeframe. Valid options: 1m, 3m, 5m, 15m",
                reply_markup=build_cs_cancel(), parse_mode="HTML"
            )
            return
        value = raw
    else:
        typ = {"int": int, "float": float, "str": str}.get(typ_name, str)
        try:
            value = typ(raw)
        except (ValueError, TypeError):
            await message.answer(
                f"❌ Expected a number for <b>{label}</b>.",
                reply_markup=build_cs_cancel(), parse_mode="HTML"
            )
            return

        if mn is not None and mx is not None:
            if not (mn <= value <= mx):
                await message.answer(
                    f"❌ <b>{label}</b> must be between <b>{mn}</b> and <b>{mx}</b> {unit}.",
                    reply_markup=build_cs_cancel(), parse_mode="HTML"
                )
                return

    await state.clear()
    await update_cs_field(user_id, field, value)
    cfg  = await get_cs_settings(user_id)
    tier = await get_active_tier(user_id)
    ents = get_cs_entitlements(tier)

    await message.answer(f"✅ <b>{label}</b> set to <b>{value} {unit}</b>", parse_mode="HTML")
    await message.answer(
        "⚙️ <b>Candle Sniper Settings</b>",
        reply_markup=build_cs_settings(cfg, ents),
        parse_mode="HTML",
    )


# ── Locked Feature ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("cs:locked:"))
async def cb_cs_locked(callback: CallbackQuery) -> None:
    await callback.answer(
        "👑 This feature requires SUPREME tier.\nBurn $BRAINROT to unlock!",
        show_alert=True,
    )


# ── Candidates View ───────────────────────────────────────────────────────────

@router.callback_query(F.data == "cs:candidates")
async def cb_cs_candidates(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    cfg     = await get_cs_settings(user_id)
    tier    = await get_active_tier(user_id)
    ents    = get_cs_entitlements(tier)
    profile = cfg.get("strategy_profile", "balanced")

    candidates = await get_top_candidates(profile, limit=ents.max_candidates)
    watchlist  = await get_user_watchlist(user_id)
    watchlist_addrs = {e["token_address"] for e in watchlist}
    await callback.answer()

    if not candidates:
        text = (
            "🔍 <b>Candle Sniper Candidates</b>\n\n"
            "No candidates scored yet.\n\n"
            "<i>The discovery engine runs every 60 seconds. "
            "Enable Candle Sniper and check back shortly.</i>"
        )
    else:
        lines = [f"🔍 <b>Candle Sniper Candidates</b> ({profile.title()} profile)\n"]
        for i, c in enumerate(candidates[:ents.max_candidates], 1):
            sym  = (c.get("token_symbol") or "???")[:8]
            addr = c.get("token_address", "")
            score = c.get("composite_score", 0)
            eqs   = c.get("equations_passed", 0)
            liq   = c.get("liquidity_usd", 0)
            age   = c.get("age_minutes", 0)
            watch = " ✓" if addr in watchlist_addrs else ""
            lines.append(
                f"\n<b>{i}. ${sym}</b>{watch} — Score: <b>{score:.0f}/100</b> "
                f"({eqs}/9 ✅)\n"
                f"   Liq: ${liq:,.0f} | Age: {age}m\n"
                f"   <code>{addr}</code>"
            )
        text = "\n".join(lines)

    try:
        await callback.message.edit_text(
            text,
            reply_markup=build_cs_candidates(candidates, watchlist_addrs, limit=ents.max_candidates),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(text, parse_mode="HTML")


@router.callback_query(F.data.startswith("cs:candidate_detail:"))
async def cb_candidate_detail(callback: CallbackQuery) -> None:
    partial_addr = callback.data.split(":", 2)[-1]
    await callback.answer("Loading…")

    # Find full address from DB
    from services.candle_sniper_service import get_top_candidates
    user_id = callback.from_user.id
    cfg     = await get_cs_settings(user_id)
    profile = cfg.get("strategy_profile", "balanced")
    all_cands = await get_top_candidates(profile, limit=50)
    token_addr = next(
        (c["token_address"] for c in all_cands
         if c["token_address"].startswith(partial_addr) or c["token_address"][:20] == partial_addr),
        None,
    )
    if not token_addr:
        await callback.answer("Candidate not found — may have expired", show_alert=True)
        return

    token = await fetch_cs_token_data(token_addr)
    if not token:
        await callback.answer("Could not fetch token data", show_alert=True)
        return

    cfg      = await get_cs_settings(user_id)
    result   = score_candidate(token, min_confirmations=cfg.get("min_confirmations", 5))

    watchlist = await get_user_watchlist(user_id)
    in_watchlist = any(e["token_address"] == token_addr for e in watchlist)
    text = _format_candidate_detail(token, result)
    markup = build_cs_candidate_action(token_addr, in_watchlist=in_watchlist)
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=markup, parse_mode="HTML")


def _format_candidate_detail(token: dict, result: dict) -> str:
    sym   = token.get("symbol", "???")
    name  = token.get("name", "Unknown")
    addr  = token.get("address", "")
    score = result["composite_score"]
    eqs   = result["equations_passed"]
    rating = result["rating"]
    liq   = token.get("liquidity_usd", 0)
    vol   = token.get("volume_h1", 0)
    age   = token.get("age_minutes", 0)
    pc_h1 = token.get("price_change_h1", 0)
    pc_m5 = token.get("price_change_m5", 0)

    lines = [
        f"🕯️ <b>${sym}</b> — {name}",
        f"<code>{addr}</code>",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"<b>Score:</b> {score:.1f}/100  {rating}",
        f"<b>Equations:</b> {eqs}/9 passed",
        f"<b>Liquidity:</b> ${liq:,.0f}",
        f"<b>Vol h1:</b> ${vol:,.0f}",
        f"<b>Age:</b> {age}m",
        f"<b>Price Δ:</b> m5 {pc_m5:+.1f}%  h1 {pc_h1:+.1f}%",
        f"",
        f"<b>Equation Breakdown:</b>",
    ]
    for eq in result["equations"]:
        icon = "✅" if eq["passed"] else "❌"
        lines.append(f"{icon} {eq['name'].replace('_',' ').title()} "
                     f"({eq['score']:.0f}/{eq['weight']}) — {eq['reason']}")
    return "\n".join(lines)


# ── Debug Mode ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "cs:debug_prompt")
async def cb_cs_debug_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(CSFieldEditState.waiting_value)
    await state.update_data(field="__debug__")
    await callback.message.edit_text(
        "🔬 <b>Debug Token</b>\n\n"
        "Paste a Solana token address to see its full Candle Sniper equation breakdown:",
        reply_markup=build_cs_cancel(),
        parse_mode="HTML",
    )


@router.message(CSFieldEditState.waiting_value)
async def fsm_cs_field_value_main(message: Message, state: FSMContext) -> None:
    """Single FSM handler for both field edits and debug token input."""
    data  = await state.get_data()
    field = data.get("field", "")

    # Both __debug__ and __contract__ take a token address and show the detail
    if field in ("__debug__", "__contract__"):
        await state.clear()
        token_addr = (message.text or "").strip()
        if len(token_addr) < 20:
            await message.answer("❌ Invalid token address.", parse_mode="HTML")
            return

        await message.answer("🔬 Fetching token data and running equations…")
        token = await fetch_cs_token_data(token_addr)
        if not token:
            await message.answer(
                "❌ Could not fetch data for that token. "
                "It may not be on Solana or not yet indexed by DexScreener.",
                parse_mode="HTML",
            )
            return

        cfg    = await get_cs_settings(message.from_user.id)
        result = score_candidate(token, min_confirmations=cfg.get("min_confirmations", 3))
        text   = _format_candidate_detail(token, result)
        markup = build_cs_candidate_action(token_addr)
        await message.answer(text, reply_markup=markup, parse_mode="HTML")
        return

    # Field edit path
    await _handle_field_edit(message, state)


# ── Enter Contract Address ────────────────────────────────────────────────────

@router.callback_query(F.data == "cs:enter_contract")
async def cb_cs_enter_contract(callback: CallbackQuery, state: FSMContext) -> None:
    """User taps 'Enter Contract Address' — prompts for a Solana mint address."""
    await callback.answer()
    await state.set_state(CSFieldEditState.waiting_value)
    await state.update_data(field="__contract__")
    await callback.message.edit_text(
        "📋 <b>Enter Contract Address</b>\n\n"
        "Paste a Solana token mint address.\n"
        "The bot will score it and let you open a position using your CS settings.",
        reply_markup=build_cs_cancel(),
        parse_mode="HTML",
    )


# ── Buy a Candidate ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("cs:buy:"))
async def cb_cs_buy(callback: CallbackQuery) -> None:
    """User taps 'Buy This Token Now' from a candidate detail. Shows confirm screen."""
    partial = callback.data.split(":", 2)[-1]
    user_id = callback.from_user.id
    await callback.answer("Loading…")

    # Resolve full address from candidates table
    from services.candle_sniper_service import get_top_candidates
    cfg     = await get_cs_settings(user_id)
    profile = cfg.get("strategy_profile", "balanced")
    all_cands = await get_top_candidates(profile, limit=100)
    token_addr = next(
        (c["token_address"] for c in all_cands if c["token_address"][:20] == partial),
        None,
    )

    # Fallback: treat partial as the address itself if long enough
    if not token_addr and len(partial) >= 20:
        token_addr = partial

    if not token_addr:
        await callback.answer("Token not found — try refreshing candidates", show_alert=True)
        return

    trade_size = float(cfg.get("trade_size_sol") or 0.05)
    token    = await fetch_cs_token_data(token_addr)
    name     = token.get("name", "???") if token else "???"
    sym      = token.get("symbol", "???") if token else "???"
    liq      = token.get("liquidity_usd", 0) if token else 0
    slippage = float(cfg.get("slippage_pct") or 5.0)

    # Warn if slippage is likely too tight for this token
    is_pumpfun = token_addr.endswith("pump")
    low_liq    = liq < 100_000
    slip_warn  = ""
    if (is_pumpfun or low_liq) and slippage < 15:
        slip_warn = (
            f"\n\n⚠️ <b>Slippage Warning:</b> This token has "
            f"{'low liquidity ($' + f'{liq:,.0f}' + ')' if low_liq else 'a bonding curve'}. "
            f"Your current slippage ({slippage:.0f}%) may be too tight — "
            f"consider raising it to 15%+ in ⚙️ Settings to avoid rejection."
        )

    text = (
        f"💰 <b>Confirm Buy — Candle Sniper</b>\n\n"
        f"<b>Token:</b> ${sym} — {name}\n"
        f"<code>{token_addr}</code>\n\n"
        f"<b>Trade Size:</b> {trade_size:.4f} SOL\n"
        f"<b>Slippage:</b> {slippage:.0f}%\n"
        f"<b>Stop Loss:</b> -{cfg.get('stop_loss_pct', 15):.0f}%  "
        f"<b>Take Profit:</b> +{cfg.get('take_profit_pct', 50):.0f}%"
        f"{slip_warn}"
    )
    await callback.message.edit_text(
        text,
        reply_markup=build_cs_confirm_buy(token_addr, trade_size),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("cs:confirm_buy:"))
async def cb_cs_confirm_buy(callback: CallbackQuery) -> None:
    """Executes the actual buy after user confirmation."""
    from services.solana_execution_service import execute_buy
    from services.bot_wallet_service import get_or_create_bot_wallet, get_sol_balance
    from services.token_data_provider import get_token_price_in_sol
    from services.candle_sniper_service import open_cs_position

    partial = callback.data.split(":", 2)[-1]
    user_id = callback.from_user.id

    # Resolve token address
    cfg     = await get_cs_settings(user_id)
    profile = cfg.get("strategy_profile", "balanced")
    from services.candle_sniper_service import get_top_candidates
    all_cands = await get_top_candidates(profile, limit=100)
    token_addr = next(
        (c["token_address"] for c in all_cands if c["token_address"][:20] == partial),
        None,
    ) or (partial if len(partial) >= 20 else None)

    if not token_addr:
        await callback.answer("Token not found", show_alert=True)
        return

    trade_size = float(cfg.get("trade_size_sol") or 0.05)

    # Balance check
    wallet_row = await get_or_create_bot_wallet(user_id)
    balance    = await get_sol_balance(wallet_row["wallet_address"])
    if not balance or balance < trade_size + 0.002:
        await callback.answer(
            f"⚠️ Insufficient balance: {balance or 0:.4f} SOL (need {trade_size + 0.002:.4f} SOL)\n"
            f"Top up your bot wallet and try again.",
            show_alert=True,
        )
        return

    slippage = float(cfg.get("slippage_pct") or 5.0)
    await callback.answer("Executing buy…")
    result = await execute_buy(
        user_id          = user_id,
        token_address    = token_addr,
        amount_sol       = trade_size,
        slippage_pct     = slippage,
        priority_fee_sol = 0.005,
        platform         = "auto",
        exit_preset_id   = None,
    )

    if result.get("success"):
        sig          = result.get("signature", "")
        entry_price  = await get_token_price_in_sol(token_addr) or 0.0
        pos_id = await open_cs_position(
            user_id              = user_id,
            token_address        = token_addr,
            entry_price_sol      = entry_price,
            tx_signature         = sig,
            trade_size_sol       = trade_size,
            stop_loss_pct        = float(cfg.get("stop_loss_pct", 15.0)),
            take_profit_pct      = float(cfg.get("take_profit_pct", 50.0)),
            trailing_stop_pct    = float(cfg.get("trailing_stop_pct", 10.0)),
            max_duration_minutes = 120,
        )
        token = await fetch_cs_token_data(token_addr)
        sym   = token.get("symbol", "???") if token else "???"
        await callback.message.edit_text(
            f"✅ <b>Position Opened — ${sym}</b>\n\n"
            f"<code>{token_addr}</code>\n"
            f"<b>Size:</b> {trade_size:.4f} SOL\n"
            f"<b>TP:</b> +{cfg.get('take_profit_pct', 50):.0f}%  "
            f"<b>SL:</b> -{cfg.get('stop_loss_pct', 15):.0f}%\n"
            f"<b>TX:</b> <code>{sig[:20]}…</code>\n\n"
            f"<i>Position #{pos_id} is now being monitored.</i>",
            reply_markup=build_cs_back_to_main(),
            parse_mode="HTML",
        )
        logger.info(f"CS manual buy success user={user_id} pos={pos_id} token={token_addr[:8]}")
    else:
        err = result.get("error", "Unknown error")
        # Give actionable hints based on error type
        if "RPC rejected" in err:
            hint = (
                "\n\n💡 <b>Most likely cause: slippage too tight.</b>\n"
                "Go to ⚙️ Settings → Slippage and raise it to <b>15–25%</b> for volatile or "
                "low-liquidity tokens, then try again."
            )
        elif "bonding curve" in err and "no route" in err:
            hint = (
                "\n\n💡 Token is between bonding curve and DEX listing — "
                "try again in a few minutes once the Raydium pool is indexed."
            )
        elif "no route found" in err or "no route" in err.lower():
            hint = (
                "\n\n💡 Token may have very thin liquidity or no DEX pair yet. "
                "Try raising slippage in ⚙️ Settings or wait for more liquidity."
            )
        elif "bonding curve" in err:
            hint = (
                "\n\n💡 Token may have graduated from pump.fun. "
                "It should now be tradeable via Jupiter — try again in 1–2 minutes."
            )
        elif "low balance" in err.lower() or "insufficient" in err.lower():
            hint = "\n\n💡 Top up your bot wallet with more SOL and try again."
        else:
            hint = ""
        await callback.message.edit_text(
            f"❌ <b>Buy Failed</b>\n\n{err}{hint}",
            reply_markup=build_cs_back_to_main(),
            parse_mode="HTML",
        )


# ── Watchlist Add / Remove ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("cs:add_token:"))
async def cb_cs_add_token(callback: CallbackQuery) -> None:
    token_addr = callback.data.split(":", 2)[-1]
    user_id    = callback.from_user.id

    # Try to get symbol from candidates to store alongside address
    cfg     = await get_cs_settings(user_id)
    profile = cfg.get("strategy_profile", "balanced")
    all_cands = await get_top_candidates(profile, limit=100)
    match = next((c for c in all_cands if c["token_address"].startswith(token_addr)), None)
    symbol = (match.get("token_symbol") or "") if match else ""
    name   = (match.get("token_name")   or "") if match else ""

    try:
        await add_watchlist_token(user_id, token_addr, symbol, name)
        await callback.answer(f"✅ ${symbol or token_addr[:8]} added to your list", show_alert=False)
    except Exception as exc:
        logger.warning(f"add_watchlist_token error: {exc}")
        await callback.answer("Already in your list", show_alert=False)

    # Refresh candidates view
    await cb_cs_candidates(callback)


@router.callback_query(F.data.startswith("cs:rm_token:"))
async def cb_cs_rm_token(callback: CallbackQuery) -> None:
    token_addr = callback.data.split(":", 2)[-1]
    user_id    = callback.from_user.id

    await remove_watchlist_token(user_id, token_addr)
    await callback.answer("❌ Removed from your list", show_alert=False)

    # Return to candidates view
    await cb_cs_candidates(callback)


# ── Positions ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "cs:positions")
async def cb_cs_positions(callback: CallbackQuery) -> None:
    user_id    = callback.from_user.id
    positions  = await get_cs_open_positions(user_id)
    await callback.answer()

    if not positions:
        text = "📈 <b>Candle Sniper Positions</b>\n\nNo open positions."
    else:
        lines = [f"📈 <b>Candle Sniper Positions</b> ({len(positions)} open)\n"]
        for pos in positions:
            addr    = pos.get("token_address", "")
            entry   = float(pos.get("entry_price_sol") or 0)
            current = float(pos.get("current_price_sol") or 0)
            size    = float(pos.get("trade_size_sol") or 0)
            tp      = float(pos.get("take_profit_pct") or 50)
            sl      = float(pos.get("stop_loss_pct") or 15)
            pnl     = ((current - entry) / entry * 100) if entry > 0 else 0
            icon    = "🟢" if pnl >= 0 else "🔴"
            lines.append(
                f"\n{icon} <code>{addr[:20]}…</code>\n"
                f"   PnL: <b>{pnl:+.1f}%</b> | Size: {size:.4f} SOL\n"
                f"   TP: +{tp:.0f}%  SL: -{sl:.0f}%"
            )
        text = "\n".join(lines)

    try:
        await callback.message.edit_text(
            text, reply_markup=build_cs_positions(positions), parse_mode="HTML"
        )
    except Exception:
        await callback.message.answer(text, parse_mode="HTML")


@router.callback_query(F.data == "cs:share_positions")
async def cb_cs_share_positions(callback: CallbackQuery) -> None:
    from services.candle_sniper_service import get_cs_open_positions
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    from urllib.parse import quote

    user_id   = callback.from_user.id
    positions = await get_cs_open_positions(user_id)
    bot_link  = _bot_link()

    if not positions:
        pos_lines = "No open positions yet — watching the market 👀"
    else:
        pos_lines = ""
        for pos in positions:
            addr  = pos.get("token_address", "")
            entry = float(pos.get("entry_price_sol") or 0)
            curr  = float(pos.get("current_price_sol") or 0)
            size  = float(pos.get("trade_size_sol") or 0)
            pnl   = ((curr - entry) / entry * 100) if entry > 0 else 0
            icon  = "🟢" if pnl >= 0 else "🔴"
            pos_lines += f"{icon} {addr[:8]}...{addr[-4:]}  {pnl:+.1f}%  {size:.4f} SOL\n"

    tweet = (
        f"🕯️ $BRAINROT Candle Sniper — Live Positions\n\n"
        f"{pos_lines}\n"
        f"Automated Solana trading with $BRAINROT Alpha Bot ⚡\n\n"
        f"{settings.BRAND_HANDLE}\n"
        f"#Solana #BRAINROT #DeFi #Memecoin #SolanaTrading #CandleSniper"
    )

    tg_post = (
        f"🕯️ $BRAINROT Candle Sniper — Live Positions\n\n"
        f"{pos_lines}\n"
        f"Running fully automated on Solana with $BRAINROT Alpha Bot\n"
        f"Try it 👇\n{bot_link}\n\n"
        f"{settings.BRAND_HANDLE}  #Solana #BRAINROT"
    )

    tiktok_ig = (
        f"🕯️ My $BRAINROT bot is live trading Solana tokens RIGHT NOW\n\n"
        f"{pos_lines}\n"
        f"Fully automated. No charts. No stress. 🚀\n\n"
        f"#Solana #Crypto #BRAINROT #DeFi #Memecoin #TradingBot {settings.SHARE_HASHTAG} #CryptoTrading"
    )

    x_url  = f"https://x.com/intent/tweet?text={quote(tweet)}"
    tg_url = f"https://t.me/share/url?url={quote(bot_link)}&text={quote(tg_post)}"
    reddit_url = (
        f"https://www.reddit.com/submit"
        f"?title={quote('$BRAINROT Candle Sniper — Live Positions')}"
        f"&text={quote(tweet)}"
    )

    _BRAINROT_CA = settings.BRAINROT_MINT

    # Individual tap-to-copy address lines per position
    addr_lines = ""
    for pos in positions:
        addr    = pos.get("token_address", "")
        entry   = float(pos.get("entry_price_sol") or 0)
        curr    = float(pos.get("current_price_sol") or 0)
        pnl_p   = ((curr - entry) / entry * 100) if entry > 0 else 0
        icon    = "🟢" if pnl_p >= 0 else "🔴"
        addr_lines += f"{icon} {pnl_p:+.1f}%\n<pre>{addr}</pre>\n"

    text = (
        f"📣 <b>Share Your Candle Sniper Positions</b>\n"
        f"{'━' * 30}\n\n"
        + (f"<b>Position CAs:</b>\n{addr_lines}\n" if addr_lines else "No open positions.\n\n")
        + f"<b>$BRAINROT CA:</b>\n"
        f"<pre>{_BRAINROT_CA}</pre>\n"
        f"<b>X / Twitter (tap to copy):</b>\n"
        f"<code>{tweet}</code>\n\n"
        f"<b>TikTok / Instagram caption:</b>\n"
        f"<code>{tiktok_ig}</code>\n\n"
        f"🔗 Follow <a href=\"{settings.TWITTER_URL}\">{settings.BRAND_HANDLE}</a> on X"
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
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="cs:positions"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), disable_web_page_preview=True)
    await callback.answer()


@router.callback_query(F.data == "cs:share_stats")
async def cb_cs_share_stats(callback: CallbackQuery) -> None:
    from services.candle_sniper_worker import get_stats
    from services.candle_sniper_service import get_cs_open_positions
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    from urllib.parse import quote
    import time

    user_id   = callback.from_user.id
    cfg       = await get_cs_settings(user_id)
    positions = await get_cs_open_positions(user_id)
    stats     = get_stats()

    cycles  = stats.get("discovery_cycles", 0)
    scored  = stats.get("candidates_scored", 0)
    buys    = stats.get("buys_executed", 0)
    closed  = stats.get("positions_closed", 0)
    last_ts = stats.get("last_discovery_ts", 0)
    surge_alerts = stats.get("surge_alerts", 0)
    surge_buys   = stats.get("surge_buys", 0)

    if last_ts:
        secs_ago = int(time.time() - last_ts)
        last_scan = f"{secs_ago}s ago" if secs_ago < 120 else f"{secs_ago // 60}m ago"
    else:
        last_scan = "not yet"

    profile  = cfg.get("strategy_profile", "balanced").title()
    trade_sz = cfg.get("trade_size_sol", 0.05)

    # PnL summary across open positions
    total_pnl_pct = 0.0
    pnl_count     = 0
    pnl_lines     = ""
    for pos in positions:
        entry   = float(pos.get("entry_price_sol") or 0)
        current = float(pos.get("current_price_sol") or 0)
        if entry > 0 and current > 0:
            pnl = ((current - entry) / entry) * 100
            total_pnl_pct += pnl
            pnl_count += 1
            icon = "🟢" if pnl >= 0 else "🔴"
            addr = pos.get("token_address", "")
            pnl_lines += f"{icon} {addr[:6]}…{addr[-4:]}  {pnl:+.1f}%\n"

    avg_pnl_str = f"{total_pnl_pct / pnl_count:+.1f}%" if pnl_count else "—"

    # ── Compose posts ─────────────────────────────────────────────────────────
    bot_link = _bot_link()

    stats_block = (
        f"📊 {cycles} scans  ·  {scored} scored  ·  {buys} buys  ·  {closed} closed\n"
        f"🚀 Surge alerts: {surge_alerts}  ·  Surge buys: {surge_buys}\n"
        f"📈 Open positions: {len(positions)}  ·  Avg PnL: {avg_pnl_str}\n"
        f"⏱ Last scan: {last_scan}  ·  Profile: {profile}  ·  Size: {trade_sz} SOL"
    )

    tweet = (
        f"🕯️ $BRAINROT Candle Sniper — Live Stats\n\n"
        f"{stats_block}\n\n"
        f"{pnl_lines}"
        f"Fully automated Solana trading powered by $BRAINROT Alpha Bot ⚡\n\n"
        f"{settings.BRAND_HANDLE}\n"
        f"#Solana #BRAINROT #DeFi #Memecoin #SolanaTrading #CandleSniper #TradingBot"
    )

    tg_post = (
        f"🕯️ $BRAINROT Candle Sniper — Live Stats\n\n"
        f"{stats_block}\n\n"
        f"{pnl_lines}"
        f"Running 24/7 on Solana with $BRAINROT Alpha Bot ⚡\n"
        f"Try it 👉 {bot_link}\n\n"
        f"{settings.BRAND_HANDLE}  #Solana #BRAINROT #CandleSniper"
    )

    tiktok_ig = (
        f"🕯️ My $BRAINROT bot just ran {cycles} scans and executed {buys} trades — fully automatic 🤖\n\n"
        f"{pnl_lines}"
        f"No charts. No stress. Solana trading on autopilot 🚀\n\n"
        f"#Solana #Crypto #BRAINROT #DeFi #TradingBot #Memecoin {settings.SHARE_HASHTAG} #CandleSniper"
    )

    x_url = f"https://x.com/intent/tweet?text={quote(tweet)}"
    tg_url = f"https://t.me/share/url?url={quote(bot_link)}&text={quote(tg_post)}"
    reddit_url = (
        f"https://www.reddit.com/submit"
        f"?title={quote('$BRAINROT Candle Sniper — Live Trading Stats')}"
        f"&text={quote(tweet)}"
    )

    _BRAINROT_CA = settings.BRAINROT_MINT

    # Individual tap-to-copy address lines
    addr_lines = ""
    for pos in positions:
        addr    = pos.get("token_address", "")
        entry   = float(pos.get("entry_price_sol") or 0)
        current = float(pos.get("current_price_sol") or 0)
        pnl_p   = ((current - entry) / entry * 100) if entry > 0 else 0
        icon    = "🟢" if pnl_p >= 0 else "🔴"
        addr_lines += f"{icon} {pnl_p:+.1f}%\n<pre>{addr}</pre>\n"

    text = (
        f"📣 <b>Share Candle Sniper Stats</b>\n"
        f"{'━' * 30}\n\n"
        f"<b>Session Progress</b>\n"
        f"🔍 Scans: <b>{cycles}</b>  ·  Scored: <b>{scored}</b>\n"
        f"💰 Buys: <b>{buys}</b>  ·  Closed: <b>{closed}</b>\n"
        f"🚀 Surge alerts: <b>{surge_alerts}</b>  ·  Surge buys: <b>{surge_buys}</b>\n"
        f"📈 Open: <b>{len(positions)}</b>  ·  Avg PnL: <b>{avg_pnl_str}</b>\n"
        f"⏱ Last scan: <b>{last_scan}</b>\n\n"
        + (f"<b>Open position CAs</b>:\n{addr_lines}\n" if addr_lines else "")
        + f"<b>$BRAINROT CA:</b>\n"
        f"<pre>{_BRAINROT_CA}</pre>\n"
        f"<b>X / Twitter post (tap to copy):</b>\n"
        f"<code>{tweet}</code>\n\n"
        f"<b>TikTok / Instagram caption:</b>\n"
        f"<code>{tiktok_ig}</code>\n\n"
        f"🔗 <a href=\"{settings.TWITTER_URL}\">{settings.BRAND_HANDLE}</a>"
    )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="𝕏  Post to X",        url=x_url),
        InlineKeyboardButton(text="✈️ Share on Telegram", url=tg_url),
    )
    builder.row(
        InlineKeyboardButton(text="🔴 Share on Reddit",  url=reddit_url),
        InlineKeyboardButton(text="📈 View Positions",   callback_data="cs:positions"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="cs:main"))

    await callback.message.edit_text(
        text, reply_markup=builder.as_markup(),
        parse_mode="HTML", disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cs:pos_detail:"))
async def cb_cs_pos_detail(callback: CallbackQuery) -> None:
    pos_id = int(callback.data.split(":")[-1])
    user_id = callback.from_user.id
    positions = await get_cs_open_positions(user_id)
    pos = next((p for p in positions if p["id"] == pos_id), None)

    if not pos:
        await callback.answer("Position not found", show_alert=True)
        return

    await callback.answer()
    addr    = pos.get("token_address", "")
    entry   = float(pos.get("entry_price_sol") or 0)
    current = float(pos.get("current_price_sol") or 0)
    highest = float(pos.get("highest_price_sol") or 0)
    size    = float(pos.get("trade_size_sol") or 0)
    tp      = float(pos.get("take_profit_pct") or 50)
    sl      = float(pos.get("stop_loss_pct") or 15)
    trail   = float(pos.get("trailing_stop_pct") or 10)
    pnl     = ((current - entry) / entry * 100) if entry > 0 else 0

    text = (
        f"📈 <b>CS Position Detail</b>\n"
        f"<code>{addr}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>PnL:</b> {pnl:+.1f}%\n"
        f"<b>Entry:</b> {entry:.8f} SOL\n"
        f"<b>Current:</b> {current:.8f} SOL\n"
        f"<b>Peak:</b> {highest:.8f} SOL\n"
        f"<b>Size:</b> {size:.4f} SOL\n"
        f"<b>TP:</b> +{tp:.0f}%  <b>SL:</b> -{sl:.0f}%  "
        f"<b>Trail:</b> {trail:.0f}%\n"
        f"<b>Opened:</b> {pos.get('opened_at','')}"
    )
    await callback.message.edit_text(
        text, reply_markup=build_cs_pos_detail(pos_id), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("cs:pos_close:"))
async def cb_cs_pos_close(callback: CallbackQuery) -> None:
    pos_id  = int(callback.data.split(":")[-1])
    user_id = callback.from_user.id

    # Verify ownership
    positions = await get_cs_open_positions(user_id)
    pos = next((p for p in positions if p["id"] == pos_id), None)
    if not pos:
        await callback.answer("Position not found or already closed", show_alert=True)
        return

    from services.solana_execution_service import execute_sell
    token_addr = pos["token_address"]
    cfg_for_slip = await get_cs_settings(user_id)
    slippage = float(cfg_for_slip.get("slippage_pct") or 5.0)

    await callback.answer("Executing sell…")
    result = await execute_sell(
        user_id=user_id, token_address=token_addr,
        sell_pct=100.0, slippage_pct=slippage,
        priority_fee_sol=0.005, platform="auto",
    )
    await close_cs_position(pos_id, "Manual close via UI")

    if result.get("success"):
        sig = result.get("signature", "")
        await callback.message.edit_text(
            f"✅ <b>Position closed</b>\n<code>{token_addr}</code>\n"
            f"TX: <code>{sig[:20]}…</code>",
            reply_markup=build_cs_back_to_main(), parse_mode="HTML",
        )
    else:
        err = result.get("error", "Unknown")
        await callback.message.edit_text(
            f"⚠️ <b>Sell failed</b>\n{err}\n\n"
            f"<i>Position marked closed — check your wallet manually.</i>",
            reply_markup=build_cs_back_to_main(), parse_mode="HTML",
        )
