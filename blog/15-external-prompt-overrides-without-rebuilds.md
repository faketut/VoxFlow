# Prompts as Config: `PROMPT_DIR` and the Tunable Agent

*Turn "change the agent's behavior" from a code change into a `kubectl apply`.*

## When a prompt change is a deployment

In an early VoxFlow build, every stage prompt was a triple-quoted string in `prompts.py`. A non-trivial chunk of the company's IP — the tone, the verification script, the escalation rules — lived inside Python source. Consequences:

- "Soften the rejection script" was a PR, a review, a CI run, and a redeploy.
- The product manager could see the prompts but not edit them.
- A new tenant ("can you make Sara say 'g'day' for the Sydney office?") required either a fork or a feature flag.
- A/B testing two prompts meant deploying two builds.

This isn't a tooling problem. It's a *boundary* problem: code and content were tangled together.

## The fix is two changes and one env var

**1. Each prompt becomes a file.**

```
prompts/
├── system.md       # stage 1 — greet & verify
├── main_convo.md   # stage 2 — main conversation
└── call_summary.md # stage 3 — wrap-up
```

Plain markdown, with `{agent_name}`, `{company_name}`, `{now}` placeholders.

**2. A loader with a fallback.**

```python
def _load_template(name: str, default: str) -> str:
    """Return template `name` from PROMPT_DIR, or the built-in default."""
    if not PROMPT_DIR:
        return default
    path = Path(PROMPT_DIR) / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    except OSError as e:
        logger.warning("Cannot read %s, using default: %s", path, e)
        return default

_SYSTEM_MESSAGE_TEMPLATE  = _load_template("system",       _DEFAULT_SYSTEM_TEMPLATE)
_MAINCONVO_STAGE_TEMPLATE = _load_template("main_convo",   _DEFAULT_MAINCONVO_TEMPLATE)
_CALL_SUMMARY_TEMPLATE    = _load_template("call_summary", _DEFAULT_CALL_SUMMARY_TEMPLATE)
```

**3. An env var to point at the directory.**

```
PROMPT_DIR=/etc/voxflow/prompts
```

If unset → built-in defaults. If set but a file is missing → that one prompt falls back, the others load. If set and the directory is read-only → it still works, the loader catches `OSError`.

Every behavior the prompt controls is now a file. Every file is now mountable. Code never has to know.

## What this unlocks

**Per-tenant prompts via ConfigMaps.**
Each tenant gets a `ConfigMap` mounted at `/etc/voxflow/prompts`. Spawn a new deployment with a different mount, same image. Zero code changes per customer.

```yaml
volumes:
  - name: prompts
    configMap:
      name: voxflow-prompts-acme-dental
volumeMounts:
  - name: prompts
    mountPath: /etc/voxflow/prompts
env:
  - name: PROMPT_DIR
    value: /etc/voxflow/prompts
  - name: COMPANY_NAME
    value: Acme Dental
```

**Edits become reviewable like content, not code.**
PMs and content writers can open PRs against a `prompts/` repo, get reviewed by a clinical lead, and merge — without touching the Python codebase. Deploy is `kubectl apply`.

**Rollback is a `git revert`.**
If a new prompt regresses behavior, you revert the prompts repo and the next pod that starts (or the next `configmap reload`) picks up the old one. No image rebuild.

**A/B testing is two ConfigMaps and a service mesh split.**
Route 10% of inbound traffic to a deployment with the `prompts-v2` mount. Compare `voxflow_tool_invocations_total{tool="verify",outcome="ok"}` between the two. If v2 wins, flip the split. If it loses, delete the deployment.

## The placeholder discipline

Three placeholders, no more:

| Placeholder | Purpose |
|-------------|---------|
| `{agent_name}` | The persona ("Sara", "Mark", "Aisha") |
| `{company_name}` | The brand ("Acme Dental", "Sunset Realty") |
| `{now}` | Wall-clock time at call start, computed per-call |

Why so few? Because every placeholder is a coupling between the prompt content and the code that supplies it. Add `{caller_first_name}` and now the renderer needs caller context, the loader needs a different signature, the templates without that placeholder need to keep working, and you've started building a templating engine.

If you need real templating, use Jinja2 from the start. If you don't, two-string `str.format()` is plenty.

## What about hot-reloading?

VoxFlow loads templates *once at import*. Restarting a pod re-reads the files; running pods don't. This is intentional:

- Mid-call template swaps would produce calls that change voice halfway through.
- ConfigMap mounts in Kubernetes are eventually-consistent across replicas anyway.
- "Restart pods to pick up changes" is a one-line `kubectl rollout restart` and aligns with every other config-change workflow.

If hot-reload genuinely matters (it usually doesn't), use `inotify` + a debounce. But don't ship it until someone asks twice.

## What this does *not* solve

This pattern externalizes prompt *text*. It doesn't externalize prompt *structure* — the stages, the tools per stage, the transition graph. That's a code-level concept (see the multi-stage state machine post). The two concerns intentionally stay separate: behavior is code, content is config.

## Takeaway

A two-line loader and one env var turn your prompts from compiled-in IP into mountable, reviewable, rollbackable artifacts. Non-engineers can change the agent's words. A new tenant is a ConfigMap, not a fork. A/B testing is a deployment, not a feature flag. The cost is ~20 lines and the discipline to keep the placeholder set tiny.
