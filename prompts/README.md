# VoxFlow Prompt Overrides

Drop `.md` files in this directory (or any directory pointed at by
`PROMPT_DIR`) to replace the built-in prompt templates **without touching
code or rebuilding the Docker image**.

## Files VoxFlow looks for

| File              | Stage                       | Required? |
|-------------------|-----------------------------|-----------|
| `system.md`       | Stage 1 — greeting & verify | optional  |
| `main_convo.md`   | Stage 2 — main conversation | optional  |
| `call_summary.md` | Stage 3 — wrap-up           | optional  |

Any missing file falls back to the built-in default — you only need to
override the stages you actually want to change.

## Placeholders

These tokens are substituted at runtime; everything else passes through
verbatim:

| Token            | Value                                                        |
|------------------|--------------------------------------------------------------|
| `{agent_name}`   | `AGENT_NAME` env (default `Sara`)                            |
| `{company_name}` | `COMPANY_NAME` env (default `Acme Services`)                 |
| `{now}`          | Current UTC timestamp (`YYYY-MM-DD HH:MM:SS`) at render time |

> Use plain `{` / `}` curly braces around any literal that you do **not**
> want substituted — Python's `str.format` will raise on unknown keys, so
> double them like `{{this is literal}}`.

## Usage

```bash
# Locally
export PROMPT_DIR=/path/to/your/prompts
uvicorn app.main:app --port 8000

# Docker — mount a volume
docker run --env-file .env \
  -v $(pwd)/my-prompts:/app/prompts:ro \
  -e PROMPT_DIR=/app/prompts \
  -p 8000:8000 \
  ghcr.io/faketut/voxflow:latest
```

## Example

A minimal `system.md`:

```markdown
## Role
You are {agent_name}, the friendly voice of {company_name}.

## Greeting
"Hi, thanks for calling {company_name}! This is {agent_name}.
 How can I help today?"

## Notes
- Current time: {now}
- Never mention tool names.
```

Restart the service after editing (templates are loaded once at startup).
