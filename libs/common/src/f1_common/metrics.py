"""Prometheus helpers shared by workers and HTTP services."""

from opentelemetry import trace
from prometheus_client import start_http_server


def start_metrics_server(port: int) -> None:
    """Expose ``/metrics`` for Prometheus on a background thread (worker services)."""
    start_http_server(port)


def trace_exemplar() -> dict[str, str] | None:
    """Exemplar linking a histogram observation to the current trace in Tempo."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return {"trace_id": format(span_context.trace_id, "032x")}
