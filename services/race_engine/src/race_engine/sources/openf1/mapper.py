"""Maps raw OpenF1 records onto the source-agnostic race model.

Pure functions over already-downloaded data: no I/O, fully unit-testable.
Values OpenF1 does not publish (tyre wear, fuel) are estimated with the same
models the simulator uses.
"""

import statistics
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from race_engine.domain.fuel import fuel_after_lap
from race_engine.domain.models import (
    Compound,
    Driver,
    DriverLap,
    LapFrame,
    PitStopInfo,
    RaceControlMessage,
    RaceInfo,
    RaceSession,
    RaceSourceKind,
    Retirement,
    Team,
)
from race_engine.domain.tyres import TyreModel
from race_engine.sources.catalog import circuit_by_name

Record = dict[str, Any]

_RELEVANT_CATEGORIES = frozenset({"Flag", "SafetyCar", "CarEvent"})
_RELEVANT_KEYWORDS = ("PENALTY", "DELETED", "INVESTIGATION")
_IGNORED_FLAGS = frozenset({"BLUE"})
_RETIREMENT_MARGIN = timedelta(seconds=60)
_DEFAULT_LAP_TIME = 95.0


@dataclass(frozen=True, slots=True)
class OpenF1RaceData:
    session: Record
    meeting: Record | None
    drivers: list[Record]
    laps: list[Record]
    pits: list[Record]
    stints: list[Record]
    race_control: list[Record]


class OpenF1Mapper:
    def __init__(self, tyres: TyreModel | None = None) -> None:
        self._tyres = tyres or TyreModel()

    def to_session(self, data: OpenF1RaceData) -> RaceSession:
        timeline = _Timeline(data)
        return RaceSession(info=self._race_info(data, timeline), frames=self._frames(timeline))

    def _race_info(self, data: OpenF1RaceData, timeline: "_Timeline") -> RaceInfo:
        session = data.session
        meeting_name = (data.meeting or {}).get("meeting_name") or f"{session['country_name']} Grand Prix"
        return RaceInfo(
            name=f"{session['year']} {meeting_name} (replay)",
            season=int(session["year"]),
            circuit=circuit_by_name(session["circuit_short_name"]),
            total_laps=timeline.total_laps,
            source=RaceSourceKind.REPLAY,
            drivers=tuple(timeline.drivers.values()),
        )

    def _frames(self, timeline: "_Timeline") -> Iterator[LapFrame]:
        safety_car = False
        for lap in range(1, timeline.total_laps + 1):
            messages = timeline.messages.get(lap, ())
            if any("SAFETY CAR DEPLOYED" in m.message for m in messages):
                safety_car = True
            yield LapFrame(
                lap=lap,
                laps=tuple(
                    self._driver_lap(timeline, number, lap)
                    for number in timeline.drivers
                    if lap <= timeline.last_lap(number)
                ),
                retirements=tuple(
                    Retirement(timeline.drivers[number].code, "Retired")
                    for number, last_lap in timeline.retirements.items()
                    if last_lap + 1 == lap
                ),
                messages=tuple(messages),
                safety_car=safety_car,
            )
            if any(("IN THIS LAP" in m.message or "ENDING" in m.message) for m in messages):
                safety_car = False

    def _driver_lap(self, timeline: "_Timeline", number: int, lap: int) -> DriverLap:
        record = timeline.laps[number].get(lap, {})
        compound, tyre_age = timeline.tyre(number, lap)
        pit = timeline.pits.get((number, lap))
        pit_stop = None
        if pit is not None:
            pit_stop = PitStopInfo(
                pit_lane_time=float(pit.get("lane_duration") or pit.get("pit_duration") or 0.0),
                stationary_time=pit.get("stop_duration"),
                compound_out=timeline.tyre(number, lap + 1)[0],
            )
        top_speed = record.get("st_speed") or max(record.get("i1_speed") or 0, record.get("i2_speed") or 0)
        return DriverLap(
            driver_code=timeline.drivers[number].code,
            lap_time=round(timeline.lap_time(number, lap), 3),
            sectors=(
                record.get("duration_sector_1"),
                record.get("duration_sector_2"),
                record.get("duration_sector_3"),
            ),
            compound=compound,
            tyre_age=tyre_age,
            tyre_wear=round(self._tyres.wear(compound, tyre_age), 1),
            fuel_kg=round(fuel_after_lap(lap, timeline.total_laps), 1),
            top_speed_kmh=top_speed or None,
            pit_stop=pit_stop,
        )


