"""
utils/config.py
===============
Loads and validates all environment variables.
Single shared settings object — import `settings` everywhere.
"""

import sys
import logging
from dataclasses import dataclass, field

from dotenv import load_dotenv
import os

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class Settings:
    BOT_TOKEN: str

    # ── Admin ──────────────────────────────────────────────────────────────────
    ADMIN_IDS: list[int] = field(default_factory=list)

    # ── Branding / public links ────────────────────────────────────────────
    # Your bot's @username (no @) — used to build share / referral links.
    BOT_USERNAME: str = ""
    # Optional community links shown on share buttons. Blank = button hidden.
    DISCORD_URL:  str = ""
    TWITTER_URL:  str = ""
    WEBSITE_URL:  str = ""
    TOKEN_NAME:   str = "TOKEN"      # display name used in copy, e.g. "BRAINROT"
    BRAND_HANDLE: str = ""           # social handle shown in share copy, e.g. "@myproject"
    SHARE_HASHTAG: str = ""          # e.g. "#mybot" — blank = no hashtag

    # ── Payments ──────────────────────────────────────────────────────────
    # SOL address that receives subscription / signup payments.
    # MUST be your own wallet. Payment features stay disabled while blank.
    PAYMENT_WALLET: str = ""

    # ── Raid Hub behaviour ─────────────────────────────────────────────────────
    # True  = raids go live immediately after creation
    # False = raids wait for admin /approve_raid before appearing
    RAID_AUTO_APPROVE: bool = True

    # Max hub raids a user can create per day
    DAILY_RAID_LIMIT: int = 2
    PREMIUM_DAILY_RAID_LIMIT: int = 10

    # ── $BRAINROT Burn / SUPREME ───────────────────────────────────────────────
    BRAINROT_MINT:                 str   = ""   # your SPL token mint — see .env.example
    SOLANA_RPC_URL:                str   = "https://api.mainnet-beta.solana.com"
    SOLANA_RPC_URLS:               list  = field(default_factory=list)  # fallback list
    WALLET_ENCRYPTION_KEY:         str   = ""   # required — see .env.example
    SUPREME_REQUIRED_BURN_AMOUNT:       float = 1_000_000.0   # $BRAINROT tokens → SUPREME
    SUPREME_BLACK_REQUIRED_BURN_AMOUNT: float = 10_000_000.0  # $BRAINROT tokens → SUPREME BLACK
    SUPREME_PERMANENT_UNLOCK:           bool  = True
    SUPREME_DURATION_DAYS:         int   = 30           # used only if not permanent
    FOUNDING_BADGE_ENABLED:        bool  = True
    FOUNDING_BADGE_CUTOFF:         str   = ""           # ISO date, e.g. "2025-06-01" or ""
    FOUNDING_BADGE_MAX_USERS:      int   = 100          # 0 = unlimited

    # ── Sniper Tool — Free tier limits ─────────────────────────────────────────
    FREE_MAX_BUY_SOL:       float = 0.5
    FREE_MAX_BUYS_PER_HOUR: int   = 3
    FREE_WATCH_LIMIT:       int   = 5
    FREE_PRESETS_LIMIT:     int   = 1
    FREE_BLACKLIST_LIMIT:   int   = 10
    FREE_FEED_LIMIT:        int   = 5

    # ── Sniper Tool — SUPREME tier limits ──────────────────────────────────────
    SUPREME_MAX_BUY_SOL:       float = 10.0
    SUPREME_MAX_BUYS_PER_HOUR: int   = 50
    SUPREME_WATCH_LIMIT:       int   = 50
    SUPREME_PRESETS_LIMIT:     int   = 20
    SUPREME_BLACKLIST_LIMIT:   int   = 200
    SUPREME_FEED_LIMIT:        int   = 25

    # ── Affiliate / Referral system ────────────────────────────────────────────
    # SOL amount for the $100 qualifying Supreme signup payment
    # Adjust when SOL price changes significantly (e.g. $100 / SOL_PRICE)
    AFFILIATE_SIGNUP_SOL:              float = 0.67
    # Enable mock payment confirmation for local testing (never enable in prod)
    MOCK_SUPREME_PAYMENT_CONFIRMATION: bool  = False

    # ── Candle Sniper tier limits ───────────────────────────────────────────────
    CS_FREE_MAX_CANDIDATES:    int   = 15
    CS_FREE_MAX_POSITIONS:     int   = 5
    CS_SUPREME_MAX_CANDIDATES: int   = 50
    CS_SUPREME_MAX_POSITIONS:  int   = 15
    CS_SB_MAX_CANDIDATES:      int   = 9999  # Supreme Black — unlimited
    CS_SB_MAX_POSITIONS:       int   = 9999  # Supreme Black — unlimited


