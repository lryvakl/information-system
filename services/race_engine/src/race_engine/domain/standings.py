"""Live classification: positions, gaps, on-track overtakes and fastest lap."""

from dataclasses import dataclass, field

from race_engine.domain.models import LapFrame


@dataclass(slots=True)
class _DriverState:
    code: str
    laps: int = 0
    total_time: float = 0.0
    last_lap: float | None = None
    retired: bool = False

    def sort_key(self) -> tuple[bool, int, float]:
        return (self.retired, -self.laps, self.total_time)


@dataclass(frozen=True, slots=True)
class StandingEntry:
    position: int
    driver_code: str
    laps: int
    total_time: float
    gap_to_leader: float
    interval: float
    last_lap: float | None
    retired: bool


@dataclass(frozen=True, slots=True)
class OvertakeRecord:
    driver_code: str
    overtaken_code: str
    position: int


@dataclass(frozen=True, slots=True)
class FastestLapRecord:
    driver_code: str
    lap_time: float


@dataclass(frozen=True, slots=True)
class StandingsUpdate:
    entries: tuple[StandingEntry, ...]
    overtakes: tuple[OvertakeRecord, ...] = ()
    new_fastest_lap: FastestLapRecord | None = None

    def entry(self, driver_code: str) -> StandingEntry:
        return next(e for e in self.entries if e.driver_code == driver_code)


@dataclass(slots=True)
class StandingsCalculator:
    driver_codes: list[str]
    _states: dict[str, _DriverState] = field(init=False)
    _previous_order: list[str] = field(init=False, default_factory=list)
    _previous_pitted: set[str] = field(init=False, default_factory=set)
    _fastest: FastestLapRecord | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self._states = {code: _DriverState(code) for code in self.driver_codes}

    @property
    def fastest_lap(self) -> FastestLapRecord | None:
        return self._fastest

    def apply(self, frame: LapFrame) -> StandingsUpdate:
        for lap in frame.laps:
            state = self._states[lap.driver_code]
            state.laps += 1
            state.total_time += lap.lap_time
            state.last_lap = lap.lap_time
        for retirement in frame.retirements:
            self._states[retirement.driver_code].retired = True

        order = self._order()
        pitted = {lap.driver_code for lap in frame.laps if lap.pit_stop}
        update = StandingsUpdate(
            entries=self._entries(order),
            # In-laps and out-laps are both slow, so ignore cars that pitted this or last lap.
            overtakes=self._detect_overtakes(order, pitted | self._previous_pitted),
            new_fastest_lap=self._update_fastest(frame),
        )
        self._previous_order = order
        self._previous_pitted = pitted
        return update

    def classification(self) -> tuple[StandingEntry, ...]:
        return self._entries(self._order())

    def _order(self) -> list[str]:
        return [s.code for s in sorted(self._states.values(), key=_DriverState.sort_key)]

    def _entries(self, order: list[str]) -> tuple[StandingEntry, ...]:
        leader = self._states[order[0]]
        entries: list[StandingEntry] = []
        ahead = leader
        for position, code in enumerate(order, start=1):
            state = self._states[code]
            entries.append(
                StandingEntry(
                    position=position,
                    driver_code=code,
                    laps=state.laps,
                    total_time=state.total_time,
                    gap_to_leader=max(0.0, state.total_time - leader.total_time),
                    interval=max(0.0, state.total_time - ahead.total_time),
                    last_lap=state.last_lap,
                    retired=state.retired,
                )
            )
            ahead = state
        return tuple(entries)

    def _detect_overtakes(self, order: list[str], pit_affected: set[str]) -> tuple[OvertakeRecord, ...]:
        """A pass counts only when both cars stayed out: pit-stop shuffles are not overtakes."""
        if not self._previous_order:
            return ()
        before = {code: index for index, code in enumerate(self._previous_order)}
        after = {code: index for index, code in enumerate(order)}
        overtakes = []
        for code in order:
            if code in pit_affected or self._states[code].retired:
                continue
            for other, other_before in before.items():
                passed = other_before < before[code] and after[other] > after[code]
                if passed and other not in pit_affected and not self._states[other].retired:
                    overtakes.append(OvertakeRecord(code, other, after[code] + 1))
        return tuple(overtakes)

    def _update_fastest(self, frame: LapFrame) -> FastestLapRecord | None:
        if not frame.laps:
            return None
        best = min(frame.laps, key=lambda lap: lap.lap_time)
        if self._fastest is None or best.lap_time < self._fastest.lap_time:
            self._fastest = FastestLapRecord(best.driver_code, best.lap_time)
            return self._fastest
        return None
