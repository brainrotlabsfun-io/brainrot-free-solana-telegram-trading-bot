"""
utils/share_utils.py
====================
Builds inline share buttons for trade notifications.
Generates pre-filled posts for Twitter and Telegram,
and links to the community server if one is configured.

All links come from .env (BOT_USERNAME, DISCORD_URL, SHARE_HASHTAG)
so a fork advertises its own bot, not someone else's.
"""

import urllib.parse
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.config import settings


def bot_link() -> str:
    """Public t.me link for this bot, or '' if BOT_USERNAME isn't configured."""
    return f"https://t.me/{settings.BOT_USERNAME}" if settings.BOT_USERNAME else ""


DISCORD_URL = settings.DISCORD_URL
HASHTAG     = settings.SHARE_HASHTAG


def build_share_markup(share_text: str) -> InlineKeyboardMarkup:
    """
    Returns a one-row keyboard with Twitter, Telegram, and (optionally)
    Discord share buttons. share_text should be plain text (no HTML) —
    it will be URL-encoded.
    """
    encoded = urllib.parse.quote(share_text, safe="")
    twitter_url = f"https://twitter.com/intent/tweet?text={encoded}"

    buttons = [InlineKeyboardButton(text="🐦 Tweet", url=twitter_url)]

    # Telegram's share dialog needs a url= target; skip it if we have no bot link.
    link = bot_link()
    if link:
        telegram_url = (
            "https://t.me/share/url"
            f"?url={urllib.parse.quote(link, safe='')}&text={encoded}"
        )
        buttons.append(InlineKeyboardButton(text="✈️ Share", url=telegram_url))

    if DISCORD_URL:
        buttons.append(InlineKeyboardButton(text="💬 Discord", url=DISCORD_URL))

    builder = InlineKeyboardBuilder()
    builder.row(*buttons)
    return builder.as_markup()


def share_footer() -> str:
    """
    Optional branding line appended to share posts.
    Built from WEBSITE_URL / SHARE_HASHTAG in .env; empty when neither is set.
    """
    parts = []
    if settings.WEBSITE_URL:
        parts.append(settings.WEBSITE_URL.replace("https://", "").replace("http://", ""))
    if HASHTAG:
        parts.append(HASHTAG)
    return "  ".join(parts)


def website_buttons() -> list[InlineKeyboardButton]:
    """A single Website button, or [] when WEBSITE_URL isn't configured."""
    if not settings.WEBSITE_URL:
        return []
    return [InlineKeyboardButton(text="🌐 Website", url=settings.WEBSITE_URL)]
