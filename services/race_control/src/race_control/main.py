"""Composition root of Race Control."""

import logging

from f1_common.db import create_pool
from f1_common.lifecycle import on_shutdown
from f1_common.logging import configure_logging
from f1_common.messaging import RabbitMQConsumer
from f1_common.metrics import start_metrics_server
from f1_common.tracing import configure_tracing, shutdown_tracing
from race_control.config import RaceControlSettings
from race_control.dispatcher import EventDispatcher
from race_control.handlers import ChampionshipHandler, CommentaryHandler, EventJournalHandler, RaceStatsHandler
from race_control.repository import PostgresRaceControlRepository

logger = logging.getLogger(__name__)


def run() -> None:
    settings = RaceControlSettings()
    configure_logging(settings.service_name, settings.log_level)
    configure_tracing(settings)
    start_metrics_server(settings.metrics_port)

    pool = create_pool(settings.database_url, settings.database_pool_size)
    repository = PostgresRaceControlRepository(pool)
    dispatcher = EventDispatcher(
        [
            EventJournalHandler(repository),
            ChampionshipHandler(repository),
            CommentaryHandler(),
            RaceStatsHandler(),
        ]
    )
    consumer = RabbitMQConsumer(settings.amqp_url, settings.queue_name, prefetch=settings.prefetch_count)
    on_shutdown(consumer.stop)

    logger.info("Race Control online", extra={"queue": settings.queue_name})
    try:
        consumer.run(dispatcher)
    finally:
        pool.close()
        shutdown_tracing()
        logger.info("Race Control stopped")
