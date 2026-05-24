# WebSocket Idle Timeouts (or: How to Kill Zombie Calls)

*Twilio sometimes goes quiet without sending `stop`. Your handler waits forever, your worker leaks, and your bill grows. Here's the 15-line fix.*

## The bug you'll only see in production

In every Twilio Media Stream tutorial, the receive loop looks like this:

```python
while True:
    message = await twilio_ws.receive_text()
    data = json.loads(message)
    if data["event"] == "stop":
        break
```

This works for 99% of calls. The 1% kills you.

What actually happens at scale:
- Network partition between Twilio and your pod — TCP keepalive eventually trips, but not for minutes.
- Twilio container restart — they drop the stream without sending `stop`.
- Caller hangs up in a weird state — Twilio sometimes sends nothing.
- Mobile dies in a tunnel — connection just stops emitting bytes.

In all four cases, `await receive_text()` blocks forever. Your worker is now:

- Tying up an asyncio task
- Holding an open Ultravox WebSocket (which costs money)
- Holding session state in memory
- Counted as a "live" connection by your load balancer

Multiply by your daily call volume × the fraction that hit one of these states. After a week, your replicas need restarting "because of a memory leak."

## The fix: wrap the receive in a timeout

```python
WS_IDLE_TIMEOUT_SECONDS = 60  # tune to your call profile

while True:
    try:
        message = await asyncio.wait_for(
            twilio_ws.receive_text(),
            timeout=WS_IDLE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("Twilio WS idle for %ds; tearing down",
                       WS_IDLE_TIMEOUT_SECONDS)
        call_disconnects_total.labels(reason="idle_timeout").inc()
        raise WebSocketDisconnect(code=1001, reason="idle timeout")
```

Three things to notice:

**1. We raise `WebSocketDisconnect`, not `cancel()`.** This is the key insight. The whole call lifecycle is wrapped in a `TaskGroup` that already knows how to tear down on `WebSocketDisconnect`. Reusing that path means cleanup runs uniformly — sockets close, transcripts flush, sessions get popped — whether the disconnect was natural or synthetic. One teardown code path, zero special cases.

**2. We label the disconnect.** This is why `voxflow_call_disconnects_total{reason="idle_timeout"}` from the metrics post matters. Without the label, your "disconnect" graph blurs together call ends and zombies. With it, idle timeouts become a dedicated SLI: a sudden spike means an upstream network problem.

**3. We log the timeout duration.** When you tune `WS_IDLE_TIMEOUT_SECONDS` later, you want to see *which* calls actually crossed the line. A bare "timeout" log line is useless six months in.

## How to pick the threshold

Your timeout needs to be:

- **Longer than the longest legitimate silence in a call.** During a 30-second "let me look that up" hold, Twilio still ships periodic media frames (silence is still bytes), so this is rarely the limit.
- **Shorter than your replica's lifetime budget.** If you scale down pods after 1 hour of "no new calls," your zombies must die before then or they'll prevent scale-down.
- **Longer than your ping interval, if you have one.** Twilio doesn't, but if you add app-level keepalives, the timeout must be >= 2× your keepalive interval.

60 seconds is the sweet spot for voice. 30 seconds is too aggressive (you'll kill real calls during long backend lookups). 5 minutes is too lenient (zombies linger).

Make it an env var (`WS_IDLE_TIMEOUT_SECONDS`) and tune from metrics, not from gut feel.

## Why not just rely on TCP keepalive?

OS-level TCP keepalive defaults are:

- Linux: 2-hour idle before first probe, then 9 probes × 75s.
- Most cloud LBs: drop idle TCP at 60s–10min.

Two problems:

- 2 hours is much too slow to catch the zombie before it hurts you.
- The LB will drop your TCP socket without telling the application layer, so your `receive_text()` still blocks until the next write attempt errors out.

Application-layer timeout is the only one that's both fast and reliable.

## Why not WebSocket ping/pong?

You could. The `websockets` library on the Ultravox side does (we set `ping_interval=20.0`). For Twilio's Media Stream, the protocol doesn't standardize ping behavior, so the simpler approach — *if a frame doesn't arrive in N seconds, we're done* — is more portable and matches the actual failure mode you care about (no media = no call).

## The graph that proves it works

After deploying the timeout, you should see a flat-ish line on:

```promql
sum(rate(voxflow_call_disconnects_total{reason="idle_timeout"}[5m]))
```

A non-zero baseline is normal (zombies exist). A sudden spike means an upstream problem — Twilio incident, your TLS termination flaking, ISP routing event. Either way it's noticed in 5 minutes instead of "next time the on-call notices replicas are slow."

## Takeaway

Every long-lived WebSocket loop needs an idle timeout, every timeout needs to feed the normal disconnect path, and every disconnect needs a labeled metric. Fifteen lines of code prevents a class of production memory leaks that's invisible in dev and obvious in prod. Add it on day one, not after the first incident.
