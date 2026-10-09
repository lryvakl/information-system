"""Composition root of the Pit Wall API."""

from fastapi import FastAPI

from f1_common.db import create_pool
from f1_common.web import create_app, serve
from pitwall_api.api import race_not_found_handler, router
from pitwall_api.config import ApiSettings
from pitwall_api.repository import PitwallRepository, PostgresPitwallRepository
from pitwall_api.service import PitwallService, RaceNotFound


def build_app(settings: ApiSettings, repository: PitwallRepository | None = None) -> FastAPI:
    app = create_app(settings, title="F1 Pit Wall API", docs_url="/api/docs", openapi_url="/api/openapi.json")
    if repository is None:
        repository = PostgresPitwallRepository(create_pool(settings.database_url, settings.database_pool_size))
    app.state.pitwall_service = PitwallService(repository)
    app.add_exception_handler(RaceNotFound, race_not_found_handler)
    app.include_router(router)
    return app


def run() -> None:
    settings = ApiSettings()
    serve(build_app(settings), settings.port)
