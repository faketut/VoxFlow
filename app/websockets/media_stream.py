"""
WebSocket handlers for Twilio and Ultravox media streaming.
"""
from __future__ import annotations

import asyncio
import audioop
import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from websockets.protocol import State

from app.core.config import LOG_EVENT_TYPES
from app.core.prompts import SYSTEM_MESSAGE
from app.core.shared_state import Session, session_manager
from app.services.n8n_service import send_transcript_to_n8n
from app.services.ultravox_service import create_ultravox_call
from app.services.tools_service import handle_tool_invocation
from app.utils.websocket_utils import safe_close_websocket

logger = logging.getLogger(__name__)


@dataclass
class CallState:
    """Mutable per-call coordination state shared between the two handler tasks."""

    twilio_ws: WebSocket
    call_sid: str | None = None
    stream_sid: str = ""
    session: Session | None = None
    uv_ws: Any = None
    twilio_active: bool = True
    ultravox_active: bool = False
    started: asyncio.Event = field(default_factory=asyncio.Event)


async def media_stream(websocket: WebSocket) -> None:
    """Bridge a Twilio Media Stream WebSocket to an Ultravox call WebSocket."""
    await websocket.accept()
    logger.info("Client connected to /media-stream (Twilio)")

    state = CallState(twilio_ws=websocket)

    try:
        async with asyncio.TaskGroup() as tg:
            twilio_task = tg.create_task(_handle_twilio(state), name="twilio")
            # Ultravox handler waits for the Twilio "start" event before pulling.
            tg.create_task(_handle_ultravox_when_ready(state, twilio_task),
                           name="ultravox-bootstrap")
    except* WebSocketDisconnect:
        logger.info("Twilio WebSocket disconnected (CallSid=%s)", state.call_sid)
    except* Exception as eg:  # noqa: BLE001 — log any unexpected error groups
        for exc in eg.exceptions:
            logger.exception("Unhandled exception in media_stream", exc_info=exc)
    finally:
        await _cleanup(state)


async def _handle_ultravox_when_ready(state: CallState,
                                      twilio_task: asyncio.Task) -> None:
    """Wait for the Twilio start event, then run the Ultravox receive loop."""
    # Wait for either the start event or the Twilio task ending early.
    started_wait = asyncio.create_task(state.started.wait())
    done, _ = await asyncio.wait(
        {started_wait, twilio_task}, return_when=asyncio.FIRST_COMPLETED
    )
    if started_wait not in done:
        # Twilio handler finished before we ever started; nothing to do.
        started_wait.cancel()
        return

    if state.uv_ws is None:
        return

    await _handle_ultravox(state)


async def _handle_ultravox(state: CallState) -> None:
    """Receive messages from Ultravox and forward audio to Twilio."""
    try:
        async for raw_message in state.uv_ws:
            if state.session and state.session.get('hanging_up', False):
                logger.debug("hanging_up flag set; exiting ultravox loop")
                break

            if isinstance(raw_message, bytes):
                await _forward_agent_audio(state, raw_message)
            else:
                await _handle_ultravox_text(state, raw_message)

    except (websockets.exceptions.ConnectionClosedError,
            websockets.exceptions.ConnectionClosedOK) as e:
        logger.info("Ultravox WebSocket closed: %s", e)
    except Exception:
        logger.exception("Error in _handle_ultravox")
    finally:
        state.ultravox_active = False
        if state.session is not None:
            state.session['ultravox_ws_active'] = False


async def _forward_agent_audio(state: CallState, pcm_bytes: bytes) -> None:
    try:
        mu_law_bytes = audioop.lin2ulaw(pcm_bytes, 2)
        payload_base64 = base64.b64encode(mu_law_bytes).decode('ascii')
    except Exception:
        logger.exception("Error transcoding PCM to mu-law")
        return

    if not state.twilio_active:
        return

    try:
        await state.twilio_ws.send_text(json.dumps({
            "event": "media",
            "streamSid": state.stream_sid,
            "media": {"payload": payload_base64},
        }))
    except Exception:
        logger.exception("Error sending media to Twilio")
        state.twilio_active = False


