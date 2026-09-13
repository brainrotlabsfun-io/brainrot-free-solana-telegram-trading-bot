"""
Main entry point
================
Initializes the bot, registers all routers, and starts long polling.
"""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from utils.sqlite_storage import SQLiteStorage

from utils.config import settings
from database.db import init_db

# ── Handlers ───────────────────────────────────────────────────────────────────
from bot.handlers import start, help, menu, callbacks
from bot.handlers import raid            # Legacy Raid Center (admin-created)
from bot.handlers import raids           # Raid Hub (user-generated)
from bot.handlers import admin_raids     # Admin moderation commands
from bot.handlers import admin_user      # Admin user management + /myid
from bot.handlers import sniper          # Sniper Tool
from bot.handlers import profile         # Profile + stats
from bot.handlers import auto_exit       # Auto-Exit Manager
from bot.handlers import copy_trade      # ct:* Copy Trading
from bot.handlers import wallet_scout    # ws:* Wallet Scout (Dragon mechanics)
from bot.handlers import candle_sniper   # cs:* Candle Sniper strategy
from bot.handlers import tutorial        # tut:* User Tutorial

# ── Services ───────────────────────────────────────────────────────────────────
from services.pumpportal_ws_service import pump_service
from services.auto_exit_service import seed_system_presets
import services.auto_buy_worker as auto_buy_worker
import services.auto_exit_worker as auto_exit_worker
import services.copy_trade_worker as copy_trade_worker
import services.wallet_discovery_worker as wallet_discovery_worker
import services.candle_sniper_worker as candle_sniper_worker
import services.watch_alert_worker as watch_alert_worker


# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=SQLiteStorage())

    # ── Database ───────────────────────────────────────────────────────────────
    await init_db()
    await seed_system_presets()   # built-in auto-exit presets

    # ── Routers ────────────────────────────────────────────────────────────────
    # Order matters: more specific routers must come before the catch-all callbacks router.
    dp.include_router(start.router)
    dp.include_router(help.router)
    dp.include_router(menu.router)
    dp.include_router(raid.router)          # raid:*    callbacks
    dp.include_router(raids.router)         # hub:*     callbacks + FSM
    dp.include_router(admin_raids.router)   # admin     commands
    dp.include_router(admin_user.router)    # /myid /adminuser /admingrant etc
    dp.include_router(profile.router)        # profile:* callbacks
    dp.include_router(auto_exit.router)      # ae:*      callbacks + FSM
    dp.include_router(sniper.router)         # sniper:*  callbacks + FSM
    dp.include_router(copy_trade.router)     # ct:*      callbacks + FSM
    dp.include_router(wallet_scout.router)   # ws:*      callbacks + FSM
    dp.include_router(candle_sniper.router)  # cs:*      callbacks + FSM (/candle_sniper)
    dp.include_router(tutorial.router)       # tut:*     User Tutorial
    dp.include_router(callbacks.router)      # menu:*    callbacks (last)

    # ── Startup Log ────────────────────────────────────────────────────────────
    bot_info = await bot.get_me()
    logger.info("=" * 54)
    logger.info("  Telegram Solana Trading Bot")
    logger.info(f"  Bot     : @{bot_info.username}  (ID: {bot_info.id})")
    logger.info(f"  Admins  : {settings.ADMIN_IDS or 'none configured'}")
    logger.info(f"  AutoApprove Raids : {settings.RAID_AUTO_APPROVE}")
    logger.info("=" * 54)

    # ── Background Tasks ───────────────────────────────────────────────────────
    ws_task = asyncio.create_task(pump_service.start())
    ab_task = asyncio.create_task(auto_buy_worker.start(bot))
    ae_task = asyncio.create_task(auto_exit_worker.start(bot))
    ct_task = asyncio.create_task(copy_trade_worker.start(bot))
    wd_task = asyncio.create_task(wallet_discovery_worker.start(bot))
    cs_task = asyncio.create_task(candle_sniper_worker.start(bot))
    wa_task  = asyncio.create_task(watch_alert_worker.start(bot))

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await pump_service.stop()
        auto_buy_worker.stop()
        auto_exit_worker.stop()
        copy_trade_worker.stop()
        wallet_discovery_worker.stop()
        candle_sniper_worker.stop()
        watch_alert_worker.stop()
        ws_task.cancel()
        ab_task.cancel()
        ae_task.cancel()
        ct_task.cancel()
        wd_task.cancel()
        cs_task.cancel()
        wa_task.cancel()
        await bot.session.close()
        logger.info("Bot shut down cleanly.")


if __name__ == "__main__":
    if sys.platform == "win32":
        # Windows ProactorEventLoop doesn't support async DNS — switch to SelectorEventLoop
        # which uses the system DNS thread pool correctly. Fixes "getaddrinfo failed" on Jupiter/aiohttp.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        logging.getLogger("asyncio").setLevel(logging.CRITICAL)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")
