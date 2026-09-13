"""
bot/keyboards/sniper_menu.py
=============================
All inline keyboards for the Sniper Tool module.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.keyboards.share_templates import (
    SNIPER_SHARE_URL,
    SHARE_TWITTER_URL,
    SHARE_TELEGRAM_URL,
    SHARE_REDDIT_URL,
    SHARE_HASHTAG_URL,
)


def build_share_menu() -> InlineKeyboardMarkup:
    """Universal community share menu accessible from Presets."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🐦 POST ON X",           url=SHARE_TWITTER_URL),
        InlineKeyboardButton(text="✈️ SHARE TO TELEGRAM",   url=SHARE_TELEGRAM_URL),
    )
    builder.row(
        InlineKeyboardButton(text="🟠 POST TO REDDIT",      url=SHARE_REDDIT_URL),
        InlineKeyboardButton(text="# COMMUNITY HASHTAG",    url=SHARE_HASHTAG_URL),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️  BACK TO PRESETS",    callback_data="sniper:presets"),
    )
    return builder.as_markup()


def build_sniper_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    # ── Row 1: Wallet (full width, top) ───────────────────────────────────────
    builder.row(
        InlineKeyboardButton(text="💳  WALLET",                 callback_data="sniper:wallet"),
    )
    # ── Row 2: Analyze + Settings ──────────────────────────────────────────────
    builder.row(
        InlineKeyboardButton(text="🔍  ANALYZE TOKEN",          callback_data="sniper:analyze"),
        InlineKeyboardButton(text="⚙️  SETTINGS",               callback_data="sniper:settings"),
    )
    # ── Row 3: Auto-Buy (full width) ───────────────────────────────────────────
    builder.row(
        InlineKeyboardButton(text="🤖  AUTO-BUY",               callback_data="sniper:autobuy"),
    )
    # ── Row 3: Positions (full width) ─────────────────────────────────────────
    builder.row(
        InlineKeyboardButton(text="📊  POSITIONS  📊",          callback_data="sniper:positions"),
    )
    # ── Row 4: Presets + Trade Preview ────────────────────────────────────────
    builder.row(
        InlineKeyboardButton(text="📂  PRESETS",                callback_data="sniper:presets"),
        InlineKeyboardButton(text="📋  TRADE PREVIEW",          callback_data="sniper:preview"),
    )
    # ── Row 5: Auto-Exit Manager (full width) ──────────────────────────────────
    builder.row(
        InlineKeyboardButton(text="⬛  AUTO-EXIT MANAGER  ⬛",  callback_data="ae:main"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️  BACK",                   callback_data="menu:back"),
    )
    return builder.as_markup()


def build_back_to_sniper() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️  BACK TO SNIPER", callback_data="sniper:main"))
    return builder.as_markup()


def build_token_actions(token_address: str, cache_key: str) -> InlineKeyboardMarkup:
    """Buttons shown after token analysis."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👁  WATCH",            callback_data=f"sniper:watch_add:{cache_key}"),
        InlineKeyboardButton(text="🚫  BLACKLIST",        callback_data=f"sniper:bl_add:{cache_key}"),
    )
    builder.row(
        InlineKeyboardButton(text="📋  TRADE PREVIEW",    callback_data=f"sniper:preview_token:{cache_key}"),
    )
    builder.row(InlineKeyboardButton(text="⬅️  BACK", callback_data="sniper:main"))
    return builder.as_markup()


def build_settings_menu(s: dict) -> InlineKeyboardMarkup:
    """Settings page with edit buttons for each key field."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📊 MIN LIQUIDITY",     callback_data="sniper:set:min_liquidity"),
        InlineKeyboardButton(text="📉 MIN VOLUME",        callback_data="sniper:set:min_volume"),
    )
    builder.row(
        InlineKeyboardButton(text="🛒 MIN BUYS",          callback_data="sniper:set:min_buys"),
        InlineKeyboardButton(text="⏱ MAX AGE (MIN)",      callback_data="sniper:set:max_token_age_minutes"),
    )
    builder.row(
        InlineKeyboardButton(text="💰 DEFAULT BUY SOL",   callback_data="sniper:set:default_buy_size"),
        InlineKeyboardButton(text="📐 SLIPPAGE %",        callback_data="sniper:set:default_slippage"),
    )
    # Platform selector
    plat = s.get("preferred_platform", "auto")
    builder.row(
        InlineKeyboardButton(text=f"{'✅' if plat=='auto' else '⬜'} AUTO",    callback_data="sniper:platform:auto"),
        InlineKeyboardButton(text=f"{'✅' if plat=='jupiter' else '⬜'} JUPITER", callback_data="sniper:platform:jupiter"),
        InlineKeyboardButton(text=f"{'✅' if plat=='pumpfun' else '⬜'} PUMPFUN", callback_data="sniper:platform:pumpfun"),
    )
    # Toggle buttons
    sm_icon = "✅" if s.get("strict_mode") else "⬜"
    builder.row(
        InlineKeyboardButton(text=f"{sm_icon} STRICT MODE", callback_data="sniper:toggle:strict_mode"),
    )
    af_icon  = "✅" if s.get("auto_filter_enabled") else "⬜"
    fl_icon  = "✅" if s.get("prioritize_fresh_launches") else "⬜"
    ls_icon  = "✅" if s.get("prioritize_liquidity_strength") else "⬜"
    ia_icon  = "✅" if s.get("instant_alert_on_match") else "⬜"
    builder.row(
        InlineKeyboardButton(text=f"{af_icon} AUTO FILTER",     callback_data="sniper:toggle:auto_filter_enabled"),
        InlineKeyboardButton(text=f"{fl_icon} FRESH PRIORITY",  callback_data="sniper:toggle:prioritize_fresh_launches"),
    )
    builder.row(
        InlineKeyboardButton(text=f"{ls_icon} LIQ PRIORITY",    callback_data="sniper:toggle:prioritize_liquidity_strength"),
        InlineKeyboardButton(text=f"{ia_icon} INSTANT ALERT",   callback_data="sniper:toggle:instant_alert_on_match"),
    )
    builder.row(InlineKeyboardButton(text="⬅️  BACK", callback_data="sniper:main"))
    return builder.as_markup()


