"""
Per-call logging context.

Bind ``call_sid`` once per call (in the inbound endpoint and again in the
Twilio "start" handler) and every subsequent log record made from that
asyncio task chain will carry the value automatically.

Text format gets a ``[CAxxxx]`` prefix; JSON format gets a ``call_sid``
field. No call site needs to pass ``extra={...}`` explicitly.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar

_call_sid_var: ContextVar[str | None] = ContextVar("call_sid", default=None)


def bind_call_sid(call_sid: str | None) -> None:
    """Bind ``call_sid`` to the current asyncio context."""
    _call_sid_var.set(call_sid)


def get_call_sid() -> str | None:
    return _call_sid_var.get()


def clear_call_sid() -> None:
    _call_sid_var.set(None)


class CallSidFilter(logging.Filter):
    """Inject the current contextvar ``call_sid`` onto every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.call_sid = _call_sid_var.get() or "-"
        return True
