"""Graceful shutdown for long-running worker processes."""

import logging
import signal
from collections.abc import Callable
from types import FrameType

logger = logging.getLogger(__name__)


def on_shutdown(callback: Callable[[], None]) -> None:
    """Invoke ``callback`` once on SIGTERM (docker stop) or SIGINT (Ctrl+C)."""

    def handler(signum: int, _frame: FrameType | None) -> None:
        logger.info("Shutdown signal received", extra={"signal": signal.Signals(signum).name})
        callback()

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)
