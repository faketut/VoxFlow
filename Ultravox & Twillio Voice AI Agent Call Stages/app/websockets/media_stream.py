"""
WebSocket handlers for Twilio and Ultravox media streaming.
"""
import json
import asyncio
import audioop
import base64
import traceback
import websockets
from fastapi import WebSocket, WebSocketDisconnect
from app.utils.websocket_utils import safe_close_websocket
from app.core.config import LOG_EVENT_TYPES
from app.services.n8n_service import send_transcript_to_n8n
from app.services.ultravox_service import create_ultravox_call
from app.core.prompts import SYSTEM_MESSAGE
from app.core.shared_state import sessions


async def media_stream(websocket: WebSocket):
    """
    Handles the Twilio <Stream> WebSocket and connects to Ultravox via WebSocket.
    Includes transcoding audio between Twilio's G.711 µ-law and Ultravox's s16 PCM.
    """
    await websocket.accept()
    print('Client connected to /media-stream (Twilio)')

    # Initialize session variables
    call_sid = None
    session = None
    stream_sid = ''
    uv_ws = None  # Ultravox WebSocket connection
    twilio_task = None  # Store the Twilio handler task
    
    # Add state tracking
    twilio_ws_active = True  # Track if Twilio WebSocket is active
    ultravox_ws_active = False  # Track if Ultravox WebSocket is active

    # Define handler for Ultravox messages
    async def handle_ultravox():
        nonlocal uv_ws, session, stream_sid, call_sid, twilio_task, twilio_ws_active, ultravox_ws_active
        try:
            # Setup timeout handler for the WebSocket
            uv_ws.ping_timeout = 10.0  # Shorter timeout for ping/pong
            uv_ws.close_timeout = 5.0  # Shorter timeout for closing
            
            async for raw_message in uv_ws:
                # Check if someone requested hanging up
                if session and session.get('hanging_up', False):
                    print("Detected hanging_up flag, exiting ultravox message loop")
                    break
                    
                if isinstance(raw_message, bytes):
                    # Agent audio in PCM s16le
                    try:
                        mu_law_bytes = audioop.lin2ulaw(raw_message, 2)
                        payload_base64 = base64.b64encode(mu_law_bytes).decode('ascii')
                    except Exception as e:
                        print(f"Error transcoding PCM to µ-law: {e}")
                        continue  # Skip this audio frame

                    # Send to Twilio as media payload only if WebSocket is active
                    if twilio_ws_active:
                        try:
                            await websocket.send_text(json.dumps({
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {
                                    "payload": payload_base64
                                }
                            }))
                        except Exception as e:
                            print(f"Error sending media to Twilio: {e}")
                            # If we hit an error here, mark the WebSocket as inactive
                            twilio_ws_active = False

                else:
                    # Text data message from Ultravox
                    try:
                        msg_data = json.loads(raw_message)
                        # print(f"Received data message from Ultravox: {json.dumps(msg_data)}")
                    except Exception as e:
                        print(f"Ultravox non-JSON data: {raw_message}")
                        continue

                    msg_type = msg_data.get("type") or msg_data.get("eventType")

                    if msg_type == "transcript":
                        role = msg_data.get("role")
                        text = msg_data.get("text") or msg_data.get("delta")
                        final = msg_data.get("final", False)

                        if role and text:
                            role_cap = role.capitalize()
                            session['transcript'] += f"{role_cap}: {text}\n"
                            # Add emojis based on the role
                            if role_cap == "Agent":
                                emoji = "🤖"
                            else:  # user or any other role
                                emoji = "👤"
                                
                            print(f"{emoji} {role_cap}: {text}")                            
                            
                            if final:
                                print(f"Transcript for {role_cap} finalized.")

                    elif msg_type == "client_tool_invocation":
                        toolName = msg_data.get("toolName", "")
                        invocationId = msg_data.get("invocationId")
                        parameters = msg_data.get("parameters", {})
                        print(f"Invoking tool: {toolName} with invocationId: {invocationId} and parameters: {parameters}")
                        
                        # Pass the tool invocation to our helper function
                        # Import here to avoid circular imports
                        from app.services.tools_service import handle_tool_invocation
                        await handle_tool_invocation(uv_ws, toolName, invocationId, parameters)

                    

                    elif msg_type == "state":
                        # Handle state messages
                        state = msg_data.get("state")
                        if state:
                            print(f"Agent state: {state}")

                    elif msg_type == "debug":
                        # Handle debug messages
                        debug_message = msg_data.get("message")
                        print(f"Ultravox debug message: {debug_message}")
                        # Attempt to parse nested messages within the debug message
                        try:
                            nested_msg = json.loads(debug_message)
                            nested_type = nested_msg.get("type")

                            if nested_type == "toolResult":
                                tool_name = nested_msg.get("toolName")
                                output = nested_msg.get("output")
                                print(f"Tool '{tool_name}' result: {output}")


                            else:
                                print(f"Unhandled nested message type within debug: {nested_type}")
                        except json.JSONDecodeError as e:
                            print(f"Failed to parse nested message within debug message: {e}. Message: {debug_message}")

                    elif msg_type == "playback_clear_buffer":
                        # Handle the playback_clear_buffer message
                        # No action needed, silently handle this common message type
                        pass
                    elif msg_type in LOG_EVENT_TYPES:
                        print(f"Ultravox event: {msg_type} - {msg_data}")
                    else:
                        print(f"Unhandled Ultravox message type: {msg_type} - {msg_data}")

        except websockets.exceptions.ConnectionClosedError as e:
            # This is a normal closure during hangup, so just log it without traceback
            print(f"Ultravox WebSocket connection closed: {e}")
            # Set the state to inactive
            ultravox_ws_active = False
            if session:
                session['ultravox_ws_active'] = False
                
        except websockets.exceptions.ConnectionClosedOK as e:
            # Normal closure
            print(f"Ultravox WebSocket closed normally: {e}")
            ultravox_ws_active = False
            if session:
                session['ultravox_ws_active'] = False
                
        except Exception as e:
            print(f"Error in handle_ultravox: {e}")
            traceback.print_exc()
        finally:
            # Always make sure the WebSocket is marked as inactive
            ultravox_ws_active = False
            if session:
                session['ultravox_ws_active'] = False

    # Define handler for Twilio messages
    async def handle_twilio():
        nonlocal call_sid, session, stream_sid, uv_ws, twilio_ws_active, ultravox_ws_active
        try:
            while True:
                message = await websocket.receive_text()
                data = json.loads(message)

                if data.get('event') == 'start':
                    stream_sid = data['start']['streamSid']
                    call_sid = data['start']['callSid']
                    custom_parameters = data['start'].get('customParameters', {})

                    print("Twilio event: start")
                    print("CallSid:", call_sid)
                    print("StreamSid:", stream_sid)
                    # print("Custom Params:", custom_parameters)

                    # Extract first_message and caller_number
                    first_message = custom_parameters.get('firstMessage', "Hello, how can I assist you?")
                    caller_number = custom_parameters.get('callerNumber', 'Unknown')

                    if call_sid and call_sid in sessions:
                        session = sessions[call_sid]
                        session['callerNumber'] = caller_number
                        session['streamSid'] = stream_sid
                    else:
                        print(f"Session not found for CallSid: {call_sid}")
                        await websocket.close()
                        return

                    print("Caller Number:", caller_number)
                    print("First Message:", first_message)

                    # Create Ultravox call with first_message
                    uv_join_url = await create_ultravox_call(
                        system_prompt=SYSTEM_MESSAGE,
                        first_message=first_message  # Pass the actual first_message here
                    )

                    if not uv_join_url:
                        print("Ultravox joinUrl is empty. Cannot establish WebSocket connection.")
                        await websocket.close()
                        return

                    # Connect to Ultravox WebSocket
                    try:
                        # Set custom timeouts for the WebSocket
                        uv_ws = await websockets.connect(
                            uv_join_url,
                            ping_interval=20.0,  # Send ping every 20 seconds to keep connection alive
                            ping_timeout=10.0,   # Wait 10 seconds for pong response
                            close_timeout=5.0    # Wait 5 seconds for close handshake
                        )
                        print("Ultravox WebSocket connected.")
                        # Update state tracking
                        ultravox_ws_active = True
                        # Store the uv_ws and active states in the session for tool access
                        if call_sid and call_sid in sessions:
                            sessions[call_sid]['uv_ws'] = uv_ws
                            sessions[call_sid]['ultravox_ws_active'] = True
                            sessions[call_sid]['twilio_ws_active'] = twilio_ws_active
                    except Exception as e:
                        print(f"Error connecting to Ultravox WebSocket: {e}")
                        traceback.print_exc()
                        twilio_ws_active = False  # Mark Twilio as inactive too since we're closing
                        # Close Twilio WebSocket using our safe utility
                        await safe_close_websocket(websocket, name="Twilio WebSocket (connection failure)")
                        return

                    # Start handling Ultravox messages as a separate task
                    uv_task = asyncio.create_task(handle_ultravox())
                    print("Started Ultravox handler task.")

                elif data.get('event') == 'media':
                    # Twilio sends media from user
                    payload_base64 = data['media']['payload']

                    try:
                        # Decode base64 to get raw µ-law bytes
                        mu_law_bytes = base64.b64decode(payload_base64)

                    except Exception as e:
                        print(f"Error decoding base64 payload: {e}")
                        continue  # Skip this payload

                    try:
                        # Transcode µ-law to PCM (s16le)
                        pcm_bytes = audioop.ulaw2lin(mu_law_bytes, 2)
                        
                    except Exception as e:
                        print(f"Error transcoding µ-law to PCM: {e}")
                        continue  # Skip this payload

                    # Send PCM bytes to Ultravox only if WebSocket is active
                    if ultravox_ws_active and uv_ws and uv_ws.state == websockets.protocol.State.OPEN:
                        try:
                            await uv_ws.send(pcm_bytes)
                       
                        except Exception as e:
                            print(f"Error sending PCM to Ultravox: {e}")
                            # If we hit an error here, mark the WebSocket as inactive
                            ultravox_ws_active = False

        except WebSocketDisconnect:
            print(f"Twilio WebSocket disconnected (CallSid={call_sid}).")
            # Update state tracking
            twilio_ws_active = False
            # Attempt to close Ultravox ws with timeout
            if ultravox_ws_active and uv_ws and uv_ws.state == websockets.protocol.State.OPEN:
                ultravox_ws_active = False
                # Update session if available
                if session:
                    session['ultravox_ws_active'] = False
                    session['twilio_ws_active'] = False
                # Close Ultravox WebSocket using our safe utility
                await safe_close_websocket(uv_ws, name="Ultravox WebSocket (Twilio disconnect)")
            # Post the transcript to N8N
            if session and not session.get('transcript_sent', False):
                await send_transcript_to_n8n(session)
                # Moved session removal to the finally block to ensure we don't recreate the session

        except Exception as e:
            print(f"Error in handle_twilio: {e}")
            traceback.print_exc()

    # Start handling Twilio media as a separate task
    twilio_task = asyncio.create_task(handle_twilio())

    try:
        # Wait for the Twilio handler to complete
        await twilio_task
    except asyncio.CancelledError:
        print("Twilio handler task cancelled")
    finally:
        # Mark WebSockets as inactive
        twilio_ws_active = False
        ultravox_ws_active = False
        
        if session:
            session['twilio_ws_active'] = False
            session['ultravox_ws_active'] = False
        
        # Close Ultravox WebSocket if still open - with timeout
        if uv_ws and uv_ws.state == websockets.protocol.State.OPEN:
            try:
                # Close Ultravox WebSocket using our safe utility
                await safe_close_websocket(uv_ws, name="Ultravox WebSocket (cleanup)")
            except Exception as e:
                print(f"Unexpected error in WebSocket cleanup: {e}")
        
        # Ensure everything is cleaned up
        if session and call_sid:
            # Send any final transcript data to N8N if not already sent
            if not session.get('transcript_sent', False):
                try:
                    await send_transcript_to_n8n(session)
                    # No need to set transcript_sent = True here as send_transcript_to_n8n does that
                except Exception as e:
                    print(f"Error sending final transcript: {e}")
            
            print(f"Cleaning up session for CallSid={call_sid}")
            # Remove session only now after all operations are complete
            sessions.pop(call_sid, None)