"""
Security dependencies for the Twilio-facing API.

Twilio signs every webhook with the request's full URL + sorted POST params
using HMAC-SHA1 keyed with the account auth token. We verify that here to
reject forged requests against `/incoming-call` and `/call-status`.

Validation can be disabled with ``TWILIO_VALIDATE_SIGNATURE=false`` for local
development (e.g. ngrok testing where the public URL doesn't match the
``Host`` header Twilio signed).
"""
from __future__ import annotations

import logging

from fastapi import HTTPException, Request, status
from twilio.request_validator import RequestValidator

from app.core.config import TWILIO_AUTH_TOKEN, TWILIO_VALIDATE_SIGNATURE

logger = logging.getLogger(__name__)


async def verify_twilio_signature(request: Request) -> None:
    """FastAPI dependency that rejects requests with an invalid Twilio signature.

    No-op when ``TWILIO_VALIDATE_SIGNATURE`` is false or the auth token is unset
    (keeps tests and local dev usable). Raises HTTP 403 otherwise.
    """
    if not TWILIO_VALIDATE_SIGNATURE or not TWILIO_AUTH_TOKEN:
        return

    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        logger.warning("Missing X-Twilio-Signature header on %s", request.url.path)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing Twilio signature",
        )

    # Twilio signs the public URL it dispatched to. When behind a TLS-terminating
    # proxy (Heroku, Cloud Run, etc.) FastAPI sees http://; rebuild as https.
    url = str(request.url)
    forwarded_proto = request.headers.get("X-Forwarded-Proto")
    if forwarded_proto == "https" and url.startswith("http://"):
        url = "https://" + url[len("http://"):]

    form = await request.form()
    params = {k: v for k, v in form.multi_items()}

    validator = RequestValidator(TWILIO_AUTH_TOKEN)
    if not validator.validate(url, params, signature):
        logger.warning("Invalid Twilio signature on %s", request.url.path)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Twilio signature",
        )
