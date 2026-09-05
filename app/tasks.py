"""Background task to expire stale sessions."""

import asyncio
import logging

from . import db
from .config import config

logger = logging.getLogger("analytics.tasks")

_SWEEP_INTERVAL_SECONDS = 60


async def sweep_loop() -> None:
    """Periodically mark sessions with no recent heartbeat as ended."""
    while True:
        try:
            ended = db.sweep_stale_sessions(config.SESSION_TIMEOUT_SECONDS, db.now())
            if ended:
                logger.info("Swept %d stale session(s)", ended)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sweep error: %s", exc)
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
