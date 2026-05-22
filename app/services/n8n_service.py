"""
Services for handling webhook communications with n8n.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.config import HTTP_TIMEOUT_SECONDS, N8N_WEBHOOK_URL

logger = logging.getLogger(__name__)


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

    Returns a JSON-encoded error string on failure rather than raising, so
    callers (which often forward the result to the agent) can keep running.
    """
    if not N8N_WEBHOOK_URL:
        logger.error("N8N_WEBHOOK_URL is not configured")
        return json.dumps({"error": "N8N_WEBHOOK_URL not configured"})

    try:
        logger.debug("POST %s payload=%s", N8N_WEBHOOK_URL, payload)
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.post(
                N8N_WEBHOOK_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
            )

        if response.status_code != 200:
            logger.warning(
                "n8n webhook returned %d: %s", response.status_code, response.text
            )
            return json.dumps({"error": f"N8N webhook returned status {response.status_code}"})

        return response.text

    except httpx.TimeoutException as e:
        logger.warning("Timeout calling n8n webhook: %s", e)
        return json.dumps({"error": f"N8N webhook timeout: {e}"})
    except httpx.HTTPError as e:
        logger.exception("HTTP error calling n8n webhook")
        return json.dumps({"error": f"N8N webhook HTTP error: {e}"})