_TWITTER_HASHTAG_URL = "https://x.com/hashtag/BRAINROTALPHABOTPRESET"

def build_presets_list(presets: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in presets:
        name  = p['name'].upper()[:18]
        pnl   = p.get("total_pnl")
        if pnl is None:
            label = f"⭐ {name}"
        else:
            sign  = "+" if pnl >= 0 else ""
            label = f"▸ {name}  {sign}{pnl:.4f} SOL"
        builder.row(
            InlineKeyboardButton(
                text=label,
                callback_data=f"sniper:preset_view:{p['id']}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="[ + SAVE CURRENT SETTINGS ]", callback_data="sniper:preset_create"),
    )
    builder.row(
        InlineKeyboardButton(text="🚫  BLACKLIST",               callback_data="sniper:blacklist"),
        InlineKeyboardButton(text="🌐  SHARE",                   callback_data="sniper:share_menu"),
    )
    builder.row(InlineKeyboardButton(text="⬅️  BACK", callback_data="sniper:main"))
    return builder.as_markup()


def build_preset_actions(preset_id, is_template: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="▶  LOAD PRESET",    callback_data=f"sniper:preset_apply:{preset_id}"),
        InlineKeyboardButton(text="✕  DELETE",         callback_data=f"sniper:preset_del:{preset_id}"),
    )
    if not is_template:
        builder.row(
            InlineKeyboardButton(
                text="🌐  SHARE THIS PRESET  //  COMMUNITY",
                callback_data=f"sniper:preset_share:{preset_id}",
            )
        )
    builder.row(InlineKeyboardButton(text="⬅️  BACK TO PRESETS", callback_data="sniper:presets"))
    return builder.as_markup()


def build_watch_list(targets: list[dict]) -> InlineKeyboardMarkup:
    """Legacy fallback — kept for compatibility with feed/analysis shortcuts."""
    builder = InlineKeyboardBuilder()
    for t in targets[:20]:
        addr = t["token_address"]
        short = addr[:6] + "..." + addr[-4:]
        builder.row(
            InlineKeyboardButton(
                text=f"❌ {short}",
                callback_data=f"sniper:watch_rm:{t['id']}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="➕ ADD TOKEN", callback_data="sniper:watch_add_manual"),
    )
    builder.row(InlineKeyboardButton(text="⬅️  BACK", callback_data="sniper:main"))
    return builder.as_markup()


def build_watch_targets_main(targets: list[dict]) -> InlineKeyboardMarkup:
    """Remastered Watch Targets hub — terminal aesthetic with per-token detail rows."""
    builder = InlineKeyboardBuilder()
    for t in targets[:20]:
        addr  = t["token_address"]
        short = addr[:6] + "..." + addr[-4:]
        drop  = t.get("alert_drop_pct") or 0
        sym   = t.get("token_symbol") or short
        alert_icon = "🔔" if t.get("alert_enabled", 1) else "🔕"
        builder.row(
            InlineKeyboardButton(
                text=f"{alert_icon} {sym[:14]}  ↓{drop:.0f}%",
                callback_data=f"sniper:wt_detail:{t['id']}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="➕ ADD TOKEN CA", callback_data="sniper:watch_add_manual"),
    )
    builder.row(InlineKeyboardButton(text="⬅️  BACK", callback_data="sniper:main"))
    return builder.as_markup()


def build_watch_target_detail(t: dict) -> InlineKeyboardMarkup:
    """Per-token watch target settings page keyboard."""
    builder = InlineKeyboardBuilder()
    row_id     = t["id"]
    alert_icon = "✅ ALERTS ON" if t.get("alert_enabled", 1) else "⬜ ALERTS OFF"
    builder.row(
        InlineKeyboardButton(text=alert_icon,                callback_data=f"sniper:wt_toggle:{row_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="📉 SET DROP ALERT %", callback_data=f"sniper:wt_set_drop:{row_id}"),
        InlineKeyboardButton(text="📈 SET PUMP ALERT %", callback_data=f"sniper:wt_set_pump:{row_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="💰 QUICK BUY SOL",    callback_data=f"sniper:wt_set_buy:{row_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="🗑 REMOVE",           callback_data=f"sniper:watch_rm:{row_id}"),
        InlineKeyboardButton(text="⬅️  BACK",            callback_data="sniper:watch"),
    )
    return builder.as_markup()


def build_blacklist_menu(entries: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for e in entries[:20]:
        addr  = e["token_address"]
        label = (e.get("label") or "").strip()
        short = label if label else addr[:6] + "..." + addr[-4:]
        builder.row(
            InlineKeyboardButton(
                text=f"🗑 {short}",
                callback_data=f"sniper:bl_rm:{e['id']}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="➕ ADD TOKEN", callback_data="sniper:bl_add_manual"),
    )
    builder.row(
        InlineKeyboardButton(text="🔍 DUPLICATE CREATORS", callback_data="sniper:dup_creators"),
    )
    builder.row(InlineKeyboardButton(text="⬅️  BACK", callback_data="sniper:main"))
    return builder.as_markup()


def build_feed_card_actions(cache_key: str) -> InlineKeyboardMarkup:
    """Inline actions under each feed result card."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔍 ANALYZE",  callback_data=f"sniper:fa:{cache_key}"),
        InlineKeyboardButton(text="📋 PREVIEW",  callback_data=f"sniper:fp:{cache_key}"),
    )
    builder.row(
        InlineKeyboardButton(text="👁 WATCH",    callback_data=f"sniper:fw:{cache_key}"),
        InlineKeyboardButton(text="🚫 BLACKLIST",callback_data=f"sniper:fb:{cache_key}"),
    )
    return builder.as_markup()


def build_feed_nav(has_results: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 REFRESH FEED", callback_data="sniper:feed"),
    )
    builder.row(InlineKeyboardButton(text="⬅️  BACK", callback_data="sniper:main"))
    return builder.as_markup()


def build_autobuy_menu(s: dict) -> InlineKeyboardMarkup:
    from utils.trade_presets import TRADE_PRESETS
    builder = InlineKeyboardBuilder()
    enabled_icon = "🟢 ON" if s.get("enabled") else "🔴 OFF"
    ks_icon      = "🔴 ACTIVE" if s.get("kill_switch") else "⬜ OFF"
    builder.row(
        InlineKeyboardButton(text=f"POWER: {enabled_icon}", callback_data="sniper:ab_toggle"),
        InlineKeyboardButton(text=f"KILL SWITCH: {ks_icon}", callback_data="sniper:ab_kill"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 LIVE SCAN STATUS", callback_data="sniper:ab_status"),
    )
    builder.row(
        InlineKeyboardButton(text="💰 MAX BUY SIZE",     callback_data="sniper:abset:max_buy_size_sol"),
        InlineKeyboardButton(text="⏱ MAX/HOUR",          callback_data="sniper:abset:max_buys_per_hour"),
    )
    builder.row(
        InlineKeyboardButton(text="🎯 SCORE THRESHOLD",  callback_data="sniper:abset:score_threshold"),
        InlineKeyboardButton(text="📐 SLIPPAGE",         callback_data="sniper:abset:slippage"),
    )
    builder.row(
        InlineKeyboardButton(text="⚡ PRIORITY FEE",     callback_data="sniper:abset:priority_fee"),
        InlineKeyboardButton(text="⏳ COOLDOWN (SEC)",   callback_data="sniper:abset:cooldown_seconds"),
    )
    builder.row(
        InlineKeyboardButton(text="🛑 Wallet Floor (SOL)", callback_data="sniper:abset:min_wallet_balance_sol"),
        InlineKeyboardButton(text="🔒 Daily Spend Limit",  callback_data="sniper:abset:daily_spend_limit_sol"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 MIN MCAP ($)",       callback_data="sniper:abset:min_market_cap_usd"),
        InlineKeyboardButton(text="📊 MAX MCAP ($)",       callback_data="sniper:abset:max_market_cap_usd"),
    )
    # Save / Load custom preset from this page
    builder.row(
        InlineKeyboardButton(text="💾 SAVE CURRENT SETTINGS", callback_data="sniper:ab_save_preset"),
        InlineKeyboardButton(text="📂 MY SAVED PRESETS",      callback_data="sniper:ab_load_presets"),
    )
    # Quick preset buttons (2 per row)
    builder.row(InlineKeyboardButton(text="━━━  QUICK PRESETS  ━━━", callback_data="sniper:noop"))
    preset_btns = [
        InlineKeyboardButton(text=preset["label"], callback_data=f"sniper:ab_preset:{key}")
        for key, preset in TRADE_PRESETS.items()
        if key != "liquidity_sniper"
    ]
    for i in range(0, len(preset_btns), 2):
        builder.row(*preset_btns[i:i+2])
    builder.row(InlineKeyboardButton(text="⬅️  BACK", callback_data="sniper:main"))
    return builder.as_markup()


def build_cancel_sniper() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ CANCEL", callback_data="sniper:cancel_fsm"))
    return builder.as_markup()


def build_liq_sniper_menu(ab_s: dict, exit_preset_name: str = "None") -> InlineKeyboardMarkup:
    """Liquidity Sniper control panel."""
    builder = InlineKeyboardBuilder()
    enabled_icon = "🟢 ON" if ab_s.get("enabled") and float(ab_s.get("min_initial_buy_sol") or 0) > 0 else "🔴 OFF"
    ks_icon      = "🔴 ACTIVE" if ab_s.get("kill_switch") else "⬜ OFF"
    builder.row(
        InlineKeyboardButton(text=f"POWER: {enabled_icon}", callback_data="sniper:liq_power"),
        InlineKeyboardButton(text=f"KILL: {ks_icon}",       callback_data="sniper:ab_kill"),
    )
    builder.row(
        InlineKeyboardButton(text="🎯 MIN INITIAL BUY (SOL)", callback_data="sniper:abset:min_initial_buy_sol"),
        InlineKeyboardButton(text="💰 BUY SIZE (SOL)",        callback_data="sniper:abset:max_buy_size_sol"),
    )
    builder.row(
        InlineKeyboardButton(text="⚡ PRIORITY FEE",          callback_data="sniper:abset:priority_fee"),
        InlineKeyboardButton(text="📐 SLIPPAGE %",            callback_data="sniper:abset:slippage"),
    )
    builder.row(
        InlineKeyboardButton(
            text=f"🚪 EXIT PRESET: {exit_preset_name.upper()}",
            callback_data="sniper:liq_exit_preset",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="📊 HOLDINGS",              callback_data="sniper:liq_holdings"),
        InlineKeyboardButton(text="⬛️ APPLY OPTIMAL",         callback_data="sniper:liq_activate"),
    )
    builder.row(InlineKeyboardButton(text="⬅️  BACK", callback_data="sniper:main"))
    return builder.as_markup()
