"""
Main FastAPI application entry point.
"""
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from app.api.endpoints.calls import router as calls_router
from app.websockets.media_stream import media_stream
from app.core.config import PORT, validate_config

# Create FastAPI application
app = FastAPI(title="Ultravox Twilio Voice AI")

# Include API routers
app.include_router(calls_router)

# Register WebSocket route
@app.websocket("/media-stream")
async def websocket_endpoint(websocket: WebSocket):
    await media_stream(websocket)

# Validate configuration on startup
@app.on_event("startup")
async def startup_event():
    validate_config()
    print("Validating configuration...")
    print("Application started successfully")

# Run the application if executed directly
if __name__ == "__main__":
    print(f"Starting server on port {PORT}...")
    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, reload=True)
