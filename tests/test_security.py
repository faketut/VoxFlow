"""Unit tests for the Twilio signature dependency."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from twilio.request_validator import RequestValidator

import app.api.security as security


def _make_request(headers: dict[str, str], form: dict[str, str],
                  url: str = "https://example.com/incoming-call") -> MagicMock:
    req = MagicMock()
    req.headers = headers
    url_mock = MagicMock()
    url_mock.__str__ = lambda self: url
    url_mock.path = url.split("//", 1)[-1].split("/", 1)[-1]
    req.url = url_mock
    multi = list(form.items())
    form_mock = MagicMock()
    form_mock.multi_items = lambda: multi
    req.form = AsyncMock(return_value=form_mock)
    return req


@pytest.mark.asyncio
async def test_signature_check_skipped_when_disabled(monkeypatch):
    monkeypatch.setattr(security, "TWILIO_VALIDATE_SIGNATURE", False)
    monkeypatch.setattr(security, "TWILIO_AUTH_TOKEN", "anything")
    # Even with missing header, no raise.
    req = _make_request(headers={}, form={})
    await security.verify_twilio_signature(req)


@pytest.mark.asyncio
async def test_signature_check_skipped_when_token_missing(monkeypatch):
    monkeypatch.setattr(security, "TWILIO_VALIDATE_SIGNATURE", True)
    monkeypatch.setattr(security, "TWILIO_AUTH_TOKEN", None)
    req = _make_request(headers={}, form={})
    await security.verify_twilio_signature(req)


@pytest.mark.asyncio
async def test_signature_check_rejects_missing_header(monkeypatch):
    monkeypatch.setattr(security, "TWILIO_VALIDATE_SIGNATURE", True)
    monkeypatch.setattr(security, "TWILIO_AUTH_TOKEN", "token")
    req = _make_request(headers={}, form={"From": "+1"})
    with pytest.raises(HTTPException) as exc:
        await security.verify_twilio_signature(req)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_signature_check_rejects_bad_signature(monkeypatch):
    monkeypatch.setattr(security, "TWILIO_VALIDATE_SIGNATURE", True)
    monkeypatch.setattr(security, "TWILIO_AUTH_TOKEN", "token")
    req = _make_request(
        headers={"X-Twilio-Signature": "deadbeef"},
        form={"From": "+1"},
    )
    with pytest.raises(HTTPException) as exc:
        await security.verify_twilio_signature(req)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_signature_check_accepts_valid_signature(monkeypatch):
    token = "secret-token"
    url = "https://example.com/incoming-call"
    params = {"From": "+15551234567", "CallSid": "CAabc"}
    signature = RequestValidator(token).compute_signature(url, params)

    monkeypatch.setattr(security, "TWILIO_VALIDATE_SIGNATURE", True)
    monkeypatch.setattr(security, "TWILIO_AUTH_TOKEN", token)
    req = _make_request(
        headers={"X-Twilio-Signature": signature},
        form=params,
        url=url,
    )
    await security.verify_twilio_signature(req)  # must not raise
