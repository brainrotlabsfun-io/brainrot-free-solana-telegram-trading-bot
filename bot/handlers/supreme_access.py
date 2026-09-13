"""
bot/handlers/supreme_access.py
================================
SUPREME Access page — burn-to-activate flow.

Callbacks handled (supreme:*):
  supreme:main              — show SUPREME access page
  supreme:link_wallet       — FSM: collect wallet address
  supreme:burn_instructions — show burn how-to guide
  supreme:submit_tx         — FSM: collect burn tx signature
  supreme:check             — re-check current activation status

FSM states used: LinkWalletState, SubmitBurnTxState (from utils.states)
"""

import asyncio
import logging
import re
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.supreme_menu import (
    build_supreme_access,
    build_supreme_black_info,
    build_submit_tx_cancel,
    build_back_to_supreme,
    build_activation_result,
)
from services.burn_activation_service import (
    get_activation_status,
    submit_burn_for_verification,
    get_burn_stats,
)
from services.burn_title_service import get_burn_title
from services.badge_service import get_user_badges
from services.wallet_service import set_wallet, get_wallet
from services.brainrot_token_gate import is_supreme_holder
from utils.config import settings
from utils.states import LinkWalletState, SubmitBurnTxState

logger = logging.getLogger(__name__)
router = Router()

BRAINROT_MINT    = settings.BRAINROT_MINT
INCINERATOR_ADDR = "1nc1nerator11111111111111111111111111111111"


# ── Supreme Black public info page ────────────────────────────────────────────

SUPREME_BLACK_INFO = (
    "⬛ <b>SUPREME BLACK</b>\n\n"

    "The top tier. Unlimited copy wallets, auto-sell, TP/SL, full Solana trading suite — no caps.\n\n"

    "<b>Tiers at a glance:</b>\n\n"

    "🆓 <b>FREE</b> — 3 copy wallets, 30 trades/hr, no auto-sell\n"
    "👑 <b>SUPREME</b> — 20 copy wallets, surge detector (burn 1M $BRAINROT)\n"
    "⬛ <b>SUPREME BLACK</b> — everything unlimited, auto-sell, TP/SL (burn 10M or pay $100)\n\n"

    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    "🔥 <b>PATH 1 — BURN $BRAINROT</b>\n\n"

    "Get $BRAINROT on pump.fun:\n"
    f"<pre>{BRAINROT_MINT}</pre>\n"

    "Send <b>10,000,000 $BRAINROT</b> to the burn address:\n"
    f"<pre>{INCINERATOR_ADDR}</pre>\n\n"

    "Then come back here → Submit TX → access is live.\n"
    "<i>Burns stack — you don't have to do it all at once.</i>\n\n"

    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    "⬛ <b>PATH 2 — PAY $100 (ALPHA NETWORK)</b>\n\n"

    "Skip the burn. Pay $100 in SOL, get permanent Supreme Black instantly.\n"
    "Plus you can refer others and earn 21% commission on every signup — straight to your wallet.\n\n"

    "Go to <b>Alpha Network → Supreme Black Signup</b> to pay."
)


@router.callback_query(F.data == "supreme:black_info")
async def cb_supreme_black_info(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        SUPREME_BLACK_INFO,
        reply_markup=build_supreme_black_info(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.message(Command("supremeblack"))
async def cmd_supreme_black(message: Message) -> None:
    await message.answer(
        SUPREME_BLACK_INFO,
        reply_markup=build_supreme_black_info(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


# ── Main SUPREME status page ──────────────────────────────────────────────────

@router.callback_query(F.data == "supreme:main")
@router.callback_query(F.data == "sniper:supreme")
async def cb_supreme_main(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()

    # Boot animation
    msg = await callback.message.edit_text(
        "<code>█░░░░░░░░░ CHECKING ACCESS...</code>",
        parse_mode="HTML",
    )
    await asyncio.sleep(0.5)
    await msg.edit_text(
        "<code>██████░░░░ LOADING PROFILE...</code>",
        parse_mode="HTML",
    )

    user_id  = callback.from_user.id
    status   = await get_activation_status(user_id)
    is_sup   = await is_supreme_holder(user_id)
    stats    = await get_burn_stats(user_id)
    badges   = await get_user_badges(user_id)
    top_badge = badges[0] if badges else None

    wallet   = status["wallet_address"] or ""
    short_w  = (wallet[:6] + "…" + wallet[-4:]) if wallet else "not linked"
    tier     = status.get("active_tier", "free")

    if tier == "supreme_black":
        if status.get("expires_at"):
            tier_display = "🔱 SUPREME BLACK — TIMED"
            tier_bar     = "▓▓▓▓▓▓▓▓▓▓ TIMED ACCESS"
        else:
            tier_display = "🔱 SUPREME BLACK"
            tier_bar     = "▓▓▓▓▓▓▓▓▓▓ MAX TIER"
    elif tier == "supreme":
        tier_display = "👑 SUPREME"
        tier_bar     = "▓▓▓▓▓▓░░░░ UPGRADED"
    else:
        tier_display = "🆓 FREE"
        tier_bar     = "▓░░░░░░░░░ BASIC"

    burn_needed  = max(0.0, settings.SUPREME_REQUIRED_BURN_AMOUNT - stats["total_burned"])
    badge_line   = (
        f"{top_badge['icon']} {top_badge['badge_name']}"
        if top_badge else "None yet"
    )
    title_data   = get_burn_title(stats["total_burned"])
    title_line   = f"{title_data['emoji']} {title_data['title']}"

    expires_line = ""
    if is_sup and status.get("expires_at"):
        try:
            exp_dt    = datetime.fromisoformat(str(status["expires_at"]).replace(" ", "T"))
            remaining = exp_dt - datetime.utcnow()
            total_sec = remaining.total_seconds()
            if total_sec > 0:
                hours = int(total_sec // 3600)
                mins  = int((total_sec % 3600) // 60)
                countdown = f"{hours}h {mins}m"
                expires_line = f"\n<code>  ⏱ SHUTS OFF IN  {countdown:<14}</code>"
            else:
                expires_line = f"\n<code>  ⏱ ACCESS EXPIRED                </code>"
        except (ValueError, AttributeError):
            pass

    text = (
        "👑 <b>SUPREME ACCESS</b>\n\n"
        f"<b>Status:</b> {tier_display}"
        f"{expires_line}\n"
        f"<b>Wallet:</b> <code>{short_w}</code>\n"
        f"<b>Burned:</b> {stats['total_burned']:,.0f} $BRAINROT\n"
        f"<b>Badge:</b> {badge_line}\n\n"
    )

    if not is_sup:
        text += (
            "Not activated yet. Pick your path:\n\n"
            f"🔥 <b>Burn tokens</b> — burn {burn_needed:,.0f} more $BRAINROT and submit the TX\n\n"
            "⬛ <b>Pay $100 in SOL</b> — instant Supreme Black, no burning needed, plus earn commissions when you refer others\n\n"
            "⚡ <b>Trial</b> — 12 hours of access for 0.05 SOL\n"
        )
    else:
        text += "<i>All features active. You're in ⚡</i>\n"

    await asyncio.sleep(0.3)
    await msg.edit_text(
        text,
        reply_markup=build_supreme_access(status["wallet_linked"], is_sup),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Link wallet ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "supreme:link_wallet")
async def cb_link_wallet_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(LinkWalletState.waiting_address)
    await callback.message.edit_text(
        "🔗 <b>Link your Solana wallet</b>\n\n"
        "Paste your wallet's public address below.\n\n"
        "<i>Use the same wallet you'll be burning from or paying from.</i>",
        reply_markup=build_submit_tx_cancel(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(LinkWalletState.waiting_address)
async def msg_link_wallet(message: Message, state: FSMContext) -> None:
    address = message.text.strip() if message.text else ""

    if not _is_valid_solana_address(address):
        await message.answer(
            "⚠️ <b>Invalid address</b>\n\n"
            "That doesn't look like a valid Solana public key.\n"
            "It should be 32–44 base58 characters.\n\n"
            "Try again:",
            reply_markup=build_submit_tx_cancel(),
            parse_mode="HTML",
        )
        return

    await set_wallet(message.from_user.id, address)
    await state.clear()

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🔥 Burn $BRAINROT",        callback_data="supreme:burn_instructions"),
        InlineKeyboardButton(text="⬛ Pay SOL (Alpha Network)", callback_data="af:signup:start"),
    )
    b.row(InlineKeyboardButton(text="👑 My Supreme Status",    callback_data="supreme:main"))
    await message.answer(
        "✅ <b>Wallet Linked</b>\n\n"
        f"<code>{address}</code>\n\n"
        "<b>Choose your path to Supreme access:</b>\n\n"
        "🔥 <b>Burn $BRAINROT</b> — burn tokens to activate SUPREME or SUPREME BLACK\n\n"
        "⬛ <b>Pay SOL via Alpha Network</b> — pay SOL for permanent Supreme Black + "
        "earn 21% commissions on every referral you bring in\n\n"
        "<i>Both paths coexist — you can burn AND be an affiliate at the same time.</i>",
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )


# ── Burn instructions ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "supreme:burn_instructions")
async def cb_burn_instructions(callback: CallbackQuery) -> None:
    # Animation
    msg = await callback.message.edit_text(
        "<code>█░░░░░░░░░ LOADING BURN GUIDE...</code>",
        parse_mode="HTML",
    )
    await asyncio.sleep(0.5)

    wallet   = await get_wallet(callback.from_user.id)
    w_addr   = wallet["wallet_address"] if wallet else None
    short_w  = (w_addr[:6] + "…" + w_addr[-4:]) if w_addr else "⚠️ NOT LINKED"
    needed   = settings.SUPREME_REQUIRED_BURN_AMOUNT

    text = (
        "🔥 <b>Burn to Activate</b>\n\n"
        f"<b>Wallet:</b> <code>{short_w}</code>\n"
        f"<b>Need:</b> {needed:,.0f} $BRAINROT total\n\n"
        "Send $BRAINROT from your linked wallet to this burn address:\n"
        f"<pre>{INCINERATOR_ADDR}</pre>\n"
        "You can also use <b>sol-incinerator.com</b> with the mint:\n"
        f"<pre>{BRAINROT_MINT}</pre>\n\n"
        "After burning, tap <b>Submit Burn TX</b> and paste your transaction ID — verification is instant.\n\n"
        "<i>Burns stack across multiple transactions — you don't have to do it all at once.</i>"
    )

    await asyncio.sleep(0.3)
    await msg.edit_text(
        text,
        reply_markup=build_back_to_supreme(),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Submit burn TX ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "supreme:submit_tx")
async def cb_submit_tx_start(callback: CallbackQuery, state: FSMContext) -> None:
    status = await get_activation_status(callback.from_user.id)
    if not status["wallet_linked"]:
        await callback.answer("⚠️ Link your wallet first before submitting a TX.", show_alert=True)
        return

    await state.set_state(SubmitBurnTxState.waiting_tx_signature)
    await callback.message.edit_text(
        "📥 <b>Submit your burn transaction</b>\n\n"
        "Open your wallet app or solscan.io, find the burn transaction, and copy the transaction ID.\n\n"
        "Paste it below:",
        reply_markup=build_submit_tx_cancel(),
        parse_mode="HTML",
    )
    await callback.answer()


class _SolanaTxFilter(BaseFilter):
    """Matches messages that look like Solana TX signatures (80-95 base58 chars)."""
    async def __call__(self, message: Message) -> bool:
        text = (message.text or "").strip()
        return bool(re.match(r'^[1-9A-HJ-NP-Za-km-z]{80,95}$', text))


async def _run_burn_verification(user_id: int, tx_sig: str, wait_msg: Message) -> None:
    """Shared animated verification flow used by both FSM and re-entry handlers."""
    await asyncio.sleep(0.6)
    await wait_msg.edit_text(
        "<code>████░░░░░░ QUERYING SOLANA...</code>",
        parse_mode="HTML",
    )

    result = await submit_burn_for_verification(user_id, tx_sig)

    await asyncio.sleep(0.4)
    await wait_msg.edit_text(
        "<code>██████████ VERIFYING BURN...</code>",
        parse_mode="HTML",
    )
    await asyncio.sleep(0.5)

    if result["success"]:
        activated  = result["supreme_activated"]
        burned     = result["burned_amount"]
        total      = result["total_burned"]
        new_badges = result.get("newly_awarded_badges", [])

        badge_block = ""
        if new_badges:
            badge_block = "\n\n🏅 <b>Badges Earned:</b>\n" + "\n".join(
                f"  {b['icon']} <b>{b['badge_name']}</b> — {b['description']}"
                for b in new_badges
            )

        header = (
            "╔══════════════════════════╗\n"
            "║  ⚡ <b>SUPREME ACTIVATED!</b>  ║\n"
            "╚══════════════════════════╝"
        ) if activated else (
            "╔══════════════════════════╗\n"
            "║   ✅ <b>BURN RECORDED</b>      ║\n"
            "╚══════════════════════════╝"
        )

        text = (
            f"{header}\n\n"
            f"<code>┌─ BURN SUMMARY ───────────┐\n"
            f"│  THIS TX  {burned:>14,.0f} BRAINROT │\n"
            f"│  TOTAL    {total:>14,.0f} BRAINROT │\n"
            f"└──────────────────────────┘</code>"
            f"{badge_block}\n\n"
            + ("<i>All SUPREME features are now unlocked ⚡</i>"
               if activated else
               f"<i>Keep burning — you need "
               f"{max(0, settings.SUPREME_REQUIRED_BURN_AMOUNT - total):,.0f} "
               f"more $BRAINROT to unlock.</i>")
        )
        await wait_msg.edit_text(
            text, reply_markup=build_activation_result(success=True), parse_mode="HTML"
        )
    else:
        err = result.get("error", "Unknown error.")
        await wait_msg.edit_text(
            "╔══════════════════════════╗\n"
            "║   ❌ <b>VERIFICATION FAILED</b> ║\n"
            "╚══════════════════════════╝\n\n"
            f"<b>Reason:</b> {err}\n\n"
            "<code>┌─ COMMON CAUSES ──────────┐\n"
            "│ • TX not from linked wallet│\n"
            "│ • TX not yet confirmed     │\n"
            "│ • Wrong token burned       │\n"
            "│ • TX already submitted     │\n"
            "└──────────────────────────┘</code>\n\n"
            "<i>Check your TX on Solscan and try again.</i>",
            reply_markup=build_activation_result(success=False),
            parse_mode="HTML",
        )


@router.message(SubmitBurnTxState.waiting_tx_signature)
async def msg_submit_tx(message: Message, state: FSMContext) -> None:
    tx_sig = message.text.strip() if message.text else ""

    if len(tx_sig) < 43 or len(tx_sig) > 90:
        await message.answer(
            "⚠️ <b>Invalid TX signature</b>\n\n"
            "Solana transaction signatures are 87–88 base58 characters.\n"
            "Make sure you copied the full hash from Solscan.\n\n"
            "Try again:",
            reply_markup=build_submit_tx_cancel(),
            parse_mode="HTML",
        )
        return

    await state.clear()
    wait_msg = await message.answer(
        "<code>█░░░░░░░░░ SUBMITTING TX...</code>", parse_mode="HTML"
    )
    await _run_burn_verification(message.from_user.id, tx_sig, wait_msg)


@router.message(StateFilter(None), _SolanaTxFilter())
async def supreme_tx_reentry(message: Message) -> None:
    """
    Re-entry handler for burn TX submissions after bot restart.
    MemoryStorage wipes FSM states on restart — without this, the sniper
    catch-all would intercept pasted TX hashes and show 'session expired'.
    Fires only for messages that look like Solana TX signatures (80-95 base58 chars).
    """
    tx_sig  = message.text.strip()
    user_id = message.from_user.id

    status = await get_activation_status(user_id)
    if not status["wallet_linked"]:
        await message.answer(
            "⚠️ <b>No wallet linked</b>\n\n"
            "This looks like a burn TX, but you haven't linked a wallet yet.\n"
            "Go to <b>👑 SUPREME ACCESS</b> → <b>Link Wallet</b> first.",
            reply_markup=build_back_to_supreme(),
            parse_mode="HTML",
        )
        return

    wait_msg = await message.answer(
        "<code>█░░░░░░░░░ SUBMITTING TX...</code>", parse_mode="HTML"
    )
    await _run_burn_verification(user_id, tx_sig, wait_msg)


# ── Check activation status ───────────────────────────────────────────────────

@router.callback_query(F.data == "supreme:check")
async def cb_check_activation(callback: CallbackQuery) -> None:
    msg = await callback.message.edit_text(
        "<code>█░░░░░░░░░ CHECKING STATUS...</code>",
        parse_mode="HTML",
    )
    await asyncio.sleep(0.6)

    user_id = callback.from_user.id
    status  = await get_activation_status(user_id)
    is_sup  = await is_supreme_holder(user_id)
    stats   = await get_burn_stats(user_id)

    wallet  = status["wallet_address"] or ""
    short_w = (wallet[:6] + "…" + wallet[-4:]) if wallet else "not linked"
    tier    = status.get("active_tier", "free")

    burn_tx     = status.get("last_burn_tx") or "—"
    short_tx    = (burn_tx[:10] + "…") if len(burn_tx) > 10 else burn_tx
    burn_status = (status.get("last_burn_status") or "none").upper()

    tier_label = {
        "supreme_black": "🔱 SUPREME BLACK",
        "supreme":       "👑 SUPREME",
    }.get(tier, "🆓 FREE")

    text = (
        "╔══════════════════════════╗\n"
        "║   🔄 <b>ACTIVATION STATUS</b>   ║\n"
        "╚══════════════════════════╝\n\n"
        f"<code>┌─ ACCOUNT ────────────────┐\n"
        f"│  TIER    {tier_label:<18}│\n"
        f"│  WALLET  {short_w:<18}│\n"
        f"│  BURNED  {stats['total_burned']:>14,.0f} BRAINROT │\n"
        f"│  TXCOUNT {stats['burn_count']:<18}│\n"
        f"│  LAST TX {short_tx:<18}│\n"
        f"│  STATUS  {burn_status:<18}│\n"
        f"└──────────────────────────┘</code>\n\n"
    )

    if is_sup and status.get("expires_at"):
        try:
            exp_dt    = datetime.fromisoformat(str(status["expires_at"]).replace(" ", "T"))
            remaining = exp_dt - datetime.utcnow()
            total_sec = remaining.total_seconds()
            if total_sec > 0:
                hours = int(total_sec // 3600)
                mins  = int((total_sec % 3600) // 60)
                text += f"⏱ <b>Shuts off in:</b> {hours}h {mins}m\n\n"
            else:
                text += "⏱ <b>Timed access has expired.</b>\n\n"
        except (ValueError, AttributeError):
            pass

    if not is_sup:
        still_need = max(0, settings.SUPREME_REQUIRED_BURN_AMOUNT - stats["total_burned"])
        text += f"<i>Still need <b>{still_need:,.0f} $BRAINROT</b> burned to activate.</i>"
    else:
        text += "<i>SUPREME is active — all features unlocked ⚡</i>"

    await msg.edit_text(
        text,
        reply_markup=build_supreme_access(status["wallet_linked"], is_sup),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Utility ───────────────────────────────────────────────────────────────────

def _is_valid_solana_address(address: str) -> bool:
    import re
    return bool(re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$', address))
