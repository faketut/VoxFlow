"""Coverage tests for tool handler dispatch and individual handlers.

Mocks the Ultravox WebSocket with ``AsyncMock`` and patches outbound
``send_to_webhook`` / Twilio Client / session_manager interactions.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import tools_service as svc


@pytest.fixture
def uv_ws():
    """Fake Ultravox WebSocket with async send()."""
    ws = AsyncMock()
    ws.send = AsyncMock()
    # State.OPEN check in handle_hangUp; pretend already closed so we skip the
    # 'send tool result' branch in tests that don't care about it.
    from websockets.protocol import State
    ws.state = State.CLOSED
    return ws


def _last_send_payload(uv_ws):
    args, _ = uv_ws.send.call_args
    return json.loads(args[0])


# ----- queryCorpus / verify ---------------------------------------------------

@pytest.mark.asyncio
async def test_handle_queryCorpus_is_a_noop_send(uv_ws):
    await svc.handle_queryCorpus(uv_ws, "inv1", svc.QueryCorpusParams(question="hi"))
    uv_ws.send.assert_not_called()


@pytest.mark.asyncio
async def test_handle_verify_confirmed_branch(uv_ws):
    await svc.handle_verify(uv_ws, "inv1",
                            svc.VerifyParams(full_name="Jane", phone_number="555"))
    payload = _last_send_payload(uv_ws)
    assert payload["result"] == "Confirmed"


@pytest.mark.asyncio
async def test_handle_verify_not_confirmed_branch(uv_ws):
    await svc.handle_verify(uv_ws, "inv1", svc.VerifyParams())
    payload = _last_send_payload(uv_ws)
    assert payload["result"] == "Not Confirmed"


# ----- schedule_meeting -------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_schedule_meeting_invalid_location(monkeypatch, uv_ws):
    monkeypatch.setattr(svc, "CALENDARS_LIST", {"Downtown": "cal-1"})
    params = svc.ScheduleMeetingParams(
        name="A", email="a@b.c", purpose="p", datetime="2026-01-01",
        location="Mars",
    )
    await svc.handle_schedule_meeting(uv_ws, "inv1", params)
    payload = _last_send_payload(uv_ws)
    assert payload["error_type"] == "implementation-error"
    assert "Invalid location" in payload["error_message"]


@pytest.mark.asyncio
async def test_handle_schedule_meeting_happy_path(monkeypatch, uv_ws):
    monkeypatch.setattr(svc, "CALENDARS_LIST", {"Downtown": "cal-1"})
    monkeypatch.setattr(
        svc.session_manager, "find_by_uv_ws",
        AsyncMock(return_value=("CA1", {"callerNumber": "+15555550100"})),
    )
    monkeypatch.setattr(
        svc, "send_to_webhook",
        AsyncMock(return_value=json.dumps({"message": "Booked at 10am"})),
    )
    params = svc.ScheduleMeetingParams(
        name="A", email="a@b.c", purpose="p", datetime="2026-01-01",
        location="Downtown",
    )
    await svc.handle_schedule_meeting(uv_ws, "inv1", params)
    payload = _last_send_payload(uv_ws)
    assert payload["result"] == "Booked at 10am"
    svc.send_to_webhook.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_schedule_meeting_non_json_webhook(monkeypatch, uv_ws):
    monkeypatch.setattr(svc, "CALENDARS_LIST", {"Downtown": "cal-1"})
    monkeypatch.setattr(
        svc.session_manager, "find_by_uv_ws",
        AsyncMock(return_value=(None, None)),
    )
    monkeypatch.setattr(svc, "send_to_webhook",
                        AsyncMock(return_value="not json"))
    params = svc.ScheduleMeetingParams(
        name="A", email="a@b.c", purpose="p", datetime="2026-01-01",
        location="Downtown",
    )
    await svc.handle_schedule_meeting(uv_ws, "inv1", params)
    payload = _last_send_payload(uv_ws)
    assert "couldn't schedule" in payload["result"]


# ----- move_to_main_convo / move_to_call_summary ------------------------------

@pytest.mark.asyncio
async def test_handle_move_to_main_convo_payload_structure(monkeypatch, uv_ws):
    monkeypatch.setattr(svc, "get_stage_prompt", lambda s: f"prompt-{s}")
    monkeypatch.setattr(svc, "get_stage_voice", lambda s: f"voice-{s}")
    await svc.handle_move_to_main_convo(
        uv_ws, "inv1",
        svc.MoveToMainConvoParams(issue_type="billing", customer_name="Sam"),
    )
    payload = _last_send_payload(uv_ws)
    assert payload["response_type"] == "new-stage"
    inner = json.loads(payload["result"])
    assert inner["systemPrompt"] == "prompt-main_convo"
    assert inner["voice"] == "voice-main_convo"
    assert "Sam" in inner["toolResultText"]
    assert "billing" in inner["toolResultText"]


@pytest.mark.asyncio
async def test_handle_move_to_call_summary_payload_structure(monkeypatch, uv_ws):
    monkeypatch.setattr(svc, "get_stage_prompt", lambda s: f"prompt-{s}")
    monkeypatch.setattr(svc, "get_stage_voice", lambda s: f"voice-{s}")
    await svc.handle_move_to_call_summary(
        uv_ws, "inv1", svc.MoveToCallSummaryParams(),
    )
    payload = _last_send_payload(uv_ws)
    assert payload["response_type"] == "new-stage"
    inner = json.loads(payload["result"])
    assert inner["systemPrompt"] == "prompt-call_summary"


# ----- hangUp ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_hangUp_no_session_returns_early(monkeypatch, uv_ws):
    monkeypatch.setattr(
        svc.session_manager, "find_by_uv_ws",
        AsyncMock(return_value=(None, None)),
    )
    # Should not attempt to construct Twilio Client at all.
    client_cls = MagicMock()
    monkeypatch.setattr(svc, "Client", client_cls)
    await svc.handle_hangUp(uv_ws, "inv1", svc.HangUpParams())
    client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_handle_hangUp_with_session_updates_and_calls_twilio(monkeypatch, uv_ws):
    update = AsyncMock()
    monkeypatch.setattr(
        svc.session_manager, "find_by_uv_ws",
        AsyncMock(return_value=("CA1", {"transcript_sent": True})),
    )
    monkeypatch.setattr(svc.session_manager, "update", update)
    client_cls = MagicMock()
    monkeypatch.setattr(svc, "Client", client_cls)
    monkeypatch.setattr(
        svc, "safe_close_websocket", AsyncMock(),
    )

    await svc.handle_hangUp(uv_ws, "inv1", svc.HangUpParams())

    update.assert_any_await("CA1", hanging_up=True)
    client_cls.assert_called_once()
    # .calls("CA1").update(status='completed')
    client_cls.return_value.calls.assert_any_call("CA1")


# ----- handle_tool_invocation dispatcher --------------------------------------

@pytest.mark.asyncio
async def test_handle_tool_invocation_unknown_tool(uv_ws):
    await svc.handle_tool_invocation(uv_ws, "no_such_tool", "inv1", {})
    payload = _last_send_payload(uv_ws)
    assert payload["error_type"] == "implementation-error"
    assert "Unknown tool" in payload["error_message"]


@pytest.mark.asyncio
async def test_handle_tool_invocation_invalid_params_generic(uv_ws):
    # verify's params are all optional, so use schedule_meeting w/o location
    # but supply other required fields except one we know is missing.
    await svc.handle_tool_invocation(uv_ws, "schedule_meeting", "inv1", {})
    payload = _last_send_payload(uv_ws)
    # Special-cased: should send a tool RESULT asking for missing fields.
    assert payload["type"] == "client_tool_result"
    assert "Please provide" in payload["result"]


@pytest.mark.asyncio
async def test_handle_tool_invocation_happy_dispatch_increments_counter(uv_ws):
    from app.core.metrics import tool_invocations_total
    before = tool_invocations_total.labels(tool="verify", outcome="ok")._value.get()
    await svc.handle_tool_invocation(
        uv_ws, "verify", "inv1",
        {"full_name": "Jane", "phone_number": "555"},
    )
    after = tool_invocations_total.labels(tool="verify", outcome="ok")._value.get()
    assert after == before + 1


@pytest.mark.asyncio
async def test_handle_tool_invocation_handler_exception_sends_error(monkeypatch, uv_ws):
    async def boom(*a, **k):
        raise RuntimeError("kaboom")
    monkeypatch.setitem(
        svc.TOOL_HANDLERS, "verify", (svc.VerifyParams, boom),
    )
    await svc.handle_tool_invocation(uv_ws, "verify", "inv1", {})
    payload = _last_send_payload(uv_ws)
    assert payload["error_type"] == "implementation-error"
    assert "verify" in payload["error_message"]
