"""
Application configuration settings.
"""
import os
from dotenv import load_dotenv

load_dotenv(override=True)

# Twilio credentials
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')

# Ultravox credentials
ULTRAVOX_API_KEY = os.environ.get('ULTRAVOX_API_KEY')
ULTRAVOX_MODEL = "fixie-ai/ultravox-70B"
ULTRAVOX_VOICE = "Tanya-English"   # or "Mark"
ULTRAVOX_SAMPLE_RATE = 8000        
ULTRAVOX_BUFFER_SIZE = 60


# Webhooks
N8N_WEBHOOK_URL = os.environ.get('N8N_WEBHOOK_URL')
PUBLIC_URL = os.environ.get('PUBLIC_URL')

# Server settings
PORT = int(os.environ.get('PORT', '8000'))

# Inbound Agent Default First Message
DEFAULT_FIRST_MESSAGE = "Hey, this is Sara from SecureLife Insurance. How can I assist you today?"

# Calendar settings
CALENDARS_LIST = {
    "LOCATION1": "CALENDAR_EMAIL1",
    "LOCATION2": "CALENDAR_EMAIL2",
    "LOCATION3": "CALENDAR_EMAIL3",
    # Add more locations / Calendar IDs as needed
}

# Logging settings
LOG_EVENT_TYPES = [
    'response.content.done',
    'response.done',
    'session.created',
    'conversation.item.input_audio_transcription.completed'
]

# Validate critical environment variables
def validate_config():
    """Validate that all required configuration variables are set."""
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
        print("WARNING: Missing Twilio credentials! Please check your .env file.")
    
    if not ULTRAVOX_API_KEY:
        print("WARNING: Missing Ultravox API key! Please check your .env file.")
    
    if not N8N_WEBHOOK_URL:
        print("WARNING: Missing N8N webhook URL! Please check your .env file.")
