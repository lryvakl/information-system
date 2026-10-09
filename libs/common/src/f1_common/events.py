"""Integration events exchanged between services through RabbitMQ.

This module is the contract between the producer (race-engine) and consumers
(race-control). Events are immutable and self-describing via the ``type`` field.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class EventType(StrEnum):
    RACE_STARTED = "race.started"
    LAP_COMPLETED = "lap.completed"
    PIT_STOP = "pit.stop"
    OVERTAKE = "overtake"
    FASTEST_LAP = "fastest.lap"
    RACE_CONTROL = "race.control"
    RETIREMENT = "retirement"
    RACE_FINISHED = "race.finished"


class _Event(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: UUID = Field(default_factory=uuid4)
    race_id: int
    lap: int = Field(ge=0)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def driver_code(self) -> str | None:
        return getattr(self, "driver", None)


class RaceStarted(_Event):
    type: Literal[EventType.RACE_STARTED] = EventType.RACE_STARTED
    name: str
    circuit: str
    total_laps: int
    source: str
    drivers: list[str]


class LapCompleted(_Event):
    type: Literal[EventType.LAP_COMPLETED] = EventType.LAP_COMPLETED
    driver: str
    position: int
    lap_time: float
    gap_to_leader: float
    compound: str
    tyre_age: int
    tyre_wear: float


class PitStop(_Event):
    type: Literal[EventType.PIT_STOP] = EventType.PIT_STOP
    driver: str
    team: str
    pit_lane_time: float
    stationary_time: float | None
    compound_out: str


class Overtake(_Event):
    type: Literal[EventType.OVERTAKE] = EventType.OVERTAKE
    driver: str
    overtaken: str
    position: int


class FastestLap(_Event):
    type: Literal[EventType.FASTEST_LAP] = EventType.FASTEST_LAP
    driver: str
    lap_time: float


class RaceControl(_Event):
    type: Literal[EventType.RACE_CONTROL] = EventType.RACE_CONTROL
    category: str
    message: str
    flag: str | None = None


class Retirement(_Event):
    type: Literal[EventType.RETIREMENT] = EventType.RETIREMENT
    driver: str
    reason: str


class ClassificationEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    position: int
    driver: str
    team: str
    laps: int
    total_time: float | None
    finished: bool


class RaceFinished(_Event):
    type: Literal[EventType.RACE_FINISHED] = EventType.RACE_FINISHED
    classification: list[ClassificationEntry]
    fastest_lap_driver: str | None


RaceEvent = Annotated[
    RaceStarted | LapCompleted | PitStop | Overtake | FastestLap | RaceControl | Retirement | RaceFinished,
    Field(discriminator="type"),
]

_adapter: TypeAdapter[RaceEvent] = TypeAdapter(RaceEvent)


def serialize(event: RaceEvent) -> bytes:
    return event.model_dump_json().encode()


def deserialize(body: bytes) -> RaceEvent:
    return _adapter.validate_json(body)
