"""
bot/handlers/wallet_scout.py
=============================
Wallet intelligence tools powered by gmgn.ai (Dragon mechanics).

Features:
  ws:score       — Score any wallet (win rate, PnL, tags, hold time)
  ws:toptraders  — Top traders on a specific token
  ws:earlybuyers — First wallets to buy a token
  ws:bundle      — Detect coordinated dev bundles at launch
  ws:repeated    — Cross-token repeated winners (SUPREME+)
  ws:feed        — GMGN token discovery feed

All ws:* callbacks are handled here. Router is registered before callbacks.router.
"""

import asyncio
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.keyboards.wallet_scout_menu import (
    build_wallet_scout_main,
    build_back_to_scout,
    build_cancel_scout,
    build_wallet_score_actions,
    build_top_traders_actions,
    build_feed_category,
    build_repeated_winners_actions,
    build_presets_main,
    build_preset_detail,
)
from utils.wallet_scout_states import WalletScoutStates

logger = logging.getLogger(__name__)
router = Router()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _short(addr: str) -> str:
    return addr[:6] + "..." + addr[-4:] if len(addr) > 12 else addr


async def _get_ents(user_id: int):
    from services.brainrot_token_gate import get_entitlements
    return await get_entitlements(user_id)


async def _render_main(user_id: int):
    ents     = await _get_ents(user_id)
    is_sup   = ents.has_supreme_access
    is_black = ents.has_supreme_black
    tier     = ents.tier

    if tier == "supreme_black":
        tier_label = "🔱 SUPREME BLACK"
        tier_bar   = "▓▓▓▓▓▓▓▓▓▓ CLEARANCE: MAX"
        tools_line = "All 6 intel tools unlocked."
    elif tier == "supreme":
        tier_label = "👑 SUPREME"
        tier_bar   = "▓▓▓▓▓▓▓░░░ CLEARANCE: HIGH"
        tools_line = "5 of 6 intel tools unlocked."
    else:
        tier_label = "🆓 FREE"
        tier_bar   = "▓░░░░░░░░░ CLEARANCE: BASIC"
        tools_line = "4 of 6 intel tools available."

    cross_icon = "✅" if (is_sup or is_black) else "🔒"
    text = (
        f"🔭 <b>WALLET SCOUT</b>\n"
        f"<code>{tier_bar}  {tier_label}</code>\n\n"
        f"<code>🔍 Score  🏆 Top Traders  ⏱ Early Buyers</code>\n"
        f"<code>💣 Bundle  🔁 Cross-Token {cross_icon}  🌊 GMGN Feed</code>\n\n"
        f"<i>Powered by gmgn.ai smart-money data.</i>"
    )

    kb = build_wallet_scout_main(is_sup, is_black)
    return text, kb


# ── Commands ──────────────────────────────────────────────────────────────────

@router.message(Command("walletscout"))
async def cmd_wallet_scout(message: Message, state: FSMContext):
    await state.clear()
    text, kb = await _render_main(message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.message(Command("scorewallet"))
async def cmd_score_wallet(message: Message, state: FSMContext):
    await state.set_state(WalletScoutStates.waiting_for_wallet)
    await state.update_data(mode="score")
    await message.answer(
        "🔍 <b>Score a Wallet</b>\n\nSend a Solana wallet address to analyse:",
        reply_markup=build_cancel_scout(),
    )


# ── Main Panel ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "ws:main")
async def cb_ws_main(call: CallbackQuery, state: FSMContext):
    from aiogram.exceptions import TelegramBadRequest as _TBR
    await state.clear()
    try:
        boot = await call.message.edit_text(
            "<code>█░░░░░░░░░ WALLET SCOUT BOOTING...</code>", parse_mode="HTML"
        )
        await asyncio.sleep(0.38)
        await boot.edit_text(
            "<code>████░░░░░░ CONNECTING GMGN...</code>", parse_mode="HTML"
        )
        await asyncio.sleep(0.38)
        await boot.edit_text(
            "<code>██████████ INTEL ONLINE ⚡</code>", parse_mode="HTML"
        )
        await asyncio.sleep(0.28)
    except _TBR:
        pass
    text, kb = await _render_main(call.from_user.id)
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "ws:cancel_fsm")
async def cb_ws_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    text, kb = await _render_main(call.from_user.id)
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer("Cancelled")


