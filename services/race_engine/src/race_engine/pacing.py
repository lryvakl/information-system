"""Maps race time to wall-clock time (a 90 s lap at speed factor 20 takes 4.5 s)."""

from collections.abc import Callable, Iterator

# Returns True when the wait was interrupted (e.g. ``threading.Event.wait``).
Waiter = Callable[[float], bool]


class RacePacer:
    def __init__(self, speed_factor: float, tick_seconds: float, wait: Waiter) -> None:
        if speed_factor <= 0 or tick_seconds <= 0:
            raise ValueError("speed_factor and tick_seconds must be positive")
        self._speed_factor = speed_factor
        self._tick_seconds = tick_seconds
        self._wait = wait

    def ticks(self, race_seconds: float) -> Iterator[float]:
        """Yield lap progress in [0, 1) once per tick, sleeping in between."""
        real_seconds = race_seconds / self._speed_factor
        count = max(1, round(real_seconds / self._tick_seconds))
        for index in range(count):
            yield index / count
            if self._wait(real_seconds / count):
                return
