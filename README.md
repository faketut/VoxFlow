# VoxFlow: AI Receptionist

An intelligent voice receptionist powered by **Twilio** and **Ultravox** that handles phone calls with multi-stage conversation flows, WebSocket streaming, and automated workflow integration.

## Key Features

- **Voice AI Integration** - Twilio phone system with Ultravox AI processing
- **Multi-Stage Conversations** - Structured call flows with different voice personalities
- **Real-time Streaming** - WebSocket-based media streaming and data storage
- **Workflow Automation** - N8N integration for data processing and notifications
- **Smart Scheduling** - Calendar integration for meeting bookings across locations
- **Modular Architecture** - Clean, maintainable codebase with separation of concerns

## Quick Start

### Prerequisites
- Python 3.11+
- Twilio account with phone number
- Ultravox API key
- N8N webhook URL

### Installation

1. **Clone and setup**:
   ```bash
   git clone <repository-url>
   cd VoxFlow
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your API keys and URLs
   ```

3. **Run the application**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

## Configuration

### Environment Variables

Required (the app fails to start if any are missing — see `validate_config()`):

```env
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_token
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX
ULTRAVOX_API_KEY=your_ultravox_key
N8N_WEBHOOK_URL=your_webhook_url
PUBLIC_URL=https://your-public-url
```

Optional (with defaults):

```env
PORT=8000
LOG_LEVEL=INFO
HTTP_TIMEOUT_SECONDS=10
ULTRAVOX_MODEL=fixie-ai/ultravox-70B
ULTRAVOX_VOICE=Tanya-English
ULTRAVOX_TEMPERATURE=0.1
ULTRAVOX_TURN_ENDPOINT_DELAY=0.384s
ULTRAVOX_CORPUS_ID=...
```

### Twilio Setup
1. Purchase a Twilio phone number
2. Configure webhook: `https://your-public-url/incoming-call`
3. Set HTTP method to POST

### Local Development
Use ngrok for local testing:
```bash
ngrok http 8000
# Use the HTTPS URL as your PUBLIC_URL
```

## Architecture

```
VoxFlow/
├── app/
│   ├── api/endpoints/calls.py   # REST endpoints (/incoming-call, /outgoing-call, /call-status)
│   ├── core/
│   │   ├── config.py            # Env config + fail-fast validation
│   │   ├── prompts.py           # System prompts per call stage
│   │   └── shared_state.py      # SessionManager (asyncio.Lock per call)
│   ├── services/
│   │   ├── n8n_service.py       # Async webhook client (httpx)
│   │   ├── ultravox_service.py  # Ultravox call creation
│   │   └── tools_service.py     # TOOL_HANDLERS dispatch + Pydantic params
│   ├── utils/websocket_utils.py # safe_close_websocket
│   ├── websockets/media_stream.py # CallState + asyncio.TaskGroup
│   └── main.py                  # FastAPI app (lifespan startup)
├── requirements.txt
└── README.md
```

### Call flow

```mermaid
sequenceDiagram
    autonumber
    actor Caller as 📞 Caller
    participant Twilio
    participant API as FastAPI<br/>(/incoming-call)
    participant N8N
    participant WS as /media-stream<br/>(CallState + TaskGroup)
    participant SM as SessionManager
    participant UV as Ultravox

    Caller->>Twilio: Dial number
    Twilio->>API: POST /incoming-call (CallSid, From)
    API->>N8N: POST {route:1, number} (httpx, timeout)
    N8N-->>API: { firstMessage }
    API->>SM: create(call_sid, ...)
    API-->>Twilio: TwiML <Connect><Stream> (XML-escaped)
    Twilio->>WS: WebSocket open + "start" event
    WS->>UV: create_ultravox_call(systemPrompt, firstMessage)
    UV-->>WS: joinUrl
    WS->>UV: WebSocket connect

    par Twilio → Ultravox (audio in)
        Twilio->>WS: media (µ-law, base64)
        WS->>UV: PCM s16le frames
    and Ultravox → Twilio (audio out)
        UV-->>WS: PCM s16le / events
        WS-->>Twilio: media (µ-law, base64)
    and Tool invocations
        UV-->>WS: client_tool_invocation
        WS->>WS: TOOL_HANDLERS[name] (validated Pydantic params)
        WS->>N8N: schedule_meeting / transcript (httpx)
        WS-->>UV: client_tool_result
    end

    Caller-->>Twilio: Hang up
    Twilio-->>WS: WebSocketDisconnect
    WS->>N8N: POST {route:2, transcript}
    WS->>SM: pop(call_sid)
    WS->>UV: close()
```

### Module dependencies

```mermaid
flowchart LR
    main[app.main<br/>FastAPI + lifespan] --> calls[api.endpoints.calls]
    main --> ms[websockets.media_stream]
    main --> cfg[core.config]

    calls --> sm[core.shared_state<br/>SessionManager]
    calls --> n8n[services.n8n_service]
    calls --> cfg

    ms --> sm
    ms --> uv[services.ultravox_service]
    ms --> tools[services.tools_service]
    ms --> n8n
    ms --> wsu[utils.websocket_utils]
    ms --> prompts[core.prompts]

    tools --> sm
    tools --> n8n
    tools --> wsu
    tools --> prompts
    tools --> cfg

    n8n --> cfg
    uv --> cfg
```

## Call Flow System

### Stage 1: Greeting & Authentication
- **Voice**: Tanya-English
- **Purpose**: Customer greeting and verification
- **Tools**: Query corpus, transition to main conversation

### Stage 2: Main Conversation
- **Voice**: Mark
- **Purpose**: Handle Q&A, scheduling, billing, emergencies
- **Tools**: Query corpus, schedule meetings, transition to summary

### Stage 3: Call Summary
- **Voice**: Tanya-English
- **Purpose**: Summarize call and confirm next steps
- **Tools**: Final queries, call termination

## Customization

### System Prompts
Edit `app/core/prompts.py` to customize:
- Assistant behavior and persona
- Call stage prompts
- Voice personalities

### Calendar Integration
Configure locations in `app/core/config.py`:
```python
CALENDARS_LIST = {
    "New York": "ny-office@example.com",
    "San Francisco": "sf-office@example.com",
    # Add more locations
}
```

### Adding Tools
Define a Pydantic model for the tool's parameters, write a handler, and register both in `app/services/tools_service.py`:

```python
class YourToolParams(BaseModel):
    foo: str

async def handle_your_tool(uv_ws, invocation_id, params: YourToolParams) -> None:
    # ...implement...
    await _send_tool_result(uv_ws, invocation_id, "done")

TOOL_HANDLERS["your_tool"] = (YourToolParams, handle_your_tool)
```

Also advertise the tool to Ultravox in `app/services/ultravox_service.py` (`_build_selected_tools`).

## Testing

1. **Make a test call** to your Twilio number
2. **Interact** with the AI assistant
3. **Verify** meeting bookings and data flow
4. **Check logs** for debugging

## Troubleshooting

- **Webhook unreachable**: Verify `PUBLIC_URL` and Twilio configuration
- **Ngrok URL changes**: Update `PUBLIC_URL` when ngrok restarts
- **API errors**: Check environment variables and API keys



---

**Built with**: FastAPI, Twilio, Ultravox, WebSockets, N8N
