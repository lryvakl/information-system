"""Persistence of race data in PostgreSQL (create / insert / update / delete)."""

from collections.abc import Sequence
from datetime import timedelta
from typing import Protocol

from psycopg_pool import ConnectionPool

from f1_common.db import db_operation
from race_engine.domain.models import LapFrame, RaceInfo
from race_engine.domain.standings import StandingsUpdate
from race_engine.telemetry import TelemetrySample


class RaceRepository(Protocol):
    def abort_unfinished_races(self) -> int: ...

    def create_race(self, info: RaceInfo) -> int: ...

    def record_lap(self, race_id: int, frame: LapFrame, standings: StandingsUpdate) -> None: ...

    def record_telemetry(self, race_id: int, samples: Sequence[TelemetrySample]) -> None: ...

    def finish_race(self, race_id: int, winner_code: str) -> None: ...

    def abort_race(self, race_id: int) -> None: ...

    def purge_telemetry(self, older_than: timedelta) -> int: ...


def _ms(seconds: float | None) -> int | None:
    return None if seconds is None else round(seconds * 1000)


class PostgresRaceRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def abort_unfinished_races(self) -> int:
        """Races left RUNNING by a previous crash/restart can never finish."""
        with db_operation("UPDATE", "races"), self._pool.connection() as conn:
            cursor = conn.execute("UPDATE races SET status = 'ABORTED', finished_at = now() WHERE status = 'RUNNING'")
            return cursor.rowcount

    def create_race(self, info: RaceInfo) -> int:
        with db_operation("INSERT", "races"), self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO races (name, circuit, season, total_laps, source)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
                """,
                (info.name, info.circuit.name, info.season, info.total_laps, info.source.value),
            ).fetchone()
            race_id = int(row[0])  # type: ignore[index]
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO race_entries
                        (race_id, driver_code, driver_number, full_name, team_name, team_colour, grid_position)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (race_id, d.code, d.number, d.full_name, d.team.name, d.team.colour, grid)
                        for grid, d in enumerate(info.drivers, start=1)
                    ],
                )
        return race_id

    def record_lap(self, race_id: int, frame: LapFrame, standings: StandingsUpdate) -> None:
        lap_rows = []
        pit_rows = []
        for lap in frame.laps:
            entry = standings.entry(lap.driver_code)
            s1, s2, s3 = lap.sectors
            lap_rows.append(
                (
                    race_id,
                    lap.driver_code,
                    frame.lap,
                    _ms(lap.lap_time),
                    _ms(s1),
                    _ms(s2),
                    _ms(s3),
                    entry.position,
                    _ms(entry.gap_to_leader),
                    lap.compound.value,
                    lap.tyre_age,
                    lap.tyre_wear,
                    lap.top_speed_kmh,
                )
            )
            if lap.pit_stop:
                pit_rows.append(
                    (
                        race_id,
                        lap.driver_code,
                        frame.lap,
                        _ms(lap.pit_stop.pit_lane_time),
                        _ms(lap.pit_stop.stationary_time),
                        lap.pit_stop.compound_out.value,
                    )
                )

        with self._pool.connection() as conn, conn.cursor() as cursor:
            with db_operation("INSERT", "laps"):
                cursor.executemany(
                    """
                    INSERT INTO laps (race_id, driver_code, lap_number, lap_time_ms, sector1_ms, sector2_ms,
                                      sector3_ms, position, gap_to_leader_ms, compound, tyre_age, tyre_wear,
                                      top_speed_kmh)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    lap_rows,
                )
            if pit_rows:
                with db_operation("INSERT", "pit_stops"):
                    cursor.executemany(
                        """
                        INSERT INTO pit_stops (race_id, driver_code, lap_number, pit_lane_time_ms,
                                               stationary_time_ms, compound_out)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        pit_rows,
                    )

    def record_telemetry(self, race_id: int, samples: Sequence[TelemetrySample]) -> None:
        if not samples:
            return
        with (
            db_operation("INSERT", "telemetry", traced=False),
            self._pool.connection() as conn,
            conn.cursor() as cursor,
        ):
            cursor.executemany(
                """
                INSERT INTO telemetry (race_id, driver_code, speed_kmh, rpm, gear, throttle_pct,
                                       tyre_temp_c, fuel_kg, ers_pct)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        race_id,
                        s.driver_code,
                        s.speed_kmh,
                        s.rpm,
                        s.gear,
                        s.throttle_pct,
                        s.tyre_temp_c,
                        s.fuel_kg,
                        s.ers_pct,
                    )
                    for s in samples
                ],
            )

    def finish_race(self, race_id: int, winner_code: str) -> None:
        with db_operation("UPDATE", "races"), self._pool.connection() as conn:
            conn.execute(
                "UPDATE races SET status = 'FINISHED', winner_code = %s, finished_at = now() WHERE id = %s",
                (winner_code, race_id),
            )

    def abort_race(self, race_id: int) -> None:
        with db_operation("UPDATE", "races"), self._pool.connection() as conn:
            conn.execute(
                "UPDATE races SET status = 'ABORTED', finished_at = now() WHERE id = %s AND status = 'RUNNING'",
                (race_id,),
            )

    def purge_telemetry(self, older_than: timedelta) -> int:
        with db_operation("DELETE", "telemetry"), self._pool.connection() as conn:
            cursor = conn.execute("DELETE FROM telemetry WHERE recorded_at < now() - %s", (older_than,))
            return cursor.rowcount
