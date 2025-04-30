"""
Utility functions for WebSocket management.
"""
import asyncio
import websockets


async def safe_close_websocket(ws, name="WebSocket", timeout=3.0):
    """Safely close a WebSocket with timeout handling and error management."""
    if not ws or not hasattr(ws, 'state'):
        print(f"{name} is not valid or already closed")
        return
        
    if ws.state != websockets.protocol.State.OPEN:
        print(f"{name} is not in OPEN state, current state: {ws.state}")
        return
        
    print(f"Attempting to safely close {name}...")
    
    try:
        # Set shorter timeouts before closing if possible
        if hasattr(ws, 'ping_timeout'):
            ws.ping_timeout = 2.0
        if hasattr(ws, 'close_timeout'):
            ws.close_timeout = 2.0
            
        # Close with timeout
        try:
            await asyncio.wait_for(ws.close(), timeout=timeout)
            print(f"{name} closed successfully")
        except asyncio.TimeoutError:
            # print(f"Timeout while closing {name}, forcing cleanup")
            # Force the connection to be considered closed if possible
            if hasattr(ws, '_close_connection'):
                ws._close_connection()
    except Exception as e:
        print(f"Error closing {name}: {e}")
        if hasattr(ws, '_close_connection'):
            try:
                ws._close_connection()
                print(f"Forced {name} closure after error")
            except Exception as forced_error:
                print(f"Even forced {name} closure failed: {forced_error}")
