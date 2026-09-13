"""
bot/keyboards/affiliate_menu.py
================================
Inline keyboards for the Alpha Network / Affiliate system.
"""

import urllib.parse

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from utils.share_utils import bot_link as _bot_link


def build_affiliate_hub() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    # Smaller buttons — 2 per row
    b.row(
        InlineKeyboardButton(text="🧠 My Profile",  callback_data="af:profile"),
        InlineKeyboardButton(text="💰 Earnings",    callback_data="af:earnings"),
    )
    b.row(
        InlineKeyboardButton(text="📊 My Tier",     callback_data="af:tier"),
        InlineKeyboardButton(text="📣 Share",        callback_data="af:share"),
    )
    # Signup CTA — full width, prominent
    b.row(InlineKeyboardButton(text="⬛ Supreme Black Signup — $100", callback_data="af:signup:start"))
    b.row(InlineKeyboardButton(text="⬅️ Back",       callback_data="menu:back"))
    return b.as_markup()


def build_share_menu(wallet: str | None = None) -> InlineKeyboardMarkup:
    """
    Direct-action share buttons. URL buttons open Twitter/Telegram immediately
    with the post pre-filled — no copy/paste needed.
    Wallet address is shown in the message body as a tappable <code> block.
    """
    b = InlineKeyboardBuilder()

    if wallet:
        twitter_body = (
            f"Just locked in ⬛ SUPREME BLACK on @brainrotlabs_io 🧠\n\n"
            f"Unlimited copy wallets. Auto-sell. TP/SL.\n"
            f"Full on-chain trading on $SOL.\n\n"
            f"Sign up with my wallet and I earn 21% commission:\n"
            f"{wallet}\n\n"
            f"Open @BrainRotBot → Alpha Network → Supreme Black Signup\n\n"
            f"#BRAINROT #Solana #CopyTrading #Memecoin"
        )
        twitter_url = "https://twitter.com/intent/tweet?text=" + urllib.parse.quote(twitter_body)

        tg_body = (
            f"⬛ SUPREME BLACK — $BRAINROT Bot\n\n"
            f"Unlimited copy wallets · Auto-sell · TP/SL\n"
            f"Full Solana trading suite, on-chain.\n\n"
            f"Sign up through my referral:\n"
            f"1. Open @BrainRotBot\n"
            f"2. Go to Alpha Network\n"
            f"3. Enter my wallet on signup:\n"
            f"   {wallet}\n\n"
            f"I earn 21% commission in SOL automatically 🔱"
        )
        tg_url = "https://t.me/share/url?url=" + urllib.parse.quote(_bot_link(), safe="") + "&text=" + urllib.parse.quote(tg_body)

        b.row(InlineKeyboardButton(text="𝕏  Post to Twitter / X", url=twitter_url))
        b.row(InlineKeyboardButton(text="✈️  Share on Telegram",   url=tg_url))
    else:
        b.row(InlineKeyboardButton(text="⚠️ Link wallet first", callback_data="supreme:main"))

    b.row(InlineKeyboardButton(text="⬅️ Back", callback_data="af:main"))
    return b.as_markup()


def build_affiliate_signup_wallet_prompt(has_pending: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if has_pending:
        b.row(InlineKeyboardButton(
            text="✅ I've Sent — Check Payment",
            callback_data="af:signup:check",
        ))
    b.row(InlineKeyboardButton(
        text="⏭️ Skip Affiliate Wallet",
        callback_data="af:signup:skip_wallet",
    ))
    b.row(InlineKeyboardButton(text="⬅️ Back", callback_data="af:main"))
    return b.as_markup()


def build_affiliate_payment_waiting() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="📥 Submit TX Signature",
        callback_data="af:signup:submit_tx",
    ))
    b.row(InlineKeyboardButton(
        text="🔄 Auto-Check",
        callback_data="af:signup:check",
    ))
    b.row(
        InlineKeyboardButton(text="🔄 Restart",  callback_data="af:signup:start"),
        InlineKeyboardButton(text="⬅️ Back",     callback_data="af:main"),
    )
    return b.as_markup()


def build_affiliate_payment_waiting_mock() -> InlineKeyboardMarkup:
    """Includes mock confirmation button when MOCK_SUPREME_PAYMENT_CONFIRMATION=true."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="📥 Submit TX Signature",
        callback_data="af:signup:submit_tx",
    ))
    b.row(InlineKeyboardButton(
        text="🔄 Auto-Check",
        callback_data="af:signup:check",
    ))
    b.row(InlineKeyboardButton(
        text="🧪 [MOCK] Simulate Confirmation",
        callback_data="af:signup:mock_confirm",
    ))
    b.row(
        InlineKeyboardButton(text="🔄 Restart",  callback_data="af:signup:start"),
        InlineKeyboardButton(text="⬅️ Back",     callback_data="af:main"),
    )
    return b.as_markup()


def build_affiliate_back() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Back to Alpha Network", callback_data="af:main"))
    return b.as_markup()


def build_affiliate_activated() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🧠 My Profile",    callback_data="af:profile"),
        InlineKeyboardButton(text="⬛ SUPREME ACCESS", callback_data="supreme:main"),
    )
    b.row(InlineKeyboardButton(text="⬅️ Alpha Network", callback_data="af:main"))
    return b.as_markup()


def build_affiliate_profile_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="💰 Earnings",  callback_data="af:earnings"),
        InlineKeyboardButton(text="📊 Tier",      callback_data="af:tier"),
        InlineKeyboardButton(text="📣 Share",     callback_data="af:share"),
    )
    b.row(InlineKeyboardButton(text="⬅️ Back", callback_data="af:main"))
    return b.as_markup()


def build_admin_affiliate_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="📋 All Affiliates",     callback_data="af:admin:list"),
        InlineKeyboardButton(text="💸 Unpaid",             callback_data="af:admin:unpaid"),
    )
    b.row(InlineKeyboardButton(text="⬅️ Back",             callback_data="af:main"))
    return b.as_markup()


def build_admin_back() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="⬅️ Admin Menu",  callback_data="af:admin:menu"),
        InlineKeyboardButton(text="🏠 Alpha Network", callback_data="af:main"),
    )
    return b.as_markup()
