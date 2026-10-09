"""FastAPI application factory shared by HTTP services.

Each HTTP service gets the same cross-cutting features for free:
JSON logs, tracing, ``/metrics``, ``/healthz`` and RED request metrics.
"""

import logging
from collections.abc import Awaitable, Callable
from time import perf_counter

import uvicorn
from fastapi import FastAPI, Request, Response
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import REGISTRY, Counter, Histogram
from prometheus_client.exposition import choose_encoder

from f1_common.logging import configure_logging
from f1_common.metrics import trace_exemplar
from f1_common.settings import BaseServiceSettings
from f1_common.tracing import configure_tracing

HTTP_REQUESTS = Counter("app_http_requests_total", "HTTP requests handled.", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "app_http_request_duration_seconds",
    "HTTP request latency.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)
_UNINSTRUMENTED = ("/metrics", "/healthz")


def create_app(settings: BaseServiceSettings, **fastapi_kwargs: object) -> FastAPI:
    configure_logging(settings.service_name, settings.log_level)
    configure_tracing(settings)

    app = FastAPI(**fastapi_kwargs)  # type: ignore[arg-type]
    app.middleware("http")(_record_request_metrics)
    logging.getLogger("uvicorn.access").addFilter(_skip_probe_requests)

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request) -> Response:
        # OpenMetrics format when Prometheus asks for it: required for exemplars.
        encoder, content_type = choose_encoder(request.headers.get("accept", ""))
        return Response(encoder(REGISTRY), media_type=content_type)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,metrics")
    return app


def _skip_probe_requests(record: logging.LogRecord) -> bool:
    """Drop access-log noise from Prometheus scrapes and health checks."""
    return not any(path in record.getMessage() for path in _UNINSTRUMENTED)


async def _record_request_metrics(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    if request.url.path.startswith(_UNINSTRUMENTED):
        return await call_next(request)
    started = perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        # Route template (e.g. /api/races/{race_id}) keeps label cardinality bounded.
        route = getattr(request.scope.get("route"), "path", "unmatched")
        HTTP_REQUESTS.labels(request.method, route, str(status)).inc()
        HTTP_LATENCY.labels(request.method, route).observe(perf_counter() - started, exemplar=trace_exemplar())


def serve(app: FastAPI, port: int = 8000) -> None:
    # log_config=None keeps our JSON root logger for uvicorn logs as well.
    uvicorn.run(app, host="0.0.0.0", port=port, log_config=None, proxy_headers=True)  # noqa: S104
