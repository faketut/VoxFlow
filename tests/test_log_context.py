"""Tests for per-call logging context (contextvars)."""
import logging

from app.core import log_context
from app.core.log_context import (
    CallSidFilter,
    bind_call_sid,
    clear_call_sid,
    get_call_sid,
)


def _make_record() -> logging.LogRecord:
    return logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello", args=(), exc_info=None,
    )


def test_bind_and_get_call_sid():
    clear_call_sid()
    assert get_call_sid() is None
    bind_call_sid("CA123")
    assert get_call_sid() == "CA123"
    clear_call_sid()
    assert get_call_sid() is None


def test_filter_injects_sid_when_bound():
    clear_call_sid()
    f = CallSidFilter()
    record = _make_record()
    bind_call_sid("CAabc")
    try:
        assert f.filter(record) is True
        assert record.call_sid == "CAabc"
    finally:
        clear_call_sid()


def test_filter_injects_dash_when_unbound():
    clear_call_sid()
    record = _make_record()
    assert CallSidFilter().filter(record) is True
    assert record.call_sid == "-"


def test_log_context_contextvar_is_module_state():
    # The contextvar is module-level; bind/clear round-trip is observable.
    assert hasattr(log_context, "_call_sid_var")
