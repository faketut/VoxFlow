"""
API endpoints for handling Twilio calls.
"""
import json
import requests
from datetime import datetime
from twilio.rest import Client
from fastapi import APIRouter, Request, Response
from app.core.shared_state import sessions
from app.core.config import PUBLIC_URL, DEFAULT_FIRST_MESSAGE, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, N8N_WEBHOOK_URL

router = APIRouter()


@router.get("/")
async def root():
    """Root endpoint to check if the service is running."""
    return {"message": "Twilio + Ultravox Media Stream Server is running!"}


@router.post("/incoming-call")
async def incoming_call(request: Request):
    """
    Handle the inbound call from Twilio. 
    - Fetch firstMessage from N8N
    - Store session data
    - Respond with TwiML containing <Stream> to /media-stream
    """
    form_data = await request.form()
    twilio_params = dict(form_data)
    print('Incoming call')
    # print('Twilio Inbound Details:', json.dumps(twilio_params, indent=2))

    caller_number = twilio_params.get('From', 'Unknown')
    session_id = twilio_params.get('CallSid')
    print("Caller Number:", caller_number)
    print("Session ID (CallSid):", session_id)

    # Fetch first message from N8N
    first_message = DEFAULT_FIRST_MESSAGE
    print("Fetching N8N ...")
    try:
        webhook_response = requests.post(
            N8N_WEBHOOK_URL,
            headers={"Content-Type": "application/json"},
            json={
                "route": "1",
                "number": caller_number,
                "data": "empty"
            },
            # verify=False  # Uncomment if using self-signed certs (not recommended)
        )
        if webhook_response.ok:
            response_text = webhook_response.text
            try:
                response_data = json.loads(response_text)
                if response_data and response_data.get('firstMessage'):
                    first_message = response_data['firstMessage']
                    print('Parsed firstMessage from N8N:', first_message)
            except json.JSONDecodeError:
                # If response is not JSON, treat it as raw text
                first_message = response_text.strip()
        else:
            print(f"Failed to send data to N8N webhook: {webhook_response.status_code}")
    except Exception as e:
        print(f"Error sending data to N8N webhook: {e}")

    # Save session
    session = {
        "transcript": "",
        "callerNumber": caller_number,
        "callDetails": twilio_params,
        "firstMessage": first_message,
        "streamSid": None,
        "hanging_up": False,  # Track if the call is being hung up
        "transcript_sent": False  # Track if transcript was sent to N8N
    }
    sessions[session_id] = session

    # Respond with TwiML to connect to /media-stream
    host = PUBLIC_URL
    stream_url = f"{host.replace('https', 'wss')}/media-stream"

    twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Connect>
                <Stream url="{stream_url}">
                    <Parameter name="firstMessage" value="{first_message}" />
                    <Parameter name="callerNumber" value="{caller_number}" />
                    <Parameter name="callSid" value="{session_id}" />
                </Stream>
            </Connect>
        </Response>"""

    return Response(content=twiml_response, media_type="text/xml")


@router.post("/outgoing-call")
async def outgoing_call(request: Request):
    try:
        # Get request data
        data = await request.json() 
        phone_number = data.get('phoneNumber')
        first_message = data.get('firstMessage')
        if not phone_number:
            return {"error": "Phone number is required"}, 400
        
        print('📞 Initiating outbound call to:', phone_number)
        print('📝 With the following first message:', first_message)
        
        # Initialize Twilio client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        # Store call data
        call_data = {
            "originalRequest": data,
            "startTime": datetime.now().isoformat()
        }

         # Respond with TwiML to connect to /media-stream
        host = PUBLIC_URL
        stream_url = f"{host.replace('https', 'wss')}/media-stream"
        
        print('📱 Creating Twilio call with TWIML...')
        call = client.calls.create(
            twiml=f'''<Response>
                        <Connect>
                            <Stream url="{stream_url}">
                                <Parameter name="firstMessage" value="{first_message}" />
                                <Parameter name="callerNumber" value="{phone_number}" />
                            </Stream> 
                        </Connect>
                    </Response>''',
            to=phone_number,
            from_=TWILIO_PHONE_NUMBER,
            status_callback=f"{PUBLIC_URL}/call-status",
            status_callback_event=['initiated', 'ringing', 'answered', 'completed']
        )

        print('📱 Twilio call created:', call.sid)
        # Store call data in sessions
        sessions[call.sid] = {
            "transcript": "",
            "callerNumber": phone_number,
            "callDetails": call_data,
            "firstMessage": first_message,
            "streamSid": None,
            "hanging_up": False,  # Track if the call is being hung up
            "transcript_sent": False  # Track if transcript was sent to N8N
        }

        return {
            "success": True,
            "callSid": call.sid
        }

    except Exception as error:
        print('❌ Error creating call:', str(error))
        traceback.print_exc()
        return {"error": str(error)}, 500


@router.post("/call-status")
async def call_status(request: Request):
    try:
        # Get form data
        data = await request.form()
        print('\n=== 📱 Twilio Status Update ===')
        print('Status:', data.get('CallStatus'))
        print('Duration:', data.get('CallDuration'))
        print('Timestamp:', data.get('Timestamp'))
        print('Call SID:', data.get('CallSid'))
        # print('Full status payload:', dict(data))
        print('\n====== END ======')
        
    except Exception as e:
        print(f"Error getting request data: {e}")
        return {"error": str(e)}, 400

    return {"success": True}
