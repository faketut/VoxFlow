# `/health` Lies. Add `/ready`.

*Liveness probes tell you the process is up. Readiness probes tell you it can actually do its job. For a voice agent, the difference is whether the next call connects or drops.*

## The default health check is too generous

The standard FastAPI starter ships something like:

```python
@app.get("/health")
async def health():
    return {"status": "ok"}
```

This returns 200 as long as the Python interpreter is alive and the event loop is scheduling. It tells you nothing about whether the app can actually take a call:

- Is `TWILIO_AUTH_TOKEN` set?
- Is `ULTRAVOX_API_KEY` set?
- Is `N8N_WEBHOOK_URL` reachable?
- Is `PUBLIC_URL` populated so Twilio can call us back?

If any of these are missing, the process is "healthy" but every call will fail with a 500 or worse — a dial tone that never goes anywhere.

## Liveness vs readiness — two different questions

| Probe | Question | Failure action |
|-------|----------|----------------|
| **Liveness** (`/health`) | "Is the process stuck?" | Kill and restart the container |
| **Readiness** (`/ready`) | "Should I send this pod traffic?" | Stop routing requests to it |

Conflating them is how you end up with a deployment that's "100% healthy" while 100% of calls drop.

## The shape of a useful readiness endpoint

In VoxFlow it's about ten lines:

```python
@app.get("/ready")
async def readiness_check(response: Response) -> dict[str, object]:
    checks = {
        "twilio": bool(TWILIO_ACCOUNT_SID),
        "ultravox": bool(ULTRAVOX_API_KEY),
        "n8n": bool(N8N_WEBHOOK_URL),
        "public_url": bool(PUBLIC_URL),
    }
    ready = all(checks.values())
    if not ready:
        response.status_code = 503
    return {"ready": ready, "checks": checks}
```

Two things matter here:

1. **It returns 503 when not ready.** That's the contract Kubernetes' `readinessProbe`, AWS ALB target groups, and most reverse proxies all understand. Without the 503, the orchestrator can't act on the answer.
2. **The body lists every check individually.** When something fails, your on-call doesn't need to grep logs — `curl /ready` tells them exactly which env var is missing.

## Why we don't ping Twilio/Ultravox here

You'll see "deep health check" tutorials that recommend pinging every downstream from `/ready`. Don't.

- **Cost** — Ultravox charges per API call; a probe every 5s adds up.
- **Cascading failures** — if Ultravox has a 2-minute blip, every replica suddenly fails readiness and your traffic dies, even though calls in flight would still complete.
- **Truth** — "the env var is set" is a meaningful production invariant; "the downstream answered our probe in the last second" is noise.

If you want downstream health, gauge it from real call outcomes (your Prometheus metrics, the next blog post in this series) — not from a synthetic probe.

## Kubernetes wiring

```yaml
livenessProbe:
  httpGet: { path: /health, port: 8000 }
  initialDelaySeconds: 10
  periodSeconds: 30
readinessProbe:
  httpGet: { path: /ready, port: 8000 }
  initialDelaySeconds: 5
  periodSeconds: 10
  failureThreshold: 2
```

Liveness is loose (don't kill the container for transient stalls). Readiness is tight (pull the pod from the load balancer fast when config goes bad).

## A war story

The bug this would have prevented: a rolling deploy on a Friday afternoon. New `Secret` resource was missing one env var. Pods came up healthy. `/health` returned 200. Twilio dispatched calls. Every call returned 500 because the missing var blew up inside the request handler. Pager went off four minutes later, after callers had already complained.

With `/ready` checking env-var presence, the orchestrator would never have routed a single call to those pods. The bad deploy would have stalled at "0/3 pods ready" — visible, contained, fixable before any user noticed.

## Takeaway

`/health` answers "am I alive?" `/ready` answers "should you trust me?" Voice agents need both. The readiness endpoint is twenty lines of code that turns a class of production outages into a deployment-time error. Add it before you ship.
