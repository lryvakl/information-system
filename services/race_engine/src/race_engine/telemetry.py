"""Synthesizes high-frequency car telemetry between lap timing points.

Lap timing (real or simulated) has one sample per lap; dashboards need a
continuous signal, so speed/RPM/throttle are derived from a circuit profile.
"""

import math
import random
import zlib
from dataclasses import dataclass

from race_engine.domain.models import Circuit, DriverLap
from race_engine.domain.tyres import TyreModel

_CORNERS_PER_LAP = 7
_SAFETY_CAR_SPEED_FACTOR = 0.6
_GEARS = 8


@dataclass(frozen=True, slots=True)
class TelemetrySample:
    driver_code: str
    speed_kmh: int
    rpm: int
    gear: int
    throttle_pct: int
    tyre_temp_c: float
    fuel_kg: float
    ers_pct: int


class TelemetrySynthesizer:
    def __init__(self, tyres: TyreModel | None = None, rng: random.Random | None = None) -> None:
        self._tyres = tyres or TyreModel()
        self._rng = rng or random.Random()

    def sample(self, circuit: Circuit, lap: DriverLap, progress: float, safety_car: bool) -> TelemetrySample:
        # Each car is at a slightly different point of the lap.
        position = (progress + (zlib.crc32(lap.driver_code.encode()) % 100) / 2000) % 1.0
        straight = 0.5 + 0.5 * math.cos(2 * math.pi * _CORNERS_PER_LAP * position)  # 1 = straight, 0 = apex

        top_speed = lap.top_speed_kmh or circuit.top_speed_kmh
        speed = circuit.min_speed_kmh + (top_speed - circuit.min_speed_kmh) * straight**0.7
        if safety_car:
            speed *= _SAFETY_CAR_SPEED_FACTOR
        speed = max(60.0, speed + self._rng.gauss(0, 3))

        gear = min(_GEARS, max(1, 1 + int((speed - 60) / ((top_speed - 60) / (_GEARS - 1)))))
        return TelemetrySample(
            driver_code=lap.driver_code,
            speed_kmh=round(speed),
            rpm=round(10_200 + 1_900 * straight + self._rng.gauss(0, 150)),
            gear=gear,
            throttle_pct=round(min(100.0, max(0.0, 15 + 95 * straight))),
            tyre_temp_c=round(self._tyres.temperature(lap.compound, lap.tyre_age) + 8 * (1 - straight), 1),
            fuel_kg=lap.fuel_kg,
            ers_pct=round(50 + 45 * math.sin(2 * math.pi * position)),
        )
