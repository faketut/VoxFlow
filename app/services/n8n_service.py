"""
Services for handling webhook communications with n8n.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from app.core.config import (
    HTTP_TIMEOUT_SECONDS,
    N8N_HMAC_SECRET,
    N8N_MAX_RETRIES,
    N8N_RETRY_BACKOFF_SECONDS,
    N8N_WEBHOOK_URL,
)

logger = logging.getLogger(__name__)


def build_signed_headers(body: bytes) -> dict[str, str]:
    """Return headers with HMAC-SHA256 signature of ``body`` when a secret is set.

    The signature header (``X-VoxFlow-Signature: sha256=<hex>``) can be
    verified on the n8n side to ensure the request originated from VoxFlow.
    If no secret is configured, only the Content-Type header is returned.
    """
    headers = {"Content-Type": "application/json"}
    if N8N_HMAC_SECRET:
        digest = hmac.new(
            N8N_HMAC_SECRET.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        headers["X-VoxFlow-Signature"] = f"sha256={digest}"
    return headers


async def send_transcript_to_n8n(session: dict[str, Any]) -> None:
    """Forward the full call transcript to the n8n workflow."""
    logger.info("Sending full transcript to n8n (length=%d)", len(session.get('transcript', '')))
    await send_to_webhook({
        "route": "2",
        "number": session.get("callerNumber", "Unknown"),
        "data": session.get("transcript", ""),
    })
    session['transcript_sent'] = True


async def send_to_webhook(payload: dict[str, Any]) -> str:
    """POST ``payload`` to the configured n8n webhook and return the body text.

    Retries up to ``N8N_MAX_RETRIES`` times on timeouts, transport errors, and
    5xx responses with exponential backoff. Returns a JSON-encoded error
    string on terminal failure rather than raising, so callers (which often
    forward the result to the agent) can keep running.
    """
    if not N8N_WEBHOOK_URL:
        logger.error("N8N_WEBHOOK_URL is not configured")
        return json.dumps({"error": "N8N_WEBHOOK_URL not configured"})

    body = json.dumps(payload).encode("utf-8")
    headers = build_signed_headers(body)
    attempts = max(1, N8N_MAX_RETRIES)
    last_error: str = "unknown error"

    for attempt in range(1, attempts + 1):
        try:
            logger.debug(
                "POST %s payload=%s attempt=%d/%d",
                N8N_WEBHOOK_URL, payload, attempt, attempts,
            )
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    N8N_WEBHOOK_URL, content=body, headers=headers,
                )

            if response.status_code == 200:
                return response.text

            # Retry on 5xx; surface 4xx immediately (won't succeed on retry).
            if 500 <= response.status_code < 600 and attempt < attempts:
                last_error = f"status {response.status_code}"
                logger.warning(
                    "n8n webhook returned %d (attempt %d/%d); retrying",
                    response.status_code, attempt, attempts,
                )
            else:
                logger.warning(
                    "n8n webhook returned %d: %s",
                    response.status_code, response.text,
                )
                return json.dumps(
                    {"error": f"N8N webhook returned status {response.status_code}"}
                )

        except httpx.TimeoutException as e:
            last_error = f"timeout: {e}"
            logger.warning(
                "Timeout calling n8n webhook (attempt %d/%d): %s",
                attempt, attempts, e,
            )
        except httpx.TransportError as e:
            last_error = f"transport error: {e}"
            logger.warning(
                "Transport error calling n8n webhook (attempt %d/%d): %s",
                attempt, attempts, e,
            )
        except httpx.HTTPError as e:
            logger.exception("HTTP error calling n8n webhook")
            return json.dumps({"error": f"N8N webhook HTTP error: {e}"})

        if attempt < attempts:
            await asyncio.sleep(N8N_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))

    logger.error("n8n webhook failed after %d attempts: %s", attempts, last_error)
    return json.dumps({"error": f"N8N webhook failed after {attempts} attempts: {last_error}"})

