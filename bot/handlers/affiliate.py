"""
bot/handlers/affiliate.py
==========================
Alpha Network — Affiliate & Referral System handlers.

Callbacks handled (af:*):
  af:main              — Alpha Network hub
  af:profile           — My affiliate profile (earnings, tier)
  af:earnings          — Earnings breakdown
  af:tier              — Tier progress
  af:signup:start      — Initiate $100 Supreme signup (step 1)
  af:signup:skip_wallet — Skip affiliate wallet entry
  af:signup:check      — Check if payment landed
  af:signup:mock_confirm — Mock payment confirmation (local testing only)
  af:admin:menu        — Admin hub (is_admin only)
  af:admin:list        — Admin: list all affiliates
  af:admin:unpaid      — Admin: unpaid commissions
  af:admin:paid:<id>   — Admin: mark commission ID as paid (requires FSM for tx hash)

FSM states: AffiliateWalletState (from utils.states)

IMPORTANT: This handler does NOT touch or modify the burn access system.
Burn access (burn_activations, holder_access via 'burn') remains fully intact.
"""

import asyncio
import logging
import re
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.affiliate_menu import (
    build_affiliate_hub,
    build_share_menu,
    build_affiliate_signup_wallet_prompt,
    build_affiliate_payment_waiting,
    build_affiliate_payment_waiting_mock,
    build_affiliate_back,
    build_affiliate_activated,
    build_affiliate_profile_menu,
    build_admin_affiliate_menu,
    build_admin_back,
)
from services.affiliate_service import (
    TIER_STRUCTURE,
    COMMISSION_PCT,
    get_affiliate_tier,
    get_affiliate_profile_by_user_id,
    get_affiliate_profile,
    get_or_create_affiliate_profile,
    record_referral,
    get_user_referral,
    initiate_affiliate_signup,
    get_pending_affiliate_signup,
    confirm_qualifying_payment,
    get_unpaid_commissions,
    mark_commission_paid,
    get_all_affiliate_profiles,
    get_affiliate_commissions,
)
from services.wallet_service import get_wallet
from services.brainrot_token_gate import get_active_tier
from utils.config import settings, get_rpc_url
from utils.states import AffiliateWalletState, AffiliateSubmitTxState, AffiliateMarkPaidState

logger = logging.getLogger(__name__)
router = Router()

# Receiving wallet for paid features — set PAYMENT_WALLET in .env.
# Blank means payments are not configured; flows below bail out early.
PAYMENT_WALLET = settings.PAYMENT_WALLET


def _is_admin(user_id: int) -> bool:
    return user_id in (settings.ADMIN_IDS or [])


def _shorten(addr: str) -> str:
    if not addr or len(addr) < 10:
        return addr or "—"
    return addr[:6] + "..." + addr[-4:]