class _Timeline:
    """Indexes raw OpenF1 records by driver and lap for fast lookups."""

    def __init__(self, data: OpenF1RaceData) -> None:
        self.drivers = _index_drivers(data.drivers)
        self.laps: dict[int, dict[int, Record]] = defaultdict(dict)
        for record in data.laps:
            if record["driver_number"] in self.drivers:
                self.laps[record["driver_number"]][record["lap_number"]] = record
        self.total_laps = max((lap for laps in self.laps.values() for lap in laps), default=0)
        self.pits = {(p["driver_number"], p["lap_number"]): p for p in data.pits if p.get("lap_number")}
        self._stints: dict[int, list[Record]] = defaultdict(list)
        for stint in data.stints:
            self._stints[stint["driver_number"]].append(stint)
        self.messages = _index_messages(data.race_control, self._race_start())
        self.retirements = self._detect_retirements()

    def last_lap(self, number: int) -> int:
        return max(self.laps[number], default=0)

    def lap_time(self, number: int, lap: int) -> float:
        record = self.laps[number].get(lap, {})
        if record.get("lap_duration"):
            return float(record["lap_duration"])
        start, next_start = (
            _parse(record.get("date_start")),
            _parse(self.laps[number].get(lap + 1, {}).get("date_start")),
        )
        if start and next_start:
            return (next_start - start).total_seconds()
        known = [r["lap_duration"] for r in self.laps[number].values() if r.get("lap_duration")]
        return statistics.median(known) if known else _DEFAULT_LAP_TIME

    def tyre(self, number: int, lap: int) -> tuple[Compound, int]:
        for stint in self._stints[number]:
            lap_end = stint.get("lap_end") or self.total_laps
            if stint["lap_start"] <= lap <= lap_end:
                return Compound.parse(stint.get("compound")), (stint.get("tyre_age_at_start") or 0) + lap - stint[
                    "lap_start"
                ]
        return Compound.UNKNOWN, 0

    def _race_start(self) -> datetime | None:
        starts = [_parse(laps[1].get("date_start")) for laps in self.laps.values() if 1 in laps]
        return min((s for s in starts if s), default=None)

    def _lap_end(self, number: int, lap: int) -> datetime | None:
        start = _parse(self.laps[number].get(lap, {}).get("date_start"))
        return start + timedelta(seconds=self.lap_time(number, lap)) if start else None

    def _detect_retirements(self) -> dict[int, int]:
        """Drivers whose last lap ended well before the chequered flag did not finish.

        Lapped cars also complete fewer laps, so lap count alone is not enough.
        """
        finish_times = [
            end
            for number in self.drivers
            if self.last_lap(number) == self.total_laps
            if (end := self._lap_end(number, self.total_laps))
        ]
        chequered = min(finish_times, default=None)
        retired = {}
        for number in self.drivers:
            last = self.last_lap(number)
            if last >= self.total_laps:
                continue
            last_end = self._lap_end(number, last) if last else None
            if chequered and last_end:
                is_retired = last_end < chequered - _RETIREMENT_MARGIN
            else:
                is_retired = last < self.total_laps - 3
            if is_retired:
                retired[number] = last
        return retired


def _index_drivers(records: list[Record]) -> dict[int, Driver]:
    drivers: dict[int, Driver] = {}
    for record in records:
        number = record["driver_number"]
        if number in drivers or not record.get("name_acronym"):
            continue
        name = " ".join(filter(None, (record.get("first_name"), record.get("last_name"))))
        colour = record.get("team_colour")
        drivers[number] = Driver(
            code=record["name_acronym"],
            number=number,
            full_name=name or str(record.get("full_name", "")).title(),
            team=Team(record.get("team_name") or "Unknown", f"#{colour}" if colour else "#888888"),
        )
    return drivers


def _index_messages(records: list[Record], race_start: datetime | None) -> dict[int, tuple[RaceControlMessage, ...]]:
    grouped: dict[int, list[RaceControlMessage]] = defaultdict(list)
    for record in sorted(records, key=lambda r: r.get("date") or ""):
        message = record.get("message") or ""
        relevant = (record.get("category") in _RELEVANT_CATEGORIES and record.get("flag") not in _IGNORED_FLAGS) or any(
            keyword in message for keyword in _RELEVANT_KEYWORDS
        )
        happened = _parse(record.get("date"))
        pre_race = race_start is not None and happened is not None and happened < race_start
        if relevant and not pre_race and record.get("lap_number"):
            grouped[record["lap_number"]].append(
                RaceControlMessage(record.get("category") or "Other", message, record.get("flag"))
            )
    return {lap: tuple(messages) for lap, messages in grouped.items()}


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
