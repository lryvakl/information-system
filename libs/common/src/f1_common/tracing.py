"""OpenTelemetry tracing bootstrap (traces are exported to Grafana Tempo via OTLP)."""

from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from f1_common.settings import BaseServiceSettings

P = ParamSpec("P")
R = TypeVar("R")


def configure_tracing(settings: BaseServiceSettings) -> None:
    if not settings.tracing_enabled:
        return
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: settings.service_name}))
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def shutdown_tracing() -> None:
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.shutdown()


def traced(span_name: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Wrap a function call into a span named ``span_name``."""

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        tracer = trace.get_tracer(func.__module__)

        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with tracer.start_as_current_span(span_name):
                return func(*args, **kwargs)

        return wrapper

    return decorator
