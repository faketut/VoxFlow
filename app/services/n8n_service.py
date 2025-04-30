"""
Services for handling webhook communications.
"""
import json
import requests
from app.core.config import N8N_WEBHOOK_URL


async def send_transcript_to_n8n(session):
    print("📝 Full Transcript:\n", session['transcript'])
    await send_to_webhook({
        "route": "2",
        "number": session.get("callerNumber", "Unknown"),
        "data": session["transcript"]
    })
    # Mark transcript as sent
    session['transcript_sent'] = True


async def send_to_webhook(payload):
    if not N8N_WEBHOOK_URL:
        print("Error: N8N_WEBHOOK_URL is not set")
        return json.dumps({"error": "N8N_WEBHOOK_URL not configured"})
        
    try:
        print(f"Sending payload to N8N webhook: {N8N_WEBHOOK_URL}")
        # print(f"Payload: {json.dumps(payload, indent=2)}")
        
        response = requests.post(
            N8N_WEBHOOK_URL,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code != 200:
            print(f"N8N webhook returned status code {response.status_code}")
            print(f"Response: {response.text}")
            return json.dumps({"error": f"N8N webhook returned status {response.status_code}"})
            
        return response.text
        
    except requests.exceptions.RequestException as e:
        error_msg = f"Error sending data to N8N webhook: {str(e)}"
        print(error_msg)
        return json.dumps({"error": error_msg})
