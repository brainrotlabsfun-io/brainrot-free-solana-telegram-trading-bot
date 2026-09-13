from aiogram.fsm.state import State, StatesGroup


class WalletScoutStates(StatesGroup):
    waiting_for_wallet       = State()   # score a wallet
    waiting_for_token        = State()   # top traders / early buyers / bundle
    waiting_for_token_list   = State()   # repeated winners (multi-contract input)