# ── Score a Wallet ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "ws:score")
async def cb_ws_score(call: CallbackQuery, state: FSMContext):
    await state.set_state(WalletScoutStates.waiting_for_wallet)
    await state.update_data(mode="score")
    await call.message.edit_text(
        "🔍 <b>Score a Wallet</b>\n\n"
        "Send the Solana wallet address to analyse:\n"
        "<i>Example: 9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin</i>",
        reply_markup=build_cancel_scout(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("ws:score_addr:"))
async def cb_ws_score_addr(call: CallbackQuery):
    """Score a specific wallet address passed inline (from top traders list)."""
    wallet = call.data.split(":", 2)[2]
    await call.answer("Fetching wallet data…")
    await _do_score_wallet(call.message, wallet, edit=False)


@router.message(WalletScoutStates.waiting_for_wallet)
async def fsm_wallet_input(message: Message, state: FSMContext):
    wallet = (message.text or "").strip()
    data   = await state.get_data()
    mode   = data.get("mode", "score")
    await state.clear()

    import re
    if not re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$', wallet):
        await message.answer(
            "❌ Invalid Solana address. Please try again.",
            reply_markup=build_back_to_scout(),
        )
        return

    if mode == "score":
        await _do_score_wallet(message, wallet)


async def _do_score_wallet(target, wallet_address: str, edit: bool = False):
    """Fetch and display wallet stats. target is Message or Message (from callback)."""
    from services.gmgn_service import get_wallet_stats, format_wallet_stats

    loading = f"🔍 Fetching stats for <code>{_short(wallet_address)}</code>…"
    if edit:
        msg = await target.edit_text(loading)
    else:
        msg = await target.answer(loading)

    stats = await get_wallet_stats(wallet_address)

    if not stats:
        await msg.edit_text(
            f"❌ <b>No data found</b> for <code>{wallet_address}</code>\n\n"
            f"This wallet may be new, inactive, or not indexed by gmgn.",
            reply_markup=build_back_to_scout(),
        )
        return

    text = format_wallet_stats(stats, wallet_address)
    kb   = build_wallet_score_actions(wallet_address)
    await msg.edit_text(text, reply_markup=kb)


# ── Top Traders ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "ws:toptraders")
async def cb_ws_toptraders(call: CallbackQuery, state: FSMContext):
    await state.set_state(WalletScoutStates.waiting_for_token)
    await state.update_data(mode="toptraders")
    await call.message.edit_text(
        "🏆 <b>Top Traders per Token</b>\n\n"
        "Send the token contract address to find the most profitable wallets on it:",
        reply_markup=build_cancel_scout(),
    )
    await call.answer()


@router.callback_query(F.data == "ws:earlybuyers")
async def cb_ws_earlybuyers(call: CallbackQuery, state: FSMContext):
    await state.set_state(WalletScoutStates.waiting_for_token)
    await state.update_data(mode="earlybuyers")
    await call.message.edit_text(
        "⏱ <b>Early Buyers</b>\n\n"
        "Send the token contract address to find the first buyers (dev wallets excluded):",
        reply_markup=build_cancel_scout(),
    )
    await call.answer()


@router.callback_query(F.data == "ws:bundle")
async def cb_ws_bundle(call: CallbackQuery, state: FSMContext):
    await state.set_state(WalletScoutStates.waiting_for_token)
    await state.update_data(mode="bundle")
    await call.message.edit_text(
        "💣 <b>Bundle Detector</b>\n\n"
        "Send the token contract address to check for coordinated dev buys at launch:",
        reply_markup=build_cancel_scout(),
    )
    await call.answer()


@router.message(WalletScoutStates.waiting_for_token)
async def fsm_token_input(message: Message, state: FSMContext):
    contract = (message.text or "").strip()
    data     = await state.get_data()
    mode     = data.get("mode", "toptraders")
    await state.clear()

    import re
    if not re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$', contract):
        await message.answer(
            "❌ Invalid contract address.",
            reply_markup=build_back_to_scout(),
        )
        return

    if mode == "toptraders":
        await _do_top_traders(message, contract)
    elif mode == "earlybuyers":
        await _do_early_buyers(message, contract)
    elif mode == "bundle":
        await _do_bundle(message, contract)


async def _do_top_traders(message: Message, contract: str):
    from services.gmgn_service import get_top_traders

    msg = await message.answer(
        f"🏆 Fetching top traders for <code>{_short(contract)}</code>…"
    )
    traders = await get_top_traders(contract, limit=15)

    if not traders:
        await msg.edit_text(
            "❌ No top trader data found. Token may be too new or not indexed.",
            reply_markup=build_back_to_scout(),
        )
        return

    text = (
        f"🏆 <b>Top Traders</b>\n"
        f"Token: <code>{contract}</code>\n"
        f"{'━' * 30}\n\n"
    )
    wallets = []
    for i, t in enumerate(traders[:10], 1):
        wallet = t.get("wallet") or ""
        if not wallet:
            continue
        wallets.append(wallet)
        profit  = t.get("realized_profit") or 0
        mult    = t.get("profit_change")    or 0
        cost    = t.get("total_cost")       or 0
        buys    = t.get("buy_count")        or 0
        sells   = t.get("sell_count")       or 0
        icon    = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        p_icon  = "📈" if profit >= 0 else "📉"
        text += (
            f"{icon} <code>{_short(wallet)}</code>\n"
            f"   {p_icon} ${profit:,.0f}  ×{mult:.1f}  cost ${cost:,.0f}\n"
            f"   🟢{buys} buys  🔴{sells} sells\n"
        )

    kb = build_top_traders_actions(wallets)
    await msg.edit_text(text, reply_markup=kb)


async def _do_early_buyers(message: Message, contract: str):
    from services.gmgn_service import get_early_buyers

    msg = await message.answer(
        f"⏱ Fetching early buyers for <code>{_short(contract)}</code>…"
    )
    buyers = await get_early_buyers(contract, limit=20)

    if not buyers:
        await msg.edit_text(
            "❌ No early buyer data found.",
            reply_markup=build_back_to_scout(),
        )
        return

    text = (
        f"⏱ <b>Early Buyers</b>  <i>(devs excluded)</i>\n"
        f"Token: <code>{contract}</code>\n"
        f"{'━' * 30}\n\n"
    )
    wallets = []
    for i, b in enumerate(buyers[:12], 1):
        wallet = b.get("wallet") or ""
        if not wallet:
            continue
        wallets.append(wallet)
        spent   = b.get("amount_usd")        or 0
        profit  = b.get("realized_profit")   or 0
        trades  = b.get("total_trade")       or 0
        p_icon  = "📈" if profit >= 0 else "📉"
        text += (
            f"{i}. <code>{_short(wallet)}</code>\n"
            f"   💰 ${spent:,.0f} in  {p_icon} ${profit:,.0f} PnL  🔁{trades} trades\n"
        )

    kb = build_top_traders_actions(wallets)
    await msg.edit_text(text, reply_markup=kb)


async def _do_bundle(message: Message, contract: str):
    from services.gmgn_service import detect_bundle

    msg = await message.answer(
        f"💣 Scanning for bundles in <code>{_short(contract)}</code>…\n"
        f"<i>(Decoding dev transactions — may take a moment)</i>"
    )
    result = await detect_bundle(contract)

    detected = result.get("bundle_detected")
    txns     = result.get("transactions",  0)
    total    = result.get("total_amount",  0.0)
    pct      = result.get("pct_of_supply", 0.0)
    breakdown = result.get("tx_breakdown") or []

    if txns == 0:
        verdict_text = (
            "⚠️ <b>No dev transactions found</b>\n"
            "Either no bundle data or token not indexed yet."
        )
        verdict_icon = "⚠️"
    elif detected:
        verdict_icon = "🚨"
        verdict_text = (
            f"🚨 <b>BUNDLE DETECTED</b>\n\n"
            f"The dev team executed <b>{txns} coordinated buys</b> at launch.\n"
            f"Total grabbed: <b>{total/1_000_000:.2f}M tokens</b> "
            f"(<b>{pct:.1f}% of supply</b>)\n\n"
            f"<b>Risk:</b> High — dev holds large supply and may dump."
        )
    else:
        verdict_icon = "✅"
        verdict_text = (
            f"✅ <b>No bundle detected</b>\n\n"
            f"Only {txns} dev transaction found at launch — no coordinated buying pattern.\n"
            f"This is a cleaner launch signal."
        )

    text = (
        f"💣 <b>Bundle Analysis</b>\n"
        f"Token: <code>{contract}</code>\n"
        f"{'━' * 30}\n\n"
        f"{verdict_text}\n"
    )

    if breakdown and detected:
        text += "\n<b>Transaction breakdown:</b>\n"
        for i, tx in enumerate(breakdown[:5], 1):
            amt = tx.get("amount") or 0
            p   = tx.get("pct")   or 0
            text += f"  {i}. {amt/1_000_000:.2f}M tokens ({p:.2f}%)\n"

    await msg.edit_text(text, reply_markup=build_back_to_scout())


# ── Cross-Token Repeated Winners ───────────────────────────────────────────────

@router.callback_query(F.data == "ws:repeated")
async def cb_ws_repeated(call: CallbackQuery, state: FSMContext):
    ents = await _get_ents(call.from_user.id)
    if not ents.has_supreme_access:
        await call.answer(
            "🔒 Cross-token winner analysis requires SUPREME or higher.",
            show_alert=True,
        )
        return

    await state.set_state(WalletScoutStates.waiting_for_token_list)
    await call.message.edit_text(
        "🔁 <b>Cross-Token Repeated Winners</b>\n\n"
        "Dragon's signature mechanic: wallets appearing as top traders on "
        "<b>multiple different tokens</b> simultaneously.\n\n"
        "Send up to <b>10 token contract addresses</b>, one per line:\n\n"
        "<i>Example:\n"
        "So11111111111111111111111111111111111111112\n"
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v\n"
        "...</i>",
        reply_markup=build_cancel_scout(),
    )
    await call.answer()


@router.message(WalletScoutStates.waiting_for_token_list)
async def fsm_token_list(message: Message, state: FSMContext):
    await state.clear()
    raw      = (message.text or "").strip()
    lines    = [l.strip() for l in raw.splitlines() if l.strip()]
    import re
    contracts = [l for l in lines if re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$', l)][:10]

    if len(contracts) < 2:
        await message.answer(
            "❌ Need at least 2 valid contract addresses (one per line).",
            reply_markup=build_back_to_scout(),
        )
        return

    msg = await message.answer(
        f"🔁 Scanning <b>{len(contracts)} tokens</b> for repeated winners…\n"
        f"<i>Fetching top traders per token simultaneously…</i>"
    )

    from services.gmgn_service import find_repeated_winners
    ents = await _get_ents(message.from_user.id)
    top_n = 30 if ents.has_supreme_black else 20

    winners = await find_repeated_winners(contracts, min_appearances=2, top_n_per_token=top_n)

    if not winners:
        await msg.edit_text(
            "😐 <b>No repeated winners found</b> across these tokens.\n\n"
            "Try with more tokens, or tokens in the same niche/timeframe.",
            reply_markup=build_back_to_scout(),
        )
        return

    text = (
        f"🔁 <b>Cross-Token Repeated Winners</b>\n"
        f"Scanned {len(contracts)} tokens — found <b>{len(winners)} repeated wallets</b>\n"
        f"{'━' * 30}\n\n"
    )
    top_wallets = []
    for i, w in enumerate(winners[:10], 1):
        wallet   = w["wallet"]
        appears  = w["appearances"]
        top_wallets.append(wallet)
        icon = "🔥" if appears >= 4 else "⭐" if appears >= 3 else "📌"
        text += (
            f"{icon} <code>{_short(wallet)}</code>\n"
            f"   Appears on <b>{appears}/{len(contracts)}</b> tokens\n"
        )

    text += (
        f"\n<i>Wallets appearing on more tokens are higher-conviction "
        f"smart money signals.</i>"
    )

    kb = build_repeated_winners_actions(top_wallets)
    await msg.edit_text(text, reply_markup=kb)


# ── GMGN Token Feed ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "ws:feed")
async def cb_ws_feed_menu(call: CallbackQuery):
    await call.message.edit_text(
        "🌊 <b>GMGN Token Feed</b>\n\n"
        "Live pump.fun token discovery — same data Dragon uses.\n"
        "Choose a category:",
        reply_markup=build_feed_category(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("ws:feed:"))
async def cb_ws_feed_category(call: CallbackQuery):
    category = call.data.split(":")[2]
    await call.answer("Loading feed…")

    loading_msg = await call.message.edit_text(
        f"🌊 Fetching <b>{category}</b> tokens from GMGN…"
    )

    from services.gmgn_service import get_new_pump_tokens
    tokens = await get_new_pump_tokens(category=category, limit=15)

    cat_names = {
        "new":        "🆕 New Launches",
        "completing": "📈 Completing Curve",
        "soaring":    "🚀 Soaring",
        "bonded":     "🎓 Bonded (DEX)",
    }
    cat_label = cat_names.get(category, category)

    if not tokens:
        await loading_msg.edit_text(
            f"❌ No {cat_label} tokens found right now. Try again in a moment.",
            reply_markup=build_feed_category(),
        )
        return

    text = f"🌊 <b>{cat_label}</b>\n{'━' * 30}\n\n"
    for i, t in enumerate(tokens[:10], 1):
        # Fields vary slightly by category — handle both pairs and rank responses
        name    = t.get("name")   or t.get("symbol") or "Unknown"
        symbol  = t.get("symbol") or ""
        addr    = t.get("address") or t.get("base_address") or t.get("mint") or ""
        mcap    = t.get("market_cap") or t.get("usd_market_cap") or 0
        vol1h   = t.get("volume") or t.get("volume_1h") or 0
        prog    = t.get("progress") or 0

        short_addr = _short(addr) if addr else "—"
        mcap_str   = f"${mcap/1000:.1f}k" if mcap >= 1000 else f"${mcap:.0f}"
        vol_str    = f"${vol1h/1000:.1f}k" if vol1h >= 1000 else f"${vol1h:.0f}"
        prog_str   = f"  📊{prog:.0f}%" if prog else ""

        text += (
            f"{i}. <b>{name}</b> ${symbol}\n"
            f"   <code>{short_addr}</code>\n"
            f"   Mcap: {mcap_str}  Vol: {vol_str}{prog_str}\n"
        )

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔄 Refresh", callback_data=f"ws:feed:{category}"))
    builder.row(InlineKeyboardButton(text="⬅️  Categories", callback_data="ws:feed"))
    await loading_msg.edit_text(text, reply_markup=builder.as_markup())


# ── Dragon Presets ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "ws:presets")
async def cb_ws_presets(call: CallbackQuery):
    from services.wallet_discovery_worker import (
        get_all_presets_summary, get_user_subscriptions, get_last_run_info,
        PRESET_LABELS,
    )
    summaries  = await get_all_presets_summary()
    user_subs  = await get_user_subscriptions(call.from_user.id)
    last_run   = await get_last_run_info()

    run_str = "Never"
    if last_run and last_run.get("finished_at"):
        run_str = last_run["finished_at"][:16].replace("T", " ") + " UTC"
    elif last_run and last_run.get("started_at"):
        run_str = "Running now…"

    total_wallets = sum((summaries.get(k) or {}).get("count", 0) for k in PRESET_LABELS)

    text = (
        f"🧠 <b>Dragon Intel Presets</b>\n"
        f"{'━' * 30}\n\n"
        f"Automatically discovered daily by running the full Dragon pipeline:\n"
        f"trending tokens → top traders → cross-token scoring → ranked presets\n\n"
        f"<b>Last refresh:</b> {run_str}\n"
        f"<b>Total wallets:</b> {total_wallets}\n\n"
        f"<b>Subscribe</b> to a preset → wallets auto-added to your Copy Trading.\n"
        f"Refreshed every 24h with fresh GMGN intel.\n\n"
        f"✅ = you are subscribed"
    )

    kb = build_presets_main(summaries, user_subs)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("ws:preset_view:"))
async def cb_ws_preset_view(call: CallbackQuery):
    from services.wallet_discovery_worker import (
        get_preset_wallets, get_user_subscriptions, PRESET_LABELS,
    )
    import json as _json

    preset_key = call.data.split(":", 2)[2]
    wallets    = await get_preset_wallets(preset_key)
    user_subs  = await get_user_subscriptions(call.from_user.id)
    is_subbed  = preset_key in user_subs
    label      = PRESET_LABELS.get(preset_key, preset_key)

    if not wallets:
        await call.answer(
            "No wallets in this preset yet — run a discovery first.",
            show_alert=True,
        )
        return

    text = (
        f"{label}\n"
        f"{'━' * 30}\n\n"
    )
    for i, w in enumerate(wallets[:10], 1):
        addr  = w["wallet_address"]
        wr    = (w.get("win_rate") or 0) * 100
        pnl   = w.get("pnl_7d") or 0
        apps  = w.get("appearances") or 1
        hold  = w.get("avg_hold_secs") or 0
        score = w.get("intel_score") or 0
        tags  = []
        try:
            tags = _json.loads(w.get("tags") or "[]")
        except Exception:
            pass

        hold_str = (
            f"{hold/60:.0f}m" if hold < 3600
            else f"{hold/3600:.1f}h"
        )
        tag_str = f"  [{', '.join(tags[:2])}]" if tags else ""
        icon = "🔥" if score >= 70 else "⭐" if score >= 50 else "📌"

        text += (
            f"{icon} {i}. <code>{_short(addr)}</code>\n"
            f"   {wr:.0f}% WR  ${pnl:,.0f} 7d  ×{apps} tokens  ⏱{hold_str}"
            f"  score:{score:.0f}{tag_str}\n"
        )

    sub_status = "✅ Subscribed" if is_subbed else "⬜ Not subscribed"
    text += f"\n<b>Status:</b> {sub_status}"

    kb = build_preset_detail(preset_key, wallets, is_subbed)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("ws:preset_sub:"))
async def cb_ws_preset_sub(call: CallbackQuery):
    from services.wallet_discovery_worker import subscribe_to_preset, PRESET_LABELS
    preset_key = call.data.split(":", 2)[2]
    ok, err    = await subscribe_to_preset(call.from_user.id, preset_key)
    label      = PRESET_LABELS.get(preset_key, preset_key)
    if ok:
        await call.answer(
            f"✅ Subscribed to {label}! Wallets added to Copy Trading.",
            show_alert=True,
        )
        # Refresh the view
        fake = type("obj", (object,), {"data": f"ws:preset_view:{preset_key}"})()
        fake.from_user = call.from_user
        fake.message   = call.message
        fake.answer    = call.answer
        await cb_ws_preset_view(fake)
    else:
        await call.answer(f"❌ {err}", show_alert=True)


@router.callback_query(F.data.startswith("ws:preset_unsub:"))
async def cb_ws_preset_unsub(call: CallbackQuery):
    from services.wallet_discovery_worker import unsubscribe_from_preset, PRESET_LABELS
    preset_key = call.data.split(":", 2)[2]
    await unsubscribe_from_preset(call.from_user.id, preset_key)
    label = PRESET_LABELS.get(preset_key, preset_key)
    await call.answer(f"❌ Unsubscribed from {label}", show_alert=True)
    # Refresh view
    fake = type("obj", (object,), {"data": f"ws:preset_view:{preset_key}"})()
    fake.from_user = call.from_user
    fake.message   = call.message
    fake.answer    = call.answer
    await cb_ws_preset_view(fake)


@router.callback_query(F.data == "ws:preset_run")
async def cb_ws_preset_run(call: CallbackQuery):
    """Manually trigger a discovery run (admin + anyone — rate-limited by the worker)."""
    from services.wallet_discovery_worker import get_worker_status
    status = get_worker_status()
    if status["status"] == "running":
        await call.answer("Discovery is already running — check back in a few minutes.", show_alert=True)
        return

    await call.answer("🧠 Discovery pipeline starting… you'll be notified when done.")
    await call.message.edit_text(
        "🧠 <b>Dragon Intel Discovery Running</b>\n\n"
        "Fetching trending tokens → finding top traders → scoring wallets…\n\n"
        "<i>This takes 1–3 minutes. You'll receive a notification when complete.</i>",
        reply_markup=build_back_to_scout(),
    )

    # Run in background so the handler returns immediately
    import asyncio
    from services.wallet_discovery_worker import run_discovery

    async def _run_and_notify():
        try:
            result = await run_discovery()
            wallets_found = result.get("wallets_scored", 0)
            tokens_scanned = result.get("tokens_scanned", 0)
            try:
                await call.message.answer(
                    f"✅ <b>Dragon Intel Refresh Complete!</b>\n\n"
                    f"Scanned <b>{tokens_scanned}</b> tokens, "
                    f"scored <b>{wallets_found}</b> smart-money wallets.\n\n"
                    f"Open <b>Dragon Presets</b> to see updated lists."
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Manual discovery run failed: {e}")

    asyncio.create_task(_run_and_notify())


# ── Quick-add to Copy Trade ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ws:add_to_ct:"))
async def cb_ws_add_to_ct(call: CallbackQuery):
    """Add a discovered wallet directly to copy trading from the scout panel."""
    wallet = call.data.split(":", 2)[2]
    from services.copy_trade_service import add_tracked_wallet, get_copy_trade_entitlements
    ents = await get_copy_trade_entitlements(call.from_user.id)

    ok, err = await add_tracked_wallet(call.from_user.id, wallet, label="Scout find")
    if ok:
        await call.answer(
            f"✅ Added to Copy Trade! ({ents.tier.replace('_',' ').title()} tier)",
            show_alert=True,
        )
    else:
        await call.answer(f"❌ {err}", show_alert=True)


