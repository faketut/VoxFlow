# Per-Call Logging Context with `contextvars`

*Auto-tagging every log line with the active `CallSid` — without passing it through every function signature.*

## The pain you don't notice until you have it

A single voice call generates 50–200 log lines: WebSocket frames, tool invocations, n8n calls, transcript fragments, errors. Now imagine three concurrent calls. Your log file is a braided mess:

```
INFO  app.services.tools_service  Tool invocation: schedule_meeting
INFO  app.services.n8n_service    POST n8n attempt=1/3
INFO  app.services.tools_service  Tool invocation: verify
WARN  app.services.n8n_service    Timeout calling n8n
INFO  app.websockets.media_stream Twilio start: callSid=CA999...
```

Which call timed out? Which one called `verify`? You can't tell without grepping by timestamp and praying.

The naive fix is `extra={"call_sid": sid}` on every `logger.info(...)` call. That works for the five lines you remember to update, and silently fails for the rest. You need automatic propagation.

## `contextvars` is the right tool

Python's `contextvars.ContextVar` was designed for exactly this: a value that follows your asyncio task chain automatically, isolated from sibling tasks, with no global-state hazards.

The whole thing is twenty lines:

```python
# app/core/log_context.py
from contextvars import ContextVar
import logging

_call_sid_var: ContextVar[str | None] = ContextVar("call_sid", default=None)

def bind_call_sid(call_sid: str | None) -> None:
    _call_sid_var.set(call_sid)

def clear_call_sid() -> None:
    _call_sid_var.set(None)

class CallSidFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.call_sid = _call_sid_var.get() or "-"
        return True
```

Two pieces:

1. **The ContextVar** holds the active `call_sid` for the current asyncio task.
2. **A `logging.Filter`** copies that value onto every `LogRecord` as `record.call_sid`.

Attach the filter to your handler once:

```python
handler.addFilter(CallSidFilter())
handler.setFormatter(logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s [%(call_sid)s] %(message)s"
))
```

…and JSON formatters pick it up automatically because they iterate `record.__dict__`.

## Where to bind

Three sites, all in the request-entry layer:

```python
# api/endpoints/calls.py
@router.post("/incoming-call")
async def incoming_call(...):
    bind_call_sid(twilio_params.get("CallSid"))
    ...

# websockets/media_stream.py
async def _on_twilio_start(state, data):
    state.call_sid = data['start']['callSid']
    bind_call_sid(state.call_sid)
    ...
```

And one site for cleanup:

```python
finally:
    await _cleanup(state)
    clear_call_sid()
```

That's it. Every log line emitted by any module — `n8n_service`, `tools_service`, third-party libraries that use `logging` — gets tagged automatically.

## Before / after

**Before:**
```
INFO  app.services.tools_service  Tool invocation: schedule_meeting
WARN  app.services.n8n_service    Timeout calling n8n (attempt 1/3)
```

**After (text):**
```
INFO  app.services.tools_service  [CA9f7e...] Tool invocation: schedule_meeting
WARN  app.services.n8n_service    [CA9f7e...] Timeout calling n8n (attempt 1/3)
```

**After (JSON, for Loki/Datadog/Splunk):**
```json
{"ts":"...","level":"WARN","logger":"app.services.n8n_service",
 "call_sid":"CA9f7e...","msg":"Timeout calling n8n (attempt 1/3)"}
```

`grep CA9f7e...` (or `{call_sid="CA9f7e..."}` in your log aggregator's query language) replays the entire call in chronological order.

## Why not just `extra={}`?

| Approach | Updates every call site? | Works in third-party libs? | Survives across `await`? |
|----------|--------------------------|----------------------------|---------------------------|
| `logger.info(..., extra={"call_sid": sid})` | Yes (and you'll miss some) | No | Yes |
| `threading.local()` | No | Yes | No — different task, no value |
| `ContextVar` + filter | No | Yes | Yes |

`ContextVar` is the only option that propagates correctly through `asyncio` and covers every logger in the process (yours and your dependencies') with zero code changes outside the logging config.

## A subtle correctness note

`ContextVar.set()` is asyncio-task-scoped — concurrent calls don't pollute each other. But if you spawn a `TaskGroup` child and want the child to inherit the parent's `call_sid`, that already works because tasks inherit context by default. If you `asyncio.run_in_executor` to a thread pool, the value is copied with `contextvars.copy_context()` automatically as of Python 3.7+. You almost never need to think about it.

## The unexpected bonus

The same pattern scales to anything else you want to correlate by:

- `tenant_id` for multi-tenant deployments
- `request_id` for HTTP request tracing
- `trace_id` for OpenTelemetry interop (it's literally how OTel propagates context)

Add a second ContextVar. Add a second filter (or extend the first). Every log line now carries both. Your future self, three months in, will thank you.

## Takeaway

You don't need a logging framework, a tracing SDK, or a dedicated correlation library. You need 20 lines: a `ContextVar`, a `logging.Filter`, and three `bind_call_sid()` calls at request entry. Every log line, in every module, gets the active call's ID. Your post-mortems get 10× faster.
