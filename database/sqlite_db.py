"""
database/sqlite_db.py
=====================
Async SQLite connection helper used by all Raid Hub services.
Provides a single get_db() context manager with Row factory pre-set.
"""

import aiosqlite
from contextlib import asynccontextmanager

DB_PATH = "brainrot.db"


@asynccontextmanager
async def get_db():
    """
    Async context manager yielding an aiosqlite connection.
    Row factory is set so rows behave like dicts.

    Usage:
        async with get_db() as db:
            async with db.execute("SELECT ...") as cursor:
                rows = await cursor.fetchall()
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        yield conn
