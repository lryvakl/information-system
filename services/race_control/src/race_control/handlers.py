"""Event handlers. Each one has a single responsibility."""

import logging
from datetime import UTC, datetime

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Histogram

from f1_common.events import (
    EventType,
    FastestLap,
    Overtake,
    PitStop,
    RaceControl,
    RaceEvent,
    RaceFinished,
    RaceStarted,
    Retirement,
)
from f1_common.formatting import format_lap_time
from race_control.championship import score_race
from race_control.repository import RaceControlRepository

ALL_EVENTS = frozenset(EventType)


class EventJournalHandler:
    """Stores every event in PostgreSQL: the race log behind dashboards and the API."""

    handles = ALL_EVENTS

    def __init__(self, repository: RaceControlRepository) -> None:
        self._repository = repository

    def handle(self, event: RaceEvent) -> None:
        self._repository.record_event(event)


class ChampionshipHandler:
    """Awards championship points when a race is classified."""

    handles = frozenset({EventType.RACE_FINISHED})

    def __init__(self, repository: RaceControlRepository) -> None:
        self._repository = repository

    def handle(self, event: RaceEvent) -> None:
        if not isinstance(event, RaceFinished):
            return
        self._repository.record_championship(event.race_id, score_race(event.classification, event.fastest_lap_driver))


class CommentaryHandler:
    """Turns events into human-readable Race Control log lines (searchable in Loki)."""

    handles = frozenset(EventType) - {EventType.LAP_COMPLETED}

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._log = logger or logging.getLogger("race_control.commentary")

    def handle(self, event: RaceEvent) -> None:
        context = {"race_id": event.race_id, "lap": event.lap, "event_type": event.type.value}
        match event:
            case RaceStarted():
                self._log.info(f"LIGHTS OUT! {event.name}: {event.total_laps} laps at {event.circuit}", extra=context)
            case Overtake():
                self._log.info(
                    f"{event.driver} overtakes {event.overtaken} for P{event.position}",
                    extra={**context, "driver": event.driver},
                )
            case PitStop():
                stationary = f"{event.stationary_time:.1f}s stationary, " if event.stationary_time else ""
                self._log.info(
                    f"BOX BOX: {event.driver} pits ({stationary}{event.pit_lane_time:.1f}s in pit lane), "
                    f"fits {event.compound_out}",
                    extra={**context, "driver": event.driver, "team": event.team},
                )
            case FastestLap():
                self._log.info(
                    f"Fastest lap: {event.driver} {format_lap_time(event.lap_time)}",
                    extra={**context, "driver": event.driver},
                )
            case Retirement():
                self._log.warning(
                    f"{event.driver} is out of the race: {event.reason}", extra={**context, "driver": event.driver}
                )
            case RaceControl():
                level = (
                    logging.WARNING
                    if event.category == "SafetyCar" or event.flag in {"YELLOW", "RED"}
                    else logging.INFO
                )
                self._log.log(level, f"RACE CONTROL: {event.message}", extra={**context, "flag": event.flag})
            case RaceFinished():
                podium = ", ".join(f"P{e.position} {e.driver}" for e in event.classification[:3])
                self._log.info(f"CHEQUERED FLAG! Podium: {podium}", extra=context)


class RaceStatsHandler:
    """Event-derived Prometheus metrics."""

    handles = ALL_EVENTS

    def __init__(self, registry: CollectorRegistry = REGISTRY) -> None:
        self.overtakes = Counter("f1_overtakes_total", "On-track overtakes.", ["driver"], registry=registry)
        self.retirements = Counter("f1_retirements_total", "Retirements.", ["reason"], registry=registry)
        self.messages = Counter(
            "f1_race_control_messages_total", "Race Control messages.", ["category"], registry=registry
        )
        self.pit_lane_time = Histogram(
            "f1_pit_lane_time_seconds",
            "Time spent in the pit lane.",
            ["team"],
            buckets=(18, 19, 20, 21, 22, 23, 24, 25, 27, 30, 40),
            registry=registry,
        )
        self.stationary_time = Histogram(
            "f1_pit_stationary_time_seconds",
            "Car stationary in the pit box.",
            ["team"],
            buckets=(1.8, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0, 3.5, 4.0, 5.0, 8.0),
            registry=registry,
        )
        self.lag = Histogram(
            "f1_event_lag_seconds",
            "Delay between an event occurring and being processed.",
            ["type"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
            registry=registry,
        )

    def handle(self, event: RaceEvent) -> None:
        self.lag.labels(event.type.value).observe((datetime.now(UTC) - event.occurred_at).total_seconds())
        match event:
            case Overtake():
                self.overtakes.labels(event.driver).inc()
            case Retirement():
                self.retirements.labels(event.reason).inc()
            case RaceControl():
                self.messages.labels(event.category).inc()
            case PitStop():
                self.pit_lane_time.labels(event.team).observe(event.pit_lane_time)
                if event.stationary_time:
                    self.stationary_time.labels(event.team).observe(event.stationary_time)
