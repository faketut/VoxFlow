"""
Logging configuration.

Switch between plain text and JSON output via ``LOG_FORMAT=json|text``
(default ``text``). JSON mode is intended for production where logs are
shipped to an aggregator that parses structured fields.
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

# Keys that the LogRecord ships by default — anything else we treat as "extra".
_RESERVED_RECORD_KEYS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
}


class JsonFormatter(logging.Formatter):
    """Minimal stdlib-only JSON formatter (no external deps).

    Emits one JSON object per line with the standard fields plus any ``extra=``
    keyword arguments the caller passed to the logging call.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_KEYS or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)

        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str, fmt: str) -> None:
    """Configure the root logger. Idempotent — replaces existing handlers."""
    handler = logging.StreamHandler(sys.stdout)
    if fmt.strip().lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )

    root = logging.getLogger()
    root.setLevel(level)
    # Clear any pre-existing handlers (e.g. from a previous configure call).
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
