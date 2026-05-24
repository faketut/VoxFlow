# White-Labeling an AI Agent with Environment Variables

*Turn one codebase into many products without forking.*

## The opportunity

You built an AI receptionist for a dental clinic. A real-estate agency calls and wants the same thing — different greeting, different company name, different calendar list, otherwise identical.

You have three choices:

1. **Fork the repo** — diverging codebases, multiplying bug fixes by N clients.
2. **Add a "client_id" column everywhere** — your code drowns in `if client == "dental":` branches.
3. **Externalize the differences into config** — one codebase, N deployments.

Option 3 is white-labeling. Done right, onboarding a new client is editing a `.env` file.

## What "different" actually means

For VoxFlow, the per-client knobs are:

| Knob | Env var | Default |
|------|---------|---------|
| Agent name | `AGENT_NAME` | `Sara` |
| Company name | `COMPANY_NAME` | `Dental Help 360` |
| Opening line | `DEFAULT_FIRST_MESSAGE` | `"Hey, this is {AGENT_NAME}..."` |
| Voice | `ULTRAVOX_VOICE` | `Tanya-English` |
| Knowledge base | `ULTRAVOX_CORPUS_ID` | (per-tenant UUID) |
| Calendars | `CALENDARS_JSON` | (JSON map of location → email) |
| Webhook | `N8N_WEBHOOK_URL` | (per-tenant n8n flow) |

Onboarding a real estate client:

```env
AGENT_NAME=Mark
COMPANY_NAME=Sunset Realty
DEFAULT_FIRST_MESSAGE=Hello, you've reached Sunset Realty. I'm Mark, how can I help?
ULTRAVOX_VOICE=Mark-English-US
ULTRAVOX_CORPUS_ID=8a1f...
CALENDARS_JSON={"Main Office": "office@sunsetrealty.com"}
N8N_WEBHOOK_URL=https://n8n.sunsetrealty.com/webhook/abc
```

No code changes. Deploy once per client, or run multi-tenant with per-request resolution (advanced).

## How to externalize prompts without losing structure

Hardcoded:

```python
SYSTEM_PROMPT = """You are Sara, the AI assistant for Dental Help 360. ..."""
```

The reflex is to load the whole prompt from a file. That works but loses syntax highlighting and gets unwieldy for multi-stage prompts.

A middle ground: **template strings** with config-injected placeholders.

```python
_SYSTEM_TEMPLATE = """
You are {agent_name}, the AI assistant for {company_name}.
Current time: {now}.
...
"""

def get_system_prompt() -> str:
    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S")
    return _SYSTEM_TEMPLATE.format(
        now=now,
        agent_name=AGENT_NAME,
        company_name=COMPANY_NAME,
    )
```

Best of both worlds: the prompt structure stays in code (readable, version-controlled, type-checked), and the per-tenant identity lives in env vars.

## The `{now}` foot-gun

You'll see this pattern everywhere:

```python
now = datetime.datetime.now(datetime.UTC).strftime(...)
SYSTEM_PROMPT = f"Today is {now}. You are an AI assistant..."
```

It's wrong. `now` is computed **once**, when Python imports the module. The first call gets the correct time. Every call after that gets the same stale timestamp. A long-running server tells callers the date of when the process started.

The fix is the template approach above: substitute at call time, not import time. This is one of the highest-ROI bug fixes you can make in any LLM codebase.

## Configuring lists and maps via env

Strings and numbers fit in env vars cleanly. Lists and maps don't — until you treat env vars as JSON:

```python
import json
import os

_calendars_json = os.environ.get('CALENDARS_JSON')
CALENDARS_LIST: dict[str, str] = (
    json.loads(_calendars_json) if _calendars_json else {
        "LOCATION1": "CALENDAR_EMAIL1",
    }
)
```

```env
CALENDARS_JSON={"Downtown": "downtown@clinic.com", "Uptown": "uptown@clinic.com"}
```

Now adding a new location is one line in `.env`. No code change, no deploy of the codebase — only an env update + restart.

## Required vs optional, fail-fast

Some env vars are required (you literally can't function without them). Others have defaults. Distinguish them and crash at startup if required ones are missing:

```python
_REQUIRED_ENV_VARS = (
    'TWILIO_ACCOUNT_SID',
    'TWILIO_AUTH_TOKEN',
    'TWILIO_PHONE_NUMBER',
    'ULTRAVOX_API_KEY',
    'N8N_WEBHOOK_URL',
    'PUBLIC_URL',
)

def validate_config() -> None:
    missing = [v for v in _REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
```

Wire this into FastAPI's lifespan so a misconfigured deployment fails loudly at boot instead of breaking mid-call.

## Per-tenant deployment patterns

| Pattern | When |
|---------|------|
| One process per tenant | <50 tenants, low traffic each. Trivial to operate. |
| Single process, tenant resolved per call | High volume, many small tenants. Needs per-call config lookup (DB, not env vars). |
| Kubernetes namespace per tenant | Enterprise tier, isolation required. |

VoxFlow today is the first pattern. Migrating to the second means swapping `from app.core.config import AGENT_NAME` for a `get_tenant_config(call.to_number)` call. The interfaces don't change.

## Takeaway

White-labeling is mostly about discipline: never hardcode anything that varies between clients. Identity, branding, knowledge base IDs, calendar maps, webhook URLs — all of it goes in env vars. The codebase becomes the product; deployments become the product instances.
