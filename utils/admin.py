"""
utils/admin.py
==============
Centralised admin access helper.
Import is_admin() wherever admin checks are needed.
"""

from utils.config import settings


def is_admin(user_id: int) -> bool:
    """Returns True if the user ID is in the configured ADMIN_IDS list."""
    return user_id in settings.ADMIN_IDS
