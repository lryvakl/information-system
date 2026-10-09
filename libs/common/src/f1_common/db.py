"""PostgreSQL access helpers: connection pool and instrumented operations.

``db_operation`` is the single place where every repository query gets a span
(visible in Tempo) and Prometheus metrics (visible in Grafana), so repositories
stay focused on SQL only.
"""

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from time import perf_counter

from opentelemetry import trace
from opentelemetry.trace import INVALID_SPAN, Span, SpanKind
from prometheus_client import Counter, Histogram
from psycopg_pool import ConnectionPool

from f1_common.metrics import trace_exemplar

_tracer = trace.get_tracer(__name__)

DB_OPERATIONS = Counter(
    "app_db_operations_total",
    "Database operations executed by the application.",
    ["operation", "table", "status"],
)
DB_DURATION = Histogram(
    "app_db_operation_duration_seconds",
    "Latency of database operations executed by the application.",
    ["operation", "table"],
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)


def create_pool(dsn: str, max_size: int = 5, timeout: float = 60.0) -> ConnectionPool:
    """Open a pool and wait until the database accepts connections."""
    pool = ConnectionPool(dsn, min_size=1, max_size=max_size, open=False)
    pool.open(wait=True, timeout=timeout)
    return pool


@contextmanager
def db_operation(operation: str, table: str, traced: bool = True) -> Iterator[Span]:
    """Measure a DB call. ``traced=False`` keeps metrics but skips the span (high-frequency writes)."""
    attributes = {"db.system": "postgresql", "db.operation": operation, "db.sql.table": table}
    span_cm = (
        _tracer.start_as_current_span(f"db {operation} {table}", kind=SpanKind.CLIENT, attributes=attributes)
        if traced
        else nullcontext(INVALID_SPAN)
    )
    with span_cm as span:
        started = perf_counter()
        status = "ok"
        try:
            yield span
        except Exception:
            status = "error"
            raise
        finally:
            DB_OPERATIONS.labels(operation, table, status).inc()
            DB_DURATION.labels(operation, table).observe(perf_counter() - started, exemplar=trace_exemplar())
