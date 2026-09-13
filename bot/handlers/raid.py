"""
bot/handlers/raid.py
====================
All Raid Center handlers:
  - Inline button callbacks for the Raid Center UI
  - Admin commands: /create_raid, /end_raid, /raids
  - FSM flow for admin raid creation
"""

import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from utils.states import CreateRaidForm

from bot.keyboards.raid_menu import (
    build_raid_menu,
    build_raid_action_menu,
    build_back_to_raid_menu,
)
from services.raid_service import (
    get_active_raid,
    get_all_raids_summary,
    has_user_completed_raid,
    mark_raid_completed,
    end_active_raids,
    create_raid,
    get_raid_participant_count,
)
from services.raid_points_service import get_leaderboard, get_user_stats
from utils.config import settings

router = Router()
logger = logging.getLogger(__name__)


# ── Helper ─────────────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in settings.ADMIN_IDS


def _format_raid_text(raid: dict) -> str:
    """Formats a raid dict into a clean display string."""
    expires = raid.get("expires_at", "No expiry set")
    if expires and expires != "No expiry set":
        try:
            dt = datetime.fromisoformat(str(expires))
            expires = dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            pass

    return (
        f"⚔️ <b>{raid['title']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🌐 <b>Platform:</b> {raid['platform']}\n"
        f"🔗 <b>Target:</b> {raid['target_url']}\n\n"
        f"📋 <b>Instructions:</b>\n{raid['instructions']}\n\n"
        f"🎯 <b>Reward:</b> {raid['reward_points']} points\n"
        f"⏰ <b>Expires:</b> {expires}\n\n"
        f"<i>Complete all tasks, then press Mark Completed.</i>"
    )


# CreateRaidForm is defined in utils/states.py and imported above.

# ══════════════════════════════════════════════════════════════════════════════
# INLINE BUTTON CALLBACKS
# ══════════════════════════════════════════════════════════════════════════════

# ── Raid Center Main Menu ──────────────────────────────────────────────────────
@router.callback_query(F.data == "raid:main")
async def cb_raid_main(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        text=(
            "⚔️ <b>RAID CENTER</b>\n"
            "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
            "Raids are coordinated community actions — everyone hits\n"
            "the same target at the same time. Like a flash mob, but\n"
            "for crypto. The more people that raid, the louder the\n"
            "signal, and the more attention the token gets.\n\n"
            "<b>Why does this have value?</b>\n"
            "Attention = volume. Volume = price action.\n"
            "When a community raids a token together — likes, comments,\n"
            "reposts, buys — it creates real on-chain activity that\n"
            "algorithms and traders notice. You're not just clicking\n"
            "a button, you're moving a market.\n\n"
            "<b>How it works:</b>\n"
            "<code>1.</code> Admin posts a raid target (token, tweet, chart)\n"
            "<code>2.</code> You complete the tasks (like, repost, comment, buy)\n"
            "<code>3.</code> Hit ✅ Mark Completed to claim your points\n"
            "<code>4.</code> Points stack on the leaderboard — top raiders\n"
            "   earn status, rewards, and recognition\n\n"
            "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n"
            "<i>Powered by $BRAINROT. Raids are live — tap below.</i>"
        ),
        reply_markup=build_raid_menu(),
    )
    await callback.answer()


# ── Active Raid ────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "raid:active")
async def cb_raid_active(callback: CallbackQuery) -> None:
    raid = await get_active_raid()

    if not raid:
        await callback.message.edit_text(
            text=(
                "⚔️ <b>Active Raid</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "No active raid right now.\n"
                "Check back soon — new raids are announced regularly.\n\n"
                "<i>Admins use /create_raid to launch a new raid.</i>"
            ),
            reply_markup=build_back_to_raid_menu(),
        )
        await callback.answer()
        return

    user_id = callback.from_user.id
    already_done = await has_user_completed_raid(user_id, raid["id"])
    count = await get_raid_participant_count(raid["id"])

    text = _format_raid_text(raid)
    text += f"\n👥 <b>Participants so far:</b> {count}"

    if already_done:
        text += "\n\n✅ <b>You have already completed this raid.</b>"
        await callback.message.edit_text(
            text=text,
            reply_markup=build_back_to_raid_menu(),
            disable_web_page_preview=True,
        )
    else:
        await callback.message.edit_text(
            text=text,
            reply_markup=build_raid_action_menu(raid["id"], raid["target_url"]),
            disable_web_page_preview=True,
        )
    await callback.answer()