def _is_valid_solana_address(address: str) -> bool:
    return bool(re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$', address))


# ── Alpha Network Hub ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "af:main")
async def cb_af_main(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user_id  = callback.from_user.id
    username = callback.from_user.username or ""
    tier     = await get_active_tier(user_id)

    tier_label = {
        "supreme_black": "⬛ SUPREME BLACK",
        "supreme":       "🔱 SUPREME",
    }.get(tier, "🆓 FREE")

    admin_line = "\n<i>⚙️ Admin tools available below.</i>" if _is_admin(user_id) else ""

    text = (
        "🧠 <b>ALPHA NETWORK</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Your status:</b> {tier_label}\n\n"
        "Bring someone in, save them money, and get paid for it.\n\n"
        "<b>Here's how it works:</b>\n\n"
        "👥 <b>Refer a friend</b>\n"
        "Share your Solana wallet address with them.\n"
        "When they sign up through you, you automatically\n"
        "receive <b>21% of their payment in SOL</b> — straight to your wallet.\n\n"
        "💰 <b>Their deal</b>\n"
        "They pay <b>$100</b> for permanent Supreme Black access\n"
        "instead of burning millions of tokens.\n"
        "They save money, you earn — everyone wins.\n\n"
        "📈 <b>The more you refer, the higher your tier</b>\n"
        "From Entry all the way to Sovereign — commissions compound."
        f"{admin_line}"
    )

    kb = build_affiliate_hub()
    if _is_admin(user_id):
        from aiogram.types import InlineKeyboardButton
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        b = InlineKeyboardBuilder()
        for row in kb.inline_keyboard:
            b.row(*row)
        b.row(InlineKeyboardButton(text="⚙️ Admin Tools", callback_data="af:admin:menu"))
        kb = b.as_markup()

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# ── Share ─────────────────────────────────────────────────────────────────────
# One handler — builds URL buttons that open Twitter/Telegram directly.
# The post text is pre-filled in the URL so users just tap Publish.

@router.callback_query(F.data == "af:share")
async def cb_af_share(callback: CallbackQuery) -> None:
    user_id    = callback.from_user.id
    wallet_rec = await get_wallet(user_id)
    wallet     = wallet_rec["wallet_address"] if wallet_rec else None

    if wallet:
        wallet_line = (
            f"\n<b>Your affiliate wallet</b> (tap to copy):\n"
            f"<code>{wallet}</code>\n\n"
            f"Tap a button below — your post opens <b>ready to publish.</b>"
        )
    else:
        wallet_line = "\n⚠️ <b>No wallet linked.</b> Go to SUPREME ACCESS → Link Wallet first."

    text = (
        "📣 <b>Share the Alpha Network</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        f"{wallet_line}\n\n"
        "<i>Every signup through your wallet = 21% SOL commission, auto-paid.</i>"
    )
    await callback.message.edit_text(text, reply_markup=build_share_menu(wallet), parse_mode="HTML")
    await callback.answer()


# ── My Affiliate Profile ──────────────────────────────────────────────────────

@router.callback_query(F.data == "af:profile")
async def cb_af_profile(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id

    # Look up via user's linked wallet
    wallet_rec = await get_wallet(user_id)
    if not wallet_rec:
        await callback.message.edit_text(
            "╔══════════════════════════════╗\n"
            "║   🧠 <b>AFFILIATE PROFILE</b>      ║\n"
            "╚══════════════════════════════╝\n\n"
            "⚠️ <b>No wallet linked</b>\n\n"
            "Link a Solana wallet first via the SUPREME page,\n"
            "then your affiliate profile will be available here.\n\n"
            "<i>Your wallet address is your affiliate ID —\n"
            "share it with others to start earning.</i>",
            reply_markup=build_affiliate_back(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    wallet = wallet_rec["wallet_address"]
    profile = await get_affiliate_profile(wallet)

    if not profile:
        # Show "no activity yet" view with wallet address to share
        await callback.message.edit_text(
            "╔══════════════════════════════╗\n"
            "║   🧠 <b>AFFILIATE PROFILE</b>      ║\n"
            "╚══════════════════════════════╝\n\n"
            f"<b>Your Referral Wallet:</b>\n<pre>{wallet}</pre>\n\n"
            "<code>┌─ NO ACTIVITY YET ────────────────┐\n"
            "│  Share your wallet address above  │\n"
            "│  When someone enters it on signup  │\n"
            "│  and pays $100 SOL, you earn $21   │\n"
            "└──────────────────────────────────┘</code>\n\n"
            "<i>Tip: Send this wallet to anyone you want to refer.</i>",
            reply_markup=build_affiliate_back(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    referrals    = profile["total_referrals"]
    earned       = profile["total_commission_earned_usd"]
    unpaid       = profile["unpaid_commission_usd"]
    paid         = profile["total_commission_paid_usd"]
    current_tier = profile["current_tier"] or "None"
    _, next_t    = get_affiliate_tier(referrals)

    next_line = (
        f"Next Tier: {next_t[1]} at {next_t[0]} referrals"
        if next_t else "MAX TIER ACHIEVED 🏆"
    )
    progress_line = (
        f"Progress: {referrals}/{next_t[0]}"
        if next_t else f"Referrals: {referrals}"
    )

    text = (
        "╔══════════════════════════════╗\n"
        "║   🧠 <b>AFFILIATE PROFILE</b>      ║\n"
        "╚══════════════════════════════╝\n\n"
        f"<b>Wallet:</b> <code>{_shorten(wallet)}</code>\n"
        f"<b>Tier:</b> {current_tier}\n"
        f"<b>Referrals:</b> {referrals}\n\n"
        f"<code>┌─ EARNINGS ───────────────────────┐\n"
        f"│  Total Earned   ${earned:>8.2f}          │\n"
        f"│  Unpaid Balance ${unpaid:>8.2f}          │\n"
        f"│  Total Paid     ${paid:>8.2f}          │\n"
        f"└──────────────────────────────────┘</code>\n\n"
        f"<i>{next_line}</i>\n"
        f"<i>{progress_line}</i>"
    )

    await callback.message.edit_text(
        text, reply_markup=build_affiliate_profile_menu(), parse_mode="HTML"
    )
    await callback.answer()


# ── My Earnings ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "af:earnings")
async def cb_af_earnings(callback: CallbackQuery) -> None:
    user_id    = callback.from_user.id
    wallet_rec = await get_wallet(user_id)

    if not wallet_rec:
        await callback.answer("Link a wallet via SUPREME first.", show_alert=True)
        return

    wallet     = wallet_rec["wallet_address"]
    commissions = await get_affiliate_commissions(wallet, limit=10)

    if not commissions:
        await callback.message.edit_text(
            "╔══════════════════════════════╗\n"
            "║   💰 <b>MY EARNINGS</b>            ║\n"
            "╚══════════════════════════════╝\n\n"
            "No commissions yet.\n\n"
            f"<b>Your referral wallet:</b>\n<pre>{wallet}</pre>\n\n"
            "<i>When someone signs up using your wallet,\n"
            "your $21 commission will appear here.</i>",
            reply_markup=build_affiliate_back(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    lines = []
    for c in commissions:
        status_icon = "✅" if c["commission_status"] == "paid" else "⏳"
        date = c["created_at"][:10] if c.get("created_at") else "—"
        lines.append(
            f"  {status_icon} ${c['commission_amount_usd']:.2f} — {date} — {c['commission_status']}"
        )

    entries = "\n".join(lines)
    profile = await get_affiliate_profile(wallet)
    total_earned = profile["total_commission_earned_usd"] if profile else 0.0
    unpaid       = profile["unpaid_commission_usd"] if profile else 0.0

    text = (
        "╔══════════════════════════════╗\n"
        "║   💰 <b>MY EARNINGS</b>            ║\n"
        "╚══════════════════════════════╝\n\n"
        f"<b>Total Earned:</b> ${total_earned:.2f}\n"
        f"<b>Unpaid Balance:</b> ${unpaid:.2f}\n\n"
        f"<b>Recent Commissions:</b>\n<code>{entries}</code>\n\n"
        "<i>✅ = paid  ⏳ = pending payout</i>"
    )
    await callback.message.edit_text(
        text, reply_markup=build_affiliate_back(), parse_mode="HTML"
    )
    await callback.answer()


# ── My Tier ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "af:tier")
async def cb_af_tier(callback: CallbackQuery) -> None:
    user_id    = callback.from_user.id
    wallet_rec = await get_wallet(user_id)

    if not wallet_rec:
        await callback.answer("Link a wallet via SUPREME first.", show_alert=True)
        return

    wallet  = wallet_rec["wallet_address"]
    profile = await get_affiliate_profile(wallet)

    referrals    = profile["total_referrals"] if profile else 0
    current_tier, next_t = get_affiliate_tier(referrals)
    highest_tier = profile["highest_tier"] if profile else "None"

    tier_lines = []
    for threshold, name in TIER_STRUCTURE:
        marker = "✅" if referrals >= threshold else "○"
        tier_lines.append(f"  {marker} {name:<15} {threshold:>5} referrals")
    tier_table = "\n".join(tier_lines)

    if next_t:
        needed        = next_t[0] - referrals
        progress_line = f"<i>{needed} more referral(s) to reach {next_t[1]}.</i>"
    else:
        progress_line = "<i>MAX TIER ACHIEVED — SOVEREIGN 🏆</i>"

    text = (
        "╔══════════════════════════════╗\n"
        "║   📊 <b>MY TIER</b>                ║\n"
        "╚══════════════════════════════╝\n\n"
        f"<b>Current Tier:</b> {current_tier}\n"
        f"<b>Highest Tier:</b> {highest_tier}\n"
        f"<b>Total Referrals:</b> {referrals}\n\n"
        f"<code>{tier_table}</code>\n\n"
        f"{progress_line}"
    )
    await callback.message.edit_text(
        text, reply_markup=build_affiliate_back(), parse_mode="HTML"
    )
    await callback.answer()


# ── Supreme Signup — Step 1: Prompt for affiliate wallet ──────────────────────

@router.callback_query(F.data == "af:signup:start")
async def cb_af_signup_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user_id = callback.from_user.id

    # Must have a linked wallet to pay from
    wallet_rec = await get_wallet(user_id)
    if not wallet_rec:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🔱 Link Wallet → SUPREME", callback_data="supreme:main"))
        b.row(InlineKeyboardButton(text="⬅️ Back", callback_data="af:main"))
        await callback.message.edit_text(
            "⚠️ <b>No wallet linked</b>\n\n"
            "You need to link a Solana wallet before signing up for Supreme Black.\n\n"
            "Go to <b>SUPREME ACCESS</b> → <b>Link Wallet</b>, paste your wallet address,\n"
            "then come back here to complete your Supreme Black signup.",
            reply_markup=b.as_markup(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    # Check current tier
    tier = await get_active_tier(user_id)
    if tier == "supreme_black":
        await callback.answer("🔱 Supreme Black is already active!", show_alert=True)
        return

    # Check if already has a pending signup
    pending = await get_pending_affiliate_signup(user_id)
    has_pending = pending is not None

    await state.set_state(AffiliateWalletState.waiting_affiliate_wallet)
    await state.update_data(from_wallet=wallet_rec["wallet_address"])

    await callback.message.edit_text(
        "⬛ <b>Supreme Black — $100</b>\n\n"
        "Did someone refer you?\n\n"
        "Paste their Solana wallet address below and they'll automatically earn a commission when you pay — you save nothing either way, it just rewards whoever sent you here.\n\n"
        "No referral? Tap <b>Skip</b> and go straight to payment.",
        reply_markup=build_affiliate_signup_wallet_prompt(has_pending),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AffiliateWalletState.waiting_affiliate_wallet)
async def msg_affiliate_wallet(message: Message, state: FSMContext) -> None:
    address = (message.text or "").strip()

    if not _is_valid_solana_address(address):
        await message.answer(
            "⚠️ <b>Invalid wallet address</b>\n\n"
            "That doesn't look like a valid Solana wallet (32–44 base58 chars).\n\n"
            "Try again, or tap Skip below.",
            reply_markup=build_affiliate_signup_wallet_prompt(),
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    from_wallet = data.get("from_wallet", "")
    await state.clear()

    # Self-referral check
    if address.lower() == from_wallet.lower():
        await message.answer(
            "⚠️ <b>Self-referral not allowed</b>\n\n"
            "You cannot use your own wallet as an affiliate wallet.\n"
            "Please enter someone else's wallet, or skip.",
            reply_markup=build_affiliate_signup_wallet_prompt(),
            parse_mode="HTML",
        )
        return

    # Record referral (creates referral_event row)
    user_id = message.from_user.id
    result  = await record_referral(
        referred_user_id    = user_id,
        affiliate_wallet    = address,
        user_linked_wallet  = from_wallet,
        self_referral_allowed = False,
    )
    if not result["success"]:
        # Already referred — proceed to payment anyway
        logger.info(f"affiliate: record_referral skip for user {user_id}: {result['error']}")

    # Proceed to payment step
    await _show_payment_instructions(message, user_id, from_wallet, address)


@router.callback_query(F.data == "af:signup:skip_wallet")
async def cb_af_signup_skip(callback: CallbackQuery, state: FSMContext) -> None:
    data        = await state.get_data()
    from_wallet = data.get("from_wallet", "")
    await state.clear()

    if not from_wallet:
        wallet_rec = await get_wallet(callback.from_user.id)
        from_wallet = wallet_rec["wallet_address"] if wallet_rec else ""

    await _show_payment_instructions_cb(callback, callback.from_user.id, from_wallet, None)


async def _show_payment_instructions(
    message: Message,
    user_id: int,
    from_wallet: str,
    affiliate_wallet: str | None,
) -> None:
    """Record pending signup and show payment instructions (message version)."""
    if not PAYMENT_WALLET:
        await message.answer(
            "⚠️ Payments are not configured on this bot. "
            "The operator needs to set <code>PAYMENT_WALLET</code> in .env."
        )
        return
    sol_amount = settings.AFFILIATE_SIGNUP_SOL
    await initiate_affiliate_signup(user_id, from_wallet, sol_amount, affiliate_wallet)

    short_from = _shorten(from_wallet)
    short_pay  = _shorten(PAYMENT_WALLET)
    aff_line   = (
        f"\n<code>  Affiliate: {_shorten(affiliate_wallet)}</code>"
        if affiliate_wallet else "\n<code>  Affiliate: None (skipped)</code>"
    )

    kb = build_affiliate_payment_waiting_mock() if settings.MOCK_SUPREME_PAYMENT_CONFIRMATION else build_affiliate_payment_waiting()

    await message.answer(
        "⬛ <b>Supreme Black — Payment</b>\n\n"
        f"Send <b>$100 in SOL</b> to this address:\n"
        f"<pre>{PAYMENT_WALLET}</pre>\n\n"
        f"<b>Sending from:</b> <code>{short_from}</code>"
        f"{aff_line}\n\n"
        "⚠️ <b>Send once.</b> After you send, tap <b>📥 Submit TX Signature</b> and paste your transaction hash — this activates you instantly.\n\n"
        "<i>Don't send again if it's not confirming — just paste your TX hash instead.</i>",
        reply_markup=kb,
        parse_mode="HTML",
    )


async def _show_payment_instructions_cb(
    callback: CallbackQuery,
    user_id: int,
    from_wallet: str,
    affiliate_wallet: str | None,
) -> None:
    """Record pending signup and show payment instructions (callback version)."""
    sol_amount = settings.AFFILIATE_SIGNUP_SOL
    await initiate_affiliate_signup(user_id, from_wallet, sol_amount, affiliate_wallet)

    short_from = _shorten(from_wallet)
    aff_line   = (
        f"\n<code>  Affiliate: {_shorten(affiliate_wallet)}</code>"
        if affiliate_wallet else "\n<code>  Affiliate: None (skipped)</code>"
    )

    kb = build_affiliate_payment_waiting_mock() if settings.MOCK_SUPREME_PAYMENT_CONFIRMATION else build_affiliate_payment_waiting()

    await callback.message.edit_text(
        "⬛ <b>Supreme Black — Payment</b>\n\n"
        f"Send <b>$100 in SOL</b> to this address:\n"
        f"<pre>{PAYMENT_WALLET}</pre>\n\n"
        f"<b>Sending from:</b> <code>{short_from}</code>"
        f"{aff_line}\n\n"
        "⚠️ <b>Send once.</b> After you send, tap <b>📥 Submit TX Signature</b> and paste your transaction hash — this activates you instantly.\n\n"
        "<i>Don't send again if it's not confirming — just paste your TX hash instead.</i>",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


# ── Check payment ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "af:signup:check")
async def cb_af_signup_check(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id

    msg = await callback.message.edit_text(
        "<code>█░░░░░░░░░ SCANNING CHAIN...</code>", parse_mode="HTML"
    )
    await asyncio.sleep(0.7)
    await msg.edit_text(
        "<code>████░░░░░░ QUERYING WALLET...</code>", parse_mode="HTML"
    )
    await asyncio.sleep(0.6)
    await msg.edit_text(
        "<code>██████████ VERIFYING TX...</code>", parse_mode="HTML"
    )
    await asyncio.sleep(0.4)

    tier = await get_active_tier(user_id)

    if tier == "supreme_black":
        # Payment was already confirmed (worker beat us to it)
        await msg.edit_text(
            "╔══════════════════════════════╗\n"
            "║  ⚡ <b>SUPREME BLACK — ACTIVE!</b>  ║\n"
            "╚══════════════════════════════╝\n\n"
            "<code>┌─ ACCESS GRANTED ─────────────────┐\n"
            "│  TIER     Supreme Black           │\n"
            "│  ACCESS   Permanent ∞             │\n"
            "│  STATUS   ONLINE ✅               │\n"
            "└──────────────────────────────────┘</code>\n\n"
            "All Supreme Black features are live.\n"
            "<b>You're in the network. Let's go 🔱</b>",
            reply_markup=build_affiliate_activated(),
            parse_mode="HTML",
        )
    else:
        pending = await get_pending_affiliate_signup(user_id)
        if pending:
            sol    = float(pending["expected_sol"])
            exp_at = pending.get("expires_at", "")[:16]
            await msg.edit_text(
                "⏳ <b>Not confirmed yet</b>\n\n"
                "Already sent? Don't send again — tap <b>📥 Submit TX Signature</b> and paste your transaction hash for instant activation.\n\n"
                "If you haven't sent yet, send <b>$100 in SOL</b> to the address shown above, then submit your TX hash.\n\n"
                "<i>Auto-check is running every 5 seconds in the background.</i>",
                reply_markup=build_affiliate_payment_waiting(),
                parse_mode="HTML",
            )
        else:
            await msg.edit_text(
                "❌ <b>Payment Window Expired</b>\n\n"
                "Your 30-minute payment window has closed.\n"
                "Start a new signup below.",
                reply_markup=build_affiliate_back(),
                parse_mode="HTML",
            )

    await callback.answer()


# ── Manual TX submission ──────────────────────────────────────────────────────

@router.callback_query(F.data == "af:signup:submit_tx")
async def cb_af_submit_tx_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Ask the user to paste their Solana TX signature."""
    user_id = callback.from_user.id

    # If already activated (worker beat them to it), show success immediately
    tier = await get_active_tier(user_id)
    if tier == "supreme_black":
        await callback.message.edit_text(
            "╔══════════════════════════════╗\n"
            "║  ⚡ <b>SUPREME BLACK — ACTIVE!</b>  ║\n"
            "╚══════════════════════════════╝\n\n"
            "Your payment was already confirmed ✅\n"
            "Supreme Black is live on your account.",
            reply_markup=build_affiliate_activated(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    pending = await get_pending_affiliate_signup(user_id)
    if not pending:
        await callback.answer("No active signup. Start the flow again.", show_alert=True)
        return

    await state.set_state(AffiliateSubmitTxState.waiting_tx_signature)
    sol = float(pending["expected_sol"])

    await callback.message.edit_text(
        "📥 <b>Paste your transaction hash</b>\n\n"
        "Open your wallet app, find the transaction you just sent, and copy the transaction ID (also called the TX hash or signature).\n\n"
        "You can also find it on <b>solscan.io</b> if needed.\n\n"
        "Paste it below:",
        reply_markup=build_affiliate_back(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AffiliateSubmitTxState.waiting_tx_signature)
async def msg_af_submit_tx(message: Message, state: FSMContext) -> None:
    """Receive TX signature, verify on-chain, confirm payment + trigger commission."""
    from services.sol_payment_service import fetch_tx_details, mark_tx_processed
    from services.affiliate_payout_service import pay_commission

    sig     = (message.text or "").strip()
    user_id = message.from_user.id

    # Basic format check — Solana sigs are 87-88 base58 chars
    if not re.match(r'^[1-9A-HJ-NP-Za-km-z]{80,90}$', sig):
        await message.answer(
            "⚠️ <b>Invalid signature format</b>\n\n"
            "A Solana TX signature is ~88 characters.\n"
            "Copy it from your wallet or solscan.io and try again.",
            reply_markup=build_affiliate_back(),
            parse_mode="HTML",
        )
        return

    await state.clear()

    pending = await get_pending_affiliate_signup(user_id)
    if not pending:
        await message.answer(
            "❌ <b>No active signup found</b>\n\n"
            "Your 30-minute payment window may have expired.\n"
            "Go back to Alpha Network and start a new signup.",
            reply_markup=build_affiliate_back(),
            parse_mode="HTML",
        )
        return

    # Scanning animation
    scanning = await message.answer(
        "<code>█░░░░░░░░░ FETCHING TX...</code>",
        parse_mode="HTML",
    )
    await asyncio.sleep(0.6)
    await scanning.edit_text(
        "<code>████░░░░░░ VERIFYING ON-CHAIN...</code>",
        parse_mode="HTML",
    )

    # Fetch from RPC
    details = await fetch_tx_details(get_rpc_url(), sig)

    if not details:
        await scanning.edit_text(
            "❌ <b>Transaction Not Found</b>\n\n"
            "<code>┌─ POSSIBLE REASONS ───────────────┐\n"
            "│  • TX not yet confirmed (~30s)    │\n"
            "│  • Wrong signature pasted         │\n"
            "│  • TX failed on-chain             │\n"
            "└──────────────────────────────────┘</code>\n\n"
            "Wait 30 seconds and try again, or check solscan.io.",
            reply_markup=build_affiliate_payment_waiting(),
            parse_mode="HTML",
        )
        return

    await scanning.edit_text(
        "<code>████████░░ CHECKING AMOUNT...</code>",
        parse_mode="HTML",
    )

    amount_sol   = details["amount_sol"]
    expected_sol = float(pending["expected_sol"])
    tolerance    = 0.05

    if abs(amount_sol - expected_sol) > tolerance:
        await scanning.edit_text(
            f"❌ <b>Amount Mismatch</b>\n\n"
            f"<code>┌─ PAYMENT CHECK ──────────────────┐\n"
            f"│  Expected   {expected_sol:.4f} SOL             │\n"
            f"│  Received   {amount_sol:.4f} SOL             │\n"
            f"│  Tolerance  ±0.05 SOL              │\n"
            f"└──────────────────────────────────┘</code>\n\n"
            "The amount sent does not match. Contact support if you believe this is an error.",
            reply_markup=build_affiliate_payment_waiting(),
            parse_mode="HTML",
        )
        return

    await scanning.edit_text(
        "<code>██████████ CONFIRMING ACCESS...</code>",
        parse_mode="HTML",
    )

    # Replay protection
    if not await mark_tx_processed(sig, user_id):
        await scanning.edit_text(
            "⚠️ <b>Already Processed</b>\n\n"
            "This transaction has already been used to activate an account.",
            reply_markup=build_affiliate_back(),
            parse_mode="HTML",
        )
        return

    # Confirm payment, grant Supreme Black, create commission
    affiliate_wallet = pending.get("affiliate_wallet")
    result = await confirm_qualifying_payment(
        user_id    = user_id,
        tx_hash    = sig,
        amount_sol = amount_sol,
        amount_usd = 100.0,
    )

    if not result["success"]:
        await scanning.edit_text(
            f"❌ <b>Confirmation Failed</b>\n\n{result['error']}",
            reply_markup=build_affiliate_back(),
            parse_mode="HTML",
        )
        return

    # Fire commission payout immediately
    if result["commission_created"] and affiliate_wallet and result["commission_id"]:
        try:
            await pay_commission(
                affiliate_wallet    = affiliate_wallet,
                amount_sol_received = amount_sol,
                commission_id       = result["commission_id"],
            )
        except Exception as e:
            logger.error(f"affiliate: manual TX commission payout failed: {e}")

    # Build success message
    short_sig = sig[:16] + "..."
    aff_line  = ""
    if result["commission_created"] and affiliate_wallet:
        aff_line = (
            f"\n<code>┌─ REFERRAL ───────────────────────┐\n"
            f"│  Affiliate  {_shorten(affiliate_wallet):<22}│\n"
            f"│  Commission 21% SOL sent ✅       │\n"
            f"└──────────────────────────────────┘</code>"
        )

    await scanning.edit_text(
        "╔══════════════════════════════╗\n"
        "║  ⚡ <b>SUPREME BLACK — ACTIVATED</b> ║\n"
        "╚══════════════════════════════╝\n\n"
        "<code>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</code>\n"
        "Payment verified on-chain ✅\n"
        "Supreme Black access is now LIVE.\n"
        "<code>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</code>\n\n"
        f"<code>┌─ PAYMENT SUMMARY ────────────────┐\n"
        f"│  PAID     {amount_sol:.4f} SOL              │\n"
        f"│  TIER     Supreme Black           │\n"
        f"│  ACCESS   Permanent ∞             │\n"
        f"│  TX       {short_sig:<25}│\n"
        f"└──────────────────────────────────┘</code>"
        f"{aff_line}\n\n"
        "<b>Welcome to the network ⬛</b>",
        reply_markup=build_affiliate_activated(),
        parse_mode="HTML",
    )


# ── Mock confirmation (testing only) ─────────────────────────────────────────

@router.callback_query(F.data == "af:signup:mock_confirm")
async def cb_af_mock_confirm(callback: CallbackQuery) -> None:
    if not settings.MOCK_SUPREME_PAYMENT_CONFIRMATION:
        await callback.answer("Mock mode is disabled.", show_alert=True)
        return

    user_id = callback.from_user.id
    pending = await get_pending_affiliate_signup(user_id)
    if not pending:
        await callback.answer(
            "No pending signup found. Start the flow again.", show_alert=True
        )
        return

    mock_tx = f"MOCK_TX_{user_id}_{int(datetime.utcnow().timestamp())}"
    result  = await confirm_qualifying_payment(
        user_id    = user_id,
        tx_hash    = mock_tx,
        amount_sol = float(pending["expected_sol"]),
        amount_usd = 100.0,
    )

    if result["success"]:
        comm_line = (
            f"\n✅ Commission ${result['commission_usd']:.2f} created for "
            f"{_shorten(result['affiliate_wallet'])}"
            if result["commission_created"] else "\nℹ️ No affiliate wallet — no commission."
        )
        await callback.message.edit_text(
            "╔══════════════════════════════╗\n"
            "║  🧪 <b>MOCK CONFIRMATION OK</b>    ║\n"
            "╚══════════════════════════════╝\n\n"
            "✅ Supreme Black access granted.\n"
            f"<code>TX: {mock_tx[:30]}...</code>"
            f"{comm_line}",
            reply_markup=build_affiliate_activated(),
            parse_mode="HTML",
        )
    else:
        await callback.answer(f"Mock confirm failed: {result['error']}", show_alert=True)


# ── Admin: hub ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "af:admin:menu")
async def cb_af_admin_menu(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Admin only.", show_alert=True)
        return

    await callback.message.edit_text(
        "╔══════════════════════════════╗\n"
        "║   ⚙️ <b>AFFILIATE ADMIN</b>        ║\n"
        "╚══════════════════════════════╝\n\n"
        "Manage affiliate profiles, commissions,\n"
        "and qualifying payment records.",
        reply_markup=build_admin_affiliate_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Admin: list all affiliates ────────────────────────────────────────────────

@router.callback_query(F.data == "af:admin:list")
async def cb_af_admin_list(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Admin only.", show_alert=True)
        return

    profiles = await get_all_affiliate_profiles(limit=20)

    if not profiles:
        await callback.message.edit_text(
            "No affiliate profiles yet.",
            reply_markup=build_admin_back(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    lines = []
    for p in profiles:
        w      = _shorten(p["affiliate_wallet_address"])
        earned = p["total_commission_earned_usd"]
        refs   = p["total_referrals"]
        tier   = p["current_tier"] or "None"
        lines.append(f"  {w}  ${earned:.0f}  {refs}r  {tier}")

    text = (
        "╔══════════════════════════════╗\n"
        "║   📋 <b>ALL AFFILIATES</b>         ║\n"
        "╚══════════════════════════════╝\n\n"
        "<code>" + "\n".join(lines) + "</code>\n\n"
        f"<i>Showing top {len(profiles)} by earned.</i>"
    )
    await callback.message.edit_text(
        text, reply_markup=build_admin_back(), parse_mode="HTML"
    )
    await callback.answer()


# ── Admin: unpaid commissions ─────────────────────────────────────────────────

@router.callback_query(F.data == "af:admin:unpaid")
async def cb_af_admin_unpaid(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Admin only.", show_alert=True)
        return

    unpaid = await get_unpaid_commissions()

    if not unpaid:
        await callback.message.edit_text(
            "✅ No unpaid commissions.",
            reply_markup=build_admin_back(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    lines = []
    b = InlineKeyboardBuilder()
    for c in unpaid:
        w      = _shorten(c["affiliate_wallet_address"])
        date   = c["created_at"][:10]
        lines.append(f"  #{c['id']}  {w}  ${c['commission_amount_usd']:.2f}  {date}")
        b.row(InlineKeyboardButton(
            text=f"✅ Mark #{c['id']} Paid",
            callback_data=f"af:admin:markpaid:{c['id']}",
        ))
    b.row(InlineKeyboardButton(text="⬅️ Back", callback_data="af:admin:menu"))

    text = (
        "╔══════════════════════════════╗\n"
        "║   💸 <b>UNPAID COMMISSIONS</b>     ║\n"
        "╚══════════════════════════════╝\n\n"
        "<code>" + "\n".join(lines) + "</code>\n\n"
        "<i>Tap a button to mark as paid.\n"
        "You will be prompted for a TX hash.</i>"
    )
    await callback.message.edit_text(
        text, reply_markup=b.as_markup(), parse_mode="HTML"
    )
    await callback.answer()


# ── Admin: mark paid — step 1: capture commission ID, ask for TX hash ─────────

@router.callback_query(F.data.startswith("af:admin:markpaid:"))
async def cb_af_admin_markpaid(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Admin only.", show_alert=True)
        return

    commission_id = int(callback.data.split(":")[-1])
    await state.set_state(AffiliateMarkPaidState.waiting_tx_hash)
    await state.update_data(commission_id=commission_id)

    await callback.message.edit_text(
        f"📝 <b>Mark Commission #{commission_id} as Paid</b>\n\n"
        "Paste the Solana TX hash for the payout below.\n"
        "<i>Type 'skip' to mark paid without a TX hash.</i>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AffiliateMarkPaidState.waiting_tx_hash)
async def msg_mark_paid_tx(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return

    tx_input       = (message.text or "").strip()
    payout_tx_hash = "" if tx_input.lower() == "skip" else tx_input
    data           = await state.get_data()
    commission_id  = data.get("commission_id")
    await state.clear()

    success = await mark_commission_paid(commission_id, payout_tx_hash)

    if success:
        tx_disp = _shorten(payout_tx_hash) if payout_tx_hash else "none"
        await message.answer(
            f"✅ Commission #{commission_id} marked as paid.\n"
            f"TX: <code>{tx_disp}</code>",
            parse_mode="HTML",
        )
    else:
        await message.answer(f"❌ Commission #{commission_id} not found.")
