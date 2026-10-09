"""Thin HTTP client for the public OpenF1 API (https://openf1.org) with a disk cache.

The cache makes replays reproducible and lets the demo run offline once a race
has been downloaded.
"""

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
from opentelemetry import trace

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

Record = dict[str, Any]
_RETRYABLE = {429, 500, 502, 503, 504}


class OpenF1Client:
    def __init__(
        self,
        base_url: str = "https://api.openf1.org/v1",
        cache_dir: Path | None = None,
        http: httpx.Client | None = None,
        retries: int = 4,
        backoff_seconds: float = 2.0,
    ) -> None:
        self._http = http or httpx.Client(base_url=base_url, timeout=30.0)
        self._cache_dir = cache_dir
        self._retries = retries
        self._backoff = backoff_seconds

    def get(self, endpoint: str, **params: str | int) -> list[Record]:
        cache_file = self._cache_path(endpoint, params)
        if cache_file and cache_file.exists():
            return json.loads(cache_file.read_text())

        with _tracer.start_as_current_span(f"openf1 GET /{endpoint}", attributes={"http.url": endpoint}):
            records = self._fetch(endpoint, params)
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(records))
        return records

    def _fetch(self, endpoint: str, params: dict[str, str | int]) -> list[Record]:
        for attempt in range(1, self._retries + 1):
            response = self._http.get(f"/{endpoint}", params=params)
            if response.status_code == 404:  # OpenF1 answers 404 for "no results"
                return []
            if response.status_code not in _RETRYABLE:
                response.raise_for_status()
                payload = response.json()
                return payload if isinstance(payload, list) else []
            logger.warning("OpenF1 throttled, retrying", extra={"endpoint": endpoint, "attempt": attempt})
            time.sleep(self._backoff * attempt)
        raise ConnectionError(f"OpenF1 /{endpoint} failed after {self._retries} attempts")

    def _cache_path(self, endpoint: str, params: dict[str, str | int]) -> Path | None:
        if self._cache_dir is None:
            return None
        key = json.dumps(params, sort_keys=True)
        digest = hashlib.sha256(key.encode()).hexdigest()[:16]
        return self._cache_dir / endpoint / f"{digest}.json"
