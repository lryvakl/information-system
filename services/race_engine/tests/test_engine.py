import threading
from collections import Counter
from collections.abc import Sequence
from datetime import timedelta

from prometheus_client import CollectorRegistry

from f1_common.events import EventType, RaceEvent, RaceFinished
from race_engine.domain.models import LapFrame, RaceInfo
from race_engine.domain.standings import StandingsUpdate
from race_engine.engine import RaceEngine
from race_engine.metrics import RaceMetrics
from race_engine.pacing import RacePacer
from race_engine.sources.catalog import TRACKS
from race_engine.sources.simulation import SimulatedRaceSource
from race_engine.telemetry import TelemetrySample


class InMemoryRepository:
    def __init__(self) -> None:
        self.races: dict[int, str] = {}
        self.laps = 0
        self.telemetry = 0

    def abort_unfinished_races(self) -> int:
        return 0

    def create_race(self, info: RaceInfo) -> int:
        race_id = len(self.races) + 1
        self.races[race_id] = "RUNNING"
        return race_id

    def record_lap(self, race_id: int, frame: LapFrame, standings: StandingsUpdate) -> None:
        self.laps += len(frame.laps)

    def record_telemetry(self, race_id: int, samples: Sequence[TelemetrySample]) -> None:
        self.telemetry += len(samples)

    def finish_race(self, race_id: int, winner_code: str) -> None:
        self.races[race_id] = f"FINISHED:{winner_code}"

    def abort_race(self, race_id: int) -> None:
        self.races[race_id] = "ABORTED"

    def purge_telemetry(self, older_than: timedelta) -> int:
        return 0


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[RaceEvent] = []

    def publish(self, event: RaceEvent) -> None:
        self.events.append(event)


def _engine(stop: threading.Event) -> tuple[RaceEngine, InMemoryRepository, RecordingPublisher]:
    repository, publisher = InMemoryRepository(), RecordingPublisher()
    engine = RaceEngine(
        source=SimulatedRaceSource(tracks=TRACKS[:1], seed=11),
        repository=repository,
        publisher=publisher,
        metrics=RaceMetrics(CollectorRegistry()),
        pacer=RacePacer(speed_factor=1000, tick_seconds=0.02, wait=lambda _: False),
        stop_event=stop,
    )
    return engine, repository, publisher


def test_runs_a_full_race_and_publishes_events() -> None:
    engine, repository, publisher = _engine(threading.Event())
    session = SimulatedRaceSource(tracks=TRACKS[:1], seed=11).next_race()

    race_id = engine.run_race(session)

    types = Counter(event.type for event in publisher.events)
    assert repository.races[race_id].startswith("FINISHED:")
    assert types[EventType.RACE_STARTED] == 1
    assert types[EventType.RACE_FINISHED] == 1
    assert types[EventType.LAP_COMPLETED] == repository.laps
    assert types[EventType.PIT_STOP] >= 15
    assert repository.telemetry > 0

    finished = publisher.events[-1]
    assert isinstance(finished, RaceFinished)
    assert finished.classification[0].finished
    assert repository.races[race_id] == f"FINISHED:{finished.classification[0].driver}"


def test_stop_signal_aborts_running_race() -> None:
    stop = threading.Event()
    engine, repository, publisher = _engine(stop)
    stop.set()

    race_id = engine.run_race(SimulatedRaceSource(tracks=TRACKS[:1], seed=1).next_race())

    assert repository.races[race_id] == "ABORTED"
    assert publisher.events[-1].type is EventType.RACE_STARTED


def test_pacer_spreads_lap_over_ticks() -> None:
    waits: list[float] = []
    pacer = RacePacer(speed_factor=20, tick_seconds=1.0, wait=lambda s: waits.append(s) or False)

    progress = list(pacer.ticks(80.0))

    assert progress == [0.0, 0.25, 0.5, 0.75]
    assert sum(waits) == 4.0
