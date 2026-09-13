"""
bot/keyboards/share_templates.py
==================================
Pre-built Twitter/X share URLs for each module.
Used as url= on InlineKeyboardButton — opens directly in browser, no handler needed.
"""

from urllib.parse import quote
from utils.share_utils import bot_link as _bot_link
from utils.config import settings

_BASE = "https://twitter.com/intent/tweet?text="

SHARE_HASHTAG_URL = "https://x.com/hashtag/BRAINROTONCHAINBOT"


def _community_urls(text: str, title: str) -> tuple[str, str, str]:
    """Returns (twitter_url, telegram_url, reddit_url) for a given share text."""
    twitter  = "https://twitter.com/intent/tweet?text=" + quote(text, safe="")
    telegram = "https://t.me/share/url?url=" + quote(_bot_link(), safe="") + "&text=" + quote(text, safe="")
    reddit   = "https://www.reddit.com/submit?title=" + quote(title, safe="") + "&text=" + quote(text, safe="")
    return twitter, telegram, reddit


# ── Sniper community share
_SNIPER_TEXT = (
    "🎯 Running $BRAINROT Sniper on Solana — auto-buying token launches before they 100x.\n\n"
    f"Powered by {settings.BRAND_HANDLE} 🔥\n\n"
    "#BRAINROT #BRAINROTONCHAINBOT #Solana #SolanaSniper #DeFi"
)
SHARE_TWITTER_URL, SHARE_TELEGRAM_URL, SHARE_REDDIT_URL = _community_urls(
    _SNIPER_TEXT, "Running $BRAINROT Sniper on Solana 🎯"
)

# ── Candle Sniper community share
_CS_TEXT = (
    "🕯️ Running $BRAINROT Candle Sniper on Solana — catching pattern entries and surge setups on autopilot.\n\n"
    f"Powered by {settings.BRAND_HANDLE} 🔥\n\n"
    "#BRAINROT #BRAINROTONCHAINBOT #Solana #CandleSniper #DeFi"
)
CS_SHARE_TWITTER_URL, CS_SHARE_TELEGRAM_URL, CS_SHARE_REDDIT_URL = _community_urls(
    _CS_TEXT, "Running $BRAINROT Candle Sniper on Solana 🕯️"
)


def _url(text: str) -> str:
    return _BASE + quote(text, safe="")


# ── Module share templates ─────────────────────────────────────────────────────

SNIPER_SHARE_URL = _url(
    "🎯 Running $BRAINROT Sniper on Solana — auto-buying token launches before they 100x.\n\n"
    f"Powered by {settings.BRAND_HANDLE} 🔥\n\n"
    "#BRAINROT #Solana #SolanaSniper #DeFi #CryptoBot"
)

COPY_TRADE_SHARE_URL = _url(
    "📋 Copy trading alpha wallets on Solana with $BRAINROT Bot — mirroring smart money moves in real time.\n\n"
    f"Powered by {settings.BRAND_HANDLE} 🔥\n\n"
    "#BRAINROT #Solana #CopyTrading #DeFi #CryptoBot"
)

CANDLE_SNIPER_SHARE_URL = _url(
    "🕯️ Running $BRAINROT Candle Sniper — catching pattern entries and surge setups on Solana on autopilot.\n\n"
    f"Powered by {settings.BRAND_HANDLE} 🔥\n\n"
    "#BRAINROT #Solana #CandleSniper #TechnicalAnalysis #CryptoBot"
)

WALLET_SCOUT_SHARE_URL = _url(
    "👁️ Scouting alpha wallets on Solana with $BRAINROT — tracking smart money before they move.\n\n"
    f"Powered by {settings.BRAND_HANDLE} 🔥\n\n"
    "#BRAINROT #Solana #WalletScout #AlphaHunting #DeFi"
)

SUPREME_SHARE_URL = _url(
    "⬛ Running $BRAINROT Supreme Black on Solana — full auto TP/SL, trailing stops, and smart exit automation.\n\n"
    f"Powered by {settings.BRAND_HANDLE} 🔥\n\n"
    "#BRAINROT #Solana #SupremeBlack #DeFiTrading #CryptoBot"
)
