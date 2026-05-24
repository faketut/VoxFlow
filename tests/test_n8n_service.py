"""Unit tests for n8n webhook service."""
import json

import pytest

import app.services.n8n_service as svc


@pytest.mark.asyncio
async def test_send_to_webhook_returns_error_when_url_not_configured(monkeypatch):
    """No N8N_WEBHOOK_URL → returns JSON error without raising."""
    monkeypatch.setattr(svc, "N8N_WEBHOOK_URL", None)
    result = await svc.send_to_webhook({"route": "1", "number": "+1", "data": "test"})
    assert json.loads(result) == {"error": "N8N_WEBHOOK_URL not configured"}


@pytest.mark.asyncio
async def test_send_transcript_skipped_when_url_not_configured(monkeypatch):
    """send_transcript_to_n8n completes without raising even with no URL."""
    monkeypatch.setattr(svc, "N8N_WEBHOOK_URL", None)
    session: dict = {"callerNumber": "+1", "transcript": "hello world"}
    await svc.send_transcript_to_n8n(session)
    # transcript_sent is set even on error path (best-effort)
    assert session.get("transcript_sent") is True
