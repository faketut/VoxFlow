"""Tests for Prometheus /metrics endpoint and counters."""
from fastapi.testclient import TestClient

from app.core import metrics as metrics_mod
from app.main import app


def test_metrics_endpoint_returns_prometheus_format():
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    # All declared metric families should appear in the exposition.
    for name in (
        "voxflow_calls_total",
        "voxflow_call_disconnects_total",
        "voxflow_tool_invocations_total",
        "voxflow_n8n_requests_total",
        "voxflow_n8n_request_duration_seconds",
    ):
        assert name in body


def test_counter_increments_are_observable():
    before = metrics_mod.calls_total.labels(direction="inbound")._value.get()
    metrics_mod.calls_total.labels(direction="inbound").inc()
    after = metrics_mod.calls_total.labels(direction="inbound")._value.get()
    assert after == before + 1
