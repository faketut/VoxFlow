"""
Services for interacting with Ultravox voice AI.
"""
import requests
from app.core.config import (
    ULTRAVOX_API_KEY,
    ULTRAVOX_MODEL,
    ULTRAVOX_VOICE,
    ULTRAVOX_SAMPLE_RATE,
    ULTRAVOX_BUFFER_SIZE,
    N8N_WEBHOOK_URL  # Assuming N8N_WEBHOOK_URL is defined in config
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
                    "corpus_id": "da6de42d-7f32-449e-a77a-9b948f834946",
                    "max_results": 5
                }
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
                        "description": "name of the patient. Leave empty if not specified."
                    },
                    "required": False
                    },
                    {
                    "name": "pt_phoneNumber",
                    "location": "PARAMETER_LOCATION_BODY",
                    "schema": { "type": "string", "pattern": "^\\d{10}$" },
                    "required": False
                    },
                    {
                    "name": "pt_email",
                    "location": "PARAMETER_LOCATION_BODY",
                    "schema": {
                        "type": "string",
                        "description": "Email address of the patient. Leave empty if not specified."
                    },
                    "required": False
                    },
                    {
                    "name": "bookinglink",
                    "location": "PARAMETER_LOCATION_BODY",
                    "schema": {
                        "type": "string",
                        "description": "Use the booking link for the corresponding clinic from queryCorpus tool"
                    },
                    "required": False
                    },
                    {
                    "name": "clinicName",
                    "location": "PARAMETER_LOCATION_BODY",
                    "schema": {
                        "type": "string",
                        "description": "Get the Clinic's name from the call context {{clinicName}}"
                    },
                    "required": False
                    },
                    {
                    "name": "route",
                    "location": "PARAMETER_LOCATION_BODY",
                    "schema": {
                        "description": "The route identifier for this tool",
                        "type": "integer",
                        "enum": [2]
                    },
                    "required": True
                    }
                ],
                "timeout": "20s",
                "http": {
                    "baseUrlPattern": N8N_WEBHOOK_URL,  # Use the imported config variable
                    "httpMethod": "POST"
                }
                }
                
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
                    "description": "Transfer the call to a manager for clinic Q&A, schedule meeting, biling questions, and dental emergency",
                    "dynamicParameters": [
                        {
                            "name": "issue_type",
                            "location": "PARAMETER_LOCATION_BODY",
                            "schema": {
                                "type": "string",
                                "enum": ["clinic_QnA", "schedule_meeting", "biling_questions", "dental_emergency"],
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
