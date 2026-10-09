"""Pit-wall decisions: when to stop and which tyres to fit."""

import random

from race_engine.domain.models import Compound
from race_engine.domain.tyres import TyreModel

DRY_COMPOUNDS = (Compound.SOFT, Compound.MEDIUM, Compound.HARD)
STINT_WEAR_LIMIT = 85.0
SAFETY_CAR_PIT_WEAR = 30.0


class PitStrategy:
    def __init__(self, tyres: TyreModel, rng: random.Random) -> None:
        self._tyres = tyres
        self._rng = rng

    def pit_threshold(self) -> float:
        """Each team runs its tyres to a slightly different wear level."""
        return self._rng.uniform(60.0, 75.0)

    def starting_compound(self, grid_position: int) -> Compound:
        if grid_position <= 10:
            return Compound.MEDIUM if self._rng.random() < 0.8 else Compound.SOFT
        return self._rng.choice(DRY_COMPOUNDS)

    def wants_pit(
        self,
        compound: Compound,
        tyre_age: int,
        compounds_used: set[Compound],
        laps_remaining: int,
        safety_car: bool,
        threshold: float,
    ) -> bool:
        if laps_remaining <= 1:
            return False
        wear = self._tyres.wear(compound, tyre_age)
        if safety_car and wear > SAFETY_CAR_PIT_WEAR and laps_remaining > 5:
            return True  # a "cheap" stop under the safety car
        if wear >= threshold:
            return True
        # Dry-race rule: at least two different compounds must be used.
        return len(compounds_used) < 2 and laps_remaining <= 3

    def choose_compound(self, compounds_used: set[Compound], laps_remaining: int) -> Compound:
        lasting = [c for c in DRY_COMPOUNDS if self._tyres.laps_until_worn(c, STINT_WEAR_LIMIT) >= laps_remaining]
        if not lasting:
            return Compound.HARD  # nothing reaches the flag: another stop will follow
        if len(compounds_used) < 2:
            lasting = [c for c in lasting if c not in compounds_used] or lasting
        return min(lasting, key=lambda c: self._tyres.spec(c).pace_offset)


class PitCrew:
    def __init__(self, rng: random.Random, slow_stop_probability: float = 0.06) -> None:
        self._rng = rng
        self._slow_stop_probability = slow_stop_probability

    def stationary_time(self) -> float:
        duration = max(1.9, self._rng.gauss(2.45, 0.25))
        if self._rng.random() < self._slow_stop_probability:
            duration += self._rng.uniform(1.5, 7.0)  # wheel-gun problem
        return round(duration, 2)
