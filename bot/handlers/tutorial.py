"""
bot/handlers/tutorial.py
=========================
Interactive user tutorial — simulated walkthroughs for:
  1. 🎯 SNIPER AUTO-TRADE
  2. 📋 COPY TRADE
  3. 🕯️ CANDLE SNIPER

Each tutorial walks the user through setup step-by-step, simulates
a real trade firing, and ends with a profit result screen.

Callback prefix: tut:*
"""

import asyncio
import random
import string
from datetime import datetime, timezone, timedelta

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from utils.config import settings

router = Router()

# ── Helpers ────────────────────────────────────────────────────────────────────

def _kb(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Quick keyboard builder: rows of (text, callback_data) tuples."""
    b = InlineKeyboardBuilder()
    for row in rows:
        b.row(*[InlineKeyboardButton(text=t, callback_data=c) for t, c in row])
    return b.as_markup()

def _fake_sig() -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=44))

def _fake_token() -> tuple[str, str, str]:
    """Returns (symbol, name, address)."""
    names = [
        ("BONK2", "Bonk Season 2"),
        ("MOON", "Moon Protocol"),
        ("CHAD", "Alpha Chad"),
        ("DEGEN", "Degen Capital"),
        ("PUMP", "PumpStar"),
        ("BULL", "BullRun Token"),
        ("FROG", "Frog Finance"),
    ]
    sym, name = random.choice(names)
    addr = "".join(random.choices(string.ascii_letters + string.digits, k=44))
    return sym, name, addr

def _fake_wallet() -> str:
    wallets = [
        "7xKX...9aQp",
        "BzR2...mW4k",
        "9pLN...vT7y",
        "Ak3Q...nF8d",
    ]
    return random.choice(wallets)

def _pnl_bar(pct: float) -> str:
    filled = min(int(abs(pct) / 10), 10)
    empty  = 10 - filled
    char   = "█" if pct >= 0 else "▓"
    return char * filled + "░" * empty

# ── Hub ────────────────────────────────────────────────────────────────────────

HUB_TEXT = (
    "<code>╔══════════════════════════════════╗\n"
    "║   📚  BRAINROT  ACADEMY          ║\n"
    "║   Interactive Trade Tutorials    ║\n"
    "╚══════════════════════════════════╝</code>\n\n"
    "Choose a tutorial below.\n"
    "Each walk-through <b>simulates a real scenario</b> — "
    "you'll see every screen exactly as it appears live.\n\n"
    "<code>┌─────────────────────────────────┐\n"
    "│  🎯  SNIPER    auto-buy new launches     │\n"
    "│  📋  COPY      mirror alpha wallets      │\n"
    "│  🕯️  CANDLE    pattern + surge entries   │\n"
    "│  ⚔️  RAIDS     center vs hub explained   │\n"
    "└─────────────────────────────────┘</code>\n\n"
    "<i>Takes about 2 minutes each. No real SOL used.</i>"
)

@router.callback_query(F.data == "tut:hub")
async def cb_tut_hub(callback: CallbackQuery) -> None:
    kb = _kb(
        [("🎯  Sniper Auto-Trade",   "tut:sniper:1")],
        [("📋  Copy Trade Setup",    "tut:copy:1")],
        [("🕯️  Candle Sniper",       "tut:candle:1")],
        [("⚔️  Raid Center",         "tut:raid_center:1"),
         ("🚀  Raid Hub",            "tut:raid_hub:1")],
        [("⬅️  Back to Menu",        "menu:back")],
    )
    try:
        await callback.message.edit_text(HUB_TEXT, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


# ══════════════════════════════════════════════════════════════════════════════
#  TUTORIAL — RAID CENTER
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "tut:raid_center:1")
async def tut_raid_center_1(callback: CallbackQuery) -> None:
    text = (
        "<code>═══════════════════════════════════\n"
        " ⚔️  RAID CENTER TUTORIAL  —  1 / 4\n"
        "═══════════════════════════════════</code>\n\n"
        "<b>First — what's the difference?</b>\n\n"
        "There are two raid dashboards in this bot.\n"
        "They look similar but work very differently:\n\n"
        "<code>⚔️ RAID CENTER</code>\n"
        "Admin-run. One official raid at a time.\n"
        "Everyone executes the same target together.\n"
        "Think of it as a coordinated strike — timed,\n"
        "focused, and organised from the top down.\n\n"
        "<code>🚀 RAID HUB</code>\n"
        "Community-run. Anyone can post a raid.\n"
        "Multiple raids live at once. You pick and join.\n"
        "Bottom-up — the community drives the action.\n\n"
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        "<i>This tutorial covers Raid Center. Tap next.</i>"
    )
    kb = _kb(
        [("▶️  Next: How It Works",  "tut:raid_center:2")],
        [("⬅️  Back to Tutorials",   "tut:hub")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:raid_center:2")
async def tut_raid_center_2(callback: CallbackQuery) -> None:
    text = (
        "<code>═══════════════════════════════════\n"
        " ⚔️  RAID CENTER TUTORIAL  —  2 / 4\n"
        "═══════════════════════════════════</code>\n\n"
        "<b>How does a Raid Center raid work?</b>\n\n"
        "An admin (the bot operator) creates a raid\n"
        "by running <code>/create_raid</code>. They set:\n\n"
        "<code>• Platform</code>  — Twitter, Telegram, DEX, etc.\n"
        "<code>• Target URL</code> — the tweet, chart, or token\n"
        "<code>• Instructions</code> — exactly what to do\n"
        "<code>• Reward points</code> — what you earn\n"
        "<code>• Expiry time</code> — how long it's live\n\n"
        "Once posted, everyone in the bot sees it\n"
        "under <b>Active Raid</b> in the Raid Center.\n\n"
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        "<i>Next: how to complete and claim points.</i>"
    )
    kb = _kb(
        [("▶️  Next: Completing a Raid", "tut:raid_center:3")],
        [("⬅️  Back",                    "tut:raid_center:1")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:raid_center:3")
async def tut_raid_center_3(callback: CallbackQuery) -> None:
    text = (
        "<code>═══════════════════════════════════\n"
        " ⚔️  RAID CENTER TUTORIAL  —  3 / 4\n"
        "═══════════════════════════════════</code>\n\n"
        "<b>Completing a raid — step by step:</b>\n\n"
        "<code>1.</code> Open <b>Raid Center</b> from the main menu\n"
        "<code>2.</code> Tap <b>Active Raid</b> to see the current target\n"
        "<code>3.</code> Read the instructions — like, repost,\n"
        "   comment, buy, or all of the above\n"
        "<code>4.</code> Do the tasks on the platform shown\n"
        "<code>5.</code> Come back and tap <b>✅ Mark Completed</b>\n"
        "<code>6.</code> Points are added to your account instantly\n\n"
        "You can only complete each raid once.\n"
        "The bot tracks who's completed what.\n\n"
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        "<i>Next: points, leaderboard, and why it matters.</i>"
    )
    kb = _kb(
        [("▶️  Next: Points & Value",  "tut:raid_center:4")],
        [("⬅️  Back",                  "tut:raid_center:2")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:raid_center:4")
async def tut_raid_center_4(callback: CallbackQuery) -> None:
    text = (
        "<code>═══════════════════════════════════\n"
        " ⚔️  RAID CENTER TUTORIAL  —  4 / 4\n"
        "═══════════════════════════════════</code>\n\n"
        "<b>Why do raids have value?</b>\n\n"
        "Attention = volume. Volume = price action.\n\n"
        "When the whole community hits the same token\n"
        "at the same time — likes, comments, buys —\n"
        "it creates real on-chain activity that\n"
        "algorithms and traders notice.\n\n"
        "You're not just clicking a button.\n"
        "You're moving a market.\n\n"
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "POINTS  → rank on the leaderboard\n"
        "RAIDS   → community rep + rewards\n"
        "$BRAINROT → powers the whole system\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
        "✅ <b>You're ready. Go raid something.</b>"
    )
    kb = _kb(
        [("⚔️  Open Raid Center",    "raid:main")],
        [("⬅️  Back to Tutorials",   "tut:hub")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


# ══════════════════════════════════════════════════════════════════════════════
#  TUTORIAL — RAID HUB
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "tut:raid_hub:1")
async def tut_raid_hub_1(callback: CallbackQuery) -> None:
    text = (
        "<code>═══════════════════════════════════\n"
        " 🚀  RAID HUB TUTORIAL  —  1 / 4\n"
        "═══════════════════════════════════</code>\n\n"
        "<b>First — what's the difference?</b>\n\n"
        "There are two raid dashboards in this bot.\n"
        "They look similar but work very differently:\n\n"
        "<code>⚔️ RAID CENTER</code>\n"
        "Admin-run. One official raid at a time.\n"
        "Everyone executes the same target together.\n"
        "Coordinated, timed, top-down.\n\n"
        "<code>🚀 RAID HUB</code>\n"
        "Community-run. Anyone can post a raid.\n"
        "Multiple raids live at once. You pick and join.\n"
        "You found alpha — you start the raid yourself.\n\n"
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        "<i>This tutorial covers Raid Hub. Tap next.</i>"
    )
    kb = _kb(
        [("▶️  Next: Posting a Raid",  "tut:raid_hub:2")],
        [("⬅️  Back to Tutorials",     "tut:hub")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:raid_hub:2")
async def tut_raid_hub_2(callback: CallbackQuery) -> None:
    text = (
        "<code>═══════════════════════════════════\n"
        " 🚀  RAID HUB TUTORIAL  —  2 / 4\n"
        "═══════════════════════════════════</code>\n\n"
        "<b>How to post your own raid:</b>\n\n"
        "Anyone can start a raid from the Hub.\n"
        "You'll be walked through 9 quick steps:\n\n"
        "<code>1.</code> Give your raid a title\n"
        "<code>2.</code> Pick the platform (Twitter, Telegram...)\n"
        "<code>3.</code> Paste the target link\n"
        "<code>4.</code> Write the instructions for raiders\n"
        "<code>5.</code> Add comment ideas (optional)\n"
        "<code>6.</code> Add hashtags (optional)\n"
        "<code>7.</code> Set the reward points\n"
        "<code>8.</code> Set an expiry time\n"
        "<code>9.</code> Confirm and publish\n\n"
        "Once live, other users can find and join it\n"
        "from the <b>Browse Raids</b> list.\n\n"
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        "<i>Next: joining and completing raids others post.</i>"
    )
    kb = _kb(
        [("▶️  Next: Joining a Raid",  "tut:raid_hub:3")],
        [("⬅️  Back",                  "tut:raid_hub:1")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:raid_hub:3")
async def tut_raid_hub_3(callback: CallbackQuery) -> None:
    text = (
        "<code>═══════════════════════════════════\n"
        " 🚀  RAID HUB TUTORIAL  —  3 / 4\n"
        "═══════════════════════════════════</code>\n\n"
        "<b>Joining a raid someone else posted:</b>\n\n"
        "<code>1.</code> Open <b>Raid Hub</b> from the main menu\n"
        "<code>2.</code> Tap <b>Browse Raids</b> to see what's live\n"
        "<code>3.</code> Pick a raid — read the instructions\n"
        "<code>4.</code> Tap <b>✅ Join Raid</b> to sign up\n"
        "<code>5.</code> Go do the tasks on the platform shown\n"
        "<code>6.</code> Come back, tap <b>✅ Mark Complete</b>\n"
        "<code>7.</code> Points land in your account immediately\n\n"
        "You can track everything under:\n"
        "<code>• My Raids</code>  — raids you created\n"
        "<code>• Joined Raids</code> — raids you participated in\n"
        "<code>• My Points</code>  — your total score + rank\n\n"
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        "<i>Next: points, leaderboard, and community value.</i>"
    )
    kb = _kb(
        [("▶️  Next: Points & Value",  "tut:raid_hub:4")],
        [("⬅️  Back",                  "tut:raid_hub:2")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:raid_hub:4")
async def tut_raid_hub_4(callback: CallbackQuery) -> None:
    text = (
        "<code>═══════════════════════════════════\n"
        " 🚀  RAID HUB TUTORIAL  —  4 / 4\n"
        "═══════════════════════════════════</code>\n\n"
        "<b>Why post a raid at all?</b>\n\n"
        "You found a token early. You want volume.\n"
        "You post a raid — the community piles in.\n"
        "Likes, comments, buys all happen at once.\n"
        "Algorithms flag it. More eyes follow.\n"
        "You earn points for starting it.\n\n"
        "<b>Why join someone else's raid?</b>\n\n"
        "They did the research. You execute.\n"
        "You earn points and ride the wave with them.\n"
        "The best raiders build a reputation here.\n\n"
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "POST RAIDS   → build rep + earn points\n"
        "JOIN RAIDS   → stack points fast\n"
        "LEADERBOARD  → top raiders get recognized\n"
        "$BRAINROT    → powers the whole system\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
        "✅ <b>You're ready. Go start or join a raid.</b>"
    )
    kb = _kb(
        [("🚀  Open Raid Hub",        "hub:main")],
        [("⬅️  Back to Tutorials",    "tut:hub")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


# ══════════════════════════════════════════════════════════════════════════════
#  TUTORIAL 1 — SNIPER AUTO-TRADE
# ══════════════════════════════════════════════════════════════════════════════

SNIPER_STEPS = 8

def _sniper_progress(step: int) -> str:
    filled = "█" * step
    empty  = "░" * (SNIPER_STEPS - step)
    return f"[{filled}{empty}] Step {step}/{SNIPER_STEPS}"


@router.callback_query(F.data == "tut:sniper:1")
async def tut_sniper_1(callback: CallbackQuery) -> None:
    text = (
        f"<code>{_sniper_progress(1)}\n"
        "══════════════════════════════════\n"
        " 🎯  SNIPER AUTO-TRADE TUTORIAL\n"
        "══════════════════════════════════</code>\n\n"
        "<b>What is the Sniper?</b>\n\n"
        "The Sniper monitors the <b>Solana blockchain in real-time</b> "
        "and automatically buys new token launches that pass your filters — "
        "before most traders even see them.\n\n"
        "<code>┌──────────────────────────────┐\n"
        "│  New token launches on pump.fun  │\n"
        "│           ↓                      │\n"
        "│  Score filter (quality check)    │\n"
        "│           ↓                      │\n"
        "│  Auto-Buy fires instantly        │\n"
        "│           ↓                      │\n"
        "│  Auto-Exit manages profit/loss   │\n"
        "└──────────────────────────────┘</code>\n\n"
        "⚡ Speed is everything — early entries = max upside.\n\n"
        "<i>Step 1: Let's set up your bot wallet first.</i>"
    )
    kb = _kb(
        [("▶️  Next: Set Up Wallet", "tut:sniper:2")],
        [("⬅️  Back to Tutorials",   "tut:hub")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:sniper:2")
async def tut_sniper_2(callback: CallbackQuery) -> None:
    fake_addr = "7xKXmW4k" + "".join(random.choices("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz", k=28))
    text = (
        f"<code>{_sniper_progress(2)}\n"
        "══════════════════════════════════\n"
        " 💼  STEP 2 — BOT WALLET SETUP\n"
        "══════════════════════════════════</code>\n\n"
        "The bot uses a <b>dedicated trading wallet</b> — completely separate "
        "from your personal wallet. You control deposits and withdrawals.\n\n"
        "<code>╔══════════════════════════════╗\n"
        "║  YOUR BOT WALLET             ║\n"
        f"║  {fake_addr[:32]}  ║\n"
        "║                              ║\n"
        "║  Balance:  0.00000 SOL       ║\n"
        "║  Status:   🔴  NEEDS FUNDING  ║\n"
        "╚══════════════════════════════╝</code>\n\n"
        "📥 <b>To fund your wallet:</b>\n"
        "  1. Go to <b>💼 Wallet</b> from the main menu\n"
        "  2. Copy your bot wallet address\n"
        "  3. Send SOL from your personal wallet or exchange\n"
        "  4. Recommended: start with <b>0.5 – 2 SOL</b>\n\n"
        "<code>⚠️  MINIMUM REQUIRED: 0.05 SOL + fees (~0.008 SOL)\n"
        "    Each auto-buy uses your configured buy size.\n"
        "    Keep 5–10 buys worth of SOL in the wallet.</code>\n\n"
        "<i>In this tutorial your wallet is pre-funded. Let's configure the sniper.</i>"
    )
    kb = _kb(
        [("▶️  Next: Configure Sniper", "tut:sniper:3")],
        [("⬅️  Back",                   "tut:sniper:1")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:sniper:3")
async def tut_sniper_3(callback: CallbackQuery) -> None:
    text = (
        f"<code>{_sniper_progress(3)}\n"
        "══════════════════════════════════\n"
        " ⚙️  STEP 3 — SNIPER SETTINGS\n"
        "══════════════════════════════════</code>\n\n"
        "Navigate to <b>🎯 SNIPER TOOL → ⚙️ Settings</b> to configure filters.\n\n"
        "<code>┌─ RECOMMENDED STARTER SETTINGS ──┐\n"
        "│                                  │\n"
        "│  SCORE THRESHOLD   ≥ 45 / 100    │\n"
        "│  ↳ filters low-quality launches  │\n"
        "│                                  │\n"
        "│  MIN LIQUIDITY     $5,000 USD    │\n"
        "│  ↳ real money in the pool        │\n"
        "│                                  │\n"
        "│  MIN VOLUME        $2,000/hr     │\n"
        "│  ↳ confirms active trading       │\n"
        "│                                  │\n"
        "│  MIN BUYS          15 txns       │\n"
        "│  ↳ organic buy pressure          │\n"
        "│                                  │\n"
        "│  MAX TOKEN AGE     30 min        │\n"
        "│  ↳ only fresh launches           │\n"
        "│                                  │\n"
        "│  BUY SIZE          0.05 SOL      │\n"
        "│  MAX BUYS / HOUR   3             │\n"
        "│  PRIORITY FEE      0.005 SOL     │\n"
        "└──────────────────────────────────┘</code>\n\n"
        "💡 <b>Pro tip:</b> Lower score threshold = more buys, more risk.\n"
        "Higher threshold = fewer buys, higher quality signals."
    )
    kb = _kb(
        [("▶️  Next: Select Exit Preset", "tut:sniper:4")],
        [("⬅️  Back",                      "tut:sniper:2")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:sniper:4")
async def tut_sniper_4(callback: CallbackQuery) -> None:
    text = (
        f"<code>{_sniper_progress(4)}\n"
        "══════════════════════════════════\n"
        " ⭐  STEP 4 — CHOOSE EXIT PRESET\n"
        "══════════════════════════════════</code>\n\n"
        "An <b>Exit Preset</b> tells the bot exactly when to sell — "
        "take profit, cut losses, and protect gains automatically.\n\n"
        "<code>╔══════════════════════════════════╗\n"
        "║  ⚡ QUICK FLIP  ← RECOMMENDED    ║\n"
        "╠══════════════════════════════════╣\n"
        "║  TP1  +20%  → sell 60% of pos   ║\n"
        "║  TP2  +50%  → sell 25% of pos   ║\n"
        "║  TP3 +100%  → sell 10% of pos   ║\n"
        "║  MOON BAG   → keep 5% forever   ║\n"
        "║                                  ║\n"
        "║  STOP LOSS  -12%  (hard floor)   ║\n"
        "║  TRAILING   -8%   (after TP1)    ║\n"
        "║  BREAK-EVEN → after TP1 fires    ║\n"
        "║  MAX HOLD   → 8 minutes          ║\n"
        "╚══════════════════════════════════╝</code>\n\n"
        "🔑 <b>Why Quick Flip works:</b> Taking 60% at TP1 means once "
        "TP1 fires, you're already in profit — even if the rest dumps to zero.\n\n"
        "Navigate to <b>⬛ SUPREME → 📡 Positions & Config → ⭐ Select Exit Preset</b>\n"
        "and tap <b>⚡ Quick Flip</b> — this also activates auto-exit automatically."
    )
    kb = _kb(
        [("▶️  Next: Enable Auto-Buy",  "tut:sniper:5")],
        [("⬅️  Back",                    "tut:sniper:3")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:sniper:5")
async def tut_sniper_5(callback: CallbackQuery) -> None:
    text = (
        f"<code>{_sniper_progress(5)}\n"
        "══════════════════════════════════\n"
        " ⚡  STEP 5 — ACTIVATE THE SNIPER\n"
        "══════════════════════════════════</code>\n\n"
        "You're now ready to go live.\n\n"
        "<code>┌─ ACTIVATION CHECKLIST ──────────┐\n"
        "│  ✅  Bot wallet funded            │\n"
        "│  ✅  Filters configured           │\n"
        "│  ✅  Exit preset selected         │\n"
        "│  ⬜  Auto-Buy: OFF  ← tap to turn ON │\n"
        "└──────────────────────────────────┘</code>\n\n"
        "Navigate to <b>🎯 SNIPER TOOL</b> and tap:\n\n"
        "<code>  🔴 AUTO-BUY: OFF  →  press to activate</code>\n\n"
        "The button turns <b>🟢 AUTO-BUY: ON</b> and the sniper is live.\n\n"
        "⚡ The worker scans <b>every 6 seconds</b> for new launches that "
        "match your filters. When one passes — it buys automatically.\n\n"
        "<i>Let's simulate a signal firing right now...</i>"
    )
    kb = _kb(
        [("🟢  ACTIVATE AUTO-BUY (Simulate)", "tut:sniper:6")],
        [("⬅️  Back",                          "tut:sniper:4")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:sniper:6")
async def tut_sniper_6(callback: CallbackQuery) -> None:
    sym, name, addr = _fake_token()
    score = random.randint(47, 78)
    liq   = random.randint(6000, 25000)
    vol   = random.randint(2500, 12000)
    buys  = random.randint(18, 55)
    age   = random.randint(2, 18)
    sig   = _fake_sig()

    text = (
        f"<code>{_sniper_progress(6)}\n"
        "══════════════════════════════════\n"
        " 🤖  SIMULATED: SIGNAL DETECTED!\n"
        "══════════════════════════════════</code>\n\n"
        "⚡ <b>New token passed all filters — auto-buy fired!</b>\n\n"
        "<code>╔══════════════════════════════════╗\n"
        "║  🤖  AUTO-BUY EXECUTED!          ║\n"
        "╠══════════════════════════════════╣\n"
        f"║  TOKEN    {sym:<24}║\n"
        f"║  NAME     {name[:24]:<24}║\n"
        f"║  CA       {addr[:12]}…{addr[-4:]}      ║\n"
        f"║  SCORE    {score}/100                  ║\n"
        f"║  LIQ      ${liq:,.0f} USD               ║\n"
        f"║  VOL/HR   ${vol:,.0f} USD               ║\n"
        f"║  BUYS     {buys} confirmed txns         ║\n"
        f"║  AGE      {age} min old                 ║\n"
        "╠══════════════════════════════════╣\n"
        "║  BOUGHT    0.05 SOL              ║\n"
        "║  PRIORITY  0.005 SOL             ║\n"
        f"║  TX        {sig[:12]}…           ║\n"
        "║  STATUS    ✅ CONFIRMED          ║\n"
        "╚══════════════════════════════════╝</code>\n\n"
        "Your position is now <b>registered in Auto-Exit</b>.\n"
        "The watcher checks price <b>every 8 seconds</b>.\n\n"
        "<i>Let's fast-forward 4 minutes to see the exit fire...</i>"
    )
    kb = _kb(
        [("⏩  Fast Forward 4 min →", "tut:sniper:7")],
        [("⬅️  Back",                  "tut:sniper:5")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer("🤖 Auto-buy fired!")


@router.callback_query(F.data == "tut:sniper:7")
async def tut_sniper_7(callback: CallbackQuery) -> None:
    sym, name, addr = _fake_token()
    sym  = "PUMP"
    entry_price  = round(random.uniform(0.0000015, 0.0000045), 10)
    tp1_price    = round(entry_price * 1.22, 10)
    pnl_sol      = round(0.05 * 0.22 * 0.60, 6)   # 22% gain on 60% of 0.05 SOL
    pnl_pct      = 22.0
    sig          = _fake_sig()

    text = (
        f"<code>{_sniper_progress(7)}\n"
        "══════════════════════════════════\n"
        " 💸  SIMULATED: TP1 TRIGGERED!\n"
        "══════════════════════════════════</code>\n\n"
        "📈 <b>Price hit +20% — Take-Profit 1 fired!</b>\n\n"
        "<code>╔══════════════════════════════════╗\n"
        "║  ⚡  AUTO-EXIT  TP1  FIRED!       ║\n"
        "╠══════════════════════════════════╣\n"
        f"║  TOKEN      {sym:<22}║\n"
        f"║  ENTRY      {entry_price:.10f} SOL  ║\n"
        f"║  EXIT       {tp1_price:.10f} SOL  ║\n"
        f"║  GAIN       +{pnl_pct:.1f}%                   ║\n"
        "╠══════════════════════════════════╣\n"
        "║  SOLD       60% of position      ║\n"
        f"║  RETURNED   {0.05*0.60*1.22:.5f} SOL           ║\n"
        f"║  PROFIT     +{pnl_sol:.5f} SOL          ║\n"
        f"║  TX         {sig[:12]}…           ║\n"
        "║  STATUS     ✅ CONFIRMED          ║\n"
        "╠══════════════════════════════════╣\n"
        "║  REMAINING  40% still held       ║\n"
        "║  STOP-LOSS  → moved to BREAK-EVEN║\n"
        "║  TRAILING   → 8% trail active    ║\n"
        "╚══════════════════════════════════╝</code>\n\n"
        "✅ <b>You're already in profit.</b> Even if the remaining 40% "
        "drops to zero, this trade is a winner.\n\n"
        "The trailing stop will capture any further upside automatically."
    )
    kb = _kb(
        [("📊  See Final Result", "tut:sniper:8")],
        [("⬅️  Back",              "tut:sniper:6")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer("💸 TP1 fired!")


@router.callback_query(F.data == "tut:sniper:8")
async def tut_sniper_8(callback: CallbackQuery) -> None:
    # Generate full simulated trade summary
    entry   = round(random.uniform(0.0000015, 0.0000045), 10)
    tp1     = round(entry * 1.22, 10)
    tp2     = round(entry * 1.53, 10)
    spent   = 0.05
    ret_tp1 = spent * 0.60 * 1.22
    ret_tp2 = spent * 0.25 * 1.53
    ret_mb  = spent * 0.05              # moon bag (still held)
    total_returned = ret_tp1 + ret_tp2
    profit  = total_returned - spent + ret_mb
    pnl_pct = (profit / spent) * 100
    bar     = _pnl_bar(pnl_pct)

    text = (
        f"<code>{_sniper_progress(8)}\n"
        "══════════════════════════════════\n"
        " 🏆  TRADE COMPLETE — FINAL RESULT\n"
        "══════════════════════════════════</code>\n\n"
        "<code>╔══════════════════════════════════╗\n"
        "║  📊  SNIPER TRADE SUMMARY        ║\n"
        "╠══════════════════════════════════╣\n"
        f"║  ENTRY PRICE   {entry:.10f}   ║\n"
        f"║  INVESTED      0.05000 SOL       ║\n"
        "╠══════════════════════════════════╣\n"
        f"║  TP1  +22%  → {ret_tp1:.5f} SOL returned ║\n"
        f"║  TP2  +53%  → {ret_tp2:.5f} SOL returned ║\n"
        f"║  MOON BAG   → {ret_mb:.5f} SOL (held)    ║\n"
        "╠══════════════════════════════════╣\n"
        f"║  TOTAL OUT     {total_returned:.5f} SOL       ║\n"
        f"║  PROFIT        +{profit:.5f} SOL       ║\n"
        f"║  ROI           {bar} +{pnl_pct:.1f}%  ║\n"
        "╠══════════════════════════════════╣\n"
        "║  TIME IN TRADE   ~6 minutes      ║\n"
        "║  EXITS FIRED     TP1, TP2        ║\n"
        "║  MOON BAG        still tracking  ║\n"
        "╚══════════════════════════════════╝</code>\n\n"
        "🎓 <b>Tutorial complete!</b>\n\n"
        "You've seen the full Sniper cycle:\n"
        "  ✅  Wallet funded\n"
        "  ✅  Filters configured\n"
        "  ✅  Exit preset selected\n"
        "  ✅  Auto-buy activated\n"
        "  ✅  Signal detected & bought\n"
        "  ✅  TP1 + TP2 fired automatically\n"
        "  ✅  Profit locked, moon bag retained\n\n"
        "<b>Ready to do this for real?</b> Fund your wallet and hit the power button."
    )
    kb = _kb(
        [("🎯  Go to Sniper Tool",  "sniper:main")],
        [("📚  More Tutorials",     "tut:hub")],
        [("⬅️  Main Menu",          "menu:back")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer("🏆 Tutorial complete!")


# ══════════════════════════════════════════════════════════════════════════════
#  TUTORIAL 2 — COPY TRADE
# ══════════════════════════════════════════════════════════════════════════════

COPY_STEPS = 7

def _copy_progress(step: int) -> str:
    filled = "█" * step
    empty  = "░" * (COPY_STEPS - step)
    return f"[{filled}{empty}] Step {step}/{COPY_STEPS}"


@router.callback_query(F.data == "tut:copy:1")
async def tut_copy_1(callback: CallbackQuery) -> None:
    text = (
        f"<code>{_copy_progress(1)}\n"
        "══════════════════════════════════\n"
        " 📋  COPY TRADE TUTORIAL\n"
        "══════════════════════════════════</code>\n\n"
        "<b>What is Copy Trade?</b>\n\n"
        "Copy Trade <b>mirrors the exact buys and sells</b> of alpha wallets "
        "in real-time. When your target wallet buys a token — your bot buys "
        "the same token within milliseconds.\n\n"
        "<code>┌──────────────────────────────────┐\n"
        "│  Alpha wallet buys TOKEN_X        │\n"
        "│           ↓                        │\n"
        "│  Copy Trade detects the TX         │\n"
        "│           ↓                        │\n"
        "│  Your bot buys TOKEN_X instantly   │\n"
        "│           ↓                        │\n"
        "│  Alpha sells → your bot follows    │\n"
        "└──────────────────────────────────┘</code>\n\n"
        "💡 <b>Best use cases:</b>\n"
        "  • Mirror wallets with proven track records\n"
        "  • Front-run large wallet moves on new launches\n"
        "  • Copy sell signals from experienced traders\n\n"
        "<i>Step 1: Find a wallet worth copying.</i>"
    )
    kb = _kb(
        [("▶️  Next: Find Alpha Wallet",  "tut:copy:2")],
        [("⬅️  Back to Tutorials",        "tut:hub")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:copy:2")
async def tut_copy_2(callback: CallbackQuery) -> None:
    w1 = "9pLNvT7y" + "".join(random.choices("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz", k=28))
    text = (
        f"<code>{_copy_progress(2)}\n"
        "══════════════════════════════════\n"
        " 🔍  STEP 2 — ADD TARGET WALLET\n"
        "══════════════════════════════════</code>\n\n"
        "Navigate to <b>📋 COPY TRADE → ➕ Add Wallet</b>\n\n"
        "Paste the Solana wallet address of the trader you want to copy.\n\n"
        "<code>╔══════════════════════════════════╗\n"
        "║  ➕  ADD WALLET TO COPY           ║\n"
        "╠══════════════════════════════════╣\n"
        f"║  Address:                        ║\n"
        f"║  {w1[:32]}  ║\n"
        f"║  {w1[32:]}...       ║\n"
        "╠══════════════════════════════════╣\n"
        "║  Label:     Alpha Wallet #1      ║\n"
        "║  Min Trade: 0.1 SOL              ║\n"
        "║  Max Copy:  0.5 SOL              ║\n"
        "╚══════════════════════════════════╝</code>\n\n"
        "🔍 <b>How to find alpha wallets:</b>\n"
        "  1. Use <b>👁 Wallet Scout</b> to discover top traders\n"
        "  2. Check <a href='https://solscan.io'>solscan.io</a> for wallet PnL\n"
        "  3. Follow on-chain influencers — their wallets are often public\n"
        "  4. Look for wallets with >60% win rate on memecoins\n\n"
        "<b>Supreme Black:</b> Copy up to 500 wallets simultaneously."
    )
    kb = _kb(
        [("▶️  Next: Configure Settings", "tut:copy:3")],
        [("⬅️  Back",                      "tut:copy:1")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:copy:3")
async def tut_copy_3(callback: CallbackQuery) -> None:
    text = (
        f"<code>{_copy_progress(3)}\n"
        "══════════════════════════════════\n"
        " ⚙️  STEP 3 — COPY TRADE SETTINGS\n"
        "══════════════════════════════════</code>\n\n"
        "Navigate to <b>📋 COPY TRADE → ⚙️ Settings</b>\n\n"
        "<code>┌─ RECOMMENDED SETTINGS ──────────┐\n"
        "│                                  │\n"
        "│  COPY MODE      Fixed Amount     │\n"
        "│  BUY AMOUNT     0.05 SOL         │\n"
        "│  ↳ same size every time          │\n"
        "│                                  │\n"
        "│  MAX BUY CAP    0.5 SOL          │\n"
        "│  ↳ never exceeds this            │\n"
        "│                                  │\n"
        "│  COPY BUYS      ✅ ON            │\n"
        "│  COPY SELLS     ✅ ON            │\n"
        "│  ↳ exit when leader exits        │\n"
        "│                                  │\n"
        "│  SLIPPAGE       15%              │\n"
        "│  PRIORITY FEE   0.005 SOL        │\n"
        "│  COOLDOWN       30s              │\n"
        "│  MAX / HOUR     30 trades        │\n"
        "└──────────────────────────────────┘</code>\n\n"
        "⚡ <b>Percentage Mode</b> (Supreme only):\n"
        "  Copies the exact % of the leader's position size.\n"
        "  If they buy 10 SOL, you buy 10% = 1 SOL."
    )
    kb = _kb(
        [("▶️  Next: Enable Copy Trade", "tut:copy:4")],
        [("⬅️  Back",                     "tut:copy:2")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:copy:4")
async def tut_copy_4(callback: CallbackQuery) -> None:
    text = (
        f"<code>{_copy_progress(4)}\n"
        "══════════════════════════════════\n"
        " ⚡  STEP 4 — GO LIVE\n"
        "══════════════════════════════════</code>\n\n"
        "Navigate to <b>📋 COPY TRADE</b> and tap the power button.\n\n"
        "<code>┌─ ACTIVATION CHECKLIST ──────────┐\n"
        "│  ✅  Wallet funded                │\n"
        "│  ✅  Target wallet added          │\n"
        "│  ✅  Settings configured          │\n"
        "│  ⬜  Copy Trade: OFF  ← tap ON    │\n"
        "└──────────────────────────────────┘</code>\n\n"
        "The system now monitors your target wallet <b>every few seconds</b>.\n\n"
        "<code>🔍  MONITORING:  Alpha Wallet #1\n"
        "📡  STATUS:     ACTIVE — watching for trades\n"
        "⏱️  LAST CHECK:  0.4s ago</code>\n\n"
        "<i>Let's simulate the target wallet making a move...</i>"
    )
    kb = _kb(
        [("🔴  ENABLE COPY TRADE (Simulate)", "tut:copy:5")],
        [("⬅️  Back",                          "tut:copy:3")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:copy:5")
async def tut_copy_5(callback: CallbackQuery) -> None:
    sym, name, addr = _fake_token()
    leader_sol = round(random.uniform(0.8, 5.0), 3)
    copy_sol   = 0.05
    sig        = _fake_sig()
    leader_w   = _fake_wallet()

    text = (
        f"<code>{_copy_progress(5)}\n"
        "══════════════════════════════════\n"
        " 📡  SIMULATED: LEADER TRADE!\n"
        "══════════════════════════════════</code>\n\n"
        "🚨 <b>Alpha wallet just bought — your bot mirrors it instantly!</b>\n\n"
        "<code>╔══════════════════════════════════╗\n"
        "║  📋  COPY TRADE EXECUTED!        ║\n"
        "╠══════════════════════════════════╣\n"
        f"║  LEADER    {leader_w:<22}║\n"
        f"║  BOUGHT    {sym:<22}  ║\n"
        f"║  NAME      {name[:22]:<22}║\n"
        f"║  CA        {addr[:12]}…{addr[-4:]}      ║\n"
        "╠══════════════════════════════════╣\n"
        f"║  LEADER SIZE   {leader_sol:.3f} SOL            ║\n"
        f"║  YOUR COPY     {copy_sol:.3f} SOL            ║\n"
        "║  MODE          Fixed Amount      ║\n"
        f"║  TX            {sig[:12]}…       ║\n"
        "║  STATUS        ✅ CONFIRMED      ║\n"
        "╚══════════════════════════════════╝</code>\n\n"
        "⚡ <b>Delay from leader:</b> ~1.2 seconds\n"
        "You're now holding the same token as the alpha wallet.\n\n"
        "<i>Now let's watch the leader sell and see our profit...</i>"
    )
    kb = _kb(
        [("⏩  Leader Sells — See Profit →", "tut:copy:6")],
        [("⬅️  Back",                         "tut:copy:4")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer("📋 Copy executed!")


@router.callback_query(F.data == "tut:copy:6")
async def tut_copy_6(callback: CallbackQuery) -> None:
    sym, _, _ = _fake_token()
    sym       = "MOON"
    gain_pct  = round(random.uniform(28, 85), 1)
    invested  = 0.05
    returned  = round(invested * (1 + gain_pct / 100), 5)
    profit    = round(returned - invested, 5)
    bar       = _pnl_bar(gain_pct)
    sig       = _fake_sig()

    text = (
        f"<code>{_copy_progress(6)}\n"
        "══════════════════════════════════\n"
        " 💸  SIMULATED: LEADER SOLD!\n"
        "══════════════════════════════════</code>\n\n"
        "🎯 <b>Alpha wallet just sold — your bot exits the same position!</b>\n\n"
        "<code>╔══════════════════════════════════╗\n"
        "║  📋  COPY SELL EXECUTED!         ║\n"
        "╠══════════════════════════════════╣\n"
        f"║  TOKEN      {sym:<22}║\n"
        f"║  SOLD       100% of position    ║\n"
        f"║  GAIN       +{gain_pct:.1f}%                  ║\n"
        "╠══════════════════════════════════╣\n"
        f"║  INVESTED   {invested:.5f} SOL           ║\n"
        f"║  RETURNED   {returned:.5f} SOL           ║\n"
        f"║  PROFIT     +{profit:.5f} SOL          ║\n"
        f"║  ROI        {bar} +{gain_pct:.1f}%  ║\n"
        f"║  TX         {sig[:12]}…           ║\n"
        "║  STATUS     ✅ CONFIRMED          ║\n"
        "╚══════════════════════════════════╝</code>\n\n"
        f"🏆 <b>+{profit:.5f} SOL in one copy trade.</b>\n\n"
        "The bot sold within <b>~1.4 seconds</b> of the leader.\n"
        "No manual action required."
    )
    kb = _kb(
        [("📊  See Tutorial Summary", "tut:copy:7")],
        [("⬅️  Back",                  "tut:copy:5")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer("💸 Sell mirrored!")


@router.callback_query(F.data == "tut:copy:7")
async def tut_copy_7(callback: CallbackQuery) -> None:
    text = (
        f"<code>{_copy_progress(7)}\n"
        "══════════════════════════════════\n"
        " 🏆  COPY TRADE TUTORIAL COMPLETE\n"
        "══════════════════════════════════</code>\n\n"
        "<code>╔══════════════════════════════════╗\n"
        "║  📊  SESSION SUMMARY             ║\n"
        "╠══════════════════════════════════╣\n"
        "║  Trades copied       1           ║\n"
        "║  Capital deployed    0.05 SOL    ║\n"
        "║  Profit generated    +0.04 SOL   ║\n"
        "║  Win rate (sim)      100%        ║\n"
        "║  Time in market      ~8 min      ║\n"
        "╠══════════════════════════════════╣\n"
        "║  Wallets tracked     1           ║\n"
        "║  Reaction time       ~1.2s       ║\n"
        "╚══════════════════════════════════╝</code>\n\n"
        "🎓 <b>Tutorial complete!</b>\n\n"
        "  ✅  Added target wallet\n"
        "  ✅  Configured copy settings\n"
        "  ✅  Enabled copy trade\n"
        "  ✅  Mirrored a buy in real-time\n"
        "  ✅  Auto-sold when leader exited\n"
        "  ✅  Profit locked\n\n"
        "💡 <b>Pro tip:</b> Copy sells is what separates winners from losers. "
        "Enable it — the exit is as important as the entry."
    )
    kb = _kb(
        [("📋  Go to Copy Trade",  "ct:main")],
        [("📚  More Tutorials",    "tut:hub")],
        [("⬅️  Main Menu",         "menu:back")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer("🏆 Tutorial complete!")


# ══════════════════════════════════════════════════════════════════════════════
#  TUTORIAL 3 — CANDLE SNIPER
# ══════════════════════════════════════════════════════════════════════════════

CANDLE_STEPS = 7

def _candle_progress(step: int) -> str:
    filled = "█" * step
    empty  = "░" * (CANDLE_STEPS - step)
    return f"[{filled}{empty}] Step {step}/{CANDLE_STEPS}"


@router.callback_query(F.data == "tut:candle:1")
async def tut_candle_1(callback: CallbackQuery) -> None:
    text = (
        f"<code>{_candle_progress(1)}\n"
        "══════════════════════════════════\n"
        " 🕯️  CANDLE SNIPER TUTORIAL\n"
        "══════════════════════════════════</code>\n\n"
        "<b>What is the Candle Sniper?</b>\n\n"
        "The Candle Sniper analyzes <b>candlestick patterns and price surges</b> "
        "across Solana tokens and enters trades when specific chart "
        "setups are detected — without you reading a single chart.\n\n"
        "<code>┌──────────────────────────────────┐\n"
        "│  Token scanning (every 30s)       │\n"
        "│           ↓                        │\n"
        "│  Pattern detection engine          │\n"
        "│  ↳ Breakout, Surge, Volume Spike   │\n"
        "│           ↓                        │\n"
        "│  Confidence score calculated       │\n"
        "│           ↓                        │\n"
        "│  Auto-buy if score ≥ threshold     │\n"
        "│           ↓                        │\n"
        "│  TP / SL / Trailing stop exits     │\n"
        "└──────────────────────────────────┘</code>\n\n"
        "📊 <b>Strategies available:</b>\n"
        "  • <b>Balanced</b>  — moderate signals, good for most users\n"
        "  • <b>Aggressive</b> — more entries, higher risk/reward\n"
        "  • <b>Conservative</b> — fewer entries, tighter filters"
    )
    kb = _kb(
        [("▶️  Next: Configure Strategy",  "tut:candle:2")],
        [("⬅️  Back to Tutorials",         "tut:hub")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:candle:2")
async def tut_candle_2(callback: CallbackQuery) -> None:
    text = (
        f"<code>{_candle_progress(2)}\n"
        "══════════════════════════════════\n"
        " 📊  STEP 2 — STRATEGY PROFILE\n"
        "══════════════════════════════════</code>\n\n"
        "Navigate to <b>🕯️ Candle Sniper → ⚙️ Settings → Strategy</b>\n\n"
        "<code>┌─ STRATEGY COMPARISON ──────────────┐\n"
        "│                                     │\n"
        "│  AGGRESSIVE                         │\n"
        "│  ↳ 40%+ confidence threshold        │\n"
        "│  ↳ 2+ pattern confirmations         │\n"
        "│  ↳ More trades, higher volatility   │\n"
        "│                                     │\n"
        "│  ✅ BALANCED  ← RECOMMENDED         │\n"
        "│  ↳ 45%+ confidence threshold        │\n"
        "│  ↳ 3+ pattern confirmations         │\n"
        "│  ↳ Quality over quantity            │\n"
        "│                                     │\n"
        "│  CONSERVATIVE                       │\n"
        "│  ↳ 60%+ confidence threshold        │\n"
        "│  ↳ 5+ confirmations required        │\n"
        "│  ↳ Fewer trades, lower risk         │\n"
        "│                                     │\n"
        "└─────────────────────────────────────┘\n"
        "\n"
        "┌─ TRADE SETTINGS ────────────────────┐\n"
        "│  TRADE SIZE         0.05 SOL        │\n"
        "│  STOP LOSS          -15%            │\n"
        "│  TAKE PROFIT        +50%            │\n"
        "│  TRAILING STOP      10%             │\n"
        "│  MAX OPEN POS       5               │\n"
        "│  COOLDOWN           5 min           │\n"
        "└─────────────────────────────────────┘</code>"
    )
    kb = _kb(
        [("▶️  Next: Surge Detector",  "tut:candle:3")],
        [("⬅️  Back",                   "tut:candle:1")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:candle:3")
async def tut_candle_3(callback: CallbackQuery) -> None:
    text = (
        f"<code>{_candle_progress(3)}\n"
        "══════════════════════════════════\n"
        " 🚀  STEP 3 — SURGE DETECTOR\n"
        "══════════════════════════════════</code>\n\n"
        "The <b>Surge Detector</b> is a separate layer that watches for "
        "explosive price moves — tokens surging 500%+ in a single scan window.\n\n"
        "<code>╔══════════════════════════════════╗\n"
        "║  🚀  SURGE DETECTOR              ║\n"
        "╠══════════════════════════════════╣\n"
        "║  Surge Threshold   500%+ gain    ║\n"
        "║  Track Window      24 hours      ║\n"
        "║  Action            Alert + Buy   ║\n"
        "╚══════════════════════════════════╝</code>\n\n"
        "💡 Surge entries are <b>high risk / high reward</b> — the token is "
        "already pumping hard. Use a tight trailing stop (8–10%) to "
        "protect the entry.\n\n"
        "Navigate to <b>🕯️ Candle Sniper → 🚀 Surge Detector</b> and toggle it on.\n\n"
        "<code>  Surge Detector:  🔴 OFF  →  🟢 ON</code>\n\n"
        "<i>Now let's activate the Candle Sniper and watch a pattern fire.</i>"
    )
    kb = _kb(
        [("▶️  Next: Activate Candle Sniper", "tut:candle:4")],
        [("⬅️  Back",                          "tut:candle:2")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:candle:4")
async def tut_candle_4(callback: CallbackQuery) -> None:
    text = (
        f"<code>{_candle_progress(4)}\n"
        "══════════════════════════════════\n"
        " ⚡  STEP 4 — GO LIVE\n"
        "══════════════════════════════════</code>\n\n"
        "Navigate to <b>🕯️ Candle Sniper</b> and tap the power button.\n\n"
        "<code>┌─ ACTIVATION CHECKLIST ──────────┐\n"
        "│  ✅  Wallet funded                │\n"
        "│  ✅  Strategy profile set         │\n"
        "│  ✅  Surge detector configured    │\n"
        "│  ⬜  Auto-Buy: OFF  ← tap ON      │\n"
        "└──────────────────────────────────┘</code>\n\n"
        "When enabled, Candle Sniper <b>temporarily overrides</b> your main "
        "sniper settings. Your previous settings are auto-restored when you disable it.\n\n"
        "<code>⚙️  CS MODE ACTIVE\n"
        "📊  Scanning 50 tokens every 30 seconds\n"
        "🎯  Looking for breakout + surge patterns</code>\n\n"
        "<i>Let's simulate a pattern being detected right now...</i>"
    )
    kb = _kb(
        [("🟢  ENABLE CANDLE SNIPER (Simulate)", "tut:candle:5")],
        [("⬅️  Back",                             "tut:candle:3")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "tut:candle:5")
async def tut_candle_5(callback: CallbackQuery) -> None:
    sym, name, addr = _fake_token()
    confidence  = random.randint(62, 89)
    vol_change  = random.randint(340, 890)
    liq         = random.randint(8000, 40000)
    patterns    = random.choice([
        "Bullish Engulfing + Volume Spike",
        "Three White Soldiers + Breakout",
        "Morning Star + Momentum Surge",
        "Hammer + Volume Confirmation",
    ])
    sig = _fake_sig()

    text = (
        f"<code>{_candle_progress(5)}\n"
        "══════════════════════════════════\n"
        " 📊  SIMULATED: PATTERN DETECTED!\n"
        "══════════════════════════════════</code>\n\n"
        "🕯️ <b>High-confidence candlestick pattern — auto-buy fired!</b>\n\n"
        "<code>╔══════════════════════════════════╗\n"
        "║  🕯️  CANDLE SNIPER ENTRY!        ║\n"
        "╠══════════════════════════════════╣\n"
        f"║  TOKEN      {sym:<22}║\n"
        f"║  NAME       {name[:22]:<22}║\n"
        f"║  CA         {addr[:12]}…{addr[-4:]}      ║\n"
        "╠══════════════════════════════════╣\n"
        f"║  PATTERN    {patterns[:30]:<30}║\n"
        f"║  CONFIDENCE {confidence}% (threshold 45%)      ║\n"
        f"║  VOL CHANGE +{vol_change}% vs prev candle      ║\n"
        f"║  LIQUIDITY  ${liq:,.0f} USD              ║\n"
        "╠══════════════════════════════════╣\n"
        "║  BOUGHT     0.05 SOL             ║\n"
        "║  STRATEGY   Balanced             ║\n"
        f"║  TX         {sig[:12]}…          ║\n"
        "║  STATUS     ✅ CONFIRMED         ║\n"
        "╚══════════════════════════════════╝</code>\n\n"
        "Stop-loss and take-profit are now active on this position.\n"
        "<i>Let's see how the exit plays out...</i>"
    )
    kb = _kb(
        [("⏩  Fast Forward — See Exit →", "tut:candle:6")],
        [("⬅️  Back",                       "tut:candle:4")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer("📊 Pattern detected!")


@router.callback_query(F.data == "tut:candle:6")
async def tut_candle_6(callback: CallbackQuery) -> None:
    sym     = "CHAD"
    gain    = round(random.uniform(35, 75), 1)
    invested= 0.05
    returned= round(invested * (1 + gain / 100), 5)
    profit  = round(returned - invested, 5)
    bar     = _pnl_bar(gain)
    method  = random.choice(["Take-Profit at 50%", "Trailing Stop -10%", "Take-Profit at 50%"])
    sig     = _fake_sig()

    text = (
        f"<code>{_candle_progress(6)}\n"
        "══════════════════════════════════\n"
        " 💸  SIMULATED: EXIT TRIGGERED!\n"
        "══════════════════════════════════</code>\n\n"
        f"📈 <b>{method} — position closed!</b>\n\n"
        "<code>╔══════════════════════════════════╗\n"
        "║  🕯️  CANDLE SNIPER EXIT!         ║\n"
        "╠══════════════════════════════════╣\n"
        f"║  TOKEN      {sym:<22}║\n"
        f"║  EXIT TYPE  {method[:22]:<22}║\n"
        f"║  GAIN       +{gain:.1f}%                   ║\n"
        "╠══════════════════════════════════╣\n"
        f"║  INVESTED   {invested:.5f} SOL           ║\n"
        f"║  RETURNED   {returned:.5f} SOL           ║\n"
        f"║  PROFIT     +{profit:.5f} SOL          ║\n"
        f"║  ROI        {bar} +{gain:.1f}%  ║\n"
        f"║  TX         {sig[:12]}…           ║\n"
        "║  STATUS     ✅ CONFIRMED          ║\n"
        "╚══════════════════════════════════╝</code>\n\n"
        f"🏆 <b>+{profit:.5f} SOL locked.</b>\n"
        "No chart reading. No manual exits. Pure automation."
    )
    kb = _kb(
        [("📊  Tutorial Summary", "tut:candle:7")],
        [("⬅️  Back",              "tut:candle:5")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer("💸 Exit fired!")


@router.callback_query(F.data == "tut:candle:7")
async def tut_candle_7(callback: CallbackQuery) -> None:
    text = (
        f"<code>{_candle_progress(7)}\n"
        "══════════════════════════════════\n"
        " 🏆  CANDLE SNIPER — COMPLETE!\n"
        "══════════════════════════════════</code>\n\n"
        "<code>╔══════════════════════════════════╗\n"
        "║  📊  SESSION SUMMARY             ║\n"
        "╠══════════════════════════════════╣\n"
        "║  Patterns scanned     ~200       ║\n"
        "║  Qualifying signals   1          ║\n"
        "║  Trades executed      1          ║\n"
        "║  Win rate (sim)       100%       ║\n"
        "║  Capital deployed     0.05 SOL   ║\n"
        "║  Profit generated     +0.03 SOL  ║\n"
        "╠══════════════════════════════════╣\n"
        "║  Patterns detected    Breakout   ║\n"
        "║  Confidence           74%        ║\n"
        "║  Exit method          Take-Profit║\n"
        "╚══════════════════════════════════╝</code>\n\n"
        "🎓 <b>Tutorial complete!</b>\n\n"
        "  ✅  Strategy profile configured\n"
        "  ✅  Surge detector activated\n"
        "  ✅  Candle Sniper enabled\n"
        "  ✅  Pattern detected automatically\n"
        "  ✅  Entry executed instantly\n"
        "  ✅  Profit exit fired without intervention\n\n"
        "💡 <b>Pro tip:</b> Run Candle Sniper alongside the regular Sniper — "
        "they use different detection engines and don't interfere."
    )
    kb = _kb(
        [("🕯️  Go to Candle Sniper",  "cs:main")],
        [("📚  More Tutorials",        "tut:hub")],
        [("⬅️  Main Menu",             "menu:back")],
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer("🏆 Tutorial complete!")
