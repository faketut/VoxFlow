# Concurrent WebSockets with asyncio.TaskGroup

*Why Python 3.11's TaskGroup makes dual-WebSocket bridging finally bearable.*

## The problem

VoxFlow holds two WebSockets at once: one to Twilio (caller's audio), one to Ultravox (AI's audio). It must:

1. Read from both concurrently.
2. If either closes or errors, close the other.
3. Always run cleanup (pop session, send transcript) regardless of how things ended.

This is the classic "structured concurrency" problem. Pre-3.11 solutions are painful.

## The old way: `asyncio.gather` + `try/except` gymnastics

```python
async def media_stream_old(websocket):
    twilio_task = asyncio.create_task(handle_twilio(...))
    ultravox_task = asyncio.create_task(handle_ultravox(...))
    try:
        done, pending = await asyncio.wait(
            [twilio_task, ultravox_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            if task.exception():
                raise task.exception()
    except WebSocketDisconnect:
        ...
    except Exception:
        ...
    finally:
        await cleanup(...)
```

Problems:
- Manual cancellation. Forget to cancel `pending` and you leak coroutines.
- One task's exception swallows the other's.
- The `try/except` ladder is fragile — adding a third task means rewriting it.

## The new way: `asyncio.TaskGroup` + `except*`

```python
async def media_stream(websocket: WebSocket) -> None:
    state = CallState(twilio_ws=websocket, ...)
    try:
        async with asyncio.TaskGroup() as tg:
            twilio_task = tg.create_task(_handle_twilio(state))
            tg.create_task(_handle_ultravox_when_ready(state, twilio_task))
    except* WebSocketDisconnect:
        logger.info("Caller hung up")
    except* Exception:
        logger.exception("Media stream error")
    finally:
        await _cleanup(state)
```

Three real wins:

### 1. Automatic cancellation

When one task raises, `TaskGroup` cancels all siblings before exiting the `async with`. Zero leaked coroutines, no manual `task.cancel()`.

### 2. Exception groups via `except*`

If both tasks fail (Twilio disconnects *and* Ultravox errors out simultaneously — a common case during call teardown), you get an `ExceptionGroup` containing both. `except*` lets you match on type and handle each individually instead of losing one.

### 3. Cleanup is in plain `finally`

No matter which task fails, in what order, or whether `TaskGroup` re-raises — your `finally` block runs. Sessions get popped, transcripts get shipped, audio buffers get flushed.

## A subtle bootstrap problem

When `media_stream` starts, you have the Twilio WebSocket but not yet the Ultravox one — Ultravox is provisioned only after Twilio sends the `start` event (which carries the `callSid`).

You can't `tg.create_task(_handle_ultravox(...))` immediately because there's no Ultravox WS to handle.

The fix: an `asyncio.Event` on the shared state, set by the Twilio handler once `start` is received.

```python
@dataclass
class CallState:
    twilio_ws: WebSocket
    uv_ws: Any = None
    started: asyncio.Event = field(default_factory=asyncio.Event)
    ...

async def _handle_ultravox_when_ready(state, twilio_task):
    await state.started.wait()  # block until Twilio start event sets it
    await _handle_ultravox(state)
```

Now both tasks live inside the same `TaskGroup`, and the ordering happens via the event rather than via task scheduling.

## When TaskGroup is the wrong tool

- **Fire-and-forget background work** — TaskGroup blocks on completion. Use `asyncio.create_task` and accept the leak risk.
- **Tasks with vastly different lifetimes** — a 1-second task and a 1-hour task in the same group means the group lives for an hour. Split them.

## Migration checklist

If you have any of these patterns, TaskGroup is probably a better fit:

```python
asyncio.gather(t1, t2, return_exceptions=True)
asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
for task in pending: task.cancel()
try: ... finally: for t in tasks: t.cancel()
```

## Takeaway

Structured concurrency turns a 30-line tangle of `try/except/cancel/await` into 6 lines of declarative code. Required reading: [PEP 654 (Exception Groups)](https://peps.python.org/pep-0654/) and the [`asyncio.TaskGroup` docs](https://docs.python.org/3/library/asyncio-task.html#task-groups).
