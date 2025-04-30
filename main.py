"""
Main entry point for the Ultravox Twilio Voice AI application.
"""
import uvicorn
from fastapi import FastAPI

from app.main import app

# Import critical services and components to ensure they're accessible
from app.core.shared_state import sessions
from app.websockets.media_stream import media_stream
from app.services.tools_service import handle_tool_invocation, handle_question_and_answer, handle_schedule_meeting
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
    MANAGER_STAGE_PROMPT, CALL_SUMMARY_STAGE_PROMPT,
    STAGE_VOICES
)

# Run the application if executed directly
if __name__ == "__main__":
    print(f"Starting server on port {PORT}...")
    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, reload=True)
