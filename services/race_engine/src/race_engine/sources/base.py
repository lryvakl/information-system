"""Race source abstraction (Strategy pattern).

The engine depends only on this protocol, so a new data source (e.g. a live
timing feed) can be added without touching the engine.
"""

import logging
from typing import Protocol

from race_engine.domain.models import RaceSession

logger = logging.getLogger(__name__)


class RaceSource(Protocol):
    def next_race(self) -> RaceSession: ...


class FallbackRaceSource:
    """Uses ``primary`` and silently degrades to ``fallback`` when it fails (e.g. no internet)."""

    def __init__(self, primary: RaceSource, fallback: RaceSource) -> None:
        self._primary = primary
        self._fallback = fallback

    def next_race(self) -> RaceSession:
        try:
            return self._primary.next_race()
        except Exception:
            logger.exception("Primary race source failed, falling back")
            return self._fallback.next_race()
