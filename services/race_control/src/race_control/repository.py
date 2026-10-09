from typing import Protocol

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from f1_common.db import db_operation
from f1_common.events import RaceEvent
from race_control.championship import ChampionshipResult


class RaceControlRepository(Protocol):
    def record_event(self, event: RaceEvent) -> None: ...

    def record_championship(self, race_id: int, results: list[ChampionshipResult]) -> None: ...


class PostgresRaceControlRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def record_event(self, event: RaceEvent) -> None:
        # ON CONFLICT makes redelivered messages harmless (at-least-once delivery).
        with db_operation("INSERT", "race_events"), self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO race_events (event_id, race_id, lap_number, event_type, driver_code, payload, occurred_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO NOTHING
                """,
                (
                    event.event_id,
                    event.race_id,
                    event.lap,
                    event.type.value,
                    event.driver_code,
                    Jsonb(event.model_dump(mode="json")),
                    event.occurred_at,
                ),
            )

    def record_championship(self, race_id: int, results: list[ChampionshipResult]) -> None:
        with (
            db_operation("INSERT", "championship_results"),
            self._pool.connection() as conn,
            conn.cursor() as cursor,
        ):
            cursor.executemany(
                """
                INSERT INTO championship_results (race_id, driver_code, team_name, position, points)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (race_id, driver_code) DO NOTHING
                """,
                [(race_id, r.driver_code, r.team_name, r.position, r.points) for r in results],
            )
