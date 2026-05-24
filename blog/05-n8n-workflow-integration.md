# Wiring Phone Calls into Any Workflow with n8n

*Use VoxFlow as the AI brain, n8n as the business logic.*

## The separation of concerns

VoxFlow does one thing: it makes a phone call into an AI conversation. It doesn't know about your CRM, your calendar, your email templates, or your business rules. That's deliberate.

```mermaid
flowchart LR
    Caller([Caller]) --> VoxFlow[VoxFlow<br/>AI]
    VoxFlow --> N8N[n8n workflow]
    N8N --> CRM[CRM lookup]
    N8N --> Cal[Calendar booking]
    N8N --> Email[Email confirmations]
    N8N --> Slack[Slack notifications]
```

VoxFlow is the **mouth and ears**. n8n is the **hands**.

## The contract: three webhook routes

VoxFlow posts to a single `N8N_WEBHOOK_URL`, distinguishing intent with a `route` field:

| `route` | When | Payload | Expected reply |
|---------|------|---------|----------------|
| `"1"` | New call starts | `{number, data: "empty"}` | `{firstMessage: "<greeting>"}` |
| `"2"` | Call ended | `{number, data: "<full transcript>"}` | (ignored) |
| `"3"` | AI booked a meeting | `{number, data: "<JSON details>"}` | `{message: "<confirmation>"}` |

This is the entire integration surface. Implement these three routes and you've integrated VoxFlow with whatever system you want.

## The minimal n8n workflow

```mermaid
flowchart TD
    WH[Webhook Trigger<br/>POST /webhook/abc123] --> SW{Switch on<br/>$json.route}
    SW -- "1" --> R1[HTTP Request: CRM lookup by phone]
    R1 --> R1b["Set: {firstMessage: 'Hi {{name}}, ...'}"]
    SW -- "2" --> R2[Postgres: INSERT INTO call_log]
    R2 --> R2b[Optional: Slack notification]
    SW -- "3" --> R3[Google Calendar: Create event]
    R3 --> R3b[Email: Send confirmation]
    R3b --> R3c["Set: {message: 'Booked for {{datetime}}'}"]
```

That's it. Three branches. No code.

## Why personalize the greeting?

Route `"1"` fires at the start of every call. If you have any record of this phone number, you can greet them by name:

```
Anonymous caller:   "Hello, this is Sara. How can I help?"
Returning customer: "Hi John, welcome back! Calling about your appointment Tuesday?"
```

The second one cuts 15 seconds off the call by skipping identity verification. Over 1000 calls/month that's hours of phone time saved.

If n8n returns nothing or fails, VoxFlow falls back to `DEFAULT_FIRST_MESSAGE`. The call never breaks.

## Why ship the transcript?

Route `"2"` is fire-and-forget. The call has ended; we're just archiving. Common downstream uses:

- **Compliance log** — financial / healthcare verticals require recordings or transcripts
- **Quality assurance** — sample 5% of calls into a Slack channel for human review
- **Lead scoring** — feed transcript into another LLM for sentiment / intent classification
- **CRM enrichment** — append to the contact's activity timeline

## Why route meeting bookings through n8n?

You *could* have VoxFlow call Google Calendar directly. Don't.

Reasons to route through n8n instead:
- **Calendar choice** — different locations, doctors, salespeople each have different calendars
- **Conflict checks** — n8n can query for double-bookings and respond `{message: "That slot is taken, how about 3pm?"}` which the AI will read aloud
- **Multi-system writes** — same booking might create a Salesforce event + send an SMS + update internal ops doc
- **Easier to change** — your scheduling logic changes more often than your AI agent

The AI doesn't care. From its perspective, `schedule_meeting()` returned a message. It reads that message to the caller.

## A complete n8n flow for a dental clinic

```mermaid
flowchart TD
    WH[Webhook trigger] --> SW{Switch on route}

    SW -- "1: greeting" --> G1[HubSpot: find contact by phone]
    G1 --> G2{Found?}
    G2 -- yes --> G3[Build personalized greeting]
    G2 -- no --> G4[Return generic greeting]

    SW -- "2: transcript" --> T1[HubSpot: append to timeline]
    T1 --> T2[GPT-4: extract intent + sentiment]
    T2 --> T3{Sentiment<br/>negative?}
    T3 -- yes --> T4[Slack alert to manager]

    SW -- "3: booking" --> B1[Google Calendar: check availability]
    B1 --> B2{Available?}
    B2 -- yes --> B3[Create event + send SMS]
    B2 -- no --> B4[Return alt slot to AI]
```

Zero lines of Python written. The receptionist now talks to HubSpot and books appointments on a real calendar.

## Authentication

n8n webhooks support HMAC signatures. VoxFlow doesn't sign requests today, so for production you should either:

- Put n8n behind a reverse proxy with IP allowlisting (VoxFlow's outbound IP)
- Add `Authorization` headers in `send_to_webhook()` and validate in n8n
- Use n8n's built-in webhook auth (username/password or header token)

## Takeaway

VoxFlow + n8n is two specialists doing what they're each good at. Don't put business logic in your AI middleware; put it where business analysts can edit it themselves.
