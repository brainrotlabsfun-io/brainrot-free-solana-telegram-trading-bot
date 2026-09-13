"""
bot/keyboards/candle_sniper_menu.py
=====================================
Inline keyboard builders for the Candle Sniper module.
All callback_data uses the "cs:" prefix to avoid conflicts.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.keyboards.share_templates import (
    CANDLE_SNIPER_SHARE_URL,
    CS_SHARE_TWITTER_URL,
    CS_SHARE_TELEGRAM_URL,
    CS_SHARE_REDDIT_URL,
    SHARE_HASHTAG_URL,
)


def build_cs_share_menu() -> InlineKeyboardMarkup:
    """Universal community share menu for Candle Sniper."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🐦 POST ON X",           url=CS_SHARE_TWITTER_URL),
        InlineKeyboardButton(text="✈️ SHARE TO TELEGRAM",   url=CS_SHARE_TELEGRAM_URL),
    )
    builder.row(
        InlineKeyboardButton(text="🟠 POST TO REDDIT",      url=CS_SHARE_REDDIT_URL),
        InlineKeyboardButton(text="# COMMUNITY HASHTAG",    url=SHARE_HASHTAG_URL),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️  BACK",               callback_data="cs:main"),
    )
    return builder.as_markup()


# ── Main Menu ─────────────────────────────────────────────────────────────────

