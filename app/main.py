"""
Main FastAPI application entry point for VoxFlow AI Receptionist.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Response, WebSocket

from app.api.endpoints.calls import router as calls_router
from app.core.config import (
    LOG_FORMAT,
    LOG_LEVEL,
    N8N_WEBHOOK_URL,
    PORT,
    PUBLIC_URL,
    TWILIO_ACCOUNT_SID,
    ULTRAVOX_API_KEY,
    validate_config,
)
from app.core.logging_config import configure_logging
from app.websockets.media_stream import media_stream

configure_logging(LOG_LEVEL, LOG_FORMAT)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown lifecycle: fail-fast on missing required config."""
    logger.info("Validating configuration...")
    validate_config()
    logger.info("VoxFlow AI Receptionist started successfully")
    yield
    logger.info("VoxFlow AI Receptionist shutting down")


app = FastAPI(
    title="VoxFlow AI Receptionist",
    description="AI-powered voice receptionist with Twilio and Ultravox integration",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(calls_router)


@app.websocket("/media-stream")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await media_stream(websocket)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "VoxFlow AI Receptionist"}


@app.get("/ready")
async def readiness_check(response: Response) -> dict[str, object]:
    """Readiness probe: 200 only when required config is populated.

    Distinct from ``/health`` (which just confirms the process is up).
    Container orchestrators should send traffic only when this returns 200.
    """
    checks = {
        "twilio": bool(TWILIO_ACCOUNT_SID),
        "ultravox": bool(ULTRAVOX_API_KEY),
        "n8n": bool(N8N_WEBHOOK_URL),
        "public_url": bool(PUBLIC_URL),
    }
    ready = all(checks.values())
    if not ready:
        response.status_code = 503
    return {"ready": ready, "checks": checks}


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting VoxFlow AI Receptionist on port %d", PORT)
    # NOTE: do not enable --reload here; enable it from the CLI for local dev:
    #   uvicorn app.main:app --reload --port 8000
    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, reload=False)

