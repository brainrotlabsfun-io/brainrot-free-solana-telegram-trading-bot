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
    Steps 8-9 (premium_only, confirm) are resolved via inline keyboard callbacks.
    """
    title         = State()   # 1 — raid title
    platform      = State()   # 2 — platform name
    target_link   = State()   # 3 — target URL
    instructions  = State()   # 4 — what to do
    comment_ideas = State()   # 5 — optional comment suggestions
    hashtag_ideas = State()   # 6 — optional hashtags
    expiry_hours  = State()   # 7 — duration in hours
    premium_only  = State()   # 8 — callback: hub:fsm:prem_yes / hub:fsm:prem_no
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


class SubmitBurnTxState(StatesGroup):
    """FSM for submitting a burn transaction signature for SUPREME activation."""
    waiting_tx_signature = State()


class WithdrawState(StatesGroup):
    """FSM for withdrawing SOL from the bot wallet to an external address."""
    waiting_address = State()
    waiting_amount  = State()


class AutoExitFSM(StatesGroup):
    """FSM states for the Supreme Black Auto-Exit Manager (defined in auto_exit.py AEState)."""
    clone_name  = State()
    edit_field  = State()


class AffiliateWalletState(StatesGroup):
    """FSM for optionally entering a referral/affiliate wallet during Supreme signup."""
    waiting_affiliate_wallet = State()


class AffiliateSubmitTxState(StatesGroup):
    """FSM for user submitting their SOL payment TX signature for manual verification."""
    waiting_tx_signature = State()


class AffiliateMarkPaidState(StatesGroup):
    """FSM for admin entering a payout TX hash when marking a commission as paid."""
    waiting_tx_hash = State()
