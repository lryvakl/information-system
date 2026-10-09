"""World Championship scoring rules."""

from dataclasses import dataclass

from f1_common.events import ClassificationEntry

POINTS_BY_POSITION = (25, 18, 15, 12, 10, 8, 6, 4, 2, 1)
FASTEST_LAP_BONUS = 1
FASTEST_LAP_BONUS_MAX_POSITION = 10


@dataclass(frozen=True, slots=True)
class ChampionshipResult:
    driver_code: str
    team_name: str
    position: int
    points: float


def score_race(classification: list[ClassificationEntry], fastest_lap_driver: str | None) -> list[ChampionshipResult]:
    results = []
    for entry in classification:
        points = 0.0
        if entry.finished and entry.position <= len(POINTS_BY_POSITION):
            points = POINTS_BY_POSITION[entry.position - 1]
        if entry.driver == fastest_lap_driver and entry.finished and entry.position <= FASTEST_LAP_BONUS_MAX_POSITION:
            points += FASTEST_LAP_BONUS
        results.append(ChampionshipResult(entry.driver, entry.team, entry.position, points))
    return results
