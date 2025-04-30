# Ultravox Twilio Integration

This FastAPI application integrates Twilio with Ultravox for voice interactions, featuring WebSocket streaming for data storage. The application is structured with a modular architecture for better maintainability.

## Prerequisites

- Python 3.11
- Environment variables set up in `.env` file
- Twilio account
- Ultravox API key
- N8N webhook URL

## Environment Variables Required

```
PUBLIC_URL=ngrok_url_when_testing_locally / railway app url when deploying
N8N_WEBHOOK_URL=your_webhook_url
ULTRAVOX_API_KEY=your_ultravox_key
PORT=8000  # Optional, defaults to 8000
```

## Installation

0. Double check python version (should be 3.11)
```bash
python3 --version #or python --version
```

1. Create a virtual environment:
```bash
python3 -m venv venv # or python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip3 install -r requirements.txt # or pip install -r requirements.txt
```

### Set Up Ngrok (for Local Development)

1. Install ngrok:
```bash
# Using Homebrew (macOS)
brew install ngrok

# Or download from ngrok website
# Visit https://ngrok.com/download and follow installation instructions
```

2. Sign up for a free ngrok account at https://dashboard.ngrok.com/signup

3. Get your authtoken from the ngrok dashboard and configure it:
```bash
ngrok config add-authtoken YOUR_AUTH_TOKEN
```

4. Start ngrok to create a tunnel to your local server:
```bash
ngrok http 8000
```

5. Copy the HTTPS URL provided by ngrok (e.g., `https://xxxx-xx-xx-xxx-xx.ngrok.io`)
   - Use this URL as your `PUBLIC_URL` in the `.env` file
   - Update your Twilio webhook URL with this ngrok URL

Note: The ngrok URL changes each time you restart ngrok unless you have a paid plan. Make sure to update your `.env` file and Twilio webhook URL with the new ngrok URL whenever it changes.

### Set Up Twilio

You'll need a Twilio account and a phone number to receive calls.

#### a. Buy a Twilio Phone Number
- Log in to your Twilio Console.
- Navigate to **Phone Numbers > Buy a Number**.
- Purchase a phone number capable of handling voice calls.

#### b. Configure the Webhook URL
- Go to **Phone Numbers > Manage > Active Numbers**.
- Click on your purchased phone number.
- Scroll down to the **Voice & Fax** section.
- In the **A CALL COMES IN** field, select **Webhook**.
- Enter your webhook URL:
  ```
  https://your-public-url/incoming-call
  ```
  Replace `https://your-public-url` with your actual `PUBLIC_URL`. (Ngrok URL when testing locally, Railway app URL when deploying)
- Set the HTTP method to **POST**.
- Save the configuration.


## Running the Application

Start the FastAPI server:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The application will be available at your ngrok URL: `https://xxxx-xx-xx-xxx-xx.ngrok.io`

## Project Structure

```
/
├── app/                      # Main application package
│   ├── api/                  # API endpoints
│   ├── core/                 # Core functionality and configuration
│   │   ├── config.py         # Application configuration
│   │   ├── prompts.py        # Call stages and system prompts
│   │   └── shared_state.py   # Shared state management
│   ├── services/             # Business logic services
│   │   ├── n8n_service.py    # N8N integration
│   │   ├── tools_service.py  # Tool invocation handlers
│   │   └── ultravox_service.py # Ultravox API integration
│   ├── utils/                # Utility functions
│   └── websockets/           # WebSocket handlers
│       └── media_stream.py   # Media streaming implementation
├── main.py                   # Application entry point
├── requirements.txt          # Python dependencies
└── .env                      # Environment variables
```


### System Message Customization
- **File:** `app/core/prompts.py`
- **Variable:** `SYSTEM_MESSAGE`
- **Description:** Defines the assistant's behavior, persona, and conversation guidelines.
- **How to Customize:**
  1. Open `app/core/prompts.py`.
  2. Modify the content within `SYSTEM_MESSAGE` to change the assistant's role, persona, and instructions.

### Call Stages Configuration

#### Overview
This application uses a multi-stage call flow system designed for SecureLife Insurance. Each stage has its own voice personality, system prompt, and available tools.

#### Call Flow Diagram
A visual representation of the call flow can be found in `diagram.md`. This shows all stages, transitions, and available tools.

#### Stage Details

1. **Stage 1: Initial Greeting & Authentication**
   - **File:** Uses the main system prompt in `app/core/prompts.py`
   - **Voice:** Tanya-English (defined as Sara in the prompt)
   - **Purpose:** Greeting customers, identity verification
   - **Tools:** 
     - `verify`: Authenticates customer identity
     - `question_and_answer`: Answers general queries
     - `move_to_claim_handling`: Transitions to claim stage
     - `escalate_to_manager`: Escalates to manager stage
     - `hangUp`: Ends the call

