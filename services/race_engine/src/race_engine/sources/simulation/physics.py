"""Simplified but plausible lap-time physics."""

import random

from race_engine.domain.fuel import FUEL_EFFECT_PER_KG, fuel_burn_per_lap
from race_engine.domain.models import Compound
from race_engine.domain.tyres import TyreModel
from race_engine.sources.catalog import Track

STANDING_START_PENALTY = 2.5
SAFETY_CAR_PACE = 1.35  # lap time multiplier behind the safety car
SAFETY_CAR_GAP = 0.9  # seconds between cars in the safety car train
_SECTOR_SPLIT = (0.32, 0.36, 0.32)


class LapTimeModel:
    def __init__(self, track: Track, tyres: TyreModel, rng: random.Random) -> None:
        self._track = track
        self._tyres = tyres
        self._rng = rng

    @property
    def fuel_burn_per_lap(self) -> float:
        return fuel_burn_per_lap(self._track.laps)

    def racing_lap(self, pace_offset: float, compound: Compound, tyre_age: int, fuel_kg: float, lap: int) -> float:
        lap_time = (
            self._track.base_lap_time
            + pace_offset
            + self._tyres.lap_time_penalty(compound, tyre_age)
            + fuel_kg * FUEL_EFFECT_PER_KG
            + self._rng.gauss(0.0, 0.22)
        )
        if lap == 1:
            lap_time += STANDING_START_PENALTY + self._rng.uniform(0.0, 1.5)
        return lap_time

    def safety_car_lap(self, total_time: float, car_ahead_total: float | None) -> float:
        """Behind the safety car the field bunches up: gaps shrink every lap."""
        sc_lap = self._track.base_lap_time * SAFETY_CAR_PACE + self._rng.gauss(0.0, 0.3)
        if car_ahead_total is None:
            return sc_lap
        natural_total = total_time + sc_lap
        desired_total = car_ahead_total + SAFETY_CAR_GAP
        new_total = desired_total + max(0.0, natural_total - desired_total) * 0.4
        return max(new_total - total_time, self._track.base_lap_time * 1.1)

    def sectors(self, lap_time: float) -> tuple[float, float, float]:
        weights = [share * self._rng.uniform(0.98, 1.02) for share in _SECTOR_SPLIT]
        scale = lap_time / sum(weights)
        s1, s2, s3 = (round(weight * scale, 3) for weight in weights)
        return s1, s2, s3

    def top_speed(self) -> int:
        return self._track.circuit.top_speed_kmh - self._rng.randint(0, 14)
