"""Mapper tests on a small hand-made race in the exact OpenF1 record format."""

from datetime import datetime, timedelta

from race_engine.domain.models import Compound, RaceSourceKind
from race_engine.sources.openf1.mapper import OpenF1Mapper, OpenF1RaceData

START = datetime.fromisoformat("2024-09-01T13:03:00+00:00")
LAPS = 5


def _lap(number: int, lap: int, duration: float | None, started: datetime) -> dict:
    return {
        "driver_number": number,
        "lap_number": lap,
        "date_start": started.isoformat(),
        "lap_duration": duration,
        "duration_sector_1": 27.0,
        "duration_sector_2": 28.0,
        "duration_sector_3": 27.5,
        "st_speed": 340,
        "i1_speed": 320,
        "i2_speed": 330,
    }


def _laps_for(number: int, pace: float, count: int) -> list[dict]:
    records, clock = [], START
    for lap in range(1, count + 1):
        records.append(_lap(number, lap, None if lap == 1 else pace, clock))
        clock += timedelta(seconds=pace)
    return records


def _race() -> OpenF1RaceData:
    return OpenF1RaceData(
        session={"session_key": 9590, "year": 2024, "country_name": "Italy", "circuit_short_name": "Monza"},
        meeting={"meeting_name": "Italian Grand Prix"},
        drivers=[
            {
                "driver_number": 16,
                "name_acronym": "LEC",
                "first_name": "Charles",
                "last_name": "Leclerc",
                "team_name": "Ferrari",
                "team_colour": "E80020",
            },
            {
                "driver_number": 81,
                "name_acronym": "PIA",
                "full_name": "Oscar PIASTRI",
                "team_name": "McLaren",
                "team_colour": "FF8000",
            },
            {
                "driver_number": 1,
                "name_acronym": "VER",
                "first_name": "Max",
                "last_name": "Verstappen",
                "team_name": "Red Bull Racing",
                "team_colour": "3671C6",
            },
            {"driver_number": 16, "name_acronym": "LEC", "team_name": "Ferrari"},  # duplicates happen
        ],
        laps=_laps_for(16, 84.0, LAPS) + _laps_for(81, 84.5, LAPS) + _laps_for(1, 85.0, 2),
        pits=[
            {"driver_number": 16, "lap_number": 3, "lane_duration": 24.5, "pit_duration": 24.5, "stop_duration": None}
        ],
        stints=[
            {"driver_number": 16, "lap_start": 1, "lap_end": 3, "compound": "MEDIUM", "tyre_age_at_start": 0},
            {"driver_number": 16, "lap_start": 4, "lap_end": None, "compound": "HARD", "tyre_age_at_start": 0},
            {"driver_number": 81, "lap_start": 1, "lap_end": 5, "compound": "SOFT", "tyre_age_at_start": 2},
        ],
        race_control=[
            {
                "date": (START - timedelta(minutes=30)).isoformat(),
                "lap_number": 1,
                "category": "Other",
                "flag": None,
                "message": "RISK OF RAIN FOR F1 RACE IS 40 %",
            },
            {
                "date": (START + timedelta(seconds=200)).isoformat(),
                "lap_number": 3,
                "category": "SafetyCar",
                "flag": None,
                "message": "VIRTUAL SAFETY CAR DEPLOYED",
            },
            {
                "date": (START + timedelta(seconds=250)).isoformat(),
                "lap_number": 3,
                "category": "Flag",
                "flag": "BLUE",
                "message": "WAVED BLUE FLAG FOR CAR 1",
            },
            {
                "date": (START + timedelta(seconds=300)).isoformat(),
                "lap_number": 4,
                "category": "SafetyCar",
                "flag": None,
                "message": "VIRTUAL SAFETY CAR ENDING",
            },
            {
                "date": (START + timedelta(seconds=310)).isoformat(),
                "lap_number": 4,
                "category": "Other",
                "flag": None,
                "message": "CAR 81 (PIA) TIME 1:24.500 DELETED - TRACK LIMITS AT TURN 1",
            },
        ],
    )


def test_race_info_is_built_from_session_and_drivers() -> None:
    info = OpenF1Mapper().to_session(_race()).info

    assert info.name == "2024 Italian Grand Prix (replay)"
    assert info.source is RaceSourceKind.REPLAY
    assert info.total_laps == LAPS
    assert info.circuit.top_speed_kmh == 350  # known Monza profile
    assert [d.code for d in info.drivers] == ["LEC", "PIA", "VER"]
    assert info.driver("LEC").full_name == "Charles Leclerc"
    assert info.driver("PIA").full_name == "Oscar Piastri"
    assert info.driver("LEC").team.colour == "#E80020"


def test_frames_cover_every_lap_with_tyres_pits_and_retirements() -> None:
    frames = list(OpenF1Mapper().to_session(_race()).frames)

    assert [f.lap for f in frames] == [1, 2, 3, 4, 5]
    lap1 = {lap.driver_code: lap for lap in frames[0].laps}
    assert lap1["LEC"].lap_time == 84.0  # missing lap_duration derived from the next lap start
    assert lap1["PIA"].tyre_age == 2 and lap1["PIA"].compound is Compound.SOFT

    lec_lap3 = next(lap for lap in frames[2].laps if lap.driver_code == "LEC")
    assert lec_lap3.pit_stop is not None
    assert lec_lap3.pit_stop.compound_out is Compound.HARD
    assert lec_lap3.pit_stop.pit_lane_time == 24.5

    assert [r.driver_code for r in frames[2].retirements] == ["VER"]
    assert all(lap.driver_code != "VER" for lap in frames[2].laps)


def test_race_control_messages_and_safety_car_window() -> None:
    frames = list(OpenF1Mapper().to_session(_race()).frames)

    assert frames[0].messages == ()  # pre-race message filtered out
    assert [m.message for m in frames[2].messages] == ["VIRTUAL SAFETY CAR DEPLOYED"]  # blue flag dropped
    assert "TRACK LIMITS" in frames[3].messages[-1].message
    assert [f.safety_car for f in frames] == [False, False, True, True, False]
