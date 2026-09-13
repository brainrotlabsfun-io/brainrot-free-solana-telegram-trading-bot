"""
grant_user.py
=============
Manually grant Supreme Black access to a Telegram user.

Usage:
    python grant_user.py <telegram_user_id>

The user can find their own ID by sending /myid to the bot.
"""

import asyncio
import sys

from services.brainrot_token_gate import grant_supreme_black


async def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print(__doc__.strip())
        print("\nExample:  python grant_user.py 123456789")
        raise SystemExit(1)

    user_id = int(sys.argv[1])
    await grant_supreme_black(user_id)
    print(f"Supreme Black granted to {user_id}")


if __name__ == "__main__":
    asyncio.run(main())
