"""
Utility functions for WebSocket management.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from websockets.protocol import State

logger = logging.getLogger(__name__)


async def safe_close_websocket(
    ws: Any, name: str = "WebSocket", timeout: float = 3.0
) -> None:
    """Close ``ws`` if open, swallowing errors and bounding the close handshake."""
    if ws is None:
        logger.debug("%s is None, nothing to close", name)
        return

    try:
        state = ws.state
    except AttributeError:
        logger.debug("%s has no `state` attribute, attempting close anyway", name)
        state = None

    if state is not None and state != State.OPEN:
        logger.debug("%s is not OPEN (state=%s), skipping close", name, state)
        return

    logger.debug("Closing %s ...", name)
    try:
        await asyncio.wait_for(ws.close(), timeout=timeout)
        logger.debug("%s closed cleanly", name)
    except asyncio.TimeoutError:
        logger.warning("Timeout while closing %s after %.1fs", name, timeout)
    except Exception:  # pragma: no cover - best-effort cleanup
        logger.exception("Error while closing %s", name)

