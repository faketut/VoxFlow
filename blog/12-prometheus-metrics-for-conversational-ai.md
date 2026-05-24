# Five Prometheus Metrics That Matter for a Voice Agent

*Generic "instrument your FastAPI" advice doesn't help. Here are the five signals that actually predict and explain voice-agent incidents.*

## "Use Prometheus" is not a metrics strategy

Most metrics tutorials end at "expose `/metrics` and scrape it." That's the easy part. The hard part is picking *which* metrics, with *which* labels, that will actually answer the questions your on-call asks at 2am:

- Why did call volume drop?
- Which tool is the LLM calling that's failing?
- Is the slowness in our code or in n8n?
- How many calls just… end without an explanation?

For a voice agent, five metric families cover ~90% of those questions.

## The shortlist

| Metric | Type | Labels | What it answers |
|--------|------|--------|-----------------|
| `voxflow_calls_total` | Counter | `direction` (inbound/outbound) | Volume, day-over-day deltas, "are we still taking calls?" |
| `voxflow_call_disconnects_total` | Counter | `reason` (normal/idle_timeout/error) | Quality-of-service. The unexplained drops live here. |
| `voxflow_tool_invocations_total` | Counter | `tool`, `outcome` (ok/invalid_params/unknown/error) | Which LLM tool is broken? Is the model hallucinating tool names? |
| `voxflow_n8n_requests_total` | Counter | `outcome` (2xx/4xx/5xx/timeout/transport_error) | Is our backend integration healthy? |
| `voxflow_n8n_request_duration_seconds` | Histogram | — | Latency for the dominant downstream — feeds p95 SLO alerts. |

Five. That's the whole list. Resist the urge to add more before you've used these.

## Why these labels and no others

**Don't put `call_sid` on a counter.** Unbounded label cardinality kills Prometheus. The call_sid belongs in logs (see the contextvars post), not in metrics.

**Do put `outcome` on every counter that can fail.** A single counter with `{outcome="ok"|"error"}` lets you compute error rate as `rate(...{outcome="error"}[5m]) / rate(...[5m])` — the canonical Google SRE "fraction of bad requests" recipe.

**Do split disconnects by reason.** `normal` (call ended) and `idle_timeout` (Twilio went silent for 60s) and `error` (exception in handler) need different alerts. Lumping them together hides the only one that actually means something is wrong.

## Wiring it up

The whole metrics module is ~40 lines:

```python
# app/core/metrics.py
from prometheus_client import Counter, Histogram, CollectorRegistry

REGISTRY = CollectorRegistry()

calls_total = Counter(
    "voxflow_calls_total", "Total calls handled.",
    labelnames=("direction",), registry=REGISTRY,
)
call_disconnects_total = Counter(
    "voxflow_call_disconnects_total", "WS disconnects by reason.",
    labelnames=("reason",), registry=REGISTRY,
)
tool_invocations_total = Counter(
    "voxflow_tool_invocations_total", "Tool invocations.",
    labelnames=("tool", "outcome"), registry=REGISTRY,
)
n8n_requests_total = Counter(
    "voxflow_n8n_requests_total", "n8n outbound requests.",
    labelnames=("outcome",), registry=REGISTRY,
)
n8n_request_duration_seconds = Histogram(
    "voxflow_n8n_request_duration_seconds", "n8n latency.",
    registry=REGISTRY,
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
```

And the endpoint:

```python
@app.get("/metrics")
async def metrics_endpoint() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
```

## Instrumentation points (where, exactly)

You only have to touch four places:

```python
# api/endpoints/calls.py — at the top of /incoming-call:
calls_total.labels(direction="inbound").inc()

# services/tools_service.py — inside handle_tool_invocation, branches:
tool_invocations_total.labels(tool=name, outcome="ok").inc()
tool_invocations_total.labels(tool=name, outcome="invalid_params").inc()
tool_invocations_total.labels(tool=name, outcome="unknown").inc()
tool_invocations_total.labels(tool=name, outcome="error").inc()

# services/n8n_service.py — around the httpx.post:
t0 = time.monotonic()
resp = await client.post(...)
n8n_request_duration_seconds.observe(time.monotonic() - t0)
n8n_requests_total.labels(outcome=bucket).inc()

# websockets/media_stream.py — three sites:
call_disconnects_total.labels(reason="normal").inc()       # except* WebSocketDisconnect
call_disconnects_total.labels(reason="error").inc()         # except* Exception
call_disconnects_total.labels(reason="idle_timeout").inc()  # asyncio.TimeoutError branch
```

That's it. No middleware, no wrapper functions, no metaclasses.

## Five queries that answer real questions

Drop these in a Grafana dashboard and you're done:

**Call volume (1-minute resolution):**
```promql
sum(rate(voxflow_calls_total[1m])) by (direction)
```

**Tool error rate (per tool):**
```promql
sum(rate(voxflow_tool_invocations_total{outcome!="ok"}[5m])) by (tool)
  /
sum(rate(voxflow_tool_invocations_total[5m])) by (tool)
```

**n8n p95 latency:**
```promql
histogram_quantile(0.95,
  sum(rate(voxflow_n8n_request_duration_seconds_bucket[5m])) by (le))
```

**Disconnect breakdown (the gold one):**
```promql
sum(rate(voxflow_call_disconnects_total[5m])) by (reason)
```

**Calls in flight (gauge derived from counters):**
```promql
sum(rate(voxflow_calls_total[1m])) * 60 * <avg_call_duration_seconds>
```

…or instrument an actual `Gauge` if you need exact concurrency.

## Alerts that won't page you for nothing

Two are enough to start:

```yaml
- alert: VoxFlowToolFailureRateHigh
  expr: |
    sum(rate(voxflow_tool_invocations_total{outcome!="ok"}[5m])) by (tool)
      /
    sum(rate(voxflow_tool_invocations_total[5m])) by (tool)
    > 0.1
  for: 10m

- alert: VoxFlowN8nLatencyHigh
  expr: |
    histogram_quantile(0.95,
      sum(rate(voxflow_n8n_request_duration_seconds_bucket[5m])) by (le))
    > 5
  for: 10m
```

10% failures for 10 minutes, or 5s p95 for 10 minutes. Both correspond to "users are noticing right now."

## What you'll resist adding (and shouldn't)

- **Per-LLM-token counters.** Belongs in your LLM provider's dashboard, not yours.
- **Per-prompt-version metrics.** Use logs + traces.
- **Audio-quality histograms.** Belongs in Twilio Voice Insights.

Every metric is a permanent commitment. Start with five.

## Takeaway

For a voice agent, the five metrics worth instrumenting are: calls (by direction), disconnects (by reason), tool invocations (by tool + outcome), n8n requests (by outcome), and n8n latency. Five counters/histograms, four instrumentation sites, two alerts. Anything else can wait until you have a question those don't answer.
