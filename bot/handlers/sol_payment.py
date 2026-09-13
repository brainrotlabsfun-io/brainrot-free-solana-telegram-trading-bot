"""
bot/handlers/sol_payment.py
============================
Handles the SOL-payment timed Supreme Black access flow.

Callbacks:
  sp:main       — tier selection page
  sp:buy:N      — payment instructions for tier N
  sp:check:N    — manually check if payment landed
"""

import asyncio
import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.sol_payment_service import (
    SOL_TIERS,
    PAYMENT_WALLET,
    PENDING_EXPIRY_MINUTES,
    initiate_payment,
    get_pending,
)
from services.wallet_service import get_wallet
from services.brainrot_token_gate import get_active_tier

logger = logging.getLogger(__name__)
router = Router()


# ── Keyboards ─────────────────────────────────────────────────────────────────

def _build_tier_select() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for i, t in enumerate(SOL_TIERS):
        b.row(InlineKeyboardButton(
            text=f"{'⚡' if i == 0 else '🔥' if i == 1 else '👑'} "
                 f"{t['label']}  —  {t['sol']} SOL ({t['approx_usd']})",
            callback_data=f"sp:buy:{i}",
        ))
    b.row(InlineKeyboardButton(text="⬅️ Back", callback_data="supreme:main"))
    return b.as_markup()


def _build_waiting_kb(tier_index: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="✅ I've Sent — Check Now",
        callback_data=f"sp:check:{tier_index}",
    ))
    b.row(InlineKeyboardButton(text="🔄 Change Tier",      callback_data="sp:main"))
    b.row(InlineKeyboardButton(text="⬅️ Back to SUPREME",  callback_data="supreme:main"))
    return b.as_markup()


def _build_back() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Back to SUPREME", callback_data="supreme:main"))
    return b.as_markup()


def _build_activated_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🎯 Open Sniper",       callback_data="sniper:main"),
        InlineKeyboardButton(text="⚫ My Status",          callback_data="supreme:main"),
    )
    return b.as_markup()


