import logging

import pytest
from prometheus_client import CollectorRegistry

from f1_common.events import (
    ClassificationEntry,
    EventType,
    Overtake,
    PitStop,
    RaceEvent,
    RaceFinished,
)
from race_control.championship import ChampionshipResult, score_race
from race_control.dispatcher import EventDispatcher
from race_control.handlers import (
    ChampionshipHandler,
    CommentaryHandler,
    EventJournalHandler,
    RaceStatsHandler,
)


class FakeRepository:
    def __init__(self) -> None:
        self.events: list[RaceEvent] = []
        self.championship: dict[int, list[ChampionshipResult]] = {}

    def record_event(self, event: RaceEvent) -> None:
        self.events.append(event)

    def record_championship(self, race_id: int, results: list[ChampionshipResult]) -> None:
        self.championship[race_id] = results


def _entry(position: int, driver: str, finished: bool = True) -> ClassificationEntry:
    return ClassificationEntry(
        position=position,
        driver=driver,
        team="Team",
        laps=53,
        total_time=5000.0 if finished else None,
        finished=finished,
    )


def _finished(fastest: str | None) -> RaceFinished:
    classification = [_entry(i, f"D{i:02d}") for i in range(1, 12)] + [_entry(12, "DNF", finished=False)]
    return RaceFinished(race_id=1, lap=53, classification=classification, fastest_lap_driver=fastest)


def _pit_stop() -> PitStop:
    return PitStop(
        race_id=1, lap=20, driver="HAM", team="Mercedes", pit_lane_time=22.3, stationary_time=2.4, compound_out="HARD"
    )


def test_scoring_follows_f1_points_system() -> None:
    points = {r.driver_code: r.points for r in score_race(_finished(fastest="D03").classification, "D03")}

    assert points["D01"] == 25
    assert points["D02"] == 18
    assert points["D03"] == 16  # 15 + fastest lap bonus
    assert points["D10"] == 1
    assert points["D11"] == 0
    assert points["DNF"] == 0


def test_no_fastest_lap_bonus_outside_top_ten() -> None:
    points = {r.driver_code: r.points for r in score_race(_finished(fastest="D11").classification, "D11")}

    assert points["D11"] == 0


def test_dispatcher_routes_by_event_type() -> None:
    repository = FakeRepository()
    dispatch = EventDispatcher([EventJournalHandler(repository), ChampionshipHandler(repository)])

    dispatch(_pit_stop())
    dispatch(_finished(fastest=None))

    assert [e.type for e in repository.events] == [EventType.PIT_STOP, EventType.RACE_FINISHED]
    assert list(repository.championship) == [1]


def test_stats_handler_tracks_overtakes_and_pit_stops() -> None:
    registry = CollectorRegistry()
    stats = RaceStatsHandler(registry)

    stats.handle(Overtake(race_id=1, lap=5, driver="NOR", overtaken="VER", position=1))
    stats.handle(_pit_stop())

    assert registry.get_sample_value("f1_overtakes_total", {"driver": "NOR"}) == 1
    assert registry.get_sample_value("f1_pit_lane_time_seconds_count", {"team": "Mercedes"}) == 1
    assert registry.get_sample_value("f1_pit_stationary_time_seconds_sum", {"team": "Mercedes"}) == 2.4


def test_commentary_logs_readable_lines(caplog: pytest.LogCaptureFixture) -> None:
    handler = CommentaryHandler()

    with caplog.at_level(logging.INFO):
        handler.handle(Overtake(race_id=1, lap=5, driver="LEC", overtaken="VER", position=1))
        handler.handle(_pit_stop())

    assert "LEC overtakes VER for P1" in caplog.messages
    assert any(m.startswith("BOX BOX: HAM pits") for m in caplog.messages)
