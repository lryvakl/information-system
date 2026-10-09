"""Synthetic race generator. Rotates through the circuit calendar forever."""

import itertools
import random
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from f1_common.formatting import format_lap_time
from race_engine.domain.fuel import FUEL_START_KG
from race_engine.domain.models import (
    Compound,
    Driver,
    DriverLap,
    LapFrame,
    PitStopInfo,
    RaceControlMessage,
    RaceInfo,
    RaceSession,
    RaceSourceKind,
    Retirement,
)
from race_engine.domain.tyres import TyreModel
from race_engine.sources.catalog import GRID, TRACKS, Track
from race_engine.sources.simulation.incidents import IncidentModel
from race_engine.sources.simulation.physics import LapTimeModel
from race_engine.sources.simulation.strategy import PitCrew, PitStrategy

SAFETY_CAR_PIT_LOSS_FACTOR = 0.55


@dataclass(slots=True)
class _Car:
    driver: Driver
    pace_offset: float
    compound: Compound
    pit_threshold: float
    fuel_kg: float = FUEL_START_KG
    tyre_age: int = 0
    total_time: float = 0.0
    retired: bool = False
    compounds_used: set[Compound] = field(default_factory=set)


class SimulatedRaceSource:
    def __init__(
        self,
        tracks: Sequence[Track] = TRACKS,
        grid: Sequence[tuple[Driver, float]] = GRID,
        season: int = 2024,
        seed: int | None = None,
    ) -> None:
        self._tracks = itertools.cycle(tracks)
        self._grid = grid
        self._season = season
        self._rng = random.Random(seed)

    def next_race(self) -> RaceSession:
        track = next(self._tracks)
        rng = random.Random(self._rng.random())
        simulation = _RaceSimulation(track, self._grid, rng)
        info = RaceInfo(
            name=f"{self._season} {track.grand_prix} (simulation)",
            season=self._season,
            circuit=track.circuit,
            total_laps=track.laps,
            source=RaceSourceKind.SIMULATION,
            drivers=simulation.starting_grid,
        )
        return RaceSession(info=info, frames=simulation.frames())