# ── Handlers ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "sp:main")
async def cb_sp_main(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    tier    = await get_active_tier(user_id)

    if tier == "supreme_black":
        await callback.answer("🔱 Supreme Black is already active!", show_alert=True)
        return

    await callback.message.edit_text(
        "╔══════════════════════════════╗\n"
        "║  🔱 <b>SUPREME BLACK — BUY ACCESS</b>  ║\n"
        "╚══════════════════════════════╝\n\n"
        "<code>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</code>\n"
        "Send SOL to the dev auto-trader wallet.\n"
        "Fuel the machine that runs this bot.\n"
        "Payment detected in ~15 seconds. Timer\n"
        "starts the moment your SOL lands.\n"
        "<code>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</code>\n\n"
        "<code>┌─ TIERS ──────────────────────────┐\n"
        "│  ⚡ 12 Hour Trial  0.05 SOL (~$5)  │\n"
        "│  🔥 3 Day Access   0.20 SOL (~$25) │\n"
        "│  👑 7 Day Access   0.30 SOL (~$40) │\n"
        "└──────────────────────────────────┘</code>\n\n"
        "Select your tier below ⬇️",
        reply_markup=_build_tier_select(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sp:buy:"))
async def cb_sp_buy(callback: CallbackQuery) -> None:
    user_id    = callback.from_user.id
    tier_index = int(callback.data.split(":")[-1])
    tier       = SOL_TIERS[tier_index]

    # Require linked bot wallet so we know who sent the payment
    wallet_rec  = await get_wallet(user_id)
    from_wallet = wallet_rec["wallet_address"] if wallet_rec else None

    if not from_wallet:
        await callback.answer(
            "⚠️ Link your Solana wallet first — SUPREME → Link Wallet.",
            show_alert=True,
        )
        return

    if not PAYMENT_WALLET:
        await callback.answer(
            "⚠️ Payments are not configured on this bot "
            "(the operator must set PAYMENT_WALLET).",
            show_alert=True,
        )
        return

    await initiate_payment(user_id, tier_index, from_wallet)

    short_pay  = PAYMENT_WALLET[:6] + "..." + PAYMENT_WALLET[-4:]
    short_from = from_wallet[:6]  + "..." + from_wallet[-4:]
    tier_icon  = ["⚡", "🔥", "👑"][tier_index]

    dur_str = (
        f"{tier['hours']}h"
        if tier["hours"] < 48
        else f"{tier['hours'] // 24} days"
    )

    await callback.message.edit_text(
        "╔══════════════════════════════╗\n"
        f"║  {tier_icon} <b>SUPREME BLACK — {tier['label'].upper()}</b>\n"
        "╚══════════════════════════════╝\n\n"
        f"<code>┌─ PAYMENT DETAILS ────────────────┐\n"
        f"│  SEND EXACTLY  {tier['sol']:.2f} SOL ({tier['approx_usd']})  │\n"
        f"│  DURATION      {dur_str:<22}│\n"
        f"│  FROM          {short_from:<22}│\n"
        f"│  WINDOW        {PENDING_EXPIRY_MINUTES} min to confirm     │\n"
        f"└──────────────────────────────────┘</code>\n\n"
        f"<b>Send {tier['sol']:.2f} SOL to the dev auto-trader wallet:</b>\n"
        f"<pre>{PAYMENT_WALLET}</pre>\n\n"
        f"<code>┌─ HOW IT WORKS ───────────────────┐\n"
        f"│  1. Copy the wallet address above  │\n"
        f"│  2. Send exactly {tier['sol']:.2f} SOL          │\n"
        f"│  3. Bot detects it on-chain ~15s   │\n"
        f"│  4. Supreme Black goes LIVE ⚡     │\n"
        f"│  5. You get a confirmation DM      │\n"
        f"└──────────────────────────────────┘</code>\n\n"
        f"⚠️ <b>Must send from your linked wallet:</b>\n"
        f"<code>{short_from}</code>\n\n"
        f"<i>Bot watches for payments from your linked wallet.\n"
        f"Payments from other addresses will not be credited.</i>\n\n"
        f"🔍 Watching... tap below once sent.",
        reply_markup=_build_waiting_kb(tier_index),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sp:check:"))
async def cb_sp_check(callback: CallbackQuery) -> None:
    user_id    = callback.from_user.id
    tier_index = int(callback.data.split(":")[-1])
    tier       = SOL_TIERS[tier_index]

    # Animated scan
    msg = await callback.message.edit_text(
        "<code>█░░░░░░░░░ SCANNING CHAIN...</code>",
        parse_mode="HTML",
    )
    await asyncio.sleep(0.7)
    await msg.edit_text(
        "<code>████░░░░░░ QUERYING WALLET...</code>",
        parse_mode="HTML",
    )
    await asyncio.sleep(0.7)
    await msg.edit_text(
        "<code>██████████ VERIFYING TX...</code>",
        parse_mode="HTML",
    )
    await asyncio.sleep(0.5)

    active_tier = await get_active_tier(user_id)

    if active_tier == "supreme_black":
        dur_str = (
            f"{tier['hours']}h"
            if tier["hours"] < 48
            else f"{tier['hours'] // 24} days"
        )
        await msg.edit_text(
            "╔══════════════════════════════╗\n"
            "║  ⚡ <b>SUPREME BLACK — ACTIVE!</b>   ║\n"
            "╚══════════════════════════════╝\n\n"
            f"<code>┌─ ACCESS GRANTED ─────────────────┐\n"
            f"│  TIER     {tier['label']:<25}│\n"
            f"│  DURATION {dur_str:<25}│\n"
            f"│  STATUS   ONLINE ✅               │\n"
            f"└──────────────────────────────────┘</code>\n\n"
            "All Supreme Black features are live.\n"
            "<b>Timer has started. Let's get it ⚫</b>",
            reply_markup=_build_activated_kb(),
            parse_mode="HTML",
        )
    else:
        pending = await get_pending(user_id)
        if pending:
            await msg.edit_text(
                "⏳ <b>Payment Not Detected Yet</b>\n\n"
                f"<code>┌─ STILL WATCHING ─────────────────┐\n"
                f"│  Expected   {float(pending['expected_sol']):.4f} SOL             │\n"
                f"│  Check rate Every 15 seconds       │\n"
                f"│  From       Your linked wallet     │\n"
                f"└──────────────────────────────────┘</code>\n\n"
                "Once your TX confirms on-chain, access fires automatically.\n"
                "You'll get a notification DM.\n\n"
                "<i>Make sure you sent the exact amount from your linked wallet.</i>",
                reply_markup=_build_waiting_kb(tier_index),
                parse_mode="HTML",
            )
        else:
            await msg.edit_text(
                "❌ <b>Payment Window Expired</b>\n\n"
                f"Your {PENDING_EXPIRY_MINUTES}-minute payment window has closed.\n"
                "Start a new payment below.",
                reply_markup=_build_back(),
                parse_mode="HTML",
            )

    await callback.answer()
