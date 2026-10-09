from pitwall_api.repository import PitwallRepository, Row


class RaceNotFound(Exception):
    pass


class PitwallService:
    def __init__(self, repository: PitwallRepository) -> None:
        self._repository = repository

    def races(self, limit: int) -> list[Row]:
        return self._repository.races(limit)

    def race(self, race_ref: str) -> Row:
        """``race_ref`` is a numeric id or ``latest``."""
        race = self._repository.race(self._resolve(race_ref))
        if race is None:
            raise RaceNotFound(race_ref)
        return race

    def standings(self, race_ref: str) -> list[Row]:
        return self._repository.standings(self.race(race_ref)["id"])

    def driver_laps(self, race_ref: str, driver_code: str) -> list[Row]:
        return self._repository.driver_laps(self.race(race_ref)["id"], driver_code)

    def pit_stops(self, race_ref: str) -> list[Row]:
        return self._repository.pit_stops(self.race(race_ref)["id"])

    def events(self, race_ref: str, event_type: str | None, limit: int) -> list[Row]:
        return self._repository.events(self.race(race_ref)["id"], event_type, limit)

    def championship(self) -> list[Row]:
        return self._repository.championship()

    def _resolve(self, race_ref: str) -> int:
        if race_ref == "latest":
            latest = self._repository.latest_race_id()
            if latest is None:
                raise RaceNotFound(race_ref)
            return latest
        if not race_ref.isdigit():
            raise RaceNotFound(race_ref)
        return int(race_ref)
