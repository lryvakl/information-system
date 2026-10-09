"""Routes each event to every handler interested in its type (Open/Closed: add handlers, not ifs)."""

from collections import defaultdict
from typing import Protocol

from opentelemetry import trace

from f1_common.events import EventType, RaceEvent

_tracer = trace.get_tracer(__name__)


class EventHandler(Protocol):
    @property
    def handles(self) -> frozenset[EventType]: ...

    def handle(self, event: RaceEvent) -> None: ...


class EventDispatcher:
    def __init__(self, handlers: list[EventHandler]) -> None:
        self._routes: dict[EventType, list[EventHandler]] = defaultdict(list)
        for handler in handlers:
            for event_type in handler.handles:
                self._routes[event_type].append(handler)

    def __call__(self, event: RaceEvent) -> None:
        for handler in self._routes.get(event.type, []):
            with _tracer.start_as_current_span(f"handle {type(handler).__name__}"):
                handler.handle(event)
