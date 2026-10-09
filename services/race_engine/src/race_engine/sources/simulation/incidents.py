"""Random race incidents: retirements, safety cars, track-limit violations."""

import random

_REASONS = ("Power Unit", "Gearbox", "Hydraulics", "Brakes", "Collision", "Accident", "Puncture damage")
_CRASH_REASONS = frozenset({"Collision", "Accident"})


class IncidentModel:
    def __init__(
        self,
        rng: random.Random,
        retirement_probability: float = 0.0012,
        track_limits_probability: float = 0.004,
    ) -> None:
        self._rng = rng
        self._retirement_probability = retirement_probability
        self._track_limits_probability = track_limits_probability

    def retirement_reason(self) -> str | None:
        if self._rng.random() < self._retirement_probability:
            return self._rng.choice(_REASONS)
        return None

    def causes_safety_car(self, reason: str) -> bool:
        return self._rng.random() < (0.8 if reason in _CRASH_REASONS else 0.25)

    def safety_car_duration(self) -> int:
        return self._rng.randint(3, 5)

    def track_limits_violation(self) -> bool:
        return self._rng.random() < self._track_limits_probability

    def corner(self) -> int:
        return self._rng.randint(1, 16)
