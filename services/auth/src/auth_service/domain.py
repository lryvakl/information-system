from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    ENGINEER = "engineer"
    VIEWER = "viewer"

    @property
    def grafana_role(self) -> str:
        return _GRAFANA_ROLES[self]

    def grants(self, required: "Role") -> bool:
        return _RANK[self] >= _RANK[required]


_GRAFANA_ROLES = {Role.ADMIN: "Admin", Role.ENGINEER: "Editor", Role.VIEWER: "Viewer"}
_RANK = {Role.VIEWER: 0, Role.ENGINEER: 1, Role.ADMIN: 2}


@dataclass(frozen=True, slots=True)
class User:
    username: str
    password_hash: str
    role: Role
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Principal:
    """Authenticated identity extracted from a valid token."""

    username: str
    role: Role


class AuthError(Exception):
    """Base class for authorization failures."""


class InvalidCredentials(AuthError):
    pass


class InvalidToken(AuthError):
    pass


class UserAlreadyExists(AuthError):
    pass
