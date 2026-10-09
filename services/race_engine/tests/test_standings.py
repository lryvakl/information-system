from race_engine_factories import driver_lap

from race_engine.domain.models import LapFrame, Retirement
from race_engine.domain.standings import StandingsCalculator


def test_orders_by_total_time_and_computes_gaps() -> None:
    calc = StandingsCalculator(["VER", "LEC", "HAM"])

    update = calc.apply(LapFrame(1, (driver_lap("VER", 90.0), driver_lap("LEC", 89.5), driver_lap("HAM", 91.0))))

    assert [e.driver_code for e in update.entries] == ["LEC", "VER", "HAM"]
    assert update.entry("VER").gap_to_leader == 0.5
    assert update.entry("HAM").interval == 1.0
    assert update.overtakes == ()  # no reference order before the first lap


def test_detects_on_track_overtake() -> None:
    calc = StandingsCalculator(["VER", "LEC"])
    calc.apply(LapFrame(1, (driver_lap("VER", 90.0), driver_lap("LEC", 90.3))))

    update = calc.apply(LapFrame(2, (driver_lap("VER", 90.0), driver_lap("LEC", 89.5))))

    assert len(update.overtakes) == 1
    overtake = update.overtakes[0]
    assert (overtake.driver_code, overtake.overtaken_code, overtake.position) == ("LEC", "VER", 1)


def test_position_changes_on_in_lap_and_out_lap_are_not_overtakes() -> None:
    calc = StandingsCalculator(["VER", "LEC", "HAM"])
    calc.apply(LapFrame(1, (driver_lap("VER", 90.0), driver_lap("LEC", 90.5), driver_lap("HAM", 108.5))))

    in_lap = calc.apply(
        LapFrame(2, (driver_lap("VER", 108.0, pit=True), driver_lap("LEC", 90.0), driver_lap("HAM", 90.0)))
    )
    out_lap = calc.apply(LapFrame(3, (driver_lap("VER", 95.0), driver_lap("LEC", 90.0), driver_lap("HAM", 90.0))))

    assert [e.driver_code for e in in_lap.entries] == ["LEC", "VER", "HAM"]
    assert in_lap.overtakes == ()
    assert [e.driver_code for e in out_lap.entries] == ["LEC", "HAM", "VER"]
    assert out_lap.overtakes == ()


def test_retired_driver_drops_to_the_back_without_overtakes() -> None:
    calc = StandingsCalculator(["VER", "LEC", "HAM"])
    calc.apply(LapFrame(1, (driver_lap("VER", 90.0), driver_lap("LEC", 90.5), driver_lap("HAM", 91.0))))

    update = calc.apply(
        LapFrame(2, (driver_lap("LEC", 90.0), driver_lap("HAM", 90.0)), retirements=(Retirement("VER", "Gearbox"),))
    )

    assert [e.driver_code for e in update.entries] == ["LEC", "HAM", "VER"]
    assert update.entries[-1].retired
    assert update.overtakes == ()


def test_reports_fastest_lap_only_when_improved() -> None:
    calc = StandingsCalculator(["VER", "LEC"])

    first = calc.apply(LapFrame(1, (driver_lap("VER", 90.0), driver_lap("LEC", 89.0))))
    second = calc.apply(LapFrame(2, (driver_lap("VER", 89.5), driver_lap("LEC", 89.6))))
    third = calc.apply(LapFrame(3, (driver_lap("VER", 88.1), driver_lap("LEC", 89.6))))

    assert first.new_fastest_lap is not None and first.new_fastest_lap.driver_code == "LEC"
    assert second.new_fastest_lap is None
    assert third.new_fastest_lap is not None and third.new_fastest_lap.lap_time == 88.1
