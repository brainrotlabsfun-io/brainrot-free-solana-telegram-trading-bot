"""
bot/handlers/raids.py
=====================
All user-facing Raid Hub handlers.

Sections:
  A. Hub menu & navigation callbacks
  B. Active raids list & pagination
  C. Raid view, join, complete
  D. My Raids / Joined Raids / My Points / Leaderboard / Premium Info
  E. FSM: Start Raid (9-step flow)
  F. FSM: Complete Raid (proof collection)
"""

import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.raid_hub_menu import (
    build_hub_menu,
    build_raids_list,
    build_raid_view,
    build_back_to_hub,
    build_skip_cancel,
    build_cancel_only,
    build_premium_choice,
    build_confirm_publish,
)
from services.raid_hub_service import (
    ensure_user_exists,
    count_user_raids_today,
    create_hub_raid,
    get_active_hub_raids,
    get_hub_raid,
    is_participant,
    has_completed_raid,
    join_hub_raid,
    complete_hub_raid,
    get_my_hub_raids,
    get_joined_hub_raids,
    get_user_hub_stats,
    HUB_PER_PAGE,
)
from services.points_service import get_leaderboard
from services.premium_service import is_premium
from utils.config import settings
from utils.states import StartRaidForm, CompleteRaidForm

router = Router()
logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fmt_expiry(raw) -> str:
    try:
        dt = datetime.fromisoformat(str(raw))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(raw)


def _fmt_raid_detail(raid: dict, join_count: int, comp_count: int) -> str:
    creator   = raid.get("creator_username") or f"User{raid['creator_user_id']}"
    prem_tag  = "👑 PREMIUM ONLY" if raid.get("premium_only") else "🌐 Public"
    feat_tag  = "  🔥 Featured" if raid.get("featured") else ""
    expiry    = _fmt_expiry(raid.get("expiry_at", "Unknown"))

    text = (
        f"⚔️ <b>{raid['title']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>Creator:</b> @{creator}\n"
        f"🌐 <b>Platform:</b> {raid['platform']}\n"
        f"🔗 <b>Link:</b> {raid['target_link']}\n\n"
        f"📋 <b>Instructions:</b>\n{raid['instructions']}\n"
    )
    if raid.get("comment_ideas"):
        text += f"\n💬 <b>Comment Ideas:</b>\n{raid['comment_ideas']}\n"
    if raid.get("hashtag_ideas"):
        text += f"\n#️⃣ <b>Hashtags:</b>\n{raid['hashtag_ideas']}\n"

    text += (
        f"\n🎯 <b>Reward:</b> {raid['reward_points']} pts"
        f"\n⏰ <b>Expires:</b> {expiry}"
        f"\n👥 <b>Joined:</b> {join_count}  ✅ <b>Completed:</b> {comp_count}"
        f"\n🏷️ {prem_tag}{feat_tag}"
    )
    return text


async def _register(callback: CallbackQuery) -> None:
    """Upsert the user into the users table on any hub interaction."""
    await ensure_user_exists(
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.first_name,
    )


