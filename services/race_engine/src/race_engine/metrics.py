"""Prometheus metrics describing the live race state (what the pit wall sees)."""

from collections.abc import Sequence

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge, Histogram

from race_engine.domain.models import LapFrame, RaceInfo
from race_engine.domain.standings import StandingsUpdate
from race_engine.telemetry import TelemetrySample

_LAP_TIME_BUCKETS = (70, 75, 80, 85, 90, 95, 100, 105, 110, 120, 140)


class RaceMetrics:
    def __init__(self, registry: CollectorRegistry = REGISTRY) -> None:
        driver = ["driver", "team"]
        self.race_info = Gauge(
            "f1_race_info", "Race currently running.", ["race_id", "name", "circuit", "source"], registry=registry
        )
        self.current_lap = Gauge("f1_race_current_lap", "Current lap of the leader.", registry=registry)
        self.total_laps = Gauge("f1_race_total_laps", "Scheduled race distance in laps.", registry=registry)
        self.safety_car = Gauge("f1_safety_car_active", "1 while the safety car is deployed.", registry=registry)
        self.cars_running = Gauge("f1_cars_running", "Cars still running.", registry=registry)
        self.races_completed = Counter(
            "f1_races_completed_total", "Races run to the flag.", ["source"], registry=registry
        )

        self.position = Gauge("f1_position", "Race position.", driver, registry=registry)
        self.gap = Gauge("f1_gap_to_leader_seconds", "Gap to the race leader.", driver, registry=registry)
        self.last_lap = Gauge("f1_last_lap_seconds", "Last lap time.", driver, registry=registry)
        self.lap_time = Histogram(
            "f1_lap_time_seconds", "Lap time distribution.", ["driver"], buckets=_LAP_TIME_BUCKETS, registry=registry
        )
        self.tyre_wear = Gauge("f1_tyre_wear_percent", "Estimated tyre wear.", driver, registry=registry)
        self.tyre_age = Gauge("f1_tyre_age_laps", "Laps on the current set of tyres.", driver, registry=registry)
        self.pit_stops = Counter("f1_pit_stops_total", "Pit stops made.", driver, registry=registry)

        self.speed = Gauge("f1_car_speed_kmh", "Car speed.", driver, registry=registry)
        self.rpm = Gauge("f1_car_rpm", "Engine RPM.", driver, registry=registry)
        self.gear = Gauge("f1_car_gear", "Selected gear.", driver, registry=registry)
        self.throttle = Gauge("f1_car_throttle_percent", "Throttle application.", driver, registry=registry)
        self.tyre_temp = Gauge("f1_tyre_temperature_celsius", "Tyre surface temperature.", driver, registry=registry)
        self.fuel = Gauge("f1_fuel_kg", "Estimated fuel load.", driver, registry=registry)
        self.ers = Gauge("f1_ers_percent", "ERS battery state of charge.", driver, registry=registry)

        self._per_driver = (
            self.position,
            self.gap,
            self.last_lap,
            self.tyre_wear,
            self.tyre_age,
            self.speed,
            self.rpm,
            self.gear,
            self.throttle,
            self.tyre_temp,
            self.fuel,
            self.ers,
        )
        self._teams: dict[str, str] = {}

    def start_race(self, race_id: int, info: RaceInfo) -> None:
        # The grid may change between races (replays of other seasons): drop stale series.
        for gauge in (*self._per_driver, self.race_info):
            gauge.clear()
        self._teams = {driver.code: driver.team.name for driver in info.drivers}
        self.race_info.labels(str(race_id), info.name, info.circuit.name, info.source.value).set(1)
        self.total_laps.set(info.total_laps)
        self.current_lap.set(0)
        self.safety_car.set(0)
        self.cars_running.set(len(info.drivers))

    def record_lap(self, frame: LapFrame, standings: StandingsUpdate) -> None:
        self.current_lap.set(frame.lap)
        self.safety_car.set(int(frame.safety_car))
        self.cars_running.set(sum(not entry.retired for entry in standings.entries))
        for lap in frame.laps:
            labels = self._labels(lap.driver_code)
            self.last_lap.labels(*labels).set(lap.lap_time)
            self.lap_time.labels(lap.driver_code).observe(lap.lap_time)
            self.tyre_wear.labels(*labels).set(lap.tyre_wear)
            self.tyre_age.labels(*labels).set(lap.tyre_age)
            if lap.pit_stop:
                self.pit_stops.labels(*labels).inc()
        for entry in standings.entries:
            labels = self._labels(entry.driver_code)
            self.position.labels(*labels).set(entry.position)
            self.gap.labels(*labels).set(entry.gap_to_leader)
        for retirement in frame.retirements:
            labels = self._labels(retirement.driver_code)
            for gauge in (self.speed, self.rpm, self.gear, self.throttle):
                gauge.labels(*labels).set(0)

    def record_telemetry(self, samples: Sequence[TelemetrySample]) -> None:
        for sample in samples:
            labels = self._labels(sample.driver_code)
            self.speed.labels(*labels).set(sample.speed_kmh)
            self.rpm.labels(*labels).set(sample.rpm)
            self.gear.labels(*labels).set(sample.gear)
            self.throttle.labels(*labels).set(sample.throttle_pct)
            self.tyre_temp.labels(*labels).set(sample.tyre_temp_c)
            self.fuel.labels(*labels).set(sample.fuel_kg)
            self.ers.labels(*labels).set(sample.ers_pct)

    def finish_race(self, info: RaceInfo) -> None:
        self.races_completed.labels(info.source.value).inc()
        self.safety_car.set(0)

    def _labels(self, driver_code: str) -> tuple[str, str]:
        return driver_code, self._teams.get(driver_code, "Unknown")
