"""
utils/copy_trade_states.py
===========================
FSM state groups for the Copy Trading module.
"""

from aiogram.fsm.state import State, StatesGroup


class CopyTradeStates(StatesGroup):
    waiting_for_wallet_address = State()
    waiting_for_wallet_label   = State()
    waiting_for_field_value    = State()
    waiting_for_bl_token       = State()
    waiting_for_wl_token       = State()
