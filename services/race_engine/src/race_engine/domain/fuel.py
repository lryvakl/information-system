FUEL_START_KG = 105.0
FUEL_EFFECT_PER_KG = 0.032  # seconds per lap per kg of fuel


def fuel_burn_per_lap(total_laps: int) -> float:
    return FUEL_START_KG / total_laps * 0.98


def fuel_after_lap(lap: int, total_laps: int) -> float:
    return max(0.0, FUEL_START_KG - fuel_burn_per_lap(total_laps) * lap)