# ── Mark Raid Completed ────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("raid:complete:"))
async def cb_raid_complete(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name or f"User{user_id}"

    try:
        raid_id = int(callback.data.split(":")[-1])
    except (ValueError, IndexError):
        await callback.answer("Invalid raid. Please try again.", show_alert=True)
        return

    # Verify the raid is still active
    raid = await get_active_raid()
    if not raid or raid["id"] != raid_id:
        await callback.answer("This raid is no longer active.", show_alert=True)
        return

    # Guard against duplicate completion (already handled by DB UNIQUE, but check first)
    already_done = await has_user_completed_raid(user_id, raid_id)
    if already_done:
        await callback.answer("You already completed this raid!", show_alert=True)
        return

    # Calculate points
    base_points = raid["reward_points"]
    points = base_points

    success = await mark_raid_completed(raid_id, user_id, username, points)

    if not success:
        await callback.answer("Already completed — no double dipping!", show_alert=True)
        return


    await callback.message.edit_text(
        text=(
            f"✅ <b>Raid Completed!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"You earned <b>{points} points</b>."
            f"\n\n"
            f"Keep raiding to climb the leaderboard!\n"
            f"Use My Raid Stats to check your rank."
        ),
        reply_markup=build_back_to_raid_menu(),
    )
    await callback.answer("Raid marked as completed!")


# ── Leaderboard ────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "raid:leaderboard")
async def cb_raid_leaderboard(callback: CallbackQuery) -> None:
    entries = await get_leaderboard(limit=10)

    if not entries:
        text = (
            "🏆 <b>Raid Leaderboard</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No points recorded yet.\n"
            "Complete the active raid to be the first on the board!"
        )
    else:
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        rows = []
        for entry in entries:
            rank = entry["rank"]
            medal = medals.get(rank, f"{rank}.")
            name = entry["username"]
            pts = entry["total_points"]
            rows.append(f"{medal} <b>{name}</b> — {pts} pts")

        text = (
            "🏆 <b>Raid Leaderboard</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            + "\n".join(rows)
            + "\n\n<i>Top 10 — updated in real time.</i>"
        )

    await callback.message.edit_text(
        text=text,
        reply_markup=build_back_to_raid_menu(),
    )
    await callback.answer()


# ── My Raid Stats ──────────────────────────────────────────────────────────────
@router.callback_query(F.data == "raid:stats")
async def cb_raid_stats(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name or f"User{user_id}"

    stats = await get_user_stats(user_id, username)

    rank_text = f"#{stats['rank']}" if stats["rank"] is not None else "Unranked"

    text = (
        f"📊 <b>My Raid Stats</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>Username:</b> {username}\n"
        f"⚔️ <b>Raids Completed:</b> {stats['raids_completed']}\n"
        f"🎯 <b>Total Points:</b> {stats['total_points']}\n"
        f"🏆 <b>Leaderboard Rank:</b> {rank_text}\n\n"
        f"<i>Complete more raids to earn points and climb the board!</i>"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=build_back_to_raid_menu(),
    )
    await callback.answer()


# ── Raid Rules ─────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "raid:rules")
async def cb_raid_rules(callback: CallbackQuery) -> None:
    text = (
        "📋 <b>Raid Rules</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "1. Complete all listed tasks <b>manually</b>.\n"
        "   The bot does not post on your behalf.\n\n"
        "2. Only press <b>Mark Completed</b> after genuinely finishing all tasks.\n\n"
        "3. <b>No spam</b>. Write real comments.\n"
        "   Low-quality or copy-paste comments don't count.\n\n"
        "4. <b>Respect platform rules</b>.\n"
        "   Do not violate Twitter/X, Instagram, or other platform ToS.\n\n"
        "5. <b>One completion per raid per user.</b>\n"
        "   Duplicate submissions are blocked automatically.\n\n"
        "6. Abuse or faking completions results in point removal.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Real engagement only. Build the community right.</i>"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=build_back_to_raid_menu(),
    )
    await callback.answer()


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

# ── /raids — List all raids ────────────────────────────────────────────────────
@router.message(Command("raids"))
async def cmd_raids(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("This command is for admins only.")
        return

    raids = await get_all_raids_summary()

    if not raids:
        await message.answer("No raids have been created yet.")
        return

    lines = ["<b>All Raids:</b>\n"]
    for r in raids:
        status = "✅ Active" if r["active"] else "🔴 Ended"
        lines.append(
            f"<b>#{r['id']}</b> — {r['title']}\n"
            f"  Platform: {r['platform']} | {r['reward_points']} pts | {status}\n"
            f"  Created: {r['created_at']}\n"
        )

    await message.answer("\n".join(lines))


# ── /end_raid — End all active raids ──────────────────────────────────────────
@router.message(Command("end_raid"))
async def cmd_end_raid(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("This command is for admins only.")
        return

    count = await end_active_raids()

    if count == 0:
        await message.answer("No active raids to end.")
    else:
        await message.answer(f"✅ Ended {count} active raid(s).")


# ── /create_raid — Start FSM to create a new raid ─────────────────────────────
@router.message(Command("create_raid"))
async def cmd_create_raid(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("This command is for admins only.")
        return

    await state.set_state(CreateRaidForm.title)
    await message.answer(
        "⚔️ <b>Create New Raid</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Step 1/6\n\n"
        "Enter the <b>raid title</b>:\n"
        "<i>Example: Twitter Raid — Promote $BRAINROT</i>\n\n"
        "Send /cancel to abort."
    )


@router.message(Command("cancel"), CreateRaidForm())
async def cmd_cancel_raid_creation(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Raid creation cancelled.")


@router.message(CreateRaidForm.title)
async def fsm_raid_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=message.text.strip())
    await state.set_state(CreateRaidForm.platform)
    await message.answer(
        "Step 2/6\n\n"
        "Enter the <b>platform</b>:\n"
        "<i>Example: Twitter/X, Instagram, YouTube, Reddit</i>"
    )


@router.message(CreateRaidForm.platform)
async def fsm_raid_platform(message: Message, state: FSMContext) -> None:
    await state.update_data(platform=message.text.strip())
    await state.set_state(CreateRaidForm.target_url)
    await message.answer(
        "Step 3/6\n\n"
        "Enter the <b>target URL</b>:\n"
        "<i>Example: https://twitter.com/example/status/123</i>"
    )


@router.message(CreateRaidForm.target_url)
async def fsm_raid_target_url(message: Message, state: FSMContext) -> None:
    url = message.text.strip()
    if not url.startswith("http"):
        await message.answer("That doesn't look like a valid URL. Please include https://")
        return
    await state.update_data(target_url=url)
    await state.set_state(CreateRaidForm.instructions)
    await message.answer(
        "Step 4/6\n\n"
        "Enter the <b>raid instructions</b>:\n"
        "<i>List every action users should take. Example:\n"
        "1. Like the post\n"
        "2. Retweet\n"
        "3. Comment \"$BRAINROT community supporting\"</i>"
    )


@router.message(CreateRaidForm.instructions)
async def fsm_raid_instructions(message: Message, state: FSMContext) -> None:
    await state.update_data(instructions=message.text.strip())
    await state.set_state(CreateRaidForm.reward_points)
    await message.answer(
        "Step 5/6\n\n"
        "Enter the <b>reward points</b> for completing this raid:\n"
        "<i>Example: 50</i>\n\n"
        "Note: $BRAINROT holders automatically earn 2x."
    )


@router.message(CreateRaidForm.reward_points)
async def fsm_raid_reward_points(message: Message, state: FSMContext) -> None:
    if not message.text.strip().isdigit():
        await message.answer("Please enter a whole number for points. Example: 50")
        return
    points = int(message.text.strip())
    if points <= 0:
        await message.answer("Points must be greater than 0.")
        return
    await state.update_data(reward_points=points)
    await state.set_state(CreateRaidForm.expires_hours)
    await message.answer(
        "Step 6/6\n\n"
        "How many <b>hours</b> should this raid stay active?\n"
        "<i>Example: 24 (for 24 hours)</i>"
    )


@router.message(CreateRaidForm.expires_hours)
async def fsm_raid_expires_hours(message: Message, state: FSMContext) -> None:
    if not message.text.strip().isdigit():
        await message.answer("Please enter a whole number of hours. Example: 24")
        return
    hours = int(message.text.strip())
    if hours <= 0:
        await message.answer("Hours must be greater than 0.")
        return

    data = await state.get_data()
    await state.clear()

    raid_id = await create_raid(
        title=data["title"],
        platform=data["platform"],
        target_url=data["target_url"],
        instructions=data["instructions"],
        reward_points=data["reward_points"],
        expires_hours=hours,
        created_by=message.from_user.id,
    )

    await message.answer(
        f"✅ <b>Raid Created!</b>\n\n"
        f"<b>ID:</b> #{raid_id}\n"
        f"<b>Title:</b> {data['title']}\n"
        f"<b>Platform:</b> {data['platform']}\n"
        f"<b>Points:</b> {data['reward_points']}\n"
        f"<b>Expires in:</b> {hours} hours\n\n"
        f"The raid is now live. Users can find it in Raid Center → Active Raid."
    )
