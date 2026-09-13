"""
bot/keyboards/auto_exit_menu.py
================================
All inline keyboards for the Supreme Black Auto-Exit Manager.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

BLUR = "███"  # placeholder for locked values


def build_auto_exit_main(s: dict, is_black: bool) -> InlineKeyboardMarkup:
    """Main Auto-Exit Manager menu."""
    b = InlineKeyboardBuilder()
    power_icon = "🟢 ONLINE"  if s.get("enabled")   else "🔴 OFFLINE"
    mode_icon  = "🔴 LIVE"    if s.get("live_mode") else "📄 PAPER"

    b.row(
        InlineKeyboardButton(text=f"⚡ POWER: {power_icon}", callback_data="ae:toggle"),
        InlineKeyboardButton(text=f"MODE: {mode_icon}",      callback_data="ae:live_toggle"),
    )
    b.row(
        InlineKeyboardButton(text="📡 POSITIONS & CONFIG",   callback_data="ae:positions"),
        InlineKeyboardButton(text="⚙️ SETTINGS",             callback_data="ae:settings"),
    )
    b.row(
        InlineKeyboardButton(text="⭐ BLACK PRESETS",        callback_data="ae:sys_presets"),
        InlineKeyboardButton(text="📂 MY PRESETS",           callback_data="ae:presets"),
    )
    if not is_black:
        b.row(InlineKeyboardButton(
            text="🖤 UPGRADE TO SUPREME BLACK",
            callback_data="ae:upgrade_cta",
        ))
    b.row(InlineKeyboardButton(text="⬅️  BACK", callback_data="sniper:main"))
    return b.as_markup()


def build_sys_presets(presets: list[dict], is_black: bool) -> InlineKeyboardMarkup:
    """List of Supreme Black system presets. Values blurred for non-members."""
    b = InlineKeyboardBuilder()
    for p in presets:
        b.row(InlineKeyboardButton(
            text=f"⭐ {p['name'].upper()}",
            callback_data=f"ae:view_preset:{p['id']}" if is_black else "ae:upgrade_cta",
        ))
    b.row(InlineKeyboardButton(text="⬅️  BACK", callback_data="ae:main"))
    return b.as_markup()


def build_preset_view(preset: dict, is_black: bool, is_system: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if is_black:
        b.row(
            InlineKeyboardButton(text="✅ APPLY GLOBALLY",  callback_data=f"ae:apply_preset:{preset['id']}"),
            InlineKeyboardButton(text="📋 CLONE",           callback_data=f"ae:clone_preset:{preset['id']}"),
        )
        if not is_system:
            b.row(InlineKeyboardButton(text="🗑 DELETE",    callback_data=f"ae:del_preset:{preset['id']}"))
    else:
        b.row(InlineKeyboardButton(text="🔒 UNLOCK — UPGRADE TO SUPREME BLACK", callback_data="ae:upgrade_cta"))
    b.row(InlineKeyboardButton(text="⬅️  BACK", callback_data="ae:sys_presets"))
    return b.as_markup()


def build_user_presets(presets: list[dict], is_black: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in presets:
        b.row(InlineKeyboardButton(
            text=f"📂 {p['name'].upper()}",
            callback_data=f"ae:view_preset:{p['id']}",
        ))
    if is_black:
        b.row(InlineKeyboardButton(text="📋 CLONE A BLACK PRESET", callback_data="ae:sys_presets"))
    b.row(InlineKeyboardButton(text="⬅️  BACK", callback_data="ae:main"))
    return b.as_markup()


def build_ae_positions(positions: list[dict]) -> InlineKeyboardMarkup:
    """Simple list of positions (used internally)."""
    b = InlineKeyboardBuilder()
    for ps in positions[:10]:
        token  = ps["token_address"]
        short  = token[:6] + "..." + token[-4:]
        status = ps.get("status", "?")
        b.row(InlineKeyboardButton(
            text=f"📍 {short}  [{status}]",
            callback_data=f"ae:pos_detail:{ps['position_id']}",
        ))
    b.row(InlineKeyboardButton(text="🔄 REFRESH", callback_data="ae:positions"))
    b.row(InlineKeyboardButton(text="⬅️  BACK",   callback_data="ae:main"))
    return b.as_markup()


def build_ae_positions_full(
    positions: list[dict],
    ae_s: dict,
    ab_s: dict,
    is_black: bool,
) -> InlineKeyboardMarkup:
    """
    Full positions page keyboard including sniper quick-action buttons.
    Top section: auto-buy / auto-exit toggles + preset picker.
    Bottom section: one button per active position.
    """
    b = InlineKeyboardBuilder()

    # ── Quick toggles ──────────────────────────────────────────────────────────
    ab_icon = "🟢 AUTO-BUY ON"  if ab_s.get("enabled") else "🔴 AUTO-BUY OFF"
    ae_icon = "🟢 AUTO-EXIT ON" if ae_s.get("enabled") else "🔴 AUTO-EXIT OFF"
    b.row(
        InlineKeyboardButton(text=ab_icon,  callback_data="sniper:ab_toggle"),
        InlineKeyboardButton(text=ae_icon,  callback_data="ae:toggle"),
    )

    # ── Sniper quick-filter shortcuts ──────────────────────────────────────────
    b.row(
        InlineKeyboardButton(text="🎯 SCORE THRESHOLD", callback_data="ae:qset:score_threshold"),
        InlineKeyboardButton(text="💧 MIN LIQUIDITY",   callback_data="ae:qs:min_liquidity"),
    )
    b.row(
        InlineKeyboardButton(text="⏱ MAX AGE",          callback_data="ae:qs:max_token_age_minutes"),
        InlineKeyboardButton(text="💰 BUY SIZE",         callback_data="ae:qset:max_buy_size_sol"),
    )

    # ── Preset picker ──────────────────────────────────────────────────────────
    b.row(InlineKeyboardButton(
        text="⭐ SELECT EXIT PRESET" if is_black else "🔒 EXIT PRESET (BLACK ONLY)",
        callback_data="ae:pick_exit_preset" if is_black else "ae:upgrade_cta",
    ))

    # ── Quick preset shortcut buttons ──────────────────────────────────────────
    if is_black:
        b.row(
            InlineKeyboardButton(text="⚡ QUICK FLIP",     callback_data="ae:quick_preset:0"),
            InlineKeyboardButton(text="🏃 BALANCED",       callback_data="ae:quick_preset:1"),
            InlineKeyboardButton(text="🛡️ RISK-OFF",       callback_data="ae:quick_preset:2"),
        )

    # ── Per-position rows ──────────────────────────────────────────────────────
    if positions:
        for ps in positions[:8]:
            token   = ps["token_address"]
            short   = token[:6] + "…" + token[-4:]
            status  = ps.get("status", "?")
            entry   = float(ps.get("entry_price_sol") or 0)
            current = float(ps.get("current_price_sol") or 0)
            if entry > 0 and current > 0:
                chg = (current - entry) / entry * 100
                pnl = f"{chg:+.1f}%"
            else:
                pnl = "…"
            pos_id = ps["position_id"]
            b.row(
                InlineKeyboardButton(
                    text=f"📍 {short}  {pnl}  [{status}]",
                    callback_data=f"ae:pos_detail:{pos_id}",
                ),
            )
            if is_black:
                b.row(
                    InlineKeyboardButton(text="💸 SELL 50%", callback_data=f"ae:manual_sell:{pos_id}:50"),
                    InlineKeyboardButton(text="💸 SELL ALL", callback_data=f"ae:manual_sell:{pos_id}:100"),
                )

    b.row(
        InlineKeyboardButton(text="🔄 REFRESH", callback_data="ae:positions"),
        InlineKeyboardButton(text="⬅️  BACK",   callback_data="ae:main"),
    )
    return b.as_markup()


def build_pos_detail(ps: dict, is_black: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    pos_id = ps["position_id"]
    if is_black:
        b.row(
            InlineKeyboardButton(text="💸 MANUAL SELL 50%", callback_data=f"ae:manual_sell:{pos_id}:50"),
            InlineKeyboardButton(text="💸 SELL ALL",        callback_data=f"ae:manual_sell:{pos_id}:100"),
        )
        b.row(
            InlineKeyboardButton(text="🔀 CHANGE PRESET",   callback_data=f"ae:pos_preset:{pos_id}"),
            InlineKeyboardButton(text="⏹ STOP WATCHING",   callback_data=f"ae:pos_stop:{pos_id}"),
        )
    b.row(InlineKeyboardButton(text="⬅️  BACK", callback_data="ae:positions"))
    return b.as_markup()


def build_ae_settings(s: dict) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="📐 SLIPPAGE",      callback_data="ae:set:custom_slippage"),
        InlineKeyboardButton(text="⚡ PRIORITY FEE",  callback_data="ae:set:custom_priority_fee"),
    )
    notif_icon = "✅" if s.get("notifications_enabled") else "⬜"
    b.row(
        InlineKeyboardButton(text=f"{notif_icon} NOTIFICATIONS", callback_data="ae:toggle_notif"),
    )
    b.row(InlineKeyboardButton(text="⬅️  BACK", callback_data="ae:main"))
    return b.as_markup()


def build_ae_cancel() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ CANCEL", callback_data="ae:cancel_fsm"))
    return b.as_markup()


def build_back_to_ae() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️  BACK TO AUTO-EXIT", callback_data="ae:main"))
    return b.as_markup()
