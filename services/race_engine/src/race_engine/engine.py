"""Race engine: drives a race session lap by lap.

Depends only on abstractions (source, repository, publisher), so the same
orchestration runs a simulated race or a replay of a real one.
"""

import logging
import threading
from datetime import timedelta

from opentelemetry import trace

from f1_common.events import PitStop
from f1_common.formatting import format_lap_time
from f1_common.messaging import EventPublisher
from race_engine.domain.models import LapFrame, RaceInfo, RaceSession
from race_engine.domain.standings import StandingsCalculator, StandingsUpdate
from race_engine.event_factory import RaceEventFactory
from race_engine.metrics import RaceMetrics
from race_engine.pacing import RacePacer
from race_engine.repository import RaceRepository
from race_engine.sources.base import RaceSource
from race_engine.telemetry import TelemetrySynthesizer

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

PURGE_EVERY_LAPS = 10


class RaceEngine:
    def __init__(
        self,
        source: RaceSource,
        repository: RaceRepository,
        publisher: EventPublisher,
        metrics: RaceMetrics,
        pacer: RacePacer,
        stop_event: threading.Event,
        telemetry: TelemetrySynthesizer | None = None,
        events: RaceEventFactory | None = None,
        telemetry_retention: timedelta = timedelta(minutes=30),
        pause_between_races: float = 15.0,
    ) -> None:
        self._source = source
        self._repository = repository
        self._publisher = publisher
        self._metrics = metrics
        self._pacer = pacer
        self._stop = stop_event
        self._telemetry = telemetry or TelemetrySynthesizer()
        self._events = events or RaceEventFactory()
        self._telemetry_retention = telemetry_retention
        self._pause_between_races = pause_between_races

    def run_forever(self) -> None:
        aborted = self._repository.abort_unfinished_races()
        if aborted:
            logger.warning("Marked unfinished races as aborted", extra={"count": aborted})
        while not self._stop.is_set():
            self.run_race(self._source.next_race())
            self._stop.wait(self._pause_between_races)

    def run_race(self, session: RaceSession) -> int:
        info = session.info
        race_id = self._start(info)
        standings = StandingsCalculator([driver.code for driver in info.drivers])

        for frame in session.frames:
            if self._stop.is_set():
                self._repository.abort_race(race_id)
                logger.info("Race aborted on shutdown", extra={"race_id": race_id, "lap": frame.lap})
                return race_id
            self._process_lap(race_id, info, frame, standings)
            self._play_lap(race_id, info, frame)
            if frame.lap % PURGE_EVERY_LAPS == 0:
                self._purge_old_telemetry()

        self._finish(race_id, info, standings)
        return race_id

    def _start(self, info: RaceInfo) -> int:
        with _tracer.start_as_current_span("race.start", attributes={"race.name": info.name}):
            race_id = self._repository.create_race(info)
            self._publisher.publish(self._events.race_started(race_id, info))
        self._metrics.start_race(race_id, info)
        logger.info(
            "Lights out",
            extra={"race_id": race_id, "race": info.name, "laps": info.total_laps, "source": info.source.value},
        )
        return race_id

    def _process_lap(self, race_id: int, info: RaceInfo, frame: LapFrame, standings: StandingsCalculator) -> None:
        with _tracer.start_as_current_span(
            "race.lap", attributes={"race.id": race_id, "race.lap": frame.lap, "race.safety_car": frame.safety_car}
        ):
            update = standings.apply(frame)
            self._repository.record_lap(race_id, frame, update)
            for event in self._events.lap_events(race_id, info, frame, update):
                if isinstance(event, PitStop):
                    # Dedicated span: pit stops are easy to find in Tempo (name = "pit_stop").
                    with _tracer.start_as_current_span(
                        "pit_stop", attributes={"driver": event.driver, "pit.lane_time": event.pit_lane_time}
                    ):
                        self._publisher.publish(event)
                else:
                    self._publisher.publish(event)
            self._metrics.record_lap(frame, update)
        self._log_lap(frame, update)

    def _play_lap(self, race_id: int, info: RaceInfo, frame: LapFrame) -> None:
        """Stream telemetry while the lap 'runs' in accelerated real time."""
        for progress in self._pacer.ticks(frame.leader_lap_time):
            samples = [self._telemetry.sample(info.circuit, lap, progress, frame.safety_car) for lap in frame.laps]
            self._metrics.record_telemetry(samples)
            self._repository.record_telemetry(race_id, samples)

    def _finish(self, race_id: int, info: RaceInfo, standings: StandingsCalculator) -> None:
        classification = standings.classification()
        winner = classification[0].driver_code
        with _tracer.start_as_current_span("race.finish", attributes={"race.id": race_id, "race.winner": winner}):
            self._repository.finish_race(race_id, winner)
            self._publisher.publish(self._events.race_finished(race_id, info, classification, standings.fastest_lap))
        self._metrics.finish_race(info)
        logger.info("Chequered flag", extra={"race_id": race_id, "race": info.name, "winner": winner})

    def _purge_old_telemetry(self) -> None:
        deleted = self._repository.purge_telemetry(self._telemetry_retention)
        if deleted:
            logger.info("Old telemetry purged", extra={"rows": deleted})

    @staticmethod
    def _log_lap(frame: LapFrame, update: StandingsUpdate) -> None:
        leader = update.entries[0]
        logger.info(
            "Lap completed",
            extra={
                "lap": frame.lap,
                "leader": leader.driver_code,
                "leader_lap": format_lap_time(leader.last_lap) if leader.last_lap else None,
                "safety_car": frame.safety_car,
            },
        )
