"""
Services for interacting with Ultravox voice AI.
"""
from __future__ import annotations

import logging

import httpx

from app.core.config import (
    HTTP_TIMEOUT_SECONDS,
    N8N_WEBHOOK_URL,
    ULTRAVOX_API_KEY,
    ULTRAVOX_BUFFER_SIZE,
    ULTRAVOX_CORPUS_ID,
    ULTRAVOX_MODEL,
    ULTRAVOX_SAMPLE_RATE,
    ULTRAVOX_TEMPERATURE,
    ULTRAVOX_TURN_ENDPOINT_DELAY,
    ULTRAVOX_VOICE,
)

logger = logging.getLogger(__name__)

ULTRAVOX_CALLS_URL = "https://api.ultravox.ai/api/calls"


async def create_ultravox_call(system_prompt: str, first_message: str) -> str:
    """Create an Ultravox call in serverWebSocket mode and return its ``joinUrl``.

    Returns an empty string on failure (matching the previous contract); the
    caller is expected to treat empty as "could not establish call".
    """
    headers = {
        "X-API-Key": ULTRAVOX_API_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "systemPrompt": system_prompt,
        "model": ULTRAVOX_MODEL,
        "voice": ULTRAVOX_VOICE,
        "temperature": ULTRAVOX_TEMPERATURE,
        "initialMessages": [
            {
                "role": "MESSAGE_ROLE_USER",
                "text": first_message,
            }
        ],
        "medium": {
            "serverWebSocket": {
                "inputSampleRate": ULTRAVOX_SAMPLE_RATE,
                "outputSampleRate": ULTRAVOX_SAMPLE_RATE,
                "clientBufferSizeMs": ULTRAVOX_BUFFER_SIZE,
            }
        },
        "vadSettings": {
            "turnEndpointDelay": ULTRAVOX_TURN_ENDPOINT_DELAY,
            "minimumTurnDuration": "0s",
            "minimumInterruptionDuration": "0.09s",
        },
        "selectedTools": _build_selected_tools(),
    }

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.post(ULTRAVOX_CALLS_URL, headers=headers, json=payload)
    except httpx.TimeoutException as e:
        logger.warning("Ultravox create-call timed out: %s", e)
        return ""
    except httpx.HTTPError:
        logger.exception("Ultravox create-call request failed")
        return ""

    if resp.status_code >= 400:
        logger.error(
            "Ultravox create-call error: %d %s", resp.status_code, resp.text
        )
        return ""

    body = resp.json()
    join_url = body.get("joinUrl") or ""
    logger.info("Ultravox joinUrl received (len=%d)", len(join_url))
    return join_url


def _build_selected_tools() -> list[dict]:
    """Return the static Ultravox tool registration list."""
    return [
        {
            "temporaryTool": {
                "modelToolName": "move_to_call_summary",
                "description": "Transition to the call summary stage when the conversation is ready to conclude",
                "dynamicParameters": [],
                "timeout": "20s",
                "client": {},
            },
        },
        {
            "toolName": "queryCorpus",
            "parameterOverrides": {
                "corpus_id": ULTRAVOX_CORPUS_ID,
                "max_results": 5,
            },
        },
        {
            "temporaryTool": {
                "modelToolName": "schedule_meeting",
                "description": "Send an online booking link to the patient via email or text.",
                "dynamicParameters": [
                    {
                        "name": "pt_Name",
                        "location": "PARAMETER_LOCATION_BODY",
                        "schema": {
                            "type": "string",
                            "description": "name of the patient. Leave empty if not specified.",
                        },
                        "required": False,
                    },
                    {
                        "name": "pt_phoneNumber",
                        "location": "PARAMETER_LOCATION_BODY",
                        "schema": {"type": "string", "pattern": r"^\d{10}$"},
                        "required": False,
                    },
                    {
                        "name": "pt_email",
                        "location": "PARAMETER_LOCATION_BODY",
                        "schema": {
                            "type": "string",
                            "description": "Email address of the patient. Leave empty if not specified.",
                        },
                        "required": False,
                    },
                    {
                        "name": "bookinglink",
                        "location": "PARAMETER_LOCATION_BODY",
                        "schema": {
                            "type": "string",
                            "description": "Use the booking link for the corresponding location from queryCorpus tool",
                        },
                        "required": False,
                    },
                    {
                        "name": "locationName",
                        "location": "PARAMETER_LOCATION_BODY",
                        "schema": {
                            "type": "string",
                            "description": "Get the location name from the call context {{locationName}}",
                        },
                        "required": False,
                    },
                    {
                        "name": "route",
                        "location": "PARAMETER_LOCATION_BODY",
                        "schema": {
                            "description": "The route identifier for this tool",
                            "type": "integer",
                            "enum": [2],
                        },
                        "required": True,
                    },
                ],
                "timeout": "20s",
                "http": {
                    "baseUrlPattern": N8N_WEBHOOK_URL,
                    "httpMethod": "POST",
                },
            },
        },
        {
            "temporaryTool": {
                "modelToolName": "hangUp",
                "description": "End the call",
                "client": {},
            }
        },
        {
            "temporaryTool": {
                "modelToolName": "move_to_main_convo",
                "description": "Transfer the call to a specialist for general inquiries, scheduling, billing, or urgent issues",
                "dynamicParameters": [
                    {
                        "name": "issue_type",
                        "location": "PARAMETER_LOCATION_BODY",
                        "schema": {
                            "type": "string",
                            "enum": [
                                "general_inquiry",
                                "schedule_meeting",
                                "billing_questions",
                                "urgent_issue",
                            ],
                            "description": "Type of issue requiring manager assistance",
                        },
                        "required": True,
                    },
                    {
                        "name": "issue_details",
                        "location": "PARAMETER_LOCATION_BODY",
                        "schema": {
                            "type": "string",
                            "description": "Detailed description of the customer's issue",
                        },
                        "required": True,
                    },
                    {
                        "name": "customer_name",
                        "location": "PARAMETER_LOCATION_BODY",
                        "schema": {
                            "type": "string",
                            "description": "Customer's name if available",
                        },
                        "required": False,
                    },
                ],
                "timeout": "20s",
                "client": {},
            },
        },
    ]

