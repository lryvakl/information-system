"""Source-agnostic race model.

Both the simulator and the OpenF1 replay produce exactly these structures,
so everything downstream (standings, storage, events, metrics) is shared.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum


class Compound(StrEnum):
    SOFT = "SOFT"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    INTERMEDIATE = "INTERMEDIATE"
    WET = "WET"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def parse(cls, value: str | None) -> "Compound":
        try:
            return cls((value or "").upper())
        except ValueError:
            return cls.UNKNOWN


class RaceSourceKind(StrEnum):
    SIMULATION = "SIMULATION"
    REPLAY = "REPLAY"


@dataclass(frozen=True, slots=True)
class Team:
    name: str
    colour: str


@dataclass(frozen=True, slots=True)
class Driver:
    code: str
    number: int
    full_name: str
    team: Team


@dataclass(frozen=True, slots=True)
class Circuit:
    name: str
    min_speed_kmh: int
    top_speed_kmh: int


@dataclass(frozen=True, slots=True)
class RaceInfo:
    name: str
    season: int
    circuit: Circuit
    total_laps: int
    source: RaceSourceKind
    drivers: tuple[Driver, ...]

    def driver(self, code: str) -> Driver:
        return next(d for d in self.drivers if d.code == code)


@dataclass(frozen=True, slots=True)
class PitStopInfo:
    pit_lane_time: float
    stationary_time: float | None
    compound_out: Compound


@dataclass(frozen=True, slots=True)
class DriverLap:
    driver_code: str
    lap_time: float
    sectors: tuple[float | None, float | None, float | None]
    compound: Compound
    tyre_age: int
    tyre_wear: float
    fuel_kg: float
    top_speed_kmh: int | None
    pit_stop: PitStopInfo | None = None


@dataclass(frozen=True, slots=True)
class Retirement:
    driver_code: str
    reason: str


@dataclass(frozen=True, slots=True)
class RaceControlMessage:
    category: str
    message: str
    flag: str | None = None


@dataclass(frozen=True, slots=True)
class LapFrame:
    """Everything that happened during one race lap."""

    lap: int
    laps: tuple[DriverLap, ...]
    retirements: tuple[Retirement, ...] = ()
    messages: tuple[RaceControlMessage, ...] = ()
    safety_car: bool = False

    @property
    def leader_lap_time(self) -> float:
        return min((lap.lap_time for lap in self.laps), default=0.0)


@dataclass(frozen=True, slots=True)
class RaceSession:
    info: RaceInfo
    frames: Iterable[LapFrame] = field(repr=False)
