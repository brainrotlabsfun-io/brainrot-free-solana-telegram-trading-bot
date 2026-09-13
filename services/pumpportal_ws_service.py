"""
services/pumpportal_ws_service.py
===================================
PumpPortal WebSocket feed for new token launches.
Connects to: wss://pumpportal.fun/api/data

Subscribes to:
  - subscribeNewToken   — every new token mint on pump.fun

Usage:
    service = PumpPortalWSService()
    await service.start()
    # access service.recent_launches for buffered token data

To activate in main.py, call asyncio.create_task(service.start())
"""

import asyncio
import json
import logging
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)

WS_URL         = "wss://pumpportal.fun/api/data"
MAX_BUFFERED   = 200   # recent launch events to keep


class PumpPortalWSService:
    """
    Manages a persistent WebSocket connection to PumpPortal.
    Stores the N most recent token launch events in a deque.
    """

    def __init__(self):
        self.recent_launches: deque = deque(maxlen=MAX_BUFFERED)
        self._running = False
        self._ws = None

    async def start(self) -> None:
        """Main loop — reconnects automatically on disconnect."""
        self._running = True
        logger.info("PumpPortal WS service starting...")

        while self._running:
            try:
                await self._connect_and_listen()
            except Exception as exc:
                logger.warning(f"PumpPortal WS disconnected: {exc}. Reconnecting in 5s...")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()

    async def _connect_and_listen(self) -> None:
        try:
            import aiohttp
        except ImportError:
            logger.error("aiohttp not installed — PumpPortal WS unavailable")
            self._running = False
            return

        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(WS_URL, heartbeat=30) as ws:
                self._ws = ws
                logger.info("PumpPortal WS connected")

                # Subscribe to new token mints
                await ws.send_json({"method": "subscribeNewToken"})

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await self._handle_message(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break

    async def _handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        # New token event structure from PumpPortal
        if "mint" in data:
            token = {
                "address":                data.get("mint", ""),
                "name":                   data.get("name", "Unknown"),
                "symbol":                 data.get("symbol", "???"),
                "creator":                data.get("traderPublicKey", ""),
                "initial_buy":            data.get("initialBuy", 0),
                "market_cap":             data.get("marketCapSol", 0),
                # Bonding curve state — strongest quality signal for brand-new tokens
                "v_sol_in_bonding_curve": data.get("vSolInBondingCurve", 0),
                "v_tokens_in_bonding_curve": data.get("vTokensInBondingCurve", 0),
                "bonding_curve_key":      data.get("bondingCurveKey", ""),
                "uri":                    data.get("uri", ""),
                "source":                 "pumpportal",
                "age_minutes":            0,
                "liquidity_usd":          0,
                "volume_h1":              0,
                "buys_h1":                1,
                "sells_h1":               0,
            }
            self.recent_launches.appendleft(token)
            logger.debug(f"New token from PumpPortal: {token['symbol']} ({token['address'][:8]}...)")

    def get_recent(self, limit: int = 50) -> list[dict]:
        """Returns the N most recent launches from the buffer."""
        return list(self.recent_launches)[:limit]


# Singleton instance — import and use this across the app
pump_service = PumpPortalWSService()
