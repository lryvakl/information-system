"""Composition root of the race engine."""

import logging
import threading
from datetime import timedelta

from f1_common.db import create_pool
from f1_common.lifecycle import on_shutdown
from f1_common.logging import configure_logging
from f1_common.messaging import RabbitMQPublisher
from f1_common.metrics import start_metrics_server
from f1_common.tracing import configure_tracing, shutdown_tracing
from race_engine.config import EngineSettings
from race_engine.engine import RaceEngine
from race_engine.metrics import RaceMetrics
from race_engine.pacing import RacePacer
from race_engine.repository import PostgresRaceRepository
from race_engine.sources.factory import build_race_source

logger = logging.getLogger(__name__)


def run() -> None:
    settings = EngineSettings()
    configure_logging(settings.service_name, settings.log_level)
    configure_tracing(settings)
    start_metrics_server(settings.metrics_port)

    stop = threading.Event()
    on_shutdown(stop.set)

    pool = create_pool(settings.database_url, settings.database_pool_size)
    publisher = RabbitMQPublisher(settings.amqp_url)
    engine = RaceEngine(
        source=build_race_source(settings),
        repository=PostgresRaceRepository(pool),
        publisher=publisher,
        metrics=RaceMetrics(),
        pacer=RacePacer(settings.speed_factor, settings.telemetry_tick_seconds, wait=stop.wait),
        stop_event=stop,
        telemetry_retention=timedelta(minutes=settings.telemetry_retention_minutes),
        pause_between_races=settings.pause_between_races_seconds,
    )
    logger.info("Race engine started", extra={"source": settings.race_source, "speed_factor": settings.speed_factor})
    try:
        engine.run_forever()
    finally:
        publisher.close()
        pool.close()
        shutdown_tracing()
        logger.info("Race engine stopped")
