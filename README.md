# ApexVoice AI

Self-hostable prototype for a SignalWire inbound voice assistant, using ElevenLabs for spoken replies, the Hugging Face chat-completions router for reasoning, Redis for shared serverless call state, and FastAPI for the web/API layer.

**Release status: NOT PRODUCTION READY.** This version has not been verified with live SignalWire, ElevenLabs, Hugging Face, Upstash Redis or Vercel. It is not safe to route a live phone number here. Outbound PSTN calls are intentionally disabled.

## Current capabilities

- Signed inbound SignalWire Compatibility API webhook handlers and cXML conversation turns.
- Version-controlled assistant templates in `prompts/`. Inbound uses one template or a fallback receptionist prompt.
- Short-lived, opaque TTS clip IDs with Redis-backed MP3 retry caching in Vercel.
- One-call admission lock and **estimated** Redis budget reservations. These are not independently enforced carrier limits.
- Protected administrative read endpoints and a minimal same-origin operations dashboard.
- Local SQLite simulator / assistant editing functionality only. These features are deliberately unavailable on Vercel, where Redis is the required shared state.
- Degraded-mode replies do not fabricate appointment confirmations, return numbers or discounts.

## Run locally

Requires Python 3.11+ and dependencies from `requirements.txt`:

```sh
python -m pip install -r requirements.txt
cp .env.example .env
uvicorn app:app --host 127.0.0.1 --port 8080
```

**Environment note:** This app reads process environment variables; copying `.env.example` does not automatically load `.env`. Load values through a trusted process manager or local shell. Never commit live keys. Set `APEX_ADMIN_TOKEN` to a strong secret to access administrative endpoints.

For Docker: `docker build -t apexvoice-ai . && docker run --env-file .env -p 8000:8000 apexvoice-ai` (for local development only).

## Offline checks

```sh
python -m compileall -q app.py config.py database.py telephony.py voice_engine.py api
python test_security_regressions.py
python test_audio_retries.py
python test_safe_fallbacks.py
```

`legacy_vercel_corrections_reference.py` is an outdated test fixture that predates the Redis Lua state machine; it is retained only for traceability and is **not** a passing test.

## Before production

See `RELEASE_STATUS.md` for blockers: carrier-enforced 20-minute cutoff, provider fixture verification, actual invoice/usage reconciliation, Redis expiry and MP3 cache limits, serverless admin state, fully configured secrets, deployment and live end-to-end acceptance tests. Do **not** change the existing carrier number routing before these are completed.


## Harbour & Main inbound AI receptionist (staged)

The `tpl_hm_receptionist` template is now the default inbound assistant. It answers as
Harbour & Main, tells callers they are speaking with AI and that speech may be
transcribed, gathers caller contact details, and avoids fabricated bookings or
promises of callbacks. Call data is available through a protected API while retained.
There is **no automatic staff notification** or human transfer.

**Not yet enabled:** Set `RECEPTIONIST_ENABLED=true` only after validating the
account number, configuring SignalWire signed POST callbacks and durable Redis,
checking provider credits and costs, and completing live end-to-end tests.
`REQUIRE_MATCHING_INBOUND_NUMBER=true` rejects webhook calls whose
`To` does not match the exact `SIGNALWIRE_PHONE_NUMBER` value. Do not point
an existing business number here before this verification.

- Inbound voice webhook (POST): `/webhooks/signalwire/voice`
- Gather follow-up (POST, generated automatically by cXML): `/webhooks/signalwire/gather`
- Status callback (POST): `/webhooks/signalwire/status`
- Protected manual hangup: `POST /api/calls/{call_id}/terminate` (bearer admin token)
- Optional duration watchdog: `POST /api/maintenance/enforce-call-duration`
  (bearer `CRON_SECRET`, requires an **external scheduler at least once a minute**).

A successful hangup request is not the same as a confirmed hangup. The carrier
status callback must be checked and invoices reconciled. An external 60-second
watchdog is **not** an exact 20-minute cutoff; with a failed callback or scheduler,
the call can exceed 20 minutes. Vercel Hobby cron cannot run every minute.
Do not activate live routing until carrier-enforced duration and usage tests pass.
