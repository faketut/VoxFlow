"""
Application configuration settings.
"""
import json
import os
from dotenv import load_dotenv

# override=False so real environment (Docker/Heroku/etc.) wins over .env files.
load_dotenv(override=False)

# Twilio credentials
TWILIO_ACCOUNT_SID: str | None = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN: str | None = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER: str | None = os.environ.get('TWILIO_PHONE_NUMBER')

# Ultravox credentials & tuning
ULTRAVOX_API_KEY: str | None = os.environ.get('ULTRAVOX_API_KEY')
ULTRAVOX_MODEL: str = os.environ.get('ULTRAVOX_MODEL', "fixie-ai/ultravox-70B")
ULTRAVOX_VOICE: str = os.environ.get('ULTRAVOX_VOICE', "Tanya-English")
ULTRAVOX_SAMPLE_RATE: int = int(os.environ.get('ULTRAVOX_SAMPLE_RATE', '8000'))
ULTRAVOX_BUFFER_SIZE: int = int(os.environ.get('ULTRAVOX_BUFFER_SIZE', '60'))
ULTRAVOX_TEMPERATURE: float = float(os.environ.get('ULTRAVOX_TEMPERATURE', '0.1'))
# Only multiples of 32ms are meaningful for turnEndpointDelay.
ULTRAVOX_TURN_ENDPOINT_DELAY: str = os.environ.get('ULTRAVOX_TURN_ENDPOINT_DELAY', '0.384s')
ULTRAVOX_CORPUS_ID: str = os.environ.get(
    'ULTRAVOX_CORPUS_ID', 'da6de42d-7f32-449e-a77a-9b948f834946'
)

# Webhooks
N8N_WEBHOOK_URL: str | None = os.environ.get('N8N_WEBHOOK_URL')
PUBLIC_URL: str | None = os.environ.get('PUBLIC_URL')

# Server settings
PORT: int = int(os.environ.get('PORT', '8000'))

# Outbound HTTP behaviour
HTTP_TIMEOUT_SECONDS: float = float(os.environ.get('HTTP_TIMEOUT_SECONDS', '10'))

# Logging
LOG_LEVEL: str = os.environ.get('LOG_LEVEL', 'INFO').upper()

# Agent identity — override to white-label VoxFlow for a different business.
AGENT_NAME: str = os.environ.get('AGENT_NAME', 'Sara')
COMPANY_NAME: str = os.environ.get('COMPANY_NAME', 'Dental Help 360')

# Inbound Agent Default First Message
DEFAULT_FIRST_MESSAGE: str = os.environ.get(
    'DEFAULT_FIRST_MESSAGE',
    f"Hey, this is {AGENT_NAME}. How can I assist you today?",
)

# Calendar settings — set CALENDARS_JSON='{"Location": "cal@email"}' to override.
_calendars_json: str | None = os.environ.get('CALENDARS_JSON')
CALENDARS_LIST: dict[str, str] = (
    json.loads(_calendars_json) if _calendars_json else {
        "LOCATION1": "CALENDAR_EMAIL1",
        "LOCATION2": "CALENDAR_EMAIL2",
        "LOCATION3": "CALENDAR_EMAIL3",
    }
)

# Logging event types we surface from Ultravox
LOG_EVENT_TYPES: list[str] = [
    'response.content.done',
    'response.done',
    'session.created',
    'conversation.item.input_audio_transcription.completed',
]

# Required environment variables — process refuses to start if any are missing.
_REQUIRED_ENV_VARS: tuple[str, ...] = (
    'TWILIO_ACCOUNT_SID',
    'TWILIO_AUTH_TOKEN',
    'TWILIO_PHONE_NUMBER',
    'ULTRAVOX_API_KEY',
    'N8N_WEBHOOK_URL',
    'PUBLIC_URL',
)


def validate_config() -> None:
    """Raise ``RuntimeError`` if any required environment variable is missing.

    Called at app startup so the process fails fast rather than emitting a
    confusing stack trace later when an unset value is used.
    """
    missing = [name for name in _REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
            + ". Set them in your shell or .env file before starting the server."
        )
