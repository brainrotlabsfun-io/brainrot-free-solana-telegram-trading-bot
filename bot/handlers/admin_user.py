"""
bot/handlers/admin_user.py
===========================
Admin tools for managing user accounts and debugging broken verifications.

Commands:
  /myid                    — shows your own Telegram user ID (everyone)
  /adminuser <user_id>     — full status: wallet, tier, burns, errors
  /adminburns <user_id>    — last 10 burn submissions with errors
  /admingrant <user_id>    — manually grant Supreme Black (fixes broken burns)
  /adminreset <user_id>    — remove Supreme access (for testing)
"""

import logging
from datetime import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from database.sqlite_db import get_db
from utils.admin import is_admin
from services.burn_activation_service import get_activation_status, get_burn_stats
from services.wallet_service import get_wallet

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("myid"))
async def cmd_myid(message: Message) -> None:
    """Anyone can use this to find their Telegram user ID."""
    uid  = message.from_user.id
    name = message.from_user.username or message.from_user.first_name
    await message.answer(
        f"👤 <b>Your Telegram ID</b>\n\n"
        f"<code>{uid}</code>\n\n"
        f"Name: {name}\n\n"
        f"<i>Give this ID to an admin to look up your account.</i>",
        parse_mode="HTML",
    )


@router.message(Command("adminuser"))
async def cmd_adminuser(message: Message) -> None:
    """Show full status for a user ID."""
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: /adminuser <user_id>")
        return

    uid    = int(parts[1])
    status = await get_activation_status(uid)
    stats  = await get_burn_stats(uid)
    wallet = await get_wallet(uid)

    wallet_addr = wallet["wallet_address"] if wallet else "NOT LINKED"
    tier        = status.get("active_tier", "free")
    via         = status.get("activated_via") or "—"
    act_tx      = status.get("activation_tx") or "—"
    act_at      = (status.get("activated_at") or "—")[:19]
    expires     = (status.get("expires_at") or "permanent")
    last_burn   = status.get("last_burn_status") or "none"
    total_burn  = stats.get("total_burned", 0)
    burn_count  = stats.get("burn_count", 0)

    # Check affiliate signup pending
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM affiliate_signup_pending WHERE user_id = ?", (uid,)
        ) as cur:
            aff_pending = await cur.fetchone()
        async with db.execute(
            "SELECT * FROM holder_access WHERE user_id = ?", (uid,)
        ) as cur:
            ha = await cur.fetchone()

    ha_raw = dict(ha) if ha else None

    text = (
        f"🔍 <b>Admin: User {uid}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Wallet:</b> <code>{wallet_addr}</code>\n"
        f"<b>Tier:</b> {tier}\n"
        f"<b>Via:</b> {via}\n"
        f"<b>Activated:</b> {act_at}\n"
        f"<b>Expires:</b> {expires}\n"
        f"<b>Act TX:</b> <code>{act_tx[:30] if act_tx != '—' else '—'}</code>\n\n"
        f"<b>Total Burned:</b> {total_burn:,.0f}\n"
        f"<b>Burn Count:</b> {burn_count}\n"
        f"<b>Last Burn Status:</b> {last_burn}\n\n"
    )

    if aff_pending:
        exp = (dict(aff_pending).get("expires_at") or "")[:19]
        expected = dict(aff_pending).get("expected_sol")
        text += f"<b>Affiliate Signup Pending:</b> {expected} SOL (exp {exp})\n\n"

    if ha_raw:
        text += f"<b>holder_access raw:</b> <code>{ha_raw}</code>\n\n"

    text += f"Use /adminburns {uid} to see burn TX history.\nUse /admingrant {uid} to force-activate Supreme Black."

    await message.answer(text, parse_mode="HTML")


@router.message(Command("adminburns"))
async def cmd_adminburns(message: Message) -> None:
    """Show recent burn submissions and their verification results."""
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: /adminburns <user_id>")
        return

    uid = int(parts[1])

    async with get_db() as db:
        async with db.execute("""
            SELECT tx_signature, status, burned_amount, created_at, verified_at
            FROM burn_activations
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 10
        """, (uid,)) as cur:
            rows = await cur.fetchall()

    if not rows:
        await message.answer(f"No burn submissions found for user {uid}.")
        return

    lines = [f"🔥 <b>Burns for user {uid}:</b>\n"]
    for r in rows:
        r = dict(r)
        status_icon = "✅" if r["status"] == "verified" else ("⏳" if r["status"] == "pending" else "❌")
        sig_short = (r["tx_signature"] or "")[:20] + "..."
        amount = r["burned_amount"] or 0
        date = (r["created_at"] or "")[:16]
        lines.append(
            f"{status_icon} <code>{sig_short}</code>\n"
            f"   {r['status']} · {amount:,.0f} tokens · {date}"
        )

    await message.answer("\n\n".join(lines), parse_mode="HTML")


@router.message(Command("admingrant"))
async def cmd_admingrant(message: Message) -> None:
    """
    Manually grant Supreme Black to a user.
    Use when burn verification is broken / RPC failed / user sent valid TX.
    """
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: /admingrant <user_id>")
        return

    uid = int(parts[1])
    now = datetime.utcnow().isoformat()

    async with get_db() as db:
        # Check user exists (has wallet)
        async with db.execute(
            "SELECT wallet_address FROM wallet_links WHERE user_id = ?", (uid,)
        ) as cur:
            wrow = await cur.fetchone()

        await db.execute("""
            INSERT INTO holder_access
                (user_id, wallet_address, tier, active, activated_via,
                 activation_tx_signature, activated_at, expires_at, updated_at)
            VALUES (?, ?, 'supreme_black', 1, 'admin_grant', 'ADMIN_GRANT', ?, NULL, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                tier                    = 'supreme_black',
                active                  = 1,
                activated_via           = 'admin_grant',
                activation_tx_signature = 'ADMIN_GRANT',
                activated_at            = ?,
                expires_at              = NULL,
                updated_at              = ?
        """, (uid, wrow["wallet_address"] if wrow else "", now, now, now, now))
        await db.commit()

    wallet_addr = wrow["wallet_address"] if wrow else "no wallet linked"
    await message.answer(
        f"✅ <b>Supreme Black granted</b>\n\n"
        f"User ID: <code>{uid}</code>\n"
        f"Wallet: <code>{wallet_addr}</code>\n"
        f"Via: admin_grant\n\n"
        f"User now has permanent Supreme Black access.",
        parse_mode="HTML",
    )
    logger.info(f"admin_grant: Supreme Black granted to user {uid} by admin {message.from_user.id}")


@router.message(Command("adminreset"))
async def cmd_adminreset(message: Message) -> None:
    """Remove Supreme access from a user (useful for resetting test accounts)."""
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: /adminreset <user_id>")
        return

    uid = int(parts[1])
    now = datetime.utcnow().isoformat()

    async with get_db() as db:
        await db.execute("""
            UPDATE holder_access SET active = 0, updated_at = ? WHERE user_id = ?
        """, (now, uid))
        # Also clear pending signups so they can restart the flow
        await db.execute("DELETE FROM affiliate_signup_pending WHERE user_id = ?", (uid,))
        await db.commit()

    await message.answer(
        f"🔄 <b>Access reset</b>\n\nUser {uid} is now FREE tier.\n"
        f"affiliate_signup_pending cleared.\n"
        f"They can now re-test the full signup flow.",
        parse_mode="HTML",
    )