class _RaceSimulation:
    def __init__(self, track: Track, grid: Sequence[tuple[Driver, float]], rng: random.Random) -> None:
        self._track = track
        self._rng = rng
        self._tyres = TyreModel(stress=track.tyre_stress)
        self._physics = LapTimeModel(track, self._tyres, rng)
        self._strategy = PitStrategy(self._tyres, rng)
        self._crew = PitCrew(rng)
        self._incidents = IncidentModel(rng)
        self._safety_car_laps_left = 0
        self._cars = self._qualifying(grid)

    @property
    def starting_grid(self) -> tuple[Driver, ...]:
        return tuple(car.driver for car in self._cars)

    def frames(self) -> Iterator[LapFrame]:
        for lap in range(1, self._track.laps + 1):
            yield self._simulate_lap(lap)

    def _qualifying(self, grid: Sequence[tuple[Driver, float]]) -> list[_Car]:
        ranked = sorted(grid, key=lambda entry: entry[1] + self._rng.gauss(0.0, 0.15))
        cars = []
        for position, (driver, pace) in enumerate(ranked, start=1):
            compound = self._strategy.starting_compound(position)
            cars.append(_Car(driver, pace, compound, self._strategy.pit_threshold(), compounds_used={compound}))
        return cars

    def _simulate_lap(self, lap: int) -> LapFrame:
        messages: list[RaceControlMessage] = []
        if lap == 1:
            messages.append(RaceControlMessage("Flag", "GREEN LIGHT - RACE START", "GREEN"))

        retirements = self._retirements(messages)
        safety_car = self._safety_car_laps_left > 0
        laps = self._drive_lap(lap, safety_car, messages)
        self._advance_safety_car(messages)

        if lap == self._track.laps:
            messages.append(RaceControlMessage("Flag", "CHEQUERED FLAG", "CHEQUERED"))
        return LapFrame(lap, tuple(laps), tuple(retirements), tuple(messages), safety_car)

    def _running_cars(self) -> list[_Car]:
        return sorted((car for car in self._cars if not car.retired), key=lambda car: car.total_time)

    def _retirements(self, messages: list[RaceControlMessage]) -> list[Retirement]:
        retirements = []
        for car in self._running_cars():
            reason = self._incidents.retirement_reason()
            if reason is None:
                continue
            car.retired = True
            retirements.append(Retirement(car.driver.code, reason))
            messages.append(
                RaceControlMessage(
                    "CarEvent", f"CAR {car.driver.number} ({car.driver.code}) STOPPED - {reason.upper()}"
                )
            )
            if self._safety_car_laps_left == 0 and self._incidents.causes_safety_car(reason):
                self._safety_car_laps_left = self._incidents.safety_car_duration()
                messages.append(RaceControlMessage("SafetyCar", "SAFETY CAR DEPLOYED", "YELLOW"))
        return retirements

    def _drive_lap(self, lap: int, safety_car: bool, messages: list[RaceControlMessage]) -> list[DriverLap]:
        results = []
        car_ahead_total: float | None = None
        laps_remaining = self._track.laps - lap
        for car in self._running_cars():
            if safety_car:
                lap_time = self._physics.safety_car_lap(car.total_time, car_ahead_total)
            else:
                lap_time = self._physics.racing_lap(car.pace_offset, car.compound, car.tyre_age, car.fuel_kg, lap)
            car_ahead_total = car.total_time + lap_time

            compound, tyre_age = car.compound, car.tyre_age
            pit_stop = None
            if self._strategy.wants_pit(
                car.compound, car.tyre_age, car.compounds_used, laps_remaining, safety_car, car.pit_threshold
            ):
                pit_stop = self._pit(car, safety_car, laps_remaining)
                lap_time += pit_stop.pit_lane_time
            else:
                car.tyre_age += 1

            car.total_time += lap_time
            car.fuel_kg = max(0.0, car.fuel_kg - self._physics.fuel_burn_per_lap)
            results.append(
                DriverLap(
                    driver_code=car.driver.code,
                    lap_time=round(lap_time, 3),
                    sectors=self._physics.sectors(lap_time),
                    compound=compound,
                    tyre_age=tyre_age,
                    tyre_wear=round(self._tyres.wear(compound, tyre_age), 1),
                    fuel_kg=round(car.fuel_kg, 1),
                    top_speed_kmh=self._physics.top_speed(),
                    pit_stop=pit_stop,
                )
            )
            if not safety_car and self._incidents.track_limits_violation():
                messages.append(
                    RaceControlMessage(
                        "Other",
                        f"CAR {car.driver.number} ({car.driver.code}) TIME {format_lap_time(lap_time)} DELETED "
                        f"- TRACK LIMITS AT TURN {self._incidents.corner()}",
                    )
                )
        return results

    def _pit(self, car: _Car, safety_car: bool, laps_remaining: int) -> PitStopInfo:
        stationary = self._crew.stationary_time()
        lane_loss = self._track.pit_lane_loss * (SAFETY_CAR_PIT_LOSS_FACTOR if safety_car else 1.0)
        new_compound = self._strategy.choose_compound(car.compounds_used, laps_remaining)
        car.compound = new_compound
        car.tyre_age = 0
        car.compounds_used.add(new_compound)
        return PitStopInfo(round(lane_loss + stationary, 2), stationary, new_compound)

    def _advance_safety_car(self, messages: list[RaceControlMessage]) -> None:
        if self._safety_car_laps_left == 0:
            return
        self._safety_car_laps_left -= 1
        if self._safety_car_laps_left == 0:
            messages.append(RaceControlMessage("SafetyCar", "SAFETY CAR IN THIS LAP"))
            messages.append(RaceControlMessage("Flag", "TRACK CLEAR", "GREEN"))
