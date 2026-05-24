# Verifying Twilio Webhook Signatures (and Why You Must)

*Your `/incoming-call` endpoint is on the public internet. Treat it that way.*

## The threat that nobody mentions in the tutorial

The "five-minute Twilio quickstart" ends at:

```python
@app.post("/incoming-call")
async def incoming_call(request: Request):
    ...  # return TwiML
```

What the tutorial doesn't say: this URL is a public, unauthenticated POST endpoint. Anyone who guesses or scrapes it can:

- Trigger your AI agent — burning Ultravox tokens, eating your minutes, and tying up worker capacity.
- Drive synthetic traffic to your `n8n` workflows, polluting your CRM with fake leads.
- Trigger outbound calls (if your `/outgoing-call` route is similarly open) — instant abuse vector.

Twilio knows this, which is why they sign every webhook. Most people just don't verify the signature.

## How the signature works

For every webhook, Twilio computes:

```
HMAC-SHA1(
  key   = your_auth_token,
  input = full_request_url + concat(sorted(form_field=value for each form field))
)
```

…and sends the base64 of that in the `X-Twilio-Signature` header. If you recompute the same thing on your side and the values match, the request really came from Twilio.

The Twilio Python SDK ships `RequestValidator` so you don't write the HMAC yourself.

## The FastAPI dependency

In VoxFlow this is one small dependency that gates `/incoming-call` and `/call-status`:

```python
async def verify_twilio_signature(request: Request) -> None:
    if not TWILIO_VALIDATE_SIGNATURE or not TWILIO_AUTH_TOKEN:
        return  # opt-out for local dev / tests

    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        raise HTTPException(403, "Missing Twilio signature")

    url = str(request.url)
    if request.headers.get("X-Forwarded-Proto") == "https" \
            and url.startswith("http://"):
        url = "https://" + url[len("http://"):]

    form = await request.form()
    params = {k: v for k, v in form.multi_items()}

    if not RequestValidator(TWILIO_AUTH_TOKEN).validate(url, params, signature):
        raise HTTPException(403, "Invalid Twilio signature")
```

Wire it in once:

```python
@router.post("/incoming-call", dependencies=[Depends(verify_twilio_signature)])
async def incoming_call(request: Request): ...
```

Every other request handler stays oblivious. Auth becomes a deployment knob.

## The three subtle gotchas

**1. The scheme is the most common bug.**
Twilio signs `https://yourapp.com/incoming-call`. Behind a TLS-terminating proxy (Heroku, Cloud Run, Fly, k8s ingress), your app sees the connection as `http://`. Recompute over `http://` and the HMAC won't match. Always read `X-Forwarded-Proto` and patch the scheme.

**2. The form fields must be the parsed ones.**
Twilio sorts the keys, concatenates `key+value`, then appends. Use `request.form()` — not the raw body. The Twilio SDK does the sorting; you just hand it a dict.

**3. The opt-out matters for testability.**
A `TWILIO_VALIDATE_SIGNATURE=false` knob lets your test suite POST without minting fake signatures, and lets ngrok-based local dev work when the public URL the tunnel exposes doesn't exactly match what FastAPI sees. Production stays `true`; CI and laptops stay `false`.

## The "but we're behind a private VPC" excuse

Nope. Twilio's media servers come from a known public IP range — putting your app in a VPC means whitelisting that range, which is its own ongoing maintenance burden. Signature validation is the same security guarantee, deployable anywhere, and tied to a secret you already rotate (the auth token).

## Test it before you ship it

A two-line negative test catches most regressions:

```python
def test_incoming_call_rejects_missing_signature(client_with_validation_on):
    resp = client_with_validation_on.post("/incoming-call", data={"CallSid": "CA1"})
    assert resp.status_code == 403
```

And one positive test using `RequestValidator` to mint a valid signature.

## Takeaway

Twilio gives you a tamper-evident channel for free. Not using it is choosing to leave the front door unlocked because the lock looks complicated. The whole thing is one dependency, one env var, and a 30-line module. Ship it before the first malicious POST does.
