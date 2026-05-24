"""
API endpoints for handling Twilio calls.
"""
from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from twilio.rest import Client
from twilio.twiml.voice_response import Connect, VoiceResponse

from app.api.security import verify_twilio_signature

from app.core.config import (
    DEFAULT_FIRST_MESSAGE,
    HTTP_TIMEOUT_SECONDS,
    N8N_WEBHOOK_URL,
    PUBLIC_URL,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_PHONE_NUMBER,
)
from app.core.shared_state import session_manager
from app.services.n8n_service import build_signed_headers

logger = logging.getLogger(__name__)

router = APIRouter()

# n8n route identifiers (documented in the n8n workflow itself).
N8N_ROUTE_FIRST_MESSAGE = "1"

# Twilio status-callback event subscription.
_TWILIO_STATUS_EVENTS: tuple[str, ...] = (
    'initiated', 'ringing', 'answered', 'completed',
)


class OutgoingCallRequest(BaseModel):
    """Request body for ``POST /outgoing-call``."""

    phoneNumber: str = Field(
        ..., pattern=r"^\+?[1-9]\d{7,14}$",
        description="Destination phone number in E.164-ish form."
    )
    firstMessage: str | None = None


def _build_stream_twiml(stream_url: str, first_message: str,
                        caller_number: str, call_sid: str | None = None) -> str:
    """Build a TwiML <Connect><Stream> response.

    Uses the Twilio helper so values are properly XML-escaped (prevents
    TwiML injection when the upstream first-message contains ``<`` / ``&`` / ``"``).
    """
    response = VoiceResponse()
    connect = Connect()
    stream = connect.stream(url=stream_url)
    stream.parameter(name="firstMessage", value=first_message)
    stream.parameter(name="callerNumber", value=caller_number)
    if call_sid is not None:
        stream.parameter(name="callSid", value=call_sid)
    response.append(connect)
    return str(response)


async def _fetch_first_message_from_n8n(caller_number: str) -> str:
    """Ask n8n for the dynamic first-message; fall back to the default on any error."""
    if not N8N_WEBHOOK_URL:
        logger.warning("N8N_WEBHOOK_URL not set; using DEFAULT_FIRST_MESSAGE")
        return DEFAULT_FIRST_MESSAGE

    try:
        body = json.dumps({
            "route": N8N_ROUTE_FIRST_MESSAGE,
            "number": caller_number,
            "data": "empty",
        }).encode("utf-8")
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                N8N_WEBHOOK_URL,
                content=body,
                headers=build_signed_headers(body),
            )
    except (httpx.TimeoutException, httpx.HTTPError) as e:
        logger.warning("n8n first-message fetch failed: %s", e)
        return DEFAULT_FIRST_MESSAGE

    if resp.status_code >= 400:
        logger.warning("n8n first-message non-OK status: %d", resp.status_code)
        return DEFAULT_FIRST_MESSAGE

    text = resp.text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text.strip() or DEFAULT_FIRST_MESSAGE

    if isinstance(data, dict) and data.get('firstMessage'):
        return str(data['firstMessage'])
    return DEFAULT_FIRST_MESSAGE


@router.get("/")
async def root() -> dict[str, str]:
    """Root endpoint to check if the service is running."""
    return {"message": "Twilio + Ultravox Media Stream Server is running!"}


@router.post("/incoming-call", dependencies=[Depends(verify_twilio_signature)])
async def incoming_call(request: Request) -> Response:
    """Handle the inbound call from Twilio.

    Fetches the first message from n8n, stores session data, and returns a
    TwiML response that bridges the call into ``/media-stream``.
    """
    form_data = await request.form()
    twilio_params: dict[str, Any] = dict(form_data)
    logger.info("Incoming call")

    caller_number = twilio_params.get('From', 'Unknown')
    session_id = twilio_params.get('CallSid')
    logger.info("Caller Number: %s, CallSid: %s", caller_number, session_id)

    first_message = await _fetch_first_message_from_n8n(caller_number)

    if session_id:
        await session_manager.create(
            session_id,
            transcript="",
            callerNumber=caller_number,
            callDetails=twilio_params,
            firstMessage=first_message,
            streamSid=None,
            hanging_up=False,
            transcript_sent=False,
        )

    host = PUBLIC_URL or ""
    stream_url = f"{host.replace('https', 'wss')}/media-stream"

    twiml = _build_stream_twiml(
        stream_url=stream_url,
        first_message=first_message,
        caller_number=caller_number,
        call_sid=session_id,
    )
    return Response(content=twiml, media_type="text/xml")


@router.post("/outgoing-call")
async def outgoing_call(payload: OutgoingCallRequest) -> dict[str, Any]:
    """Initiate an outbound Twilio call wired into ``/media-stream``."""
    phone_number = payload.phoneNumber
    first_message = payload.firstMessage or DEFAULT_FIRST_MESSAGE

    logger.info("Initiating outbound call to %s", phone_number)

    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        host = PUBLIC_URL or ""
        stream_url = f"{host.replace('https', 'wss')}/media-stream"

        twiml = _build_stream_twiml(
            stream_url=stream_url,
            first_message=first_message,
            caller_number=phone_number,
        )

        call = client.calls.create(
            twiml=twiml,
            to=phone_number,
            from_=TWILIO_PHONE_NUMBER,
            status_callback=f"{PUBLIC_URL}/call-status",
            status_callback_event=list(_TWILIO_STATUS_EVENTS),
        )

        logger.info("Twilio call created: %s", call.sid)

        await session_manager.create(
            call.sid,
            transcript="",
            callerNumber=phone_number,
            callDetails={
                "originalRequest": payload.model_dump(),
                "startTime": datetime.now().isoformat(),
            },
            firstMessage=first_message,
            streamSid=None,
            hanging_up=False,
            transcript_sent=False,
        )

        return {"success": True, "callSid": call.sid}

    except Exception as error:
        logger.exception("Error creating outbound call")
        # Keep parity with previous error envelope so existing clients still parse it.
        raise HTTPException(status_code=500, detail=str(error))


@router.post("/call-status", dependencies=[Depends(verify_twilio_signature)])
async def call_status(request: Request) -> dict[str, Any]:
    """Receive Twilio status-callback events (currently logged only)."""
    try:
        data = await request.form()
        logger.info(
            "Twilio status update: status=%s duration=%s timestamp=%s callSid=%s",
            data.get('CallStatus'),
            data.get('CallDuration'),
            data.get('Timestamp'),
            data.get('CallSid'),
        )
    except Exception:
        logger.exception("Error reading /call-status request")
        # Silence used to need `traceback`; logger.exception now captures it.
        _ = traceback  # keep import live for downstream debugging
        raise HTTPException(status_code=400, detail="Invalid request")

    return {"success": True}