def build_cs_main(cfg: dict, tier: str, ents) -> InlineKeyboardMarkup:
    """Main Candle Sniper menu with status-aware toggle button."""
    builder  = InlineKeyboardBuilder()
    enabled  = bool(cfg.get("enabled"))
    auto_buy = bool(cfg.get("auto_buy"))
    profile  = cfg.get("strategy_profile", "balanced")

    toggle_label = "🟢 ACTIVE — TAP TO DISABLE" if enabled else "⚪ OFF — TAP TO ENABLE"
    builder.row(InlineKeyboardButton(text=toggle_label, callback_data="cs:toggle"))

    ab_label = "🤖 AUTO-BUY: ON" if auto_buy else "🤖 AUTO-BUY: OFF"
    builder.row(InlineKeyboardButton(text=ab_label, callback_data="cs:toggle_autobuy"))

    builder.row(
        InlineKeyboardButton(text=f"📊 PROFILE: {profile.upper()}", callback_data="cs:profile_menu"),
        InlineKeyboardButton(text="⚙️ SETTINGS",                    callback_data="cs:settings"),
    )
    builder.row(
        InlineKeyboardButton(text="🔍 VIEW CANDIDATES",  callback_data="cs:candidates"),
        InlineKeyboardButton(text="📈 MY POSITIONS",     callback_data="cs:positions"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 ENTER CONTRACT ADDRESS", callback_data="cs:enter_contract"),
    )

    builder.row(InlineKeyboardButton(text="👑 SUPREME ACCESS", callback_data="supreme:main"))
    builder.row(InlineKeyboardButton(text="🌐  SHARE TO COMMUNITY", callback_data="cs:share_menu"))
    builder.row(InlineKeyboardButton(text="⬅️ BACK TO MENU", callback_data="menu:back"))
    return builder.as_markup()


# ── Strategy Profile Picker ───────────────────────────────────────────────────

def build_cs_profile_menu(current: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    profiles = [
        ("🔵 SAFE",         "safe"),
        ("🛡️ CONSERVATIVE", "conservative"),
        ("⚖️ BALANCED",     "balanced"),
        ("⚡ ACTIVE",       "active"),
        ("🔥 AGGRESSIVE",   "aggressive"),
        ("💀 DEGEN",        "degen"),
    ]
    for label, key in profiles:
        mark = " ✓" if current == key else ""
        builder.row(InlineKeyboardButton(
            text=f"{label}{mark}", callback_data=f"cs:set_profile:{key}"
        ))
    builder.row(InlineKeyboardButton(text="⬅️ BACK", callback_data="cs:main"))
    return builder.as_markup()


# ── Settings Menu ─────────────────────────────────────────────────────────────

def build_cs_settings(cfg: dict, ents) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    def _fmt(key):
        return str(cfg.get(key, "—"))

    builder.row(
        InlineKeyboardButton(text=f"💰 TRADE SIZE: {_fmt('trade_size_sol')} SOL",
                             callback_data="cs:set_field:trade_size_sol"),
        InlineKeyboardButton(text=f"📦 MAX POSITIONS: {_fmt('max_open_positions')}",
                             callback_data="cs:set_field:max_open_positions"),
    )
    builder.row(
        InlineKeyboardButton(text=f"🔴 STOP LOSS: {_fmt('stop_loss_pct')}%",
                             callback_data="cs:set_field:stop_loss_pct"),
        InlineKeyboardButton(text=f"🟢 TAKE PROFIT: {_fmt('take_profit_pct')}%",
                             callback_data="cs:set_field:take_profit_pct"),
    )
    builder.row(
        InlineKeyboardButton(text=f"💧 SLIPPAGE: {_fmt('slippage_pct')}%",
                             callback_data="cs:set_field:slippage_pct"),
        InlineKeyboardButton(text=f"⏳ COOLDOWN: {_fmt('cooldown_seconds')}S",
                             callback_data="cs:set_field:cooldown_seconds"),
    )
    builder.row(
        InlineKeyboardButton(text=f"⏱ MAX HOLD: {_fmt('max_hold_minutes')}M",
                             callback_data="cs:set_field:max_hold_minutes"),
    )
    builder.row(
        InlineKeyboardButton(text=f"🎯 CONFIDENCE: {_fmt('confidence_threshold')}%",
                             callback_data="cs:set_field:confidence_threshold"),
        InlineKeyboardButton(text=f"✅ MIN SIGNALS: {_fmt('min_confirmations')}/9",
                             callback_data="cs:set_field:min_confirmations"),
    )
    if ents.can_trailing_stop:
        builder.row(InlineKeyboardButton(
            text=f"📉 TRAILING STOP: {_fmt('trailing_stop_pct')}%",
            callback_data="cs:set_field:trailing_stop_pct",
        ))
    else:
        builder.row(InlineKeyboardButton(
            text="📉 TRAILING STOP: 👑 SUPREME ONLY",
            callback_data="cs:locked:trailing_stop",
        ))
    builder.row(
        InlineKeyboardButton(
            text=f"♻️ RESTORE ON EXIT: {'ON' if cfg.get('restore_previous_config') else 'OFF'}",
            callback_data="cs:toggle_restore",
        ),
    )
    # ── Surge Detector ─────────────────────────────────────────────────────────
    surge_on = bool(cfg.get("surge_enabled"))
    surge_label = f"🚀 SURGE DETECTOR: {'ON ✅' if surge_on else 'OFF'}"
    builder.row(InlineKeyboardButton(text=surge_label, callback_data="cs:toggle_surge"))
    if surge_on:
        builder.row(
            InlineKeyboardButton(
                text=f"📈 SURGE THRESHOLD: {cfg.get('surge_threshold_pct', 500):.0f}%",
                callback_data="cs:set_field:surge_threshold_pct",
            ),
            InlineKeyboardButton(
                text=f"⏱ TRACK WINDOW: {cfg.get('surge_track_hours', 24)}H",
                callback_data="cs:set_field:surge_track_hours",
            ),
        )
    builder.row(InlineKeyboardButton(text="⬅️ BACK", callback_data="cs:main"))
    return builder.as_markup()


# ── Candidates List ───────────────────────────────────────────────────────────

def build_cs_candidates(candidates: list[dict], watchlist_addrs: set,
                        limit: int = 10) -> InlineKeyboardMarkup:
    """
    Each candidate row shows: $SYMBOL | $Xm mcap | score
    with an ➕ Add button (or ✓ if already in watchlist).
    """
    builder = InlineKeyboardBuilder()
    shown   = candidates[:limit]

    if not shown:
        builder.row(InlineKeyboardButton(
            text="🔄 NO CANDIDATES YET — CHECK BACK IN 60S", callback_data="cs:candidates"
        ))
    else:
        for c in shown:
            addr   = c.get("token_address", "")
            sym    = (c.get("token_symbol") or "???")[:7]
            score  = c.get("composite_score", 0)
            mcap   = c.get("market_cap", 0) or 0
            mcap_s = f"${mcap/1_000_000:.1f}M" if mcap >= 1_000_000 else f"${mcap/1000:.0f}k"
            label  = f"${sym}  {mcap_s}  score:{score:.0f}"

            if addr in watchlist_addrs:
                add_btn = InlineKeyboardButton(text="✓", callback_data="cs:candidates")
            else:
                add_btn = InlineKeyboardButton(
                    text="➕", callback_data=f"cs:add_token:{addr[:44]}"
                )
            builder.row(
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"cs:candidate_detail:{addr[:20]}",
                ),
                add_btn,
            )

    builder.row(
        InlineKeyboardButton(text="🔄 REFRESH",    callback_data="cs:candidates"),
        InlineKeyboardButton(text="⬅️ BACK",       callback_data="cs:main"),
    )
    return builder.as_markup()


# ── Positions List ────────────────────────────────────────────────────────────

def build_cs_positions(positions: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if not positions:
        builder.row(InlineKeyboardButton(
            text="📭 NO OPEN CS POSITIONS", callback_data="cs:main"
        ))
    else:
        for pos in positions:
            addr   = pos.get("token_address", "")[:8]
            pnl    = _pnl_str(pos)
            pos_id = pos.get("id", 0)
            builder.row(
                InlineKeyboardButton(
                    text=f"…{addr} {pnl}",
                    callback_data=f"cs:pos_detail:{pos_id}"
                ),
                InlineKeyboardButton(
                    text="✖ CLOSE",
                    callback_data=f"cs:pos_close:{pos_id}"
                ),
            )

    builder.row(InlineKeyboardButton(text="📣 SHARE POSITIONS", callback_data="cs:share_positions"))
    builder.row(
        InlineKeyboardButton(text="🔄 REFRESH", callback_data="cs:positions"),
        InlineKeyboardButton(text="⬅️ BACK",    callback_data="cs:main"),
    )
    return builder.as_markup()


def build_cs_pos_detail(pos_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✖ FORCE CLOSE", callback_data=f"cs:pos_close:{pos_id}"),
        InlineKeyboardButton(text="⬅️ BACK",        callback_data="cs:positions"),
    )
    return builder.as_markup()


# ── Token action (candidate detail) ──────────────────────────────────────────

def build_cs_candidate_action(token_address: str, in_watchlist: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    short   = token_address[:20]
    full    = token_address[:44]
    if in_watchlist:
        builder.row(
            InlineKeyboardButton(text="💰 BUY NOW",   callback_data=f"cs:buy:{short}"),
            InlineKeyboardButton(text="❌ REMOVE",    callback_data=f"cs:rm_token:{full}"),
        )
    else:
        builder.row(
            InlineKeyboardButton(text="➕ ADD TO LIST", callback_data=f"cs:add_token:{full}"),
            InlineKeyboardButton(text="💰 BUY NOW",     callback_data=f"cs:buy:{short}"),
        )
    builder.row(
        InlineKeyboardButton(text="⬅️ BACK", callback_data="cs:candidates"),
    )
    return builder.as_markup()


# ── Confirm Buy ───────────────────────────────────────────────────────────────

def build_cs_confirm_buy(token_address: str, trade_size: float) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    short   = token_address[:20]
    builder.row(
        InlineKeyboardButton(
            text=f"✅ CONFIRM BUY  ({trade_size:.4f} SOL)",
            callback_data=f"cs:confirm_buy:{short}",
        ),
        InlineKeyboardButton(text="❌ CANCEL", callback_data="cs:main"),
    )
    return builder.as_markup()


# ── Misc ──────────────────────────────────────────────────────────────────────

def build_cs_cancel() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ CANCEL", callback_data="cs:main"))
    return builder.as_markup()


def build_cs_back_to_main() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ BACK TO CANDLE SNIPER", callback_data="cs:main"))
    return builder.as_markup()


def _pnl_str(pos: dict) -> str:
    entry   = float(pos.get("entry_price_sol") or 0)
    current = float(pos.get("current_price_sol") or 0)
    if entry <= 0 or current <= 0:
        return ""
    pnl  = ((current - entry) / entry) * 100
    icon = "🟢" if pnl >= 0 else "🔴"
    return f"{icon}{pnl:+.1f}%"
