from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pitwall_api.config import ApiSettings
from pitwall_api.main import build_app

GATEWAY_HEADERS = {"X-User": "toto", "X-Role": "engineer"}

RACE = {
    "id": 3,
    "name": "2024 Italian Grand Prix (replay)",
    "circuit": "Monza",
    "season": 2024,
    "total_laps": 53,
    "source": "REPLAY",
    "status": "RUNNING",
    "winner_code": None,
    "started_at": datetime(2026, 10, 9, tzinfo=UTC),
    "finished_at": None,
}
STANDING = {
    "position": 1,
    "driver_code": "LEC",
    "full_name": "Charles Leclerc",
    "team_name": "Ferrari",
    "team_colour": "#E80020",
    "laps": 20,
    "gap_s": 0,
    "last_lap_s": 83.8,
    "compound": "HARD",
    "tyre_age": 5,
    "tyre_wear": 8.0,
    "pit_stops": 1,
}


class FakeRepository:
    def races(self, limit: int) -> list[dict[str, Any]]:
        return [RACE][:limit]

    def race(self, race_id: int) -> dict[str, Any] | None:
        return RACE if race_id == RACE["id"] else None

    def latest_race_id(self) -> int | None:
        return RACE["id"]

    def standings(self, race_id: int) -> list[dict[str, Any]]:
        return [STANDING]

    def driver_laps(self, race_id: int, driver_code: str) -> list[dict[str, Any]]:
        return []

    def pit_stops(self, race_id: int) -> list[dict[str, Any]]:
        return []

    def events(self, race_id: int, event_type: str | None, limit: int) -> list[dict[str, Any]]:
        return []

    def championship(self) -> list[dict[str, Any]]:
        return [{"driver_code": "LEC", "team_name": "Ferrari", "points": 25, "wins": 1, "podiums": 1, "races": 1}]


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(ApiSettings(tracing_enabled=False), FakeRepository()))


def test_rejects_requests_that_bypass_the_gateway(client: TestClient) -> None:
    assert client.get("/api/races").status_code == 401


def test_lists_races(client: TestClient) -> None:
    response = client.get("/api/races", headers=GATEWAY_HEADERS)

    assert response.status_code == 200
    assert response.json()[0]["circuit"] == "Monza"


def test_latest_alias_resolves_to_newest_race(client: TestClient) -> None:
    response = client.get("/api/races/latest/standings", headers=GATEWAY_HEADERS)

    assert response.status_code == 200
    assert response.json()[0]["driver_code"] == "LEC"


@pytest.mark.parametrize("ref", ["999", "monza"])
def test_unknown_race_is_404(client: TestClient, ref: str) -> None:
    assert client.get(f"/api/races/{ref}", headers=GATEWAY_HEADERS).status_code == 404


def test_me_echoes_gateway_identity(client: TestClient) -> None:
    assert client.get("/api/me", headers=GATEWAY_HEADERS).json() == {"username": "toto", "role": "engineer"}


def test_championship(client: TestClient) -> None:
    assert client.get("/api/championship", headers=GATEWAY_HEADERS).json()[0]["points"] == "25"
