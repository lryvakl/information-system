"""Replays real Grand Prix races (lap by lap) from OpenF1 historical data."""

import itertools
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from race_engine.domain.models import RaceSession
from race_engine.sources.openf1.client import OpenF1Client
from race_engine.sources.openf1.mapper import OpenF1Mapper, OpenF1RaceData

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReplayRace:
    year: int
    circuit: str  # OpenF1 ``circuit_short_name``, e.g. "Monza", "Silverstone"

    @classmethod
    def parse(cls, value: str) -> "ReplayRace":
        """'2024:Monza' -> ReplayRace(2024, 'Monza')."""
        year, circuit = value.split(":", 1)
        return cls(int(year), circuit.strip())


class OpenF1ReplaySource:
    def __init__(self, client: OpenF1Client, races: Sequence[ReplayRace], mapper: OpenF1Mapper | None = None) -> None:
        if not races:
            raise ValueError("At least one race to replay is required")
        self._client = client
        self._races = itertools.cycle(races)
        self._mapper = mapper or OpenF1Mapper()

    def next_race(self) -> RaceSession:
        race = next(self._races)
        logger.info("Loading race from OpenF1", extra={"year": race.year, "circuit": race.circuit})
        return self._mapper.to_session(self._load(race))

    def _load(self, race: ReplayRace) -> OpenF1RaceData:
        sessions = self._client.get("sessions", year=race.year, circuit_short_name=race.circuit, session_name="Race")
        if not sessions:
            raise LookupError(f"No OpenF1 race session for {race}")
        session = sessions[0]
        key = session["session_key"]
        meetings = self._client.get("meetings", meeting_key=session["meeting_key"])
        return OpenF1RaceData(
            session=session,
            meeting=meetings[0] if meetings else None,
            drivers=self._client.get("drivers", session_key=key),
            laps=self._client.get("laps", session_key=key),
            pits=self._client.get("pit", session_key=key),
            stints=self._client.get("stints", session_key=key),
            race_control=self._client.get("race_control", session_key=key),
        )
