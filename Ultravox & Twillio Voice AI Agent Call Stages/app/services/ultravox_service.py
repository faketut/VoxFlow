"""
Services for interacting with Ultravox voice AI.
"""
import requests
from app.core.config import (
    ULTRAVOX_API_KEY,
    ULTRAVOX_MODEL, 
    ULTRAVOX_VOICE, 
    ULTRAVOX_SAMPLE_RATE,
    ULTRAVOX_BUFFER_SIZE
)


async def create_ultravox_call(system_prompt: str, first_message: str) -> str:
    """
    Creates a new Ultravox call in serverWebSocket mode and returns the joinUrl.
    """
    url = "https://api.ultravox.ai/api/calls"
    headers = {
        "X-API-Key": ULTRAVOX_API_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "systemPrompt": system_prompt,
        "model": ULTRAVOX_MODEL,
        "voice": ULTRAVOX_VOICE,
        "temperature":0.1,
        "initialMessages": [
            {
                "role": "MESSAGE_ROLE_USER",  
                "text": first_message
            }
        ],
        "medium": {
            "serverWebSocket": {
                "inputSampleRate": ULTRAVOX_SAMPLE_RATE,   
                "outputSampleRate": ULTRAVOX_SAMPLE_RATE,   
                "clientBufferSizeMs": ULTRAVOX_BUFFER_SIZE
            }
        },
        "vadSettings": {
            "turnEndpointDelay": "0.384s", # only multiples of 32ms are meaningful.
            "minimumTurnDuration": "0s",
            "minimumInterruptionDuration": "0.09s"
        },
        "selectedTools": [  
            {
                "temporaryTool": {
                    "modelToolName": "verify",
                    "description": "Verify the customer's identity before proceeding with any sensitive information or actions",
                    "dynamicParameters": [
                        {
                            "name": "full_name",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Customer's full name for verification"
                            },
                            "required": True
                        },
                        {
                            "name": "date_of_birth",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Customer's date of birth (YYYY-MM-DD format)"
                            },
                            "required": True
                        },
                        {
                            "name": "policy_number",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Customer's insurance policy number"
                            },
                            "required": True
                        }
                    ],
                    "timeout": "20s",
                    "client": {},
                },
            },
            {
                "temporaryTool": {
                    "modelToolName": "move_to_claim_handling",
                    "description": "Transition to the claim handling stage after successful verification",
                    "dynamicParameters": [],
                    "timeout": "20s",
                    "client": {},
                },
            },
            {
                "temporaryTool": {
                    "modelToolName": "submit_claim",
                    "description": "Submit a new insurance claim with all required details",
                    "dynamicParameters": [
                        {
                            "name": "incident_description",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Detailed description of the incident"
                            },
                            "required": True
                        },
                        {
                            "name": "incident_date",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Date of the incident (YYYY-MM-DD format)"
                            },
                            "required": True
                        },
                        {
                            "name": "incident_location",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Location where the incident occurred"
                            },
                            "required": True
                        },
                        {
                            "name": "involved_parties",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Any other parties involved in the incident"
                            },
                            "required": False
                        },
                        {
                            "name": "supporting_info",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Any additional information supporting the claim"
                            },
                            "required": False
                        }
                    ],
                    "timeout": "20s",
                    "client": {},
                },
            },
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
                "temporaryTool": {
                    "modelToolName": "question_and_answer",
                    "description": "Get answers to customer questions about insurance policies and claims",
                    "dynamicParameters": [
                        {
                            "name": "question",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Question to be answered"
                            },
                            "required": True
                        }
                    ],
                    "timeout": "20s",
                    "client": {},
                },
            },
            {
                "temporaryTool": {
                    "modelToolName": "schedule_meeting",
                    "description": "Schedule a meeting for a customer. Returns a message indicating whether the booking was successful or not.",
                    "dynamicParameters": [
                        {
                            "name": "name",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Customer's name"
                            },
                            "required": True
                        },
                        {
                            "name": "email",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Customer's email"
                            },
                            "required": True
                        },
                        {
                            "name": "purpose",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Purpose of the Meeting"
                            },
                            "required": True
                        },
                        {
                            "name": "datetime",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Meeting Datetime"
                            },
                            "required": True
                        },
                        {
                            "name": "location",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "enum": ["London", "Manchester", "Brighton"],
                                "description": "Meeting location"
                            },
                            "required": True
                        }
                    ],
                    "timeout": "20s",
                    "client": {},
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
                    "modelToolName": "escalate_to_manager",
                    "description": "Transfer the call to a manager for handling customer complaints, escalations, or special requests",
                    "dynamicParameters": [
                        {
                            "name": "issue_type",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "enum": ["complaint", "refund_request", "special_accommodation", "general_escalation"],
                                "description": "Type of issue requiring manager assistance"
                            },
                            "required": True
                        },
                        {
                            "name": "issue_details",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Detailed description of the customer's issue"
                            },
                            "required": True
                        },
                        {
                            "name": "customer_name",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "description": "Customer's name if available"
                            },
                            "required": False
                        }
                    ],
                    "timeout": "20s",
                    "client": {},
                },
            }
        ]
    }
    try:
        resp = requests.post(url, headers=headers, json=payload)
        if not resp.ok:
            print("Ultravox create call error:", resp.status_code, resp.text)
            return ""
        body = resp.json()
        join_url = body.get("joinUrl") or ""
        print("Ultravox joinUrl received:", join_url)  # Enhanced logging
        return join_url
    except Exception as e:
        print("Ultravox create call request failed:", e)
        return ""
