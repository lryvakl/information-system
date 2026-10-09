"""Static reference data: 2024 grid and circuits."""

from dataclasses import dataclass

from race_engine.domain.models import Circuit, Driver, Team

RED_BULL = Team("Red Bull Racing", "#3671C6")
FERRARI = Team("Ferrari", "#E8002D")
MERCEDES = Team("Mercedes", "#27F4D2")
MCLAREN = Team("McLaren", "#FF8000")
ASTON_MARTIN = Team("Aston Martin", "#229971")
ALPINE = Team("Alpine", "#FF87BC")
WILLIAMS = Team("Williams", "#64C4FF")
RB = Team("RB", "#6692FF")
SAUBER = Team("Kick Sauber", "#52E252")
HAAS = Team("Haas F1 Team", "#B6BABD")

# Driver -> pace offset in seconds per lap relative to the fastest car.
GRID: tuple[tuple[Driver, float], ...] = (
    (Driver("VER", 1, "Max Verstappen", RED_BULL), 0.00),
    (Driver("NOR", 4, "Lando Norris", MCLAREN), 0.05),
    (Driver("LEC", 16, "Charles Leclerc", FERRARI), 0.10),
    (Driver("PIA", 81, "Oscar Piastri", MCLAREN), 0.15),
    (Driver("SAI", 55, "Carlos Sainz", FERRARI), 0.20),
    (Driver("HAM", 44, "Lewis Hamilton", MERCEDES), 0.25),
    (Driver("RUS", 63, "George Russell", MERCEDES), 0.28),
    (Driver("PER", 11, "Sergio Perez", RED_BULL), 0.45),
    (Driver("ALO", 14, "Fernando Alonso", ASTON_MARTIN), 0.60),
    (Driver("HUL", 27, "Nico Hulkenberg", HAAS), 0.75),
    (Driver("GAS", 10, "Pierre Gasly", ALPINE), 0.80),
    (Driver("TSU", 22, "Yuki Tsunoda", RB), 0.82),
    (Driver("ALB", 23, "Alexander Albon", WILLIAMS), 0.85),
    (Driver("OCO", 31, "Esteban Ocon", ALPINE), 0.88),
    (Driver("STR", 18, "Lance Stroll", ASTON_MARTIN), 0.90),
    (Driver("MAG", 20, "Kevin Magnussen", HAAS), 0.95),
    (Driver("RIC", 3, "Daniel Ricciardo", RB), 0.98),
    (Driver("COL", 43, "Franco Colapinto", WILLIAMS), 1.05),
    (Driver("BOT", 77, "Valtteri Bottas", SAUBER), 1.20),
    (Driver("ZHO", 24, "Zhou Guanyu", SAUBER), 1.30),
)


@dataclass(frozen=True, slots=True)
class Track:
    circuit: Circuit
    grand_prix: str
    laps: int
    base_lap_time: float  # seconds, fastest car on fresh MEDIUM tyres with empty tank
    pit_lane_loss: float  # seconds lost driving through the pit lane
    tyre_stress: float  # multiplier for tyre wear


TRACKS: tuple[Track, ...] = (
    Track(Circuit("Monza", 80, 350), "Italian Grand Prix", 53, 81.5, 21.5, 0.9),
    Track(Circuit("Silverstone", 95, 330), "British Grand Prix", 52, 88.0, 20.0, 1.25),
    Track(Circuit("Spa-Francorchamps", 75, 340), "Belgian Grand Prix", 44, 106.0, 19.0, 1.1),
    Track(Circuit("Suzuka", 90, 320), "Japanese Grand Prix", 53, 92.5, 22.0, 1.3),
    Track(Circuit("Monte Carlo", 50, 290), "Monaco Grand Prix", 78, 74.5, 19.5, 0.7),
)

_CIRCUITS = {track.circuit.name.lower(): track.circuit for track in TRACKS}
DEFAULT_CIRCUIT_SPEEDS = (85, 330)


def circuit_by_name(name: str) -> Circuit:
    """Known circuit profile, or a generic one for circuits we have no data for."""
    low, high = DEFAULT_CIRCUIT_SPEEDS
    return _CIRCUITS.get(name.lower(), Circuit(name, low, high))
