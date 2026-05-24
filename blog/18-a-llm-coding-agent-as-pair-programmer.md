# Shipping with an LLM Coding Agent: A Real Retrospective

*Ten commits, three workflows, a security pass, an observability pass, a coverage pass. What the agent got right, what it got wrong, and where the friction actually was.*

## Why write this

There's an enormous amount of LLM-coding marketing in 2026 and very little honest retrospective. This is one project, one developer, one agent, over one stretch — but it's specific enough to be useful. The goal isn't "agents are great" or "agents are dumb." It's "here's what working with one actually looked like at the line-of-code level."

For context: the agent's contribution to VoxFlow over this stretch was 11 commits, ~1100 line additions, ~50 deletions, and 32 new tests. All on top of an existing FastAPI + WebSocket codebase the agent didn't author.

## What the agent was good at

**Mechanical, scoped instrumentation.**
"Add Prometheus counters at these five sites" is exactly the kind of task that's tedious for a human (it's the same five-line pattern, contextualized differently) and trivial for an agent. The result was correct on the first try and consistent across files. Probably saved an hour of careful copy-paste.

**Translating "I want X" into "X plus the obvious next two."**
When I said "add a readiness endpoint," the agent also added the dependency presence check, the 503 contract, the per-dependency status body, and a README table row. Those are exactly the things I would have wanted; I just didn't have to enumerate them.

**Reading large unfamiliar files.**
Walking into a 320-line `media_stream.py` and producing accurate test plans for each branch is faster with an agent than without one. Even when the tests need adjustment, the *coverage map* the agent produces ("here are the 14 branches; here's a one-line test sketch for each") is the highest-value output.

**Safety paranoia at the right moments.**
The agent reflexively asked before `git push --force`, before dropping `.gitignore`'d files that might be in-progress work, before touching files I hadn't asked it to. It noticed unrelated stray diffs (a stray edit to a blog file I hadn't touched) and explicitly unstaged them before committing. That's the kind of discipline a tired human cuts corners on.

## What the agent was bad at

**Over-eagerness on adjacent improvements.**
First drafts often "improved" code I hadn't asked it to. A function I asked it to rename got new docstrings, new type hints, refactored helpers, and an extra error handler. Most of those changes were fine in isolation but they tripled the diff size and made review harder. Took a few cycles of "smaller, please" before drafts stayed surgical.

**Inventing context when it lacked it.**
A few times the agent fabricated a file path or a function name and used it confidently. Always caught at the first tool call (file not found) or test run (NameError), so blast radius was zero — but it's a reminder that confidence is uncorrelated with correctness.

**The mock-shaped failure.**
When tests fail because a mock didn't match reality, the agent's instinct is to make the mock more elaborate, not to check the real code. I had to step in twice to point out that the *test was wrong, not the code*. It's not bad at this, just biased toward "make the failing test pass."

**Underestimating CI environment drift.**
The CI failure that prompted the `audioop-lts; python_version >= "3.13"` marker was very obvious in retrospect — CI runs Python 3.11, the dep requires 3.13 — but the agent missed it until the build actually broke. Pattern: agents have *less* context about your specific runner environment than they appear to.

## Where the friction was

Not where I expected.

The friction was *not* in code generation. Most diffs were applied cleanly.

The friction was in **steering**. Specifically:

1. **Scope discipline.** "Do this one task" works better than "do these three things in order." Even with explicit sequencing, the agent will sometimes interleave them in a way that's hard to review.
2. **Knowing when to push back.** When I asked for an optimization that the codebase didn't need, the agent did it without comment. The cost of that didn't show up until the diff was bigger than the original feature. I wanted more "are you sure?" and less "okay, here it is."
3. **Bridging session memory.** Across long sessions the agent had to be reminded of decisions made earlier in the same conversation. Not catastrophic, but each reminder is interruption cost on my side.

## What I changed about how I worked

After a few cycles, three habits stuck:

**Always end the prompt with success criteria.**
"Add X. Verify with: `pytest tests/test_x.py`. The test should fail before the change and pass after." Specific verification commands shrink the misunderstanding window from "we'll find out at PR review" to "we'll find out in 30 seconds."

**Frame edits as 'remove what's unnecessary' not 'add what's needed.'**
"The retry loop has too many branches; collapse to one path per outcome" produces better diffs than "make the retry loop better." The first has a finish line; the second invites embellishment.

**Treat the agent's first draft as a strawman, not a deliverable.**
Especially for anything novel, the first version is usually mid-quality but it crystalizes the design decisions. Reviewing it against the codebase's existing conventions and asking for a v2 ("match the style of `n8n_service.py`") produces something I'd actually merge.

## What is genuinely better with an agent

A few categories where the lift is large enough to feel:

- **Boilerplate-heavy refactors** (instrumentation, logging, type annotations across a module).
- **Test scaffolding** for code you understand — the human writes the assertions; the agent writes the fixtures and mocks.
- **"How does this codebase do X?"** survey questions over a repo big enough that grep isn't enough.
- **Multi-file edits that follow a consistent pattern** (rename a concept, change a signature in N call sites).

## What is *not* genuinely better

- **Designing the next abstraction.** The agent will happily build whatever you describe; it won't tell you you're describing the wrong thing.
- **Reading subtle async or concurrency code.** Less so for straightforward `await`/`async`, but anything involving cancellation, task groups, or contextvar inheritance is dicier than it looks in the output.
- **Anything involving the dev environment itself.** The agent doesn't know your shell, your venv, your CI runner version. Stuff that depends on those needs explicit context every time.

## The bottom line, today

For *this codebase at this size*, working with an agent feels like having an extremely fast, slightly over-confident junior engineer who never gets tired and needs more directional steering than feedback on craft. Net positive — I shipped multiples of what I would have alone — but the steering load is real.

The framing I've landed on: the agent is best at the *execution* of decisions I've already made, and at *exploration* when I tell it explicitly to explore. It's worst when I ask it to make the decision for me.

Plan the surgery yourself. Let the agent hold the instruments.

## Takeaway

Use an agent. Be specific about scope. Give it verification commands. Read every diff with the eye of someone who will be on call when it breaks. Push back on its drafts; the second version is almost always better. And keep notes on what worked — your next 10-commit session will go faster than this one.
