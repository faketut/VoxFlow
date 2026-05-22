"""
Main FastAPI application entry point for VoxFlow AI Receptionist.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, WebSocket

from app.api.endpoints.calls import router as calls_router
from app.core.config import LOG_LEVEL, PORT, validate_config
from app.websockets.media_stream import media_stream


def _configure_logging() -> None:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


_configure_logging()
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


if __name__ == "__main__":
    logger.info("Starting VoxFlow AI Receptionist on port %d", PORT)
    # NOTE: do not enable --reload here; enable it from the CLI for local dev:
    #   uvicorn app.main:app --reload --port 8000
    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, reload=False)