2. **Stage 2: Claim Handling & Documentation**
   - **File:** `app/core/prompts.py` - `CLAIM_HANDLING_STAGE_PROMPT`
   - **Voice:** Tanya-English
   - **Purpose:** Collect claim details, process claims
   - **Tools:**
     - `submit_claim`: Processes and submits claim information
     - `escalate_to_manager`: Escalates to manager stage
     - `move_to_call_summary`: Transitions to call summary
     - `hangUp`: Ends the call

3. **Stage 3: Escalation Stage**
   - **File:** `app/core/prompts.py` - `MANAGER_STAGE_PROMPT`
   - **Voice:** Mark
   - **Purpose:** Handle complex issues, provide detailed answers
   - **Tools:**
     - `question_and_answer`: Handles complex queries
     - `schedule_meeting`: Books appointments
     - `move_to_call_summary`: Transitions to call summary
     - `hangUp`: Ends the call

4. **Stage 4: Call Summary & Closing**
   - **File:** `app/core/prompts.py` - `CALL_SUMMARY_STAGE_PROMPT`
   - **Voice:** Tanya-English
   - **Purpose:** Summarize the call, confirm next steps
   - **Tools:**
     - `question_and_answer`: Answers final queries
     - `hangUp`: Ends the call

#### How to Customize Call Stages

1. **Modify Stage Prompts**
   - Open `app/core/prompts.py`
   - Edit the corresponding stage prompt variables:
     - `CLAIM_HANDLING_STAGE_PROMPT`
     - `MANAGER_STAGE_PROMPT`
     - `CALL_SUMMARY_STAGE_PROMPT`
   - Each prompt includes sections for Role, Persona, Actions, and other guidelines

2. **Change Voice Settings**
   - In `app/core/prompts.py`, modify the `STAGE_VOICES` dictionary:
   ```python
   STAGE_VOICES = {
       "claim_handling": "Tanya-English",  # Change voice here
       "manager": "Mark",                 # Change voice here
       "call_summary": "Tanya-English"     # Change voice here
   }
   ```
   - Available voices include "Tanya-English" and "Mark"

3. **Add or Modify Tools**
   - Open `app/services/tools_service.py`
   - The `handle_tool_invocation` function contains handlers for each tool
   - To add a new tool:
     - Add a new `elif toolName == "your_tool_name":` block
     - Implement the tool's functionality
     - Add necessary response handling

4. **Modify Stage Transitions**
   - Stage transitions are handled by the following tools in `app/services/tools_service.py`:
     - `move_to_claim_handling`
     - `escalate_to_manager`
     - `move_to_call_summary`
   - Each transition sets a new system prompt and voice

#### Implementation Notes

- **Mock Verification**: The current system uses a mock verification that passes if all fields are provided
- **Mock Claim Submission**: Claims are assigned a random ID and aren't actually stored in a database
- **Voice Consistency**: Each stage uses a consistent voice to maintain character throughout that stage
- **Context Preservation**: When transitioning between stages, conversation context is preserved


### Calendar Emails and Locations

The application can schedule meetings at different locations. You need to update the calendar emails and locations to match your own.

- **Location:** In `app/core/config.py`

```python
CALENDARS_LIST = {
    "LOCATION1": "CALENDAR_EMAIL1",
    "LOCATION2": "CALENDAR_EMAIL2",
    "LOCATION3": "CALENDAR_EMAIL3",
    # Add more locations / Calendar IDs as needed
}
```

- **How to Change:**
  - Replace the location names with your actual location names (e.g., "New York", "San Francisco").
  - Replace the email addresses with the email addresses of the calendars where meetings should be scheduled.
  - The location names are used in the `schedule_meeting` tool when booking appointments.

  **Example:**
  ```python
  CALENDARS_LIST = {
      "New York": "ny-office-calendar@example.com",
      "San Francisco": "sf-office-calendar@example.com",
      "London": "london-office-calendar@example.com",
      # Add more locations as needed
  }
  ```

- **Usage in Code:**
  - The `handle_schedule_meeting` function in `app/services/tools_service.py` uses these calendar settings to book appointments.
  - When a user requests a meeting at a specific location, the corresponding calendar email is used.

## Testing the Application

1. **Make a Call:** Dial the Twilio phone number you configured.
2. **Interact with the Assistant:**
   - The assistant should greet you with a personalized message fetched via N8N.
   - Try asking questions or scheduling a meeting.
3. **Verify Functionality:**
   - Ensure that the assistant responds appropriately.
   - If you scheduled a meeting, check your N8N workflows or calendar to confirm the booking.
4. **Check Logs:**
   - In Replit, view the console logs to see the interactions and debug if necessary.
   - Ensure that transcripts and data are being sent to your N8N webhook.

## Troubleshooting

- **Issue:** Twilio says it cannot reach the webhook URL.
  - **Solution:** Ensure your application is running in Replit and publicly accessible. Double-check the `PUBLIC_URL` and that it's correctly entered in Twilio's settings.


## License

This project is licensed under the MIT License.

**Disclaimer:** This template is provided as-is and is meant for educational purposes. Ensure you comply with all relevant terms of service and legal requirements when using third-party APIs and services.
