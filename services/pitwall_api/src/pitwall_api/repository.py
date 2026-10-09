"""Read-only queries. Connects with a SELECT-only database role."""

from typing import Any, Protocol

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from f1_common.db import db_operation

Row = dict[str, Any]


class PitwallRepository(Protocol):
    def races(self, limit: int) -> list[Row]: ...

    def race(self, race_id: int) -> Row | None: ...

    def latest_race_id(self) -> int | None: ...

    def standings(self, race_id: int) -> list[Row]: ...

    def driver_laps(self, race_id: int, driver_code: str) -> list[Row]: ...

    def pit_stops(self, race_id: int) -> list[Row]: ...

    def events(self, race_id: int, event_type: str | None, limit: int) -> list[Row]: ...

    def championship(self) -> list[Row]: ...


class PostgresPitwallRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def races(self, limit: int) -> list[Row]:
        return self._all("races", "SELECT * FROM races ORDER BY id DESC LIMIT %s", (limit,))

    def race(self, race_id: int) -> Row | None:
        rows = self._all("races", "SELECT * FROM races WHERE id = %s", (race_id,))
        return rows[0] if rows else None

    def latest_race_id(self) -> int | None:
        rows = self._all("races", "SELECT max(id) AS id FROM races", ())
        return rows[0]["id"] if rows else None

    def standings(self, race_id: int) -> list[Row]:
        return self._all("laps", "SELECT * FROM race_standings(%s)", (race_id,))

    def driver_laps(self, race_id: int, driver_code: str) -> list[Row]:
        return self._all(
            "laps",
            """
            SELECT lap_number, round(lap_time_ms / 1000.0, 3) AS lap_time_s, position, compound,
                   tyre_age, tyre_wear, top_speed_kmh
            FROM laps WHERE race_id = %s AND driver_code = %s ORDER BY lap_number
            """,
            (race_id, driver_code.upper()),
        )

    def pit_stops(self, race_id: int) -> list[Row]:
        return self._all(
            "pit_stops",
            """
            SELECT driver_code, lap_number, round(pit_lane_time_ms / 1000.0, 2) AS pit_lane_time_s,
                   round(stationary_time_ms / 1000.0, 2) AS stationary_time_s, compound_out
            FROM pit_stops WHERE race_id = %s ORDER BY lap_number, pit_lane_time_ms
            """,
            (race_id,),
        )

    def events(self, race_id: int, event_type: str | None, limit: int) -> list[Row]:
        return self._all(
            "race_events",
            """
            SELECT event_type, lap_number, driver_code, payload, occurred_at
            FROM race_events
            WHERE race_id = %s AND (%s::text IS NULL OR event_type = %s)
            ORDER BY occurred_at DESC LIMIT %s
            """,
            (race_id, event_type, event_type, limit),
        )

    def championship(self) -> list[Row]:
        return self._all("championship_results", "SELECT * FROM v_championship", ())

    def _all(self, table: str, query: str, params: tuple[Any, ...]) -> list[Row]:
        with (
            db_operation("SELECT", table),
            self._pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cursor,
        ):
            return cursor.execute(query, params).fetchall()
