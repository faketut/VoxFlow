"""
Services for handling tool invocations from Ultravox.

Tools are dispatched via the ``TOOL_HANDLERS`` registry; each handler receives
a validated Pydantic model and is wrapped in a single error boundary that logs
the full traceback and returns a generic message to the agent.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

import websockets
from pydantic import BaseModel, Field, ValidationError
from twilio.rest import Client
from websockets.protocol import State

from app.core.config import (
    CALENDARS_LIST,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
)
from app.core.prompts import get_stage_prompt, get_stage_voice
from app.core.shared_state import session_manager
from app.services.n8n_service import send_to_webhook, send_transcript_to_n8n
from app.utils.websocket_utils import safe_close_websocket

logger = logging.getLogger(__name__)


# -------- Pydantic parameter models --------------------------------------------------

class QueryCorpusParams(BaseModel):
    question: str | None = None


class VerifyParams(BaseModel):
    full_name: str = ""
    phone_number: str = ""


class ScheduleMeetingParams(BaseModel):
    name: str = Field(...)
    email: str = Field(...)
    purpose: str = Field(...)
    datetime: str = Field(...)
    location: str = Field(...)


class MoveToMainConvoParams(BaseModel):
    issue_type: str = ""
    issue_details: str = ""
    customer_name: str = ""


class MoveToCallSummaryParams(BaseModel):
    pass


class HangUpParams(BaseModel):
    pass


# -------- Helpers --------------------------------------------------------------------

async def _send_tool_result(uv_ws: Any, invocation_id: str, result: str,
                            response_type: str = "tool-response") -> None:
    await uv_ws.send(json.dumps({
        "type": "client_tool_result",
        "invocationId": invocation_id,
        "result": result,
        "response_type": response_type,
    }))


async def _send_tool_error(uv_ws: Any, invocation_id: str, message: str) -> None:
    await uv_ws.send(json.dumps({
        "type": "client_tool_result",
        "invocationId": invocation_id,
        "error_type": "implementation-error",
        "error_message": message,
    }))


# -------- Individual handlers --------------------------------------------------------

async def handle_queryCorpus(uv_ws: Any, invocation_id: str, params: QueryCorpusParams) -> None:
    # Ultravox performs the actual corpus query; this client-side hook just logs.
    logger.info("[Q&A] question=%s", params.question)


async def handle_verify(uv_ws: Any, invocation_id: str, params: VerifyParams) -> None:
    # Mock verification: a real system would query a database here.
    confirmed = bool(params.full_name) and bool(params.phone_number)
    result = "Confirmed" if confirmed else "Not Confirmed"
    logger.info("Verification result for %s: %s", params.full_name, result)
    await _send_tool_result(uv_ws, invocation_id, result)


async def handle_schedule_meeting(uv_ws: Any, invocation_id: str,
                                  params: ScheduleMeetingParams) -> None:
    calendar_id = CALENDARS_LIST.get(params.location)
    if not calendar_id:
        await _send_tool_error(uv_ws, invocation_id,
                               f"Invalid location: {params.location}")
        return

    # Resolve callerNumber from the active session if we can find it.
    call_sid, session = await session_manager.find_by_uv_ws(uv_ws)
    caller_number = session.get("callerNumber", "Unknown") if session else "Unknown"

    payload = {
        "route": "3",
        "number": caller_number,
        "data": json.dumps({
            "name": params.name,
            "email": params.email,
            "purpose": params.purpose,
            "datetime": params.datetime,
            "calendar_id": calendar_id,
        }),
    }
    logger.info("Scheduling meeting for callSid=%s", call_sid)
    webhook_response = await send_to_webhook(payload)
    try:
        parsed = json.loads(webhook_response)
        booking_message = parsed.get(
            "message", "I'm sorry, I couldn't schedule the meeting at this time."
        )
    except json.JSONDecodeError:
        logger.warning("n8n schedule_meeting returned non-JSON: %s", webhook_response)
        booking_message = "I'm sorry, I couldn't schedule the meeting at this time."

    await _send_tool_result(uv_ws, invocation_id, booking_message)


async def handle_move_to_main_convo(uv_ws: Any, invocation_id: str,
                                    params: MoveToMainConvoParams) -> None:
    prompt = get_stage_prompt('main_convo')
    voice = get_stage_voice('main_convo')
    name_clause = f", {params.customer_name}" if params.customer_name else ""
    greeting = (
        f"You're now speaking with Alex, the Senior main_convo at SecureLife "
        f"Insurance. I've been briefed on your situation{name_clause}. "
        f"You're concerned about {params.issue_type}. How can I help you today?"
    )
    await uv_ws.send(json.dumps({
        "type": "client_tool_result",
        "invocationId": invocation_id,
        "result": json.dumps({
            "systemPrompt": prompt,
            "voice": voice,
            "toolResultText": greeting,
        }),
        "response_type": "new-stage",
    }))


async def handle_move_to_call_summary(uv_ws: Any, invocation_id: str,
                                      params: MoveToCallSummaryParams) -> None:
    prompt = get_stage_prompt('call_summary')
    voice = get_stage_voice('call_summary')
    msg = "Before we conclude our call, let me summarize what we've discussed and next steps."
    await uv_ws.send(json.dumps({
        "type": "client_tool_result",
        "invocationId": invocation_id,
        "result": json.dumps({
            "systemPrompt": prompt,
            "voice": voice,
            "toolResultText": msg,
        }),
        "response_type": "new-stage",
    }))


async def handle_hangUp(uv_ws: Any, invocation_id: str, params: HangUpParams) -> None:
    call_sid, session = await session_manager.find_by_uv_ws(uv_ws)
    logger.info("hangUp tool invoked (callSid=%s)", call_sid)

    if session is not None:
        await session_manager.update(call_sid, hanging_up=True)

    try:
        ultravox_active = session.get('ultravox_ws_active', True) if session else True
        if ultravox_active and uv_ws and uv_ws.state == State.OPEN:
            await _send_tool_result(uv_ws, invocation_id, "Call ended successfully")
            if session is not None and 'ultravox_ws_active' in session:
                await session_manager.update(call_sid, ultravox_ws_active=False)
    except Exception:
        logger.exception("Error sending hangUp response")

    try:
        if call_sid:
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

            # Defensive: extract canonical 34-char Twilio CallSid if it was wrapped.
            call_sid_str = str(call_sid)
            if len(call_sid_str) > 34 and 'CA' in call_sid_str:
                start = call_sid_str.find('CA')
                extracted = call_sid_str[start:start + 34]
                if len(extracted) == 34:
                    call_sid = extracted

            client.calls(call_sid).fetch()
            client.calls(call_sid).update(status='completed')
            logger.info("Twilio call %s marked completed", call_sid)

            if session is not None and not session.get('transcript_sent', False):
                await send_transcript_to_n8n(session)
    except Exception:
        logger.exception("Error ending Twilio call")

    await safe_close_websocket(uv_ws, name="Ultravox WebSocket (hangUp)")


# -------- Dispatch -------------------------------------------------------------------

ToolHandler = Callable[[Any, str, BaseModel], Awaitable[None]]

TOOL_HANDLERS: dict[str, tuple[type[BaseModel], ToolHandler]] = {
    "queryCorpus":          (QueryCorpusParams,       handle_queryCorpus),
    "verify":               (VerifyParams,            handle_verify),
    "schedule_meeting":     (ScheduleMeetingParams,   handle_schedule_meeting),
    "move_to_main_convo":   (MoveToMainConvoParams,   handle_move_to_main_convo),
    "move_to_call_summary": (MoveToCallSummaryParams, handle_move_to_call_summary),
    "hangUp":               (HangUpParams,            handle_hangUp),
}


async def handle_tool_invocation(uv_ws: Any, toolName: str, invocationId: str,
                                 parameters: dict[str, Any]) -> None:
    """Validate params for ``toolName`` and dispatch to the registered handler."""
    logger.info("Tool invocation: %s id=%s", toolName, invocationId)

    entry = TOOL_HANDLERS.get(toolName)
    if entry is None:
        logger.warning("Unknown tool: %s", toolName)
        await _send_tool_error(uv_ws, invocationId, f"Unknown tool: {toolName}")
        return

    model_cls, handler = entry
    try:
        validated = model_cls(**(parameters or {}))
    except ValidationError as e:
        logger.warning("Invalid parameters for tool %s: %s", toolName, e)
        # Match the legacy behavior for schedule_meeting: ask the agent for the
        # missing fields instead of returning a hard error.
        if toolName == "schedule_meeting":
            missing = [err["loc"][0] for err in e.errors() if err["type"] == "missing"]
            if missing:
                prompt = (
                    "Please provide the following information to schedule your "
                    f"meeting: {', '.join(map(str, missing))}."
                )
                await _send_tool_result(uv_ws, invocationId, prompt)
                return
        await _send_tool_error(uv_ws, invocationId, "Invalid parameters")
        return

    try:
        await handler(uv_ws, invocationId, validated)
    except Exception:
        logger.exception("Handler for tool %s raised", toolName)
        try:
            await _send_tool_error(
                uv_ws, invocationId, f"An error occurred while processing {toolName}."
            )
        except Exception:
            logger.exception("Failed to send error result for tool %s", toolName)

