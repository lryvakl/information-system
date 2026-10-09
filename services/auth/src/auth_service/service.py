"""Authorization use cases. Knows nothing about HTTP, SQL or cryptography details."""

import logging

from prometheus_client import Counter

from auth_service.domain import (
    InvalidCredentials,
    InvalidToken,
    Principal,
    Role,
    User,
    UserAlreadyExists,
)
from auth_service.repository import UserRepository
from auth_service.security import PasswordHasher, TokenService

logger = logging.getLogger(__name__)

LOGIN_ATTEMPTS = Counter("auth_login_attempts_total", "Login attempts.", ["result"])
TOKEN_VERIFICATIONS = Counter("auth_token_verifications_total", "Gateway token checks.", ["result"])

MIN_PASSWORD_LENGTH = 8


class AuthService:
    def __init__(self, users: UserRepository, hasher: PasswordHasher, tokens: TokenService) -> None:
        self._users = users
        self._hasher = hasher
        self._tokens = tokens
        # Verifying against a dummy hash for unknown users keeps response time
        # constant, so attackers cannot enumerate usernames by timing.
        self._dummy_hash = hasher.hash("timing-attack-guard")

    @property
    def token_ttl_seconds(self) -> int:
        return self._tokens.ttl_seconds

    def login(self, username: str, password: str) -> str:
        user = self._users.get(username)
        password_ok = self._hasher.verify(password, user.password_hash if user else self._dummy_hash)
        if user is None or not password_ok:
            LOGIN_ATTEMPTS.labels("failure").inc()
            logger.warning("Login failed", extra={"username": username})
            raise InvalidCredentials(username)
        LOGIN_ATTEMPTS.labels("success").inc()
        logger.info("Login succeeded", extra={"username": username, "role": user.role.value})
        return self._tokens.issue(Principal(user.username, user.role))

    def authenticate(self, token: str) -> Principal:
        try:
            principal = self._tokens.decode(token)
        except InvalidToken:
            TOKEN_VERIFICATIONS.labels("invalid").inc()
            raise
        TOKEN_VERIFICATIONS.labels("valid").inc()
        return principal

    def register(self, username: str, password: str, role: Role) -> User:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must have at least {MIN_PASSWORD_LENGTH} characters")
        user = User(username=username, password_hash=self._hasher.hash(password), role=role)
        self._users.add(user)
        logger.info("User registered", extra={"username": username, "role": role.value})
        return user

    def list_users(self) -> list[User]:
        return self._users.list()

    def ensure_admin(self, username: str, password: str) -> None:
        """Bootstrap the first administrator from configuration (idempotent)."""
        try:
            self.register(username, password, Role.ADMIN)
        except UserAlreadyExists:
            logger.info("Admin account already present", extra={"username": username})
