"""
from utils.config import settings
services/placeholders.py
========================
Text generators for all placeholder module pages.
When a real module is built, replace the relevant function here
with a call to the actual service logic.
"""


def wallet_page() -> str:
    return (
        "💼 <b>Wallet Module</b>\n"
        "─────────────────────────\n\n"
        "This section will manage your Solana wallet connections, "
        "view balances, and grant trading permissions to the bot.\n\n"
        "<i>Coming soon — module not yet active.</i>"
    )


def settings_page() -> str:
    return (
        "⚙️ <b>Settings Module</b>\n"
        "─────────────────────────\n\n"
        "This section will let you configure risk parameters, "
        "alert preferences, slippage tolerances, and user-level options.\n\n"
        "<i>Coming soon — module not yet active.</i>"
    )


def premium_page() -> str:
    return (
        "👑 <b>Premium Module</b>\n"
        "─────────────────────────\n\n"
        "Premium tools will connect to the <b>$BRAINROT</b> ecosystem.\n"
        "Holding $BRAINROT will unlock advanced utilities including "
        "priority alerts, AI scoring, sniper access, and more.\n\n"
        "Token Contract:\n"
        f"<code>{settings.BRAINROT_MINT or 'not configured'}</code>\n\n"
        "<i>Coming soon — premium tiers not yet active.</i>"
    )


def watchlist_page() -> str:
    return (
        "👁 <b>WATCHLIST  //  DASHBOARD</b>\n"
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
        "Your personal intel board. Save tokens,\n"
        "flag wallets, monitor devs, and generate\n"
        "ready-to-post share cards for social.\n\n"
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        "🪙  <b>TOKENS</b>       — track contract addresses\n"
        "👛  <b>WALLETS</b>      — label wallets (whales, devs)\n"
        "👨‍💻  <b>DEV RADAR</b>    — monitor dev wallet launches\n"
        "📢  <b>TEMPLATES</b>    — share to X / social media\n"
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
        "<i>Select a section below to get started.</i>"
    )


def watchlist_section_wip(section: str) -> str:
    icons = {"tokens": "🪙", "wallets": "👛", "dev_radar": "👨‍💻", "templates": "📢"}
    names = {"tokens": "TOKEN TRACKER", "wallets": "WALLET LIST", "dev_radar": "DEV RADAR", "templates": "SHARE TEMPLATES"}
    icon = icons.get(section, "👁")
    name = names.get(section, section.upper())
    return (
        f"{icon} <b>{name}</b>\n"
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
        "This section is being built.\n\n"
        "<code>COMING SOON\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
        "<i>Go back to the Watchlist dashboard.</i>"
    )
