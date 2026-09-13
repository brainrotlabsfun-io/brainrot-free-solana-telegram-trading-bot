"""
utils/candle_sniper_states.py
==============================
FSM state groups for the Candle Sniper module.
"""

from aiogram.fsm.state import State, StatesGroup


class CSFieldEditState(StatesGroup):
    """Single-field edit — field name + metadata stored in FSM context data."""
    waiting_value = State()
