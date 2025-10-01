"""
Main FastAPI application entry point for VoxFlow AI Receptionist.
"""
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from app.api.endpoints.calls import router as calls_router
from app.websockets.media_stream import media_stream
from app.core.config import PORT, validate_config

# Import critical services and components to ensure they're accessible
from app.core.shared_state import sessions
from app.services.tools_service import handle_tool_invocation, handle_queryCorpus, handle_schedule_meeting
from app.services.ultravox_service import create_ultravox_call
from app.services.n8n_service import send_transcript_to_n8n, send_to_webhook
from app.utils.websocket_utils import safe_close_websocket
from app.core.config import (
    ULTRAVOX_API_KEY, N8N_WEBHOOK_URL, PUBLIC_URL, PORT,
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER,
    ULTRAVOX_MODEL, ULTRAVOX_VOICE, ULTRAVOX_SAMPLE_RATE, ULTRAVOX_BUFFER_SIZE,
    CALENDARS_LIST, LOG_EVENT_TYPES
)
from app.core.prompts import (
    SYSTEM_MESSAGE, get_stage_prompt, get_stage_voice,
    MAINCONVO_STAGE_PROMPT, CALL_SUMMARY_STAGE_PROMPT,
    STAGE_VOICES
)

# Create FastAPI application
app = FastAPI(
    title="VoxFlow AI Receptionist",
    description="AI-powered voice receptionist with Twilio and Ultravox integration",
    version="1.0.0"
)

# Include API routers
app.include_router(calls_router)

# Register WebSocket route
@app.websocket("/media-stream")
async def websocket_endpoint(websocket: WebSocket):
    await media_stream(websocket)

# Validate configuration on startup
@app.on_event("startup")
async def startup_event():
    validate_config()
    print("Validating configuration...")
    print("VoxFlow AI Receptionist started successfully")

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "VoxFlow AI Receptionist"}

# Run the application if executed directly
if __name__ == "__main__":
    print(f"Starting VoxFlow AI Receptionist on port {PORT}...")
    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, reload=True)