# ══════════════════════════════════════════════════════════════════════════════
# A. HUB MENU
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "hub:main")
async def cb_hub_main(callback: CallbackQuery) -> None:
    await _register(callback)
    await callback.message.edit_text(
        text=(
            "🚀 <b>RAID HUB  //  COMMUNITY BOARD</b>\n"
            "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
            "The Raid Hub is the <b>community-run</b> side.\n"
            "Anyone can post a raid. Anyone can join one.\n"
            "You're not waiting for admin — you are the admin.\n\n"
            "<b>How is this different from Raid Center?</b>\n"
            "<code>⚔️ Raid Center</code> — admin posts one official raid,\n"
            "everyone executes it together at the same time.\n"
            "<code>🚀 Raid Hub</code> — the community posts raids freely.\n"
            "Multiple raids live at once. You pick what to join.\n\n"
            "<b>Why post a raid?</b>\n"
            "You found an alpha token. You want eyes on it.\n"
            "You post the raid, the community piles in,\n"
            "volume spikes, attention follows — and you\n"
            "earn points for starting it.\n\n"
            "<b>Why join a raid?</b>\n"
            "Someone else did the research. You execute,\n"
            "earn points, and ride the wave with them.\n\n"
            "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n"
            "<i>Powered by $BRAINROT. Pick an action below.</i>"
        ),
        reply_markup=build_hub_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "hub:noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


# ══════════════════════════════════════════════════════════════════════════════
# B. ACTIVE RAIDS LIST & PAGINATION
# ══════════════════════════════════════════════════════════════════════════════

async def _show_raids_page(callback: CallbackQuery, page: int) -> None:
    await _register(callback)
    user_id  = callback.from_user.id
    premium  = await is_premium(user_id)
    raids, total = await get_active_hub_raids(user_is_premium=premium, page=page)

    if not raids and page == 0:
        await callback.message.edit_text(
            text=(
                "⚔️ <b>Active Raids</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "No active raids right now.\n"
                "Be the first — press <b>Start Raid</b> to launch one!\n\n"
                "<i>Admins must approve raids if moderation is on.</i>"
            ),
            reply_markup=build_back_to_hub(),
        )
        return

    total_pages = max(1, (total + HUB_PER_PAGE - 1) // HUB_PER_PAGE)
    prem_note   = " (👑 = premium only)" if premium else " (👑 raids hidden — get Premium)"

    await callback.message.edit_text(
        text=(
            f"⚔️ <b>Active Raids</b>  —  Page {page + 1}/{total_pages}"
            f"\n{prem_note}\n\n"
            f"<i>Tap a raid to view details and join.</i>"
        ),
        reply_markup=build_raids_list(raids, page, total, HUB_PER_PAGE),
    )


@router.callback_query(F.data == "hub:active_raids")
async def cb_active_raids(callback: CallbackQuery) -> None:
    await _show_raids_page(callback, page=0)
    await callback.answer()


@router.callback_query(F.data.startswith("hub:raids_page:"))
async def cb_raids_page(callback: CallbackQuery) -> None:
    try:
        page = int(callback.data.split(":")[-1])
    except ValueError:
        page = 0
    await _show_raids_page(callback, page=page)
    await callback.answer()


# ══════════════════════════════════════════════════════════════════════════════
# C. RAID VIEW / JOIN / COMPLETE
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("hub:view:"))
async def cb_view_raid(callback: CallbackQuery) -> None:
    await _register(callback)
    try:
        raid_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer("Invalid raid.", show_alert=True)
        return

    raid = await get_hub_raid(raid_id)
    if not raid:
        await callback.answer("Raid not found.", show_alert=True)
        return

    user_id  = callback.from_user.id
    premium  = await is_premium(user_id)

    # Block access to premium-only raids for free users
    if raid.get("premium_only") and not premium:
        await callback.answer("This is a Premium-only raid. Get $BRAINROT Premium to access.", show_alert=True)
        return

    joined    = await is_participant(raid_id, user_id)
    completed = await has_completed_raid(raid_id, user_id)
    is_creator = raid["creator_user_id"] == user_id
    join_count = await get_hub_participant_count_local(raid_id)
    comp_count = await get_hub_completion_count_local(raid_id)

    await callback.message.edit_text(
        text=_fmt_raid_detail(raid, join_count, comp_count),
        reply_markup=build_raid_view(raid_id, raid["target_link"], joined, completed, is_creator),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("hub:join:"))
async def cb_join_raid(callback: CallbackQuery) -> None:
    await _register(callback)
    try:
        raid_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer("Invalid raid.", show_alert=True)
        return

    user_id  = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name or f"User{user_id}"
    premium  = await is_premium(user_id)

    raid = await get_hub_raid(raid_id)
    if raid and raid.get("premium_only") and not premium:
        await callback.answer("Premium-only raid. Get $BRAINROT Premium to join.", show_alert=True)
        return

    success, msg = await join_hub_raid(raid_id, user_id, username)

    if not success:
        await callback.answer(msg, show_alert=True)
        return

    # Refresh the view
    raid     = await get_hub_raid(raid_id)
    j_count  = await get_hub_participant_count_local(raid_id)
    c_count  = await get_hub_completion_count_local(raid_id)

    await callback.message.edit_text(
        text=(
            _fmt_raid_detail(raid, j_count, c_count) +
            "\n\n⚔️ <b>You have joined this raid!</b>\n"
            "Complete all tasks, then press <b>Mark Complete</b>."
        ),
        reply_markup=build_raid_view(raid_id, raid["target_link"], True, False, False),
        disable_web_page_preview=True,
    )
    await callback.answer(f"Joined! +{2} pts")


@router.callback_query(F.data.startswith("hub:complete:"))
async def cb_complete_raid(callback: CallbackQuery, state: FSMContext) -> None:
    await _register(callback)
    try:
        raid_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer("Invalid raid.", show_alert=True)
        return

    user_id = callback.from_user.id

    if not await is_participant(raid_id, user_id):
        await callback.answer("Join the raid first.", show_alert=True)
        return
    if await has_completed_raid(raid_id, user_id):
        await callback.answer("You already completed this raid!", show_alert=True)
        return

    raid = await get_hub_raid(raid_id)
    if not raid or raid["status"] != "active":
        await callback.answer("This raid is no longer active.", show_alert=True)
        return

    await state.set_state(CompleteRaidForm.proof)
    await state.update_data(raid_id=raid_id)

    await callback.message.answer(
        text=(
            f"✅ <b>Mark Raid Complete — {raid['title']}</b>\n\n"
            "Optionally share proof of your participation:\n"
            "<i>• Paste the comment you wrote\n"
            "• Add a link or note\n"
            "• Or type <b>skip</b> to submit without proof</i>\n\n"
            "Type your proof now or type <b>skip</b>:"
        )
    )
    await callback.answer()


# ── Proof text FSM handler ─────────────────────────────────────────────────────
@router.message(CompleteRaidForm.proof)
async def fsm_receive_proof(message: Message, state: FSMContext) -> None:
    data    = await state.get_data()
    raid_id = data.get("raid_id")
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or f"User{user_id}"

    proof_text = None if message.text.strip().lower() in ("skip", "/skip") else message.text.strip()

    await state.clear()

    success, msg, points = await complete_hub_raid(raid_id, user_id, username, proof_text)

    if not success:
        await message.answer(f"❌ {msg}")
        return

    premium = await is_premium(user_id)
    bonus_line = "\n🔥 <b>$BRAINROT Premium 2x bonus applied!</b>" if premium else ""

    await message.answer(
        f"✅ <b>Raid Completed!</b>\n\n"
        f"You earned <b>{points} points</b>.{bonus_line}\n\n"
        f"Use <b>My Points</b> to check your rank.\n"
        f"Keep raiding to climb the leaderboard!"
    )


# ══════════════════════════════════════════════════════════════════════════════
# D. MY RAIDS / JOINED RAIDS / POINTS / LEADERBOARD / PREMIUM
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "hub:my_raids")
async def cb_my_raids(callback: CallbackQuery) -> None:
    await _register(callback)
    raids = await get_my_hub_raids(callback.from_user.id)

    if not raids:
        await callback.message.edit_text(
            text=(
                "📋 <b>My Raids</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "You haven't created any raids yet.\n"
                "Press <b>Start Raid</b> to launch your first one!"
            ),
            reply_markup=build_back_to_hub(),
        )
        await callback.answer()
        return

    STATUS_EMOJI = {
        "active": "✅", "pending": "⏳", "closed": "🔴",
        "rejected": "❌", "expired": "⌛",
    }
    lines = ["📋 <b>My Raids</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
    for r in raids[:20]:
        emoji = STATUS_EMOJI.get(r["status"], "•")
        lines.append(
            f"{emoji} <b>{r['title']}</b>\n"
            f"   {r['platform']} | Joins: {r['join_count']} | Done: {r['completion_count']}\n"
            f"   Status: {r['status']}"
        )

    await callback.message.edit_text(
        text="\n".join(lines),
        reply_markup=build_back_to_hub(),
    )
    await callback.answer()


@router.callback_query(F.data == "hub:joined_raids")
async def cb_joined_raids(callback: CallbackQuery) -> None:
    await _register(callback)
    raids = await get_joined_hub_raids(callback.from_user.id)

    if not raids:
        await callback.message.edit_text(
            text=(
                "🎯 <b>Joined Raids</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "You haven't joined any raids yet.\n"
                "Browse <b>Active Raids</b> to find one!"
            ),
            reply_markup=build_back_to_hub(),
        )
        await callback.answer()
        return

    lines = ["🎯 <b>Joined Raids</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
    for r in raids[:20]:
        done = "✅ Completed" if r["participation_status"] == "completed" else "⏳ Joined"
        lines.append(f"{done} — <b>{r['title']}</b> ({r['platform']})")

    await callback.message.edit_text(
        text="\n".join(lines),
        reply_markup=build_back_to_hub(),
    )
    await callback.answer()


@router.callback_query(F.data == "hub:my_points")
async def cb_my_points(callback: CallbackQuery) -> None:
    await _register(callback)
    user_id  = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name or f"User{user_id}"
    stats    = await get_user_hub_stats(user_id, username)
    premium  = stats["is_premium"]

    rank_str  = f"#{stats['rank']}" if stats["rank"] else "Unranked"
    prem_line = "\n👑 <b>$BRAINROT Premium</b> — 2x point bonus active!" if premium else ""

    await callback.message.edit_text(
        text=(
            f"💰 <b>My Points</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {username}\n"
            f"🎯 <b>Total Points:</b>  {stats['total_points']}\n"
            f"🏆 <b>Rank:</b>  {rank_str}\n\n"
            f"🚀 <b>Raids Created:</b>  {stats['raids_created']}\n"
            f"⚔️ <b>Raids Joined:</b>  {stats['raids_joined']}\n"
            f"✅ <b>Raids Completed:</b>  {stats['raids_completed']}"
            f"{prem_line}"
        ),
        reply_markup=build_back_to_hub(),
    )
    await callback.answer()


@router.callback_query(F.data == "hub:leaderboard")
async def cb_hub_leaderboard(callback: CallbackQuery) -> None:
    entries = await get_leaderboard(limit=10)

    if not entries:
        text = (
            "🏆 <b>Leaderboard</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No points recorded yet. Complete raids to get on the board!"
        )
    else:
        rows = [f"{e['medal']} <b>{e['username']}</b> — {e['total_points']} pts" for e in entries]
        text = "🏆 <b>Raid Hub Leaderboard</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n" + "\n".join(rows)
        text += "\n\n<i>Top 10 — updates in real time.</i>"

    await callback.message.edit_text(text=text, reply_markup=build_back_to_hub())
    await callback.answer()


@router.callback_query(F.data == "hub:premium_info")
async def cb_hub_premium_info(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    premium = await is_premium(user_id)
    status  = "✅ <b>ACTIVE</b>" if premium else "❌ Not active"

    await callback.message.edit_text(
        text=(
            "👑 <b>$BRAINROT Premium</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Your status: {status}\n\n"
            "<b>Premium benefits:</b>\n"
            "🔥 2x points on every raid completion\n"
            "🚀 Launch premium-only raids\n"
            "👁 See all raids including premium-only\n"
            "📊 Higher daily raid creation limit\n"
            "🏆 Premium badge on leaderboard\n\n"
            "<b>How to get Premium:</b>\n"
            "Hold <b>$BRAINROT</b> and contact an admin.\n"
            "On-chain auto-verification coming soon.\n\n"
            f"Contract:\n<code>{settings.BRAINROT_MINT or 'not configured'}</code>"
        ),
        reply_markup=build_back_to_hub(),
    )
    await callback.answer()


# ══════════════════════════════════════════════════════════════════════════════
# E. FSM: START RAID FLOW
# ══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "hub:start_raid")
async def cb_start_raid(callback: CallbackQuery, state: FSMContext) -> None:
    await _register(callback)
    user_id = callback.from_user.id
    premium = await is_premium(user_id)

    # Daily limit check
    limit = settings.PREMIUM_DAILY_RAID_LIMIT if premium else settings.DAILY_RAID_LIMIT
    created_today = await count_user_raids_today(user_id)

    if created_today >= limit:
        await callback.answer(
            f"Daily limit reached ({limit} raids/day). Upgrade to Premium for more.",
            show_alert=True,
        )
        return

    await state.set_state(StartRaidForm.title)
    await callback.message.answer(
        text=(
            "🚀 <b>Start a Raid — Step 1/7</b>\n\n"
            "Enter your <b>raid title</b>:\n"
            "<i>Example: Twitter Push — Support $BRAINROT</i>\n\n"
            "Type /cancel to abort at any time."
        ),
        reply_markup=build_cancel_only(),
    )
    await callback.answer()


@router.message(Command("cancel"), StartRaidForm())
@router.message(Command("cancel"), CompleteRaidForm())
async def cmd_cancel_fsm(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Cancelled.")


# Step 1 — Title
@router.message(StartRaidForm.title)
async def fsm_title(message: Message, state: FSMContext) -> None:
    title = message.text.strip()
    if len(title) < 3:
        await message.answer("Title too short. Enter at least 3 characters.")
        return
    await state.update_data(title=title)
    await state.set_state(StartRaidForm.platform)
    await message.answer(
        "Step 2/7\n\n"
        "Enter the <b>platform</b>:\n"
        "<i>Twitter/X, Instagram, YouTube, Reddit, TikTok, etc.</i>",
        reply_markup=build_cancel_only(),
    )


# Step 2 — Platform
@router.message(StartRaidForm.platform)
async def fsm_platform(message: Message, state: FSMContext) -> None:
    await state.update_data(platform=message.text.strip())
    await state.set_state(StartRaidForm.target_link)
    await message.answer(
        "Step 3/7\n\n"
        "Enter the <b>target link</b>:\n"
        "<i>Must start with https://</i>",
        reply_markup=build_cancel_only(),
    )


# Step 3 — Target link
@router.message(StartRaidForm.target_link)
async def fsm_target_link(message: Message, state: FSMContext) -> None:
    url = message.text.strip()
    if not url.startswith("http"):
        await message.answer("Please enter a valid URL starting with https://")
        return
    await state.update_data(target_link=url)
    await state.set_state(StartRaidForm.instructions)
    await message.answer(
        "Step 4/7\n\n"
        "Enter the <b>raid instructions</b>:\n"
        "<i>List every action users should take:\n"
        "1. Like the post\n"
        "2. Retweet\n"
        "3. Comment \"$BRAINROT community\"</i>",
        reply_markup=build_cancel_only(),
    )


# Step 4 — Instructions
@router.message(StartRaidForm.instructions)
async def fsm_instructions(message: Message, state: FSMContext) -> None:
    if len(message.text.strip()) < 10:
        await message.answer("Please write more detailed instructions (at least 10 characters).")
        return
    await state.update_data(instructions=message.text.strip())
    await state.set_state(StartRaidForm.comment_ideas)
    await message.answer(
        "Step 5/7  <i>(optional)</i>\n\n"
        "Enter <b>comment ideas</b> for participants:\n"
        "<i>Example: \"$BRAINROT is the future of Solana!\"\n"
        "\"Great project, check out $BRAINROT!\"</i>\n\n"
        "Press <b>Skip</b> to leave this blank.",
        reply_markup=build_skip_cancel(),
    )


# Step 5 — Comment ideas (text)
@router.message(StartRaidForm.comment_ideas)
async def fsm_comment_ideas_text(message: Message, state: FSMContext) -> None:
    await state.update_data(comment_ideas=message.text.strip())
    await state.set_state(StartRaidForm.hashtag_ideas)
    await message.answer(
        "Step 6/7  <i>(optional)</i>\n\n"
        "Enter <b>hashtag ideas</b>:\n"
        "<i>Example: #BRAINROT #Solana #Crypto</i>\n\n"
        "Press <b>Skip</b> to leave this blank.",
        reply_markup=build_skip_cancel(),
    )


# Step 5 — Comment ideas (skip callback)
@router.callback_query(F.data == "hub:fsm:skip", StartRaidForm.comment_ideas)
async def fsm_skip_comments(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(comment_ideas=None)
    await state.set_state(StartRaidForm.hashtag_ideas)
    await callback.message.edit_text(
        "Step 6/7  <i>(optional)</i>\n\n"
        "Enter <b>hashtag ideas</b>:\n"
        "<i>Example: #BRAINROT #Solana #Crypto</i>\n\n"
        "Press <b>Skip</b> to leave this blank.",
        reply_markup=build_skip_cancel(),
    )
    await callback.answer()


# Step 6 — Hashtag ideas (text)
@router.message(StartRaidForm.hashtag_ideas)
async def fsm_hashtag_ideas_text(message: Message, state: FSMContext) -> None:
    await state.update_data(hashtag_ideas=message.text.strip())
    await state.set_state(StartRaidForm.expiry_hours)
    await message.answer(
        "Step 7/7\n\n"
        "How many <b>hours</b> should this raid run?\n"
        "<i>Enter a number between 1 and 168 (1 week max)</i>",
        reply_markup=build_cancel_only(),
    )


# Step 6 — Hashtag ideas (skip callback)
@router.callback_query(F.data == "hub:fsm:skip", StartRaidForm.hashtag_ideas)
async def fsm_skip_hashtags(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(hashtag_ideas=None)
    await state.set_state(StartRaidForm.expiry_hours)
    await callback.message.edit_text(
        "Step 7/7\n\n"
        "How many <b>hours</b> should this raid run?\n"
        "<i>Enter a number between 1 and 168 (1 week max)</i>",
        reply_markup=build_cancel_only(),
    )
    await callback.answer()


# Step 7 — Expiry hours
@router.message(StartRaidForm.expiry_hours)
async def fsm_expiry_hours(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("Please enter a whole number of hours. Example: 24")
        return
    hours = int(text)
    if not (1 <= hours <= 168):
        await message.answer("Enter a number between 1 and 168.")
        return

    await state.update_data(expiry_hours=hours)
    await state.set_state(StartRaidForm.premium_only)

    user_id = message.from_user.id
    premium = await is_premium(user_id)

    if premium:
        await message.answer(
            "Should this raid be <b>Premium Only</b>?\n\n"
            "👑 Premium Only — only $BRAINROT holders can join\n"
            "🌐 Public — anyone can join",
            reply_markup=build_premium_choice(),
        )
    else:
        # Free users cannot create premium-only raids
        await state.update_data(premium_only=False)
        await _show_confirm(message, state)


# Step 8 — Premium choice (callback)
@router.callback_query(
    F.data.in_({"hub:fsm:prem_yes", "hub:fsm:prem_no"}),
    StartRaidForm.premium_only,
)
async def fsm_premium_choice(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    premium = await is_premium(user_id)

    if callback.data == "hub:fsm:prem_yes" and not premium:
        await callback.answer("Only $BRAINROT Premium users can create premium-only raids.", show_alert=True)
        return

    await state.update_data(premium_only=(callback.data == "hub:fsm:prem_yes"))
    await _show_confirm(callback.message, state)
    await callback.answer()


async def _show_confirm(message: Message, state: FSMContext) -> None:
    """Show raid summary and ask user to confirm publishing."""
    await state.set_state(StartRaidForm.confirm)
    data = await state.get_data()

    prem_label = "👑 Premium Only" if data.get("premium_only") else "🌐 Public"
    comments   = data.get("comment_ideas") or "<i>None</i>"
    hashtags   = data.get("hashtag_ideas") or "<i>None</i>"

    summary = (
        "📋 <b>Raid Summary — Review Before Publishing</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Title:</b> {data.get('title')}\n"
        f"<b>Platform:</b> {data.get('platform')}\n"
        f"<b>Link:</b> {data.get('target_link')}\n"
        f"<b>Duration:</b> {data.get('expiry_hours')} hours\n"
        f"<b>Access:</b> {prem_label}\n"
        f"<b>Points:</b> 10 pts per completion\n\n"
        f"<b>Instructions:</b>\n{data.get('instructions')}\n\n"
        f"<b>Comment Ideas:</b> {comments}\n"
        f"<b>Hashtags:</b> {hashtags}\n\n"
        "Press <b>Publish Raid</b> to go live."
    )

    await message.answer(summary, reply_markup=build_confirm_publish(), disable_web_page_preview=True)


# Step 9 — Confirm publish
@router.callback_query(F.data == "hub:fsm:publish", StartRaidForm.confirm)
async def fsm_publish_raid(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()

    user_id  = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name or f"User{user_id}"

    raid_id = await create_hub_raid(
        creator_id      = user_id,
        creator_username= username,
        title           = data["title"],
        platform        = data["platform"],
        target_link     = data["target_link"],
        instructions    = data["instructions"],
        comment_ideas   = data.get("comment_ideas"),
        hashtag_ideas   = data.get("hashtag_ideas"),
        expiry_hours    = data["expiry_hours"],
        premium_only    = data.get("premium_only", False),
        auto_approve    = settings.RAID_AUTO_APPROVE,
    )

    status_msg = (
        "✅ Raid is <b>live now</b>! Users can find it in Active Raids."
        if settings.RAID_AUTO_APPROVE
        else "⏳ Raid is <b>pending admin approval</b>. It will go live once approved."
    )

    await callback.message.edit_text(
        text=(
            f"🚀 <b>Raid Published!</b>\n\n"
            f"<b>ID:</b> #{raid_id}\n"
            f"<b>Title:</b> {data['title']}\n"
            f"<b>Duration:</b> {data['expiry_hours']} hours\n\n"
            f"{status_msg}\n\n"
            f"You earned <b>+5 points</b> for creating this raid."
        ),
        reply_markup=build_back_to_hub(),
    )
    await callback.answer("Raid published!")


# ── FSM Cancel (any state) ─────────────────────────────────────────────────────
@router.callback_query(F.data == "hub:fsm:cancel")
async def fsm_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    current = await state.get_state()
    if current:
        await state.clear()
    await callback.message.edit_text(
        "❌ Cancelled.",
        reply_markup=build_back_to_hub(),
    )
    await callback.answer()


# ── Local helpers (avoid circular import with direct DB calls) ─────────────────
from services.raid_hub_service import get_hub_participant_count, get_hub_completion_count

async def get_hub_participant_count_local(raid_id: int) -> int:
    return await get_hub_participant_count(raid_id)

async def get_hub_completion_count_local(raid_id: int) -> int:
    return await get_hub_completion_count(raid_id)
