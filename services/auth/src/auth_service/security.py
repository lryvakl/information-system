"""Cryptographic primitives: password hashing and JWT issuing/validation."""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from auth_service.domain import InvalidToken, Principal, Role


class PasswordHasher:
    def __init__(self, rounds: int = 12) -> None:
        self._rounds = rounds

    def hash(self, password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt(self._rounds)).decode()

    def verify(self, password: str, password_hash: str) -> bool:
        return bcrypt.checkpw(password.encode(), password_hash.encode())


class TokenService:
    def __init__(self, secret: str, algorithm: str, ttl: timedelta) -> None:
        self._secret = secret
        self._algorithm = algorithm
        self._ttl = ttl

    @property
    def ttl_seconds(self) -> int:
        return int(self._ttl.total_seconds())

    def issue(self, principal: Principal) -> str:
        now = datetime.now(UTC)
        claims = {
            "sub": principal.username,
            "role": principal.role.value,
            "iat": now,
            "exp": now + self._ttl,
        }
        return jwt.encode(claims, self._secret, algorithm=self._algorithm)

    def decode(self, token: str) -> Principal:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                options={"require": ["sub", "role", "exp"]},
            )
            return Principal(username=claims["sub"], role=Role(claims["role"]))
        except (jwt.PyJWTError, ValueError) as exc:
            raise InvalidToken(str(exc)) from exc
