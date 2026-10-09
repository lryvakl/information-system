"""User storage. SQLite keeps the authorization server self-contained."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Protocol

from auth_service.domain import Role, User, UserAlreadyExists

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'engineer', 'viewer')),
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


class UserRepository(Protocol):
    def get(self, username: str) -> User | None: ...

    def add(self, user: User) -> None: ...

    def list(self) -> list[User]: ...


class SqliteUserRepository:
    def __init__(self, path: str) -> None:
        self._path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def get(self, username: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT username, password_hash, role, created_at FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        return _to_user(row) if row else None

    def add(self, user: User) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                    (user.username, user.password_hash, user.role.value),
                )
        except sqlite3.IntegrityError as exc:
            raise UserAlreadyExists(user.username) from exc

    def list(self) -> list[User]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT username, password_hash, role, created_at FROM users ORDER BY username"
            ).fetchall()
        return [_to_user(row) for row in rows]

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # One short-lived connection per call: safe across FastAPI worker threads.
        conn = sqlite3.connect(self._path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()


def _to_user(row: tuple[str, str, str, str]) -> User:
    username, password_hash, role, created_at = row
    return User(username, password_hash, Role(role), datetime.fromisoformat(created_at))
