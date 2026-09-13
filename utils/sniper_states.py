"""
utils/sniper_states.py
======================
All FSM state groups for the Sniper Tool module.
"""

from aiogram.fsm.state import State, StatesGroup
from utils.config import settings


class AnalyzeTokenState(StatesGroup):
    waiting_address = State()


class AddWatchTargetState(StatesGroup):
    waiting_address = State()


class AddBlacklistState(StatesGroup):
    waiting_address = State()
    waiting_label   = State()


class AddWalletState(StatesGroup):
    waiting_address = State()


class EditSettingState(StatesGroup):
    """Single-field settings edit. Field name stored in FSM data."""
    waiting_value = State()


class CreatePresetState(StatesGroup):
    """Creates a named preset from current settings."""
    waiting_name = State()


class ConfigAutoBuyState(StatesGroup):
    """Step-by-step auto-buy configuration."""
    max_buy_size    = State()
    max_per_hour    = State()
    score_threshold = State()
    slippage        = State()
    priority_fee    = State()
    cooldown        = State()


class TradePreviewState(StatesGroup):
    """Collects token address for manual trade preview."""
    waiting_address = State()
