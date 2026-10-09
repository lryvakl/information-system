from race_engine.domain.models import Compound, DriverLap, PitStopInfo


def driver_lap(code: str, lap_time: float, pit: bool = False, compound: Compound = Compound.MEDIUM) -> DriverLap:
    return DriverLap(
        driver_code=code,
        lap_time=lap_time,
        sectors=(None, None, None),
        compound=compound,
        tyre_age=5,
        tyre_wear=10.0,
        fuel_kg=80.0,
        top_speed_kmh=330,
        pit_stop=PitStopInfo(22.0, 2.4, Compound.HARD) if pit else None,
    )
