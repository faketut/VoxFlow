"""
Prometheus metrics for VoxFlow.

Lightweight counters/histograms exposed at ``GET /metrics`` in the standard
Prometheus text exposition format. Scrape with any Prometheus-compatible
collector (Prometheus, Grafana Agent, Vector, OpenTelemetry Collector …).
"""
from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

# Dedicated registry keeps VoxFlow's metrics separate from the default
# registry's process/python collectors when running embedded in tests.
REGISTRY = CollectorRegistry()

calls_total = Counter(
    "voxflow_calls_total",
    "Total number of inbound + outbound calls handled.",
    labelnames=("direction",),  # inbound | outbound
    registry=REGISTRY,
)

call_disconnects_total = Counter(
    "voxflow_call_disconnects_total",
    "Number of media-stream WebSocket disconnects by reason.",
    labelnames=("reason",),  # normal | idle_timeout | error
    registry=REGISTRY,
)

tool_invocations_total = Counter(
    "voxflow_tool_invocations_total",
    "Number of Ultravox tool invocations by tool name and outcome.",
    labelnames=("tool", "outcome"),  # outcome: ok | invalid_params | unknown | error
    registry=REGISTRY,
)

n8n_requests_total = Counter(
    "voxflow_n8n_requests_total",
    "Number of outbound n8n webhook requests by outcome.",
    labelnames=("outcome",),  # 2xx | 4xx | 5xx | timeout | transport_error
    registry=REGISTRY,
)

n8n_request_duration_seconds = Histogram(
    "voxflow_n8n_request_duration_seconds",
    "Latency of outbound n8n webhook calls (seconds).",
    registry=REGISTRY,
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def render_metrics() -> tuple[bytes, str]:
    """Return (body, content_type) for the /metrics endpoint."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
