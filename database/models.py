"""
database/models.py
==================
Placeholder data models for future ORM integration.

When ready to add a real ORM:
- Swap these dataclasses for SQLAlchemy declarative models
- Add Alembic for migrations
- Wire to db.py engine and session

These are plain Python dataclasses for now — zero dependencies required.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class User:
    """
    Represents a Telegram user who has interacted with the bot.
    Future fields: joined_at, etc.
    """
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    # Future: token balance snapshot, etc.


@dataclass
class Wallet:
    """
    Represents a Solana wallet linked to a user.
    Future fields: balance_cache, last_synced, is_primary, etc.
    """
    user_id: int                  # Foreign key → User.telegram_id
    public_key: str               # Solana wallet public key
    label: Optional[str] = None   # User-defined label, e.g. "Main Wallet"
    is_active: bool = True

    # Future: encrypted keypair reference (never store raw private keys)


@dataclass
class WatchlistItem:
    """
    Represents a token the user is monitoring.
    Future fields: alert_price, alert_percent, notes, etc.
    """
    user_id: int        # Foreign key → User.telegram_id
    token_address: str  # Solana token mint address
    token_symbol: Optional[str] = None
    added_at: datetime = field(default_factory=datetime.utcnow)

    # Future: target price, % change alerts, Dexscreener link, etc.
