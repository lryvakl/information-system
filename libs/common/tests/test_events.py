from f1_common.events import (
    ClassificationEntry,
    EventType,
    PitStop,
    RaceFinished,
    deserialize,
    serialize,
)


def test_event_round_trip_keeps_concrete_type() -> None:
    event = PitStop(
        race_id=1,
        lap=15,
        driver="LEC",
        team="Ferrari",
        pit_lane_time=24.5,
        stationary_time=2.3,
        compound_out="HARD",
    )

    restored = deserialize(serialize(event))

    assert isinstance(restored, PitStop)
    assert restored == event
    assert restored.type is EventType.PIT_STOP
    assert restored.driver_code == "LEC"


def test_race_finished_carries_classification() -> None:
    event = RaceFinished(
        race_id=7,
        lap=53,
        classification=[
            ClassificationEntry(position=1, driver="LEC", team="Ferrari", laps=53, total_time=4800.1, finished=True),
        ],
        fastest_lap_driver="NOR",
    )

    restored = deserialize(serialize(event))

    assert isinstance(restored, RaceFinished)
    assert restored.classification[0].driver == "LEC"
    assert restored.driver_code is None
