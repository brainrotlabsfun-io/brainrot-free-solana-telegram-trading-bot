"""
bot/handlers/admin_raids.py
===========================
Admin moderation commands for the Raid Hub.

Commands:
  /pending_raids          — list raids awaiting approval
  /approve_raid <id>      — approve a pending raid
  /reject_raid <id>       — reject a pending raid
  /close_raid <id>        — force-close any active raid
  /feature_raid <id>      — toggle featured flag
  /raid_stats             — hub-wide statistics
  /grant_premium <user_id> — grant premium access
  /revoke_premium <user_id> — revoke premium access
"""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from utils.admin import is_admin
from services.raid_hub_service import (
    get_pending_hub_raids,
    approve_hub_raid,
    reject_hub_raid,
    close_hub_raid,
    toggle_feature_hub_raid,
    get_hub_raid_stats,
)
from services.premium_service import (
    grant_premium,
    revoke_premium,
    get_all_premium_users,
)

router = Router()
logger = logging.getLogger(__name__)


def _parse_id(message: Message, command: str) -> int | None:
    """Parses a single integer argument from a command message."""
    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    return int(parts[1])


def _admin_only(message: Message) -> bool:
    if not is_admin(message.from_user.id):
        return False
    return True


# ── /pending_raids ─────────────────────────────────────────────────────────────
@router.message(Command("pending_raids"))
async def cmd_pending_raids(message: Message) -> None:
    if not _admin_only(message):
        await message.answer("Admin only.")
        return

    raids = await get_pending_hub_raids()
    if not raids:
        await message.answer("No raids pending approval.")
        return

    lines = ["⏳ <b>Pending Raids</b>\n"]
    for r in raids:
        creator = r.get("creator_username") or f"User{r['creator_user_id']}"
        lines.append(
            f"<b>#{r['id']}</b> — {r['title']}\n"
            f"   Creator: @{creator} | Platform: {r['platform']}\n"
            f"   <code>/approve_raid {r['id']}</code>  |  <code>/reject_raid {r['id']}</code>\n"
        )

    await message.answer("\n".join(lines))


# ── /approve_raid <id> ─────────────────────────────────────────────────────────
@router.message(Command("approve_raid"))
async def cmd_approve_raid(message: Message) -> None:
    if not _admin_only(message):
        await message.answer("Admin only.")
        return

    raid_id = _parse_id(message, "approve_raid")
    if raid_id is None:
        await message.answer("Usage: /approve_raid <raid_id>")
        return

    success = await approve_hub_raid(raid_id, message.from_user.id)
    if success:
        await message.answer(f"✅ Raid #{raid_id} approved and now live.")
        logger.info(f"Admin {message.from_user.id} approved hub raid {raid_id}")
    else:
        await message.answer(f"Raid #{raid_id} not found or not pending.")


# ── /reject_raid <id> ──────────────────────────────────────────────────────────
@router.message(Command("reject_raid"))
async def cmd_reject_raid(message: Message) -> None:
    if not _admin_only(message):
        await message.answer("Admin only.")
        return

    raid_id = _parse_id(message, "reject_raid")
    if raid_id is None:
        await message.answer("Usage: /reject_raid <raid_id>")
        return

    success = await reject_hub_raid(raid_id)
    if success:
        await message.answer(f"❌ Raid #{raid_id} rejected.")
        logger.info(f"Admin {message.from_user.id} rejected hub raid {raid_id}")
    else:
        await message.answer(f"Raid #{raid_id} not found or not pending.")


# ── /close_raid <id> ───────────────────────────────────────────────────────────
@router.message(Command("close_raid"))
async def cmd_close_raid(message: Message) -> None:
    if not _admin_only(message):
        await message.answer("Admin only.")
        return

    raid_id = _parse_id(message, "close_raid")
    if raid_id is None:
        await message.answer("Usage: /close_raid <raid_id>")
        return

    success = await close_hub_raid(raid_id)
    if success:
        await message.answer(f"🔴 Raid #{raid_id} closed.")
        logger.info(f"Admin {message.from_user.id} closed hub raid {raid_id}")
    else:
        await message.answer(f"Raid #{raid_id} not found or already closed/rejected.")


# ── /feature_raid <id> ─────────────────────────────────────────────────────────
@router.message(Command("feature_raid"))
async def cmd_feature_raid(message: Message) -> None:
    if not _admin_only(message):
        await message.answer("Admin only.")
        return

    raid_id = _parse_id(message, "feature_raid")
    if raid_id is None:
        await message.answer("Usage: /feature_raid <raid_id>")
        return

    new_state = await toggle_feature_hub_raid(raid_id)
    if new_state is None:
        await message.answer(f"Raid #{raid_id} not found.")
    elif new_state:
        await message.answer(f"🔥 Raid #{raid_id} is now FEATURED.")
    else:
        await message.answer(f"Raid #{raid_id} un-featured.")


# ── /raid_stats ────────────────────────────────────────────────────────────────
@router.message(Command("raid_stats"))
async def cmd_raid_stats(message: Message) -> None:
    if not _admin_only(message):
        await message.answer("Admin only.")
        return

    s = await get_hub_raid_stats()
    await message.answer(
        f"📊 <b>Raid Hub Stats</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Total Raids:       {s['total_raids']}\n"
        f"Active Raids:      {s['active_raids']}\n"
        f"Pending Approval:  {s['pending_raids']}\n"
        f"Closed Raids:      {s['closed_raids']}\n\n"
        f"Total Joins:       {s['total_joins']}\n"
        f"Total Completions: {s['total_completions']}\n"
        f"Unique Raiders:    {s['unique_raiders']}\n"
        f"Registered Users:  {s['total_users']}"
    )


# ── /grant_premium <user_id> ───────────────────────────────────────────────────
@router.message(Command("grant_premium"))
async def cmd_grant_premium(message: Message) -> None:
    if not _admin_only(message):
        await message.answer("Admin only.")
        return

    user_id = _parse_id(message, "grant_premium")
    if user_id is None:
        await message.answer("Usage: /grant_premium <telegram_user_id>")
        return

    await grant_premium(user_id, entitlement_type="manual")
    await message.answer(f"👑 Premium granted to user {user_id}.")


# ── /revoke_premium <user_id> ──────────────────────────────────────────────────
@router.message(Command("revoke_premium"))
async def cmd_revoke_premium(message: Message) -> None:
    if not _admin_only(message):
        await message.answer("Admin only.")
        return

    user_id = _parse_id(message, "revoke_premium")
    if user_id is None:
        await message.answer("Usage: /revoke_premium <telegram_user_id>")
        return

    success = await revoke_premium(user_id)
    if success:
        await message.answer(f"Premium revoked for user {user_id}.")
    else:
        await message.answer(f"User {user_id} had no active premium.")


# ── /premium_list ──────────────────────────────────────────────────────────────
@router.message(Command("premium_list"))
async def cmd_premium_list(message: Message) -> None:
    if not _admin_only(message):
        await message.answer("Admin only.")
        return

    users = await get_all_premium_users()
    if not users:
        await message.answer("No premium users currently active.")
        return

    lines = ["👑 <b>Active Premium Users</b>\n"]
    for u in users:
        name = u.get("username") or u.get("first_name") or f"User{u['user_id']}"
        lines.append(f"• @{name} (ID: {u['user_id']}) — {u['entitlement_type']}")

    await message.answer("\n".join(lines))
