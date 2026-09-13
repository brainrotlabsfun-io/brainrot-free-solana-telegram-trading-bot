"""
bot/handlers/profile.py
========================
Profile and Badges pages.

Callbacks:
  profile:main   — full user profile summary
  profile:badges — all earned badges + next-badge progress
"""

import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.keyboards.profile_menu import build_profile_menu, build_badges_menu
from services.badge_service import get_user_badges, get_next_badge_progress
from services.burn_activation_service import get_burn_stats, get_activation_status
from services.brainrot_token_gate import is_supreme_holder, is_supreme_black
from services.burn_title_service import get_burn_title, format_title_display

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "profile:main")
async def cb_profile_main(callback: CallbackQuery) -> None:
    user_id  = callback.from_user.id
    user     = callback.from_user
    is_sup   = await is_supreme_holder(user_id)
    is_black = await is_supreme_black(user_id)
    stats    = await get_burn_stats(user_id)
    status   = await get_activation_status(user_id)
    badges   = await get_user_badges(user_id)
    top      = badges[0] if badges else None

    if is_black:
        tier_line = "⬛ SUPREME BLACK"
    elif is_sup:
        tier_line = "🔱 SUPREME"
    else:
        tier_line = "🆓 FREE"

    # Only show burn title for FREE users — for SUPREME/BLACK the tier IS the title
    title_data = get_burn_title(stats["total_burned"])
    if not is_sup and not is_black and title_data["title"] not in ("SUPREME", "SUPREME BLACK"):
        burn_title_line = f"\n<b>Burn Title:</b>  {title_data['emoji']} {title_data['title']}"
        if title_data["next_title"]:
            burn_title_line += f"\n<b>Next Title:</b>  {title_data['next_emoji']} {title_data['next_title']} — {title_data['remaining']:,.0f} more"
    else:
        burn_title_line = ""

    wallet      = status.get("wallet_address") or "—"
    short_w     = wallet[:6] + "..." + wallet[-4:] if len(wallet) > 10 else wallet
    badge_line  = f"{top['icon']} {top['badge_name']}" if top else "None yet"

    act_tx   = status.get("activation_tx") or "—"
    short_tx = act_tx[:10] + "..." if len(act_tx) > 10 else act_tx

    act_date = "—"
    if status.get("activated_at"):
        try:
            act_date = datetime.fromisoformat(str(status["activated_at"]).replace(" ", "T")).strftime("%Y-%m-%d")
        except ValueError:
            act_date = status["activated_at"][:10]

    expires = ""
    if is_sup and status.get("expires_at"):
        try:
            exp = datetime.fromisoformat(str(status["expires_at"]).replace(" ", "T")).strftime("%Y-%m-%d")
            expires = f"  ⏳ expires {exp}"
        except ValueError:
            pass

    text = (
        f"👤 <b>My Profile</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Username:</b>     @{user.username or user.first_name}\n"
        f"<b>Tier:</b>         {tier_line}{expires}"
        f"{burn_title_line}\n\n"
        f"<b>Wallet:</b>       <code>{short_w}</code>\n"
        f"<b>Badge:</b>        {badge_line}\n\n"
        f"<b>Total Burned:</b> {stats['total_burned']:,.0f} $BRAINROT\n"
        f"<b>Burn Count:</b>   {stats['burn_count']}\n"
        f"<b>Activated:</b>    {act_date}\n"
    )

    await callback.message.edit_text(text, reply_markup=build_profile_menu())
    await callback.answer()


@router.callback_query(F.data == "profile:badges")
async def cb_profile_badges(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    badges  = await get_user_badges(user_id)
    stats   = await get_burn_stats(user_id)
    next_b  = await get_next_badge_progress(user_id, stats["total_burned"])

    if not badges:
        badges_block = "<i>No badges earned yet. Burn $BRAINROT to earn your first badge!</i>\n"
    else:
        lines = []
        for b in badges:
            date = (b["awarded_at"] or "")[:10]
            lines.append(
                f"{b['icon']} <b>{b['badge_name']}</b>\n"
                f"   <i>{b['description']}</i>\n"
                f"   Awarded: {date}"
            )
        badges_block = "\n\n".join(lines) + "\n"

    top = badges[0] if badges else None
    top_line = (
        f"🏅 <b>Highest Badge:</b> {top['icon']} {top['badge_name']}\n"
        if top else "🏅 <b>Highest Badge:</b> None\n"
    )

    progress_block = ""
    if next_b:
        bar_filled = int(next_b["progress_pct"] / 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        progress_block = (
            f"\n<b>Next Badge:</b> {next_b['icon']} {next_b['badge_name']}\n"
            f"[{bar}] {next_b['progress_pct']}%\n"
            f"{next_b['current']:,.0f} / {next_b['threshold']:,.0f} $BRAINROT\n"
            f"({next_b['remaining']:,.0f} remaining)\n"
        )

    text = (
        f"🏅 <b>My Badges</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{top_line}"
        f"<b>Total Burned:</b> {stats['total_burned']:,.0f} $BRAINROT\n\n"
        f"{badges_block}"
        f"{progress_block}"
    )

    await callback.message.edit_text(text, reply_markup=build_badges_menu())
    await callback.answer()
