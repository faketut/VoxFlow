"""Tests for the JSON logging formatter."""
from __future__ import annotations

import json
import logging

from app.core.logging_config import JsonFormatter, configure_logging


def test_json_formatter_emits_valid_json():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="x", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello %s", args=("world",), exc_info=None,
    )
    out = formatter.format(record)
    payload = json.loads(out)
    assert payload["msg"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "x"


def test_json_formatter_includes_extras():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="x", level=logging.INFO, pathname=__file__, lineno=1,
        msg="event", args=(), exc_info=None,
    )
    record.call_sid = "CAabc"  # type: ignore[attr-defined]
    payload = json.loads(formatter.format(record))
    assert payload["call_sid"] == "CAabc"


def test_configure_logging_replaces_handlers():
    root = logging.getLogger()
    configure_logging("INFO", "json")
    n_json = len(root.handlers)
    configure_logging("INFO", "text")
    # Same count after reconfigure (handlers replaced, not appended).
    assert len(root.handlers) == n_json