def _load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        logger.critical(
            "BOT_TOKEN is missing. Copy .env.example to .env, paste the token "
            "@BotFather gave you, then restart. See SETUP.md."
        )
        sys.exit(1)

    # ── Wallet encryption key ─────────────────────────────────────────────────
    # This key encrypts every user's bot-wallet private key in the database.
    # Refuse to start without it: running blank would either crash later or,
    # worse, write unrecoverable wallet rows.
    enc_key = os.getenv("WALLET_ENCRYPTION_KEY", "").strip()
    if not enc_key:
        logger.critical(
            "WALLET_ENCRYPTION_KEY is missing. Generate your OWN key by "
            "running this command, then paste the output into .env:"
        )
        logger.critical("    %s", 'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"')
        logger.critical(
            "Never reuse a key from anyone else's repo, and never share "
            "yours - it decrypts every user wallet in your database."
        )
        sys.exit(1)

    admin_ids = [
        int(x.strip())
        for x in os.getenv("ADMIN_IDS", "").split(",")
        if x.strip().isdigit()
    ]

    auto_approve = os.getenv("RAID_AUTO_APPROVE", "true").strip().lower() == "true"
    daily_limit         = int(os.getenv("DAILY_RAID_LIMIT", "2"))
    premium_daily_limit = int(os.getenv("PREMIUM_DAILY_RAID_LIMIT", "10"))

    return Settings(
        BOT_TOKEN               = token,
        ADMIN_IDS               = admin_ids,
        BOT_USERNAME            = os.getenv("BOT_USERNAME", "").strip().lstrip("@"),
        DISCORD_URL             = os.getenv("DISCORD_URL", "").strip(),
        TWITTER_URL             = os.getenv("TWITTER_URL", "").strip(),
        WEBSITE_URL             = os.getenv("WEBSITE_URL", "").strip(),
        TOKEN_NAME              = os.getenv("TOKEN_NAME", "TOKEN").strip(),
        BRAND_HANDLE            = os.getenv("BRAND_HANDLE", "").strip(),
        SHARE_HASHTAG           = os.getenv("SHARE_HASHTAG", "").strip(),
        PAYMENT_WALLET          = os.getenv("PAYMENT_WALLET", "").strip(),
        RAID_AUTO_APPROVE       = auto_approve,
        DAILY_RAID_LIMIT        = daily_limit,
        PREMIUM_DAILY_RAID_LIMIT= premium_daily_limit,
        # Burn / SUPREME
        BRAINROT_MINT                = os.getenv("BRAINROT_MINT", "").strip(),
        SOLANA_RPC_URL               = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"),
        SOLANA_RPC_URLS              = [
            u.strip() for u in
            os.getenv("SOLANA_RPC_URLS", os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")).split(",")
            if u.strip()
        ],
        WALLET_ENCRYPTION_KEY        = enc_key,
        SUPREME_REQUIRED_BURN_AMOUNT       = float(os.getenv("SUPREME_REQUIRED_BURN_AMOUNT", "1000000")),
        SUPREME_BLACK_REQUIRED_BURN_AMOUNT = float(os.getenv("SUPREME_BLACK_REQUIRED_BURN_AMOUNT", "10000000")),
        SUPREME_PERMANENT_UNLOCK           = os.getenv("SUPREME_PERMANENT_UNLOCK", "true").lower() == "true",
        SUPREME_DURATION_DAYS        = int(os.getenv("SUPREME_DURATION_DAYS", "30")),
        FOUNDING_BADGE_ENABLED       = os.getenv("FOUNDING_BADGE_ENABLED", "true").lower() == "true",
        FOUNDING_BADGE_CUTOFF        = os.getenv("FOUNDING_BADGE_CUTOFF", ""),
        FOUNDING_BADGE_MAX_USERS     = int(os.getenv("FOUNDING_BADGE_MAX_USERS", "100")),
        # Sniper limits read from env with sensible defaults
        FREE_MAX_BUY_SOL        = float(os.getenv("FREE_MAX_BUY_SOL", "0.5")),
        FREE_MAX_BUYS_PER_HOUR  = int(os.getenv("FREE_MAX_BUYS_PER_HOUR", "3")),
        FREE_WATCH_LIMIT        = int(os.getenv("FREE_WATCH_LIMIT", "5")),
        FREE_PRESETS_LIMIT      = int(os.getenv("FREE_PRESETS_LIMIT", "1")),
        FREE_BLACKLIST_LIMIT    = int(os.getenv("FREE_BLACKLIST_LIMIT", "10")),
        FREE_FEED_LIMIT         = int(os.getenv("FREE_FEED_LIMIT", "5")),
        SUPREME_MAX_BUY_SOL        = float(os.getenv("SUPREME_MAX_BUY_SOL", "10.0")),
        SUPREME_MAX_BUYS_PER_HOUR  = int(os.getenv("SUPREME_MAX_BUYS_PER_HOUR", "50")),
        SUPREME_WATCH_LIMIT        = int(os.getenv("SUPREME_WATCH_LIMIT", "50")),
        SUPREME_PRESETS_LIMIT      = int(os.getenv("SUPREME_PRESETS_LIMIT", "20")),
        SUPREME_BLACKLIST_LIMIT    = int(os.getenv("SUPREME_BLACKLIST_LIMIT", "200")),
        SUPREME_FEED_LIMIT         = int(os.getenv("SUPREME_FEED_LIMIT", "25")),
        # Affiliate
        AFFILIATE_SIGNUP_SOL              = float(os.getenv("AFFILIATE_SIGNUP_SOL", "0.67")),
        MOCK_SUPREME_PAYMENT_CONFIRMATION = os.getenv("MOCK_SUPREME_PAYMENT_CONFIRMATION", "false").lower() == "true",
    )


settings: Settings = _load_settings()


def _warn_unconfigured() -> None:
    """Non-fatal nudges for features that stay off until configured."""
    if not settings.PAYMENT_WALLET:
        logger.warning(
            "PAYMENT_WALLET is not set - paid signup/subscription features are "
            "DISABLED. Set it to your own SOL address in .env to enable them."
        )
    if not settings.BRAINROT_MINT:
        logger.warning(
            "BRAINROT_MINT is not set - token-gating and burn features are "
            "DISABLED. Set it to your own SPL token mint in .env to enable them."
        )
    if not settings.BOT_USERNAME:
        logger.warning(
            "BOT_USERNAME is not set - share and referral links will be omitted."
        )
    if not settings.ADMIN_IDS:
        logger.warning(
            "ADMIN_IDS is empty - no one can use admin commands. "
            "Send /myid to your bot to get your Telegram ID, then add it to .env."
        )


_warn_unconfigured()


# ── RPC rotation ───────────────────────────────────────────────────────────────
import time as _time

_rpc_cooldowns: dict[str, float] = {}   # url → timestamp when it was rate-limited
_RPC_COOLDOWN_SEC = 10                  # skip a 429'd RPC for 10 seconds, then retry
_rpc_index = 0                          # round-robin cursor


def get_rpc_url() -> str:
    """
    Returns the best available RPC URL.
    Round-robins across all configured URLs, skipping any that recently returned 429.
    Falls back to the primary URL if all are cooling down.
    """
    global _rpc_index
    urls = settings.SOLANA_RPC_URLS or [settings.SOLANA_RPC_URL]
    now  = _time.time()

    # Find next available (not in cooldown)
    for _ in range(len(urls)):
        url = urls[_rpc_index % len(urls)]
        _rpc_index += 1
        if now - _rpc_cooldowns.get(url, 0) > _RPC_COOLDOWN_SEC:
            return url

    # All cooling down — return primary anyway
    return urls[0]


def mark_rpc_rate_limited(url: str) -> None:
    """Call this when an RPC returns 429 so it gets skipped for a bit."""
    _rpc_cooldowns[url] = _time.time()
    logger.warning(f"RPC rate-limited, cooling down {_RPC_COOLDOWN_SEC}s: {url[:50]}")
