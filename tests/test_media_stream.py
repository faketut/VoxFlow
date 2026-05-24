"""Coverage tests for media_stream pure-logic helpers.

We exercise the message-parsing branches of ``_handle_ultravox_text``,
``_on_twilio_media``, and ``_forward_agent_audio`` directly. Anything that
requires real Twilio/Ultravox WebSocket I/O is left to integration tests.
"""
import base64
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from websockets.protocol import State

from app.websockets import media_stream as ms
from app.websockets.media_stream import CallState


def _state(session=None) -> CallState:
    twilio_ws = MagicMock()
    twilio_ws.send_text = AsyncMock()
    twilio_ws.close = AsyncMock()
    cs = CallState(twilio_ws=twilio_ws)
    cs.call_sid = "CA1"
    cs.stream_sid = "MZ1"
    cs.session = session if session is not None else {"transcript": ""}
    cs.twilio_active = True
    cs.ultravox_active = True
    return cs


# ----- _handle_ultravox_text branches -----------------------------------------

@pytest.mark.asyncio
async def test_handle_ultravox_text_transcript_appends_to_session():
    cs = _state()
    await ms._handle_ultravox_text(cs, json.dumps({
        "type": "transcript", "role": "user", "text": "hello", "final": True,
    }))
    assert "User: hello" in cs.session["transcript"]


@pytest.mark.asyncio
async def test_handle_ultravox_text_non_json_is_ignored():
    cs = _state()
    await ms._handle_ultravox_text(cs, "not json {{}")
    assert cs.session["transcript"] == ""


@pytest.mark.asyncio
async def test_handle_ultravox_text_tool_invocation_dispatches(monkeypatch):
    cs = _state()
    cs.uv_ws = AsyncMock()
    dispatched = AsyncMock()
    monkeypatch.setattr(ms, "handle_tool_invocation", dispatched)
    await ms._handle_ultravox_text(cs, json.dumps({
        "type": "client_tool_invocation", "toolName": "verify",
        "invocationId": "inv1", "parameters": {"full_name": "A"},
    }))
    dispatched.assert_awaited_once_with(
        cs.uv_ws, "verify", "inv1", {"full_name": "A"},
    )


@pytest.mark.asyncio
async def test_handle_ultravox_text_debug_branch_with_nested_toolresult():
    cs = _state()
    inner = json.dumps({"type": "toolResult", "toolName": "x", "output": "ok"})
    await ms._handle_ultravox_text(cs, json.dumps({
        "type": "debug", "message": inner,
    }))
    # No exception, no transcript change.
    assert cs.session["transcript"] == ""


@pytest.mark.asyncio
async def test_handle_ultravox_text_unknown_type_is_ignored():
    cs = _state()
    await ms._handle_ultravox_text(cs, json.dumps({"type": "mystery"}))
    assert cs.session["transcript"] == ""


# ----- _forward_agent_audio ---------------------------------------------------

@pytest.mark.asyncio
async def test_forward_agent_audio_sends_media_to_twilio():
    cs = _state()
    pcm = b"\x00\x00" * 80  # 80 silent linear-PCM samples
    await ms._forward_agent_audio(cs, pcm)
    cs.twilio_ws.send_text.assert_awaited_once()
    sent = json.loads(cs.twilio_ws.send_text.call_args.args[0])
    assert sent["event"] == "media"
    assert sent["streamSid"] == "MZ1"
    base64.b64decode(sent["media"]["payload"])  # decodes cleanly


@pytest.mark.asyncio
async def test_forward_agent_audio_skips_when_twilio_inactive():
    cs = _state()
    cs.twilio_active = False
    await ms._forward_agent_audio(cs, b"\x00\x00" * 10)
    cs.twilio_ws.send_text.assert_not_called()


# ----- _on_twilio_media -------------------------------------------------------

@pytest.mark.asyncio
async def test_on_twilio_media_forwards_pcm_to_ultravox():
    cs = _state()
    cs.uv_ws = MagicMock()
    cs.uv_ws.state = State.OPEN
    cs.uv_ws.send = AsyncMock()
    # 80 bytes of mu-law silence
    mu = b"\xff" * 80
    payload = base64.b64encode(mu).decode("ascii")
    await ms._on_twilio_media(cs, {"media": {"payload": payload}})
    cs.uv_ws.send.assert_awaited_once()
    sent_bytes = cs.uv_ws.send.call_args.args[0]
    assert isinstance(sent_bytes, bytes)
    assert len(sent_bytes) == 160  # 16-bit linear PCM


@pytest.mark.asyncio
async def test_on_twilio_media_skips_when_ultravox_inactive():
    cs = _state()
    cs.ultravox_active = False
    cs.uv_ws = MagicMock()
    cs.uv_ws.send = AsyncMock()
    mu = b"\xff" * 10
    payload = base64.b64encode(mu).decode("ascii")
    await ms._on_twilio_media(cs, {"media": {"payload": payload}})
    cs.uv_ws.send.assert_not_called()


@pytest.mark.asyncio
async def test_on_twilio_media_bad_base64_is_logged_not_raised():
    cs = _state()
    cs.uv_ws = MagicMock()
    cs.uv_ws.send = AsyncMock()
    await ms._on_twilio_media(cs, {"media": {"payload": "$$$not-base64$$$"}})
    cs.uv_ws.send.assert_not_called()


# ----- _on_twilio_start -------------------------------------------------------

@pytest.mark.asyncio
async def test_on_twilio_start_closes_when_session_missing(monkeypatch):
    cs = _state(session=None)
    monkeypatch.setattr(ms.session_manager, "get", AsyncMock(return_value=None))
    data = {"start": {
        "streamSid": "MZ-new", "callSid": "CA-missing", "customParameters": {},
    }}
    await ms._on_twilio_start(cs, data)
    cs.twilio_ws.close.assert_awaited()
    assert cs.call_sid == "CA-missing"


@pytest.mark.asyncio
async def test_on_twilio_start_binds_call_sid_into_log_context(monkeypatch):
    from app.core import log_context
    log_context.clear_call_sid()
    cs = _state(session=None)
    monkeypatch.setattr(ms.session_manager, "get", AsyncMock(return_value=None))
    data = {"start": {
        "streamSid": "MZ-1", "callSid": "CA-bind", "customParameters": {},
    }}
    await ms._on_twilio_start(cs, data)
    assert log_context.get_call_sid() == "CA-bind"
    log_context.clear_call_sid()
