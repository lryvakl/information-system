import json
import logging

from opentelemetry.sdk.trace import TracerProvider

from f1_common.logging import JsonFormatter


def _record(**extra: object) -> logging.LogRecord:
    record = logging.makeLogRecord({"name": "test", "levelname": "INFO", "msg": "box box"})
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formats_record_as_json_with_extra_fields() -> None:
    line = JsonFormatter("race-control").format(_record(driver="HAM", lap=12))

    payload = json.loads(line)

    assert payload["service"] == "race-control"
    assert payload["message"] == "box box"
    assert payload["driver"] == "HAM"
    assert payload["lap"] == 12
    assert "trace_id" not in payload


def test_includes_active_trace_id() -> None:
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("span") as span:
        payload = json.loads(JsonFormatter("svc").format(_record()))

    assert payload["trace_id"] == format(span.get_span_context().trace_id, "032x")
