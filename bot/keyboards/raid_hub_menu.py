"""
bot/keyboards/raid_hub_menu.py
==============================
All inline keyboards for the Raid Hub module.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def build_hub_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🚀  START RAID",     callback_data="hub:start_raid"),
        InlineKeyboardButton(text="⚔️  ACTIVE RAIDS",   callback_data="hub:active_raids"),
    )
    builder.row(
        InlineKeyboardButton(text="📋  MY RAIDS",       callback_data="hub:my_raids"),
        InlineKeyboardButton(text="🎯  JOINED RAIDS",   callback_data="hub:joined_raids"),
    )
    builder.row(
        InlineKeyboardButton(text="💰  MY POINTS",      callback_data="hub:my_points"),
        InlineKeyboardButton(text="🏆  LEADERBOARD",    callback_data="hub:leaderboard"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️  BACK",           callback_data="menu:back"),
    )
    return builder.as_markup()


def build_raids_list(
    raids: list[dict],
    page: int,
    total: int,
    per_page: int = 5,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for raid in raids:
        prefix = ""
        if raid.get("featured"):
            prefix += "🔥 "
        title    = raid.get("title", "")[:28].upper()
        platform = raid.get("platform", "")[:10].upper()
        builder.row(
            InlineKeyboardButton(
                text=f"{prefix}{title} — {platform}",
                callback_data=f"hub:view:{raid['id']}",
            )
        )

    total_pages = max(1, (total + per_page - 1) // per_page)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="← PREV", callback_data=f"hub:raids_page:{page - 1}"))
    if (page + 1) < total_pages:
        nav.append(InlineKeyboardButton(text="NEXT →", callback_data=f"hub:raids_page:{page + 1}"))
    if nav:
        builder.row(*nav)

    builder.row(InlineKeyboardButton(text="⬅️  BACK TO HUB", callback_data="hub:main"))
    return builder.as_markup()


def build_raid_view(
    raid_id: int,
    target_link: str,
    is_joined: bool,
    is_completed: bool,
    is_creator: bool,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.row(InlineKeyboardButton(text="🔗  OPEN RAID LINK", url=target_link))

    if is_creator:
        builder.row(InlineKeyboardButton(text="📊  THIS IS YOUR RAID", callback_data="hub:noop"))
    elif is_completed:
        builder.row(InlineKeyboardButton(text="✅  ALREADY COMPLETED", callback_data="hub:noop"))
    elif is_joined:
        builder.row(InlineKeyboardButton(
            text="✅  MARK COMPLETE",
            callback_data=f"hub:complete:{raid_id}",
        ))
    else:
        builder.row(InlineKeyboardButton(
            text="⚔️  JOIN RAID",
            callback_data=f"hub:join:{raid_id}",
        ))

    builder.row(InlineKeyboardButton(text="⬅️  BACK TO RAIDS", callback_data="hub:active_raids"))
    return builder.as_markup()


def build_back_to_hub() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️  BACK TO HUB", callback_data="hub:main"))
    return builder.as_markup()


def build_skip_cancel() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏩  SKIP",   callback_data="hub:fsm:skip"),
        InlineKeyboardButton(text="❌  CANCEL", callback_data="hub:fsm:cancel"),
    )
    return builder.as_markup()


def build_cancel_only() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌  CANCEL", callback_data="hub:fsm:cancel"))
    return builder.as_markup()


def build_confirm_publish() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🚀  PUBLISH RAID", callback_data="hub:fsm:publish"),
        InlineKeyboardButton(text="❌  CANCEL",        callback_data="hub:fsm:cancel"),
    )
    return builder.as_markup()
