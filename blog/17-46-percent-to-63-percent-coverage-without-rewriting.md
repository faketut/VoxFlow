# From 46% to 63% Coverage by Writing Tests That Actually Find Bugs

*Coverage is not a number to chase. It's a flashlight pointed at the code you don't understand yet.*

## Why this number changed

VoxFlow's test suite went from 26 tests at 46% line coverage to 58 tests at 63% in a single sitting. The two biggest movers:

| Module | Before | After |
|--------|--------|-------|
| `tools_service.py` | 32% | **88%** |
| `media_stream.py` | 20% | 47% |

The point of writing those tests wasn't the number. It was that two of the new tests immediately surfaced behavior I didn't realize the code had. That's coverage doing its job.

## The wrong way to think about coverage

> "We need to be at 80% before we can merge."

This produces tests that look like:

```python
def test_handle_verify_runs():
    handle_verify(None, None, VerifyParams())  # just runs without error
```

That hits the line, increments the counter, asserts nothing. It will continue passing while the function deletes the database. Coverage as a gate is theatre.

## The right way

Coverage is a *discovery tool*. The list of uncovered lines is a map of code you don't have a working mental model for. Walk through that map slowly; for each chunk ask:

1. **What does this code actually do?** Read it. Out loud if you have to.
2. **Could it be wrong in a way that matters?** If the answer is "no, it's a one-liner that just logs," skip it. Coverage chasing here is theatre.
3. **If yes, what's the minimal scenario that would reveal a wrong behavior?** That's your test.

The tests that result are valuable not because they raise the percentage, but because they captured a behavior you didn't know was load-bearing.

## What the tools_service tests actually found

`tools_service.py` is the dispatcher that takes the LLM's "I want to call tool X with params Y" and runs a handler. There were six handlers, all uncovered. Writing tests for them surfaced:

- **`handle_schedule_meeting` silently accepts non-JSON from n8n** and falls back to a generic apology. Not a bug — the right behavior — but I didn't realize it was there until I wrote the test that triggered it. Now it's documented in test form, so refactors can't quietly drop it.

- **The `schedule_meeting` validation path is special-cased**: if the LLM forgot `location`, the dispatcher sends a `tool_result` asking the LLM to collect the missing field, rather than a `tool_error`. Every other tool gets the error path. The test:

  ```python
  async def test_handle_tool_invocation_invalid_params_generic(uv_ws):
      await svc.handle_tool_invocation(uv_ws, "schedule_meeting", "inv1", {})
      payload = _last_send_payload(uv_ws)
      assert payload["type"] == "client_tool_result"  # not "error"
      assert "Please provide" in payload["result"]
  ```

  If someone refactors the dispatcher to be "consistent" and removes the special case, the LLM stops gracefully recovering from missing slots. The test pins the behavior.

- **`handle_hangUp` is robust to a session not being found.** It logs and returns instead of crashing. Easy to miss in a refactor that "cleans up" the early-return.

These are not "test the implementation." They are "test the contract." That's why they're worth the disk space.

## The mocking patterns that scale

Two `pytest` idioms cover ~80% of WebSocket handler testing:

**Async `unittest.mock.AsyncMock` for the socket.**

```python
@pytest.fixture
def uv_ws():
    ws = AsyncMock()
    ws.send = AsyncMock()
    from websockets.protocol import State
    ws.state = State.CLOSED
    return ws
```

The handler thinks it's writing to a real Ultravox WebSocket. The test reads the last `send.call_args` to inspect the payload.

**`monkeypatch.setattr` on the module to swap collaborators.**

```python
monkeypatch.setattr(svc, "send_to_webhook",
                    AsyncMock(return_value='{"message": "Booked"}'))
monkeypatch.setattr(svc.session_manager, "find_by_uv_ws",
                    AsyncMock(return_value=("CA1", {"callerNumber": "+1"})))
```

No dependency injection rewrite. No "make this code testable" refactor. The function under test is unchanged; only its module-level names are swapped for the duration of the test.

For media_stream, the same patterns let you exercise the message-parsing branches (`_handle_ultravox_text`, `_forward_agent_audio`, `_on_twilio_media`) without standing up a real WebSocket. The bits that *require* a live socket (the `asyncio.wait_for` idle timeout, the `TaskGroup` orchestration) you leave for integration tests — or, more honestly, for production observability via the metrics from the earlier post.

## What you should *not* cover

The remaining 37% of VoxFlow's lines are mostly:

- The full `media_stream` lifecycle that requires real Twilio + Ultravox connections.
- Exception paths in `safe_close_websocket` that handle library-internal errors.
- The Twilio REST client call in `handle_hangUp` (mocking the SDK is more code than the production code).

Trying to cover these with unit tests produces enormously fragile tests that test the mock, not the code. Better:

- An end-to-end smoke test that actually places a call (run nightly in staging).
- Observability that surfaces failures from those paths in production (`voxflow_call_disconnects_total{reason="error"}`).

Coverage stops being useful when "raising it by 5%" requires more test maintenance than the bugs it catches will ever justify.

## The graph

```
Tests:    26 → 58
Coverage: 46% → 63%
Time:     ~one afternoon
Bugs found in passing: 0 (which is actually a good outcome)
Behaviors pinned by test: ~12
```

Zero bugs in the existing code is good news. The point wasn't to find bugs *today* — it was to make sure that next month's refactor can't introduce them.

## Takeaway

Don't chase coverage; let it chase the parts of the codebase you can't yet describe in plain English. Mock at the module level with `AsyncMock` and `monkeypatch.setattr`. Write tests that pin contracts ("the dispatcher special-cases `schedule_meeting`"), not lines. Stop when the marginal test is more brittle than the bug it would catch. Past 60% on a real codebase is plenty; past 80% is usually self-harm.
