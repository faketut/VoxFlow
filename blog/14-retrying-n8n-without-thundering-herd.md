# Retrying n8n Without a Thundering Herd

*Exponential backoff is one of those things everybody knows, and almost everybody implements wrong on the first try.*

## The "happy path" trap

The minimal n8n integration in every tutorial:

```python
async with httpx.AsyncClient() as client:
    resp = await client.post(N8N_WEBHOOK_URL, json=payload)
return resp.text
```

Three things this gets wrong the moment n8n hiccups:

1. **One transient 502 = lost data.** A redeploy on the n8n side, a 30-second blip — and the call's transcript is gone.
2. **No retry latency budget.** When the caller is waiting for `schedule_meeting` to return, blocking for 30 seconds is worse than failing fast.
3. **Retries that thunder.** If you bolt on a naive `for _ in range(3)` loop and n8n is recovering, you triple the load on the way back up.

The bar is "always retry the kinds of failures that go away on their own, never retry the ones that don't, and never make a struggling backend worse."

## The decision tree

| HTTP outcome | Retryable? | Why |
|--------------|-----------|-----|
| `2xx` | No — success | obviously |
| `4xx` (e.g. 400, 404, 422) | **No** | Your payload is malformed. Retrying produces the same 400. Burn through the retries for nothing. |
| `5xx` (500–599) | **Yes** | The server is having a moment. Probably transient. |
| `httpx.TimeoutException` | **Yes** | Could be slow, could be transient. |
| `httpx.TransportError` (DNS, conn reset) | **Yes** | Network blip. |
| `httpx.HTTPError` (other) | No — unexpected | Don't retry; log loudly. |

That distinction — *not retrying 4xx* — is the single biggest source of overengineered retry loops that hurt instead of help.

## What the loop actually looks like

```python
async def send_to_webhook(payload: dict[str, Any]) -> str:
    body = json.dumps(payload).encode("utf-8")
    headers = build_signed_headers(body)
    attempts = max(1, N8N_MAX_RETRIES)
    last_error = "unknown error"

    for attempt in range(1, attempts + 1):
        try:
            t0 = time.monotonic()
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                response = await client.post(N8N_WEBHOOK_URL,
                                             content=body, headers=headers)
            n8n_request_duration_seconds.observe(time.monotonic() - t0)

            if response.status_code == 200:
                n8n_requests_total.labels(outcome="2xx").inc()
                return response.text

            if 500 <= response.status_code < 600 and attempt < attempts:
                last_error = f"status {response.status_code}"
                # fall through to backoff
            else:
                bucket = "5xx" if response.status_code >= 500 else "4xx"
                n8n_requests_total.labels(outcome=bucket).inc()
                return json.dumps({"error": f"status {response.status_code}"})

        except httpx.TimeoutException as e:
            last_error = f"timeout: {e}"
        except httpx.TransportError as e:
            last_error = f"transport error: {e}"
        except httpx.HTTPError as e:
            n8n_requests_total.labels(outcome="transport_error").inc()
            return json.dumps({"error": f"HTTP error: {e}"})

        if attempt < attempts:
            await asyncio.sleep(
                N8N_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
            )

    outcome = "timeout" if "timeout" in last_error else "transport_error"
    n8n_requests_total.labels(outcome=outcome).inc()
    return json.dumps({"error": f"failed after {attempts}: {last_error}"})
```

Worth highlighting:

- **`2 ** (attempt - 1)`** turns base 0.5s into 0.5 → 1 → 2 → 4 → 8 seconds. With `N8N_MAX_RETRIES=3` and base `0.5`, the worst-case total wait is ~1.5s plus three round-trips — bounded.
- **Metrics fire on *every* terminal outcome**, including the four classes of failure. Without this, your `n8n_requests_total{outcome="..."}` graph would lie about success rates.
- **The function never raises.** It returns a JSON-encoded error string. Callers forward the result to the agent, which says "I'm sorry, I couldn't schedule that" — far better than a 500 mid-call.

## Latency budget — the underrated knob

Each retry adds:

- `HTTP_TIMEOUT_SECONDS` of waiting (worst case the network just hangs)
- Plus the exponential backoff sleep

For a 3-retry config with `HTTP_TIMEOUT_SECONDS=10` and base backoff `0.5s`:

```
attempt 1: up to 10s + 0.5s backoff
attempt 2: up to 10s + 1.0s backoff
attempt 3: up to 10s
total worst case: ~31.5s
```

A caller will hang up before 31 seconds of dead air. Make this explicit:

- `N8N_MAX_RETRIES=2` for in-call tools (`schedule_meeting`, `verify`) — fail fast, let the agent say sorry.
- `N8N_MAX_RETRIES=5` for post-call transcript send — nobody's listening, retry liberally.

If you ever need to split, factor the retry policy out as an argument; don't fork the function.

## Don't forget jitter (if you have many replicas)

With one or two replicas, deterministic backoff is fine. With twenty, every replica retrying in lockstep at `t+1s, t+2s, t+4s` *is* a thundering herd. Add 0–250ms of `random.uniform()` jitter on each sleep:

```python
await asyncio.sleep(
    N8N_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
    + random.uniform(0, 0.25)
)
```

VoxFlow runs at small scale today and skips this. Add it before you scale, not after.

## Pair with HMAC signing

Retries make every webhook arrive *at least once* (sometimes more — the network might be lying about your timeout). That means your n8n flow needs to be idempotent, or it'll double-book meetings.

Two parts:

- **Sign the body.** VoxFlow attaches `X-VoxFlow-Signature: sha256=<hmac>` so n8n can reject anything not from us. (One leaked webhook URL ≠ takeover.)
- **Carry an idempotency key.** Add a UUID to every payload; n8n's first node deduplicates.

Without these, retries are a liability instead of a safety net.

## Takeaway

A retry loop done right is: exponential backoff with a bounded ceiling, *only* on transient failures, with metrics on every outcome and a fail-soft return value. About 30 lines. Pair it with body signing and idempotency keys so retries can't double-trigger your downstream. Then forget about it — the SLO graphs will be flat.
