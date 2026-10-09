"""Tyre behaviour model shared by the simulator (physics) and replay (wear estimation)."""

from dataclasses import dataclass

from race_engine.domain.models import Compound


@dataclass(frozen=True, slots=True)
class CompoundSpec:
    pace_offset: float  # seconds vs. MEDIUM on a fresh set
    degradation: float  # seconds lost per lap of tyre age
    wear_per_lap: float  # % of tread lost per lap
    base_temperature: float  # typical operating temperature, Celsius


_SPECS: dict[Compound, CompoundSpec] = {
    Compound.SOFT: CompoundSpec(-0.65, 0.085, 3.4, 104.0),
    Compound.MEDIUM: CompoundSpec(0.0, 0.055, 2.3, 99.0),
    Compound.HARD: CompoundSpec(0.45, 0.035, 1.6, 94.0),
    Compound.INTERMEDIATE: CompoundSpec(4.0, 0.06, 2.0, 70.0),
    Compound.WET: CompoundSpec(7.0, 0.05, 1.6, 60.0),
}
_CLIFF_WEAR = 72.0
_CLIFF_PENALTY_PER_PERCENT = 0.09


class TyreModel:
    def __init__(self, stress: float = 1.0) -> None:
        self._stress = stress

    def spec(self, compound: Compound) -> CompoundSpec:
        return _SPECS.get(compound, _SPECS[Compound.MEDIUM])

    def wear(self, compound: Compound, age: int) -> float:
        return min(100.0, age * self.spec(compound).wear_per_lap * self._stress)

    def lap_time_penalty(self, compound: Compound, age: int) -> float:
        spec = self.spec(compound)
        cliff = max(0.0, self.wear(compound, age) - _CLIFF_WEAR) * _CLIFF_PENALTY_PER_PERCENT
        return spec.pace_offset + spec.degradation * age + cliff

    def laps_until_worn(self, compound: Compound, wear_limit: float) -> int:
        return int(wear_limit / (self.spec(compound).wear_per_lap * self._stress))

    def temperature(self, compound: Compound, age: int) -> float:
        return self.spec(compound).base_temperature + self.wear(compound, age) * 0.12
