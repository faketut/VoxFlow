"""Tests for /health and /ready endpoints."""
from __future__ import annotations

from fastapi.testclient import TestClient

import app.main as main_module


def _client() -> TestClient:
    return TestClient(main_module.app)


def test_health_returns_200():
    with _client() as c:
        resp = c.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_ready_returns_200_when_all_config_set(monkeypatch):
    monkeypatch.setattr(main_module, "TWILIO_ACCOUNT_SID", "AC1")
    monkeypatch.setattr(main_module, "ULTRAVOX_API_KEY", "uv")
    monkeypatch.setattr(main_module, "N8N_WEBHOOK_URL", "http://wh")
    monkeypatch.setattr(main_module, "PUBLIC_URL", "http://pu")
    with _client() as c:
        resp = c.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert all(body["checks"].values())


def test_ready_returns_503_when_config_missing(monkeypatch):
    monkeypatch.setattr(main_module, "TWILIO_ACCOUNT_SID", None)
    monkeypatch.setattr(main_module, "ULTRAVOX_API_KEY", "uv")
    monkeypatch.setattr(main_module, "N8N_WEBHOOK_URL", "http://wh")
    monkeypatch.setattr(main_module, "PUBLIC_URL", "http://pu")
    with _client() as c:
        resp = c.get("/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["ready"] is False
    assert body["checks"]["twilio"] is False
