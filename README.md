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
```env
PUBLIC_URL=your_public_url
N8N_WEBHOOK_URL=your_webhook_url
ULTRAVOX_API_KEY=your_ultravox_key
PORT=8000
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
│   ├── api/           # REST API endpoints
│   ├── core/          # Configuration & prompts
│   ├── services/      # Business logic (Twilio, Ultravox, N8N)
│   ├── websockets/    # Real-time media streaming
│   └── main.py        # Application entry point
├── requirements.txt
└── README.md
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
Extend functionality in `app/services/tools_service.py`:
```python
elif toolName == "your_tool":
    # Implement your tool logic
    pass
```

## Testing

1. **Make a test call** to your Twilio number
2. **Interact** with the AI assistant
3. **Verify** meeting bookings and data flow
4. **Check logs** for debugging

## Troubleshooting

- **Webhook unreachable**: Verify `PUBLIC_URL` and Twilio configuration
- **Ngrok URL changes**: Update `PUBLIC_URL` when ngrok restarts
- **API errors**: Check environment variables and API keys

## 📄 License

MIT License - See LICENSE file for details.

---

**Built with**: FastAPI, Twilio, Ultravox, WebSockets, N8N