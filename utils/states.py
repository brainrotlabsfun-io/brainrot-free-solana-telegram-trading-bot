"""
utils/states.py
===============
All FSM state groups for the bot, centralised in one place.
Import from here in any handler that needs FSM.
"""

from aiogram.fsm.state import State, StatesGroup


class StartRaidForm(StatesGroup):
    """
    Step-by-step flow for user-created raids.
    Steps 1-7 are message states (user types).
    Step 8 (confirm) is resolved via inline keyboard callbacks.
    """
    title         = State()   # 1 — raid title
    platform      = State()   # 2 — platform name
    target_link   = State()   # 3 — target URL
    instructions  = State()   # 4 — what to do
    comment_ideas = State()   # 5 — optional comment suggestions
    hashtag_ideas = State()   # 6 — optional hashtags
    expiry_hours  = State()   # 7 — duration in hours
    confirm       = State()   # 9 — callback: hub:fsm:publish / hub:fsm:cancel


class CompleteRaidForm(StatesGroup):
    """Collects optional proof text when a user marks a raid complete."""
    proof = State()


class CreateRaidForm(StatesGroup):
    """Legacy FSM for admin-created raids (Raid Center module)."""
    title         = State()
    platform      = State()
    target_url    = State()
    instructions  = State()
    reward_points = State()
    expires_hours = State()


class LinkWalletState(StatesGroup):
    """FSM for linking a Solana wallet to a Telegram account."""
    waiting_address = State()


class WithdrawState(StatesGroup):
    """FSM for withdrawing SOL from the bot wallet to an external address."""
    waiting_address = State()
    waiting_amount  = State()


class AutoExitFSM(StatesGroup):
    """FSM states for the Auto-Exit Manager (defined in auto_exit.py AEState)."""
    clone_name  = State()
    edit_field  = State()