async def _handle_ultravox_text(state: CallState, raw_message: str) -> None:
    try:
        msg_data = json.loads(raw_message)
    except Exception:
        logger.debug("Ultravox non-JSON text: %s", raw_message)
        return

    msg_type = msg_data.get("type") or msg_data.get("eventType")

    if msg_type == "transcript":
        role = msg_data.get("role")
        text = msg_data.get("text") or msg_data.get("delta")
        if role and text and state.session is not None:
            role_cap = role.capitalize()
            state.session['transcript'] += f"{role_cap}: {text}\n"
            logger.info("[%s] %s", role_cap, text)
            if msg_data.get("final"):
                logger.debug("Transcript for %s finalized", role_cap)

    elif msg_type == "client_tool_invocation":
        await handle_tool_invocation(
            state.uv_ws,
            msg_data.get("toolName", ""),
            msg_data.get("invocationId"),
            msg_data.get("parameters", {}),
        )

    elif msg_type == "state":
        if (agent_state := msg_data.get("state")):
            logger.debug("Agent state: %s", agent_state)

    elif msg_type == "debug":
        debug_message = msg_data.get("message")
        logger.debug("Ultravox debug: %s", debug_message)
        try:
            nested = json.loads(debug_message)
            if nested.get("type") == "toolResult":
                logger.debug("Tool '%s' result: %s",
                             nested.get("toolName"), nested.get("output"))
        except (TypeError, json.JSONDecodeError):
            pass

    elif msg_type == "playback_clear_buffer":
        pass
    elif msg_type in LOG_EVENT_TYPES:
        logger.debug("Ultravox event %s: %s", msg_type, msg_data)
    else:
        logger.debug("Unhandled Ultravox message type: %s", msg_type)


async def _handle_twilio(state: CallState) -> None:
    """Receive messages from Twilio and forward audio to Ultravox."""
    try:
        while True:
            message = await state.twilio_ws.receive_text()
            data = json.loads(message)
            event = data.get('event')

            if event == 'start':
                await _on_twilio_start(state, data)
            elif event == 'media':
                await _on_twilio_media(state, data)

    except WebSocketDisconnect:
        logger.info("Twilio disconnected (CallSid=%s)", state.call_sid)
        state.twilio_active = False
        if state.uv_ws and getattr(state.uv_ws, 'state', None) == State.OPEN:
            await safe_close_websocket(
                state.uv_ws, name="Ultravox WebSocket (Twilio disconnect)"
            )
        raise  # propagate to TaskGroup so the ultravox task is cancelled


async def _on_twilio_start(state: CallState, data: dict[str, Any]) -> None:
    state.stream_sid = data['start']['streamSid']
    state.call_sid = data['start']['callSid']
    custom_params = data['start'].get('customParameters', {})

    logger.info("Twilio start: callSid=%s streamSid=%s",
                state.call_sid, state.stream_sid)

    first_message = custom_params.get(
        'firstMessage', "Hello, how can I assist you?"
    )
    caller_number = custom_params.get('callerNumber', 'Unknown')

    state.session = await session_manager.get(state.call_sid)
    if state.session is None:
        logger.warning("Session not found for CallSid=%s", state.call_sid)
        await state.twilio_ws.close()
        return

    await session_manager.update(
        state.call_sid,
        callerNumber=caller_number,
        streamSid=state.stream_sid,
    )

    uv_join_url = await create_ultravox_call(
        system_prompt=SYSTEM_MESSAGE, first_message=first_message,
    )
    if not uv_join_url:
        logger.error("Ultravox joinUrl empty; cannot establish WebSocket")
        await state.twilio_ws.close()
        return

    try:
        state.uv_ws = await websockets.connect(
            uv_join_url,
            ping_interval=20.0, ping_timeout=10.0, close_timeout=5.0,
        )
    except Exception:
        logger.exception("Error connecting to Ultravox WebSocket")
        state.twilio_active = False
        await safe_close_websocket(
            state.twilio_ws, name="Twilio WebSocket (connection failure)"
        )
        return

    state.ultravox_active = True
    await session_manager.update(
        state.call_sid,
        uv_ws=state.uv_ws,
        ultravox_ws_active=True,
        twilio_ws_active=state.twilio_active,
    )
    state.session = await session_manager.get(state.call_sid)

    state.started.set()
    logger.info("Ultravox WebSocket connected and handler armed")


async def _on_twilio_media(state: CallState, data: dict[str, Any]) -> None:
    payload_base64 = data['media']['payload']
    try:
        mu_law_bytes = base64.b64decode(payload_base64)
        pcm_bytes = audioop.ulaw2lin(mu_law_bytes, 2)
    except Exception:
        logger.exception("Error decoding inbound Twilio audio")
        return

    if (state.ultravox_active and state.uv_ws
            and state.uv_ws.state == State.OPEN):
        try:
            await state.uv_ws.send(pcm_bytes)
        except Exception:
            logger.exception("Error sending PCM to Ultravox")
            state.ultravox_active = False


async def _cleanup(state: CallState) -> None:
    """Close sockets, flush transcript, and remove the session — exactly once."""
    state.twilio_active = False
    state.ultravox_active = False
    if state.session is not None:
        state.session['twilio_ws_active'] = False
        state.session['ultravox_ws_active'] = False

    if state.uv_ws is not None and getattr(state.uv_ws, 'state', None) == State.OPEN:
        await safe_close_websocket(state.uv_ws, name="Ultravox WebSocket (cleanup)")

    if state.session is not None and state.call_sid is not None:
        if not state.session.get('transcript_sent', False):
            try:
                await send_transcript_to_n8n(state.session)
            except Exception:
                logger.exception("Error sending final transcript")

        logger.info("Cleaning up session for CallSid=%s", state.call_sid)
        await session_manager.pop(state.call_sid)

