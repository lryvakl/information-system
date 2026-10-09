"""RabbitMQ publisher/consumer with W3C trace-context propagation.

The producer injects the current trace context into AMQP headers and the
consumer continues the same trace, so one trace in Tempo spans
race-engine -> RabbitMQ -> race-control -> PostgreSQL.

Messages that cannot be processed are rejected into a dead-letter queue
instead of being redelivered forever.
"""

import logging
import time
from collections.abc import Callable
from typing import Protocol

import pika
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind
from pika.adapters.blocking_connection import BlockingChannel
from pika.exceptions import AMQPConnectionError, AMQPError
from pika.spec import Basic, BasicProperties
from prometheus_client import Counter, Histogram
from pydantic import ValidationError

from f1_common.events import RaceEvent, deserialize, serialize

EXCHANGE = "race.events"
DEAD_LETTER_EXCHANGE = "race.events.dlx"

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

MESSAGES_PUBLISHED = Counter("app_mq_messages_published_total", "Messages published to RabbitMQ.", ["routing_key"])
MESSAGES_CONSUMED = Counter("app_mq_messages_consumed_total", "Messages consumed from RabbitMQ.", ["type", "status"])
MESSAGE_PROCESSING = Histogram(
    "app_mq_message_processing_seconds",
    "Time spent handling a consumed message.",
    ["type"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

EventHandler = Callable[[RaceEvent], None]


class EventPublisher(Protocol):
    def publish(self, event: RaceEvent) -> None: ...


def _connect(url: str, attempts: int = 30, delay: float = 2.0) -> pika.BlockingConnection:
    parameters = pika.URLParameters(url)
    for attempt in range(1, attempts + 1):
        try:
            return pika.BlockingConnection(parameters)
        except AMQPConnectionError:
            logger.warning("RabbitMQ not reachable", extra={"attempt": attempt})
            time.sleep(delay)
    raise ConnectionError(f"RabbitMQ unreachable after {attempts} attempts")


def _declare_topology(channel: BlockingChannel) -> None:
    channel.exchange_declare(EXCHANGE, exchange_type="topic", durable=True)
    channel.exchange_declare(DEAD_LETTER_EXCHANGE, exchange_type="fanout", durable=True)


class RabbitMQPublisher:
    def __init__(self, url: str) -> None:
        self._url = url
        self._connection: pika.BlockingConnection | None = None
        self._channel: BlockingChannel | None = None

    def publish(self, event: RaceEvent) -> None:
        routing_key = event.type.value
        with _tracer.start_as_current_span(
            f"publish {routing_key}",
            kind=SpanKind.PRODUCER,
            attributes={
                "messaging.system": "rabbitmq",
                "messaging.destination.name": EXCHANGE,
                "messaging.rabbitmq.destination.routing_key": routing_key,
            },
        ):
            headers: dict[str, str] = {}
            propagate.inject(headers)
            properties = BasicProperties(
                content_type="application/json",
                delivery_mode=pika.DeliveryMode.Persistent,
                message_id=str(event.event_id),
                type=routing_key,
                headers=headers,
            )
            self._publish_with_retry(routing_key, serialize(event), properties)
        MESSAGES_PUBLISHED.labels(routing_key).inc()

    def close(self) -> None:
        if self._connection and self._connection.is_open:
            self._connection.close()

    def _publish_with_retry(self, routing_key: str, body: bytes, props: BasicProperties) -> None:
        try:
            self._ensure_channel().basic_publish(EXCHANGE, routing_key, body, props)
        except AMQPError:
            logger.warning("Publish failed, reconnecting to RabbitMQ")
            self._channel = None
            self._ensure_channel().basic_publish(EXCHANGE, routing_key, body, props)

    def _ensure_channel(self) -> BlockingChannel:
        if self._channel is None or self._channel.is_closed:
            self.close()
            self._connection = _connect(self._url)
            self._channel = self._connection.channel()
            _declare_topology(self._channel)
        return self._channel


class RabbitMQConsumer:
    def __init__(
        self,
        url: str,
        queue: str,
        binding_keys: tuple[str, ...] = ("#",),
        prefetch: int = 50,
    ) -> None:
        self._url = url
        self._queue = queue
        self._binding_keys = binding_keys
        self._prefetch = prefetch
        self._channel: BlockingChannel | None = None
        self._running = True

    def run(self, handler: EventHandler) -> None:
        while self._running:
            connection = _connect(self._url)
            try:
                self._channel = self._setup_channel(connection)
                self._channel.basic_consume(
                    self._queue,
                    lambda ch, method, props, body: self._on_message(ch, method, props, body, handler),
                )
                logger.info("Consuming", extra={"queue": self._queue})
                self._channel.start_consuming()
            except AMQPError:
                logger.exception("Lost RabbitMQ connection, reconnecting")
            finally:
                if connection.is_open:
                    connection.close()

    def stop(self) -> None:
        self._running = False
        if self._channel and self._channel.is_open:
            self._channel.stop_consuming()

    def _setup_channel(self, connection: pika.BlockingConnection) -> BlockingChannel:
        channel = connection.channel()
        _declare_topology(channel)
        dead_letter_queue = f"{self._queue}.dead"
        channel.queue_declare(dead_letter_queue, durable=True)
        channel.queue_bind(dead_letter_queue, DEAD_LETTER_EXCHANGE)
        channel.queue_declare(self._queue, durable=True, arguments={"x-dead-letter-exchange": DEAD_LETTER_EXCHANGE})
        for key in self._binding_keys:
            channel.queue_bind(self._queue, EXCHANGE, routing_key=key)
        channel.basic_qos(prefetch_count=self._prefetch)
        return channel

    def _on_message(
        self,
        channel: BlockingChannel,
        method: Basic.Deliver,
        properties: BasicProperties,
        body: bytes,
        handler: EventHandler,
    ) -> None:
        event_type = properties.type or "unknown"
        parent = propagate.extract(properties.headers or {})
        with _tracer.start_as_current_span(
            f"consume {event_type}",
            context=parent,
            kind=SpanKind.CONSUMER,
            attributes={"messaging.system": "rabbitmq", "messaging.source.name": self._queue},
        ):
            started = time.perf_counter()
            try:
                handler(deserialize(body))
            except ValidationError:
                logger.exception("Malformed message rejected to DLQ", extra={"type": event_type})
                self._reject(channel, method, event_type, "invalid")
            except Exception:
                logger.exception("Handler failed, message moved to DLQ", extra={"type": event_type})
                self._reject(channel, method, event_type, "error")
            else:
                channel.basic_ack(method.delivery_tag)
                MESSAGES_CONSUMED.labels(event_type, "ok").inc()
            finally:
                MESSAGE_PROCESSING.labels(event_type).observe(time.perf_counter() - started)

    @staticmethod
    def _reject(channel: BlockingChannel, method: Basic.Deliver, event_type: str, status: str) -> None:
        channel.basic_nack(method.delivery_tag, requeue=False)
        MESSAGES_CONSUMED.labels(event_type, status).inc()
