from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class Race(BaseModel):
    id: int
    name: str
    circuit: str
    season: int
    total_laps: int
    source: str
    status: str
    winner_code: str | None
    started_at: datetime
    finished_at: datetime | None


class Standing(BaseModel):
    position: int
    driver_code: str
    full_name: str
    team_name: str
    team_colour: str
    laps: int
    gap_s: Decimal
    last_lap_s: Decimal
    compound: str
    tyre_age: int
    tyre_wear: Decimal
    pit_stops: int


class Lap(BaseModel):
    lap_number: int
    lap_time_s: Decimal
    position: int
    compound: str
    tyre_age: int
    tyre_wear: Decimal
    top_speed_kmh: int | None


class PitStopView(BaseModel):
    driver_code: str
    lap_number: int
    pit_lane_time_s: Decimal
    stationary_time_s: Decimal | None
    compound_out: str


class RaceEventView(BaseModel):
    event_type: str
    lap_number: int
    driver_code: str | None
    payload: dict
    occurred_at: datetime


class ChampionshipStanding(BaseModel):
    driver_code: str
    team_name: str
    points: Decimal
    wins: int
    podiums: int
    races: int


class Me(BaseModel):
    username: str
    role: str
