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


def test_build_signed_headers_without_secret(monkeypatch):
    """No secret → only Content-Type header, no signature."""
    monkeypatch.setattr(svc, "N8N_HMAC_SECRET", None)
    headers = svc.build_signed_headers(b'{"a":1}')
    assert headers == {"Content-Type": "application/json"}


def test_build_signed_headers_with_secret(monkeypatch):
    """Secret set → adds X-VoxFlow-Signature with sha256= prefix."""
    import hashlib
    import hmac as _hmac
    secret = "test-secret"
    body = b'{"route":"1","number":"+1"}'
    monkeypatch.setattr(svc, "N8N_HMAC_SECRET", secret)
    headers = svc.build_signed_headers(body)
    expected = _hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert headers["Content-Type"] == "application/json"
    assert headers["X-VoxFlow-Signature"] == f"sha256={expected}"


@pytest.mark.asyncio
async def test_send_to_webhook_retries_on_5xx(monkeypatch):
    """5xx response triggers retry; succeeds on second attempt."""
    monkeypatch.setattr(svc, "N8N_WEBHOOK_URL", "http://example.com/wh")
    monkeypatch.setattr(svc, "N8N_MAX_RETRIES", 3)
    monkeypatch.setattr(svc, "N8N_RETRY_BACKOFF_SECONDS", 0.0)

    calls = {"n": 0}

    class _FakeResp:
        def __init__(self, code, text=""):
            self.status_code = code
            self.text = text

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return _FakeResp(503, "busy")
            return _FakeResp(200, "ok")

    monkeypatch.setattr(svc.httpx, "AsyncClient", _FakeClient)
    result = await svc.send_to_webhook({"route": "1", "number": "+1", "data": "x"})
    assert result == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_send_to_webhook_no_retry_on_4xx(monkeypatch):
    """4xx response is terminal — no retries."""
    monkeypatch.setattr(svc, "N8N_WEBHOOK_URL", "http://example.com/wh")
    monkeypatch.setattr(svc, "N8N_MAX_RETRIES", 3)
    monkeypatch.setattr(svc, "N8N_RETRY_BACKOFF_SECONDS", 0.0)

    calls = {"n": 0}

    class _FakeResp:
        def __init__(self, code, text=""):
            self.status_code = code
            self.text = text

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw):
            calls["n"] += 1
            return _FakeResp(404, "not found")

    monkeypatch.setattr(svc.httpx, "AsyncClient", _FakeClient)
    result = await svc.send_to_webhook({"route": "1", "number": "+1", "data": "x"})
    assert "404" in result
    assert calls["n"] == 1
