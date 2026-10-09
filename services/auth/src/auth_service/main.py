"""Composition root: wires settings, infrastructure and the HTTP layer together."""

from datetime import timedelta

from fastapi import FastAPI

from auth_service.api import router
from auth_service.config import AuthSettings
from auth_service.repository import SqliteUserRepository
from auth_service.security import PasswordHasher, TokenService
from auth_service.service import AuthService
from f1_common.web import create_app, serve


def build_service(settings: AuthSettings, hasher: PasswordHasher | None = None) -> AuthService:
    return AuthService(
        users=SqliteUserRepository(settings.database_path),
        hasher=hasher or PasswordHasher(),
        tokens=TokenService(
            secret=settings.jwt_secret.get_secret_value(),
            algorithm=settings.jwt_algorithm,
            ttl=timedelta(minutes=settings.jwt_ttl_minutes),
        ),
    )


def build_app(settings: AuthSettings, service: AuthService | None = None) -> FastAPI:
    service = service or build_service(settings)
    service.ensure_admin(settings.admin_username, settings.admin_password.get_secret_value())

    app = create_app(settings, title="F1 Pit Wall - Auth", docs_url="/auth/docs", openapi_url="/auth/openapi.json")
    app.state.settings = settings
    app.state.auth_service = service
    app.include_router(router)
    return app


def run() -> None:
    settings = AuthSettings()  # type: ignore[call-arg]
    serve(build_app(settings), settings.port)
