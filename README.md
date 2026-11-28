# ApexVoice AI

Self-hostable prototype for a SignalWire inbound voice assistant, using ElevenLabs for spoken replies, the Hugging Face chat-completions router for reasoning, Redis for shared call state, and FastAPI for the web/API layer. It runs on a container (Oracle Cloud, Render, Docker) as well as on serverless hosts.

**Release status: NOT PRODUCTION READY.** No live SignalWire, ElevenLabs or Hugging Face call has been verified, and no deployment has passed a staging acceptance test. It is not safe to route a live phone number here. Outbound PSTN calls are intentionally disabled.

## Current capabilities

- Signed inbound SignalWire Compatibility API webhook handlers and cXML conversation turns.
- Version-controlled assistant templates in `prompts/`. Inbound uses one template or a fallback receptionist prompt.
- Short-lived, opaque TTS clip IDs with retry-safe MP3 caching. Clip IDs are derived from the words and voice, so a retried webhook reuses cached audio instead of paying for a second synthesis.
- One-call admission lock and **estimated** budget reservations. These are not independently enforced carrier limits.
- Protected administrative read endpoints and a minimal same-origin operations dashboard, including an on-demand staging readiness drill.
- Local SQLite assistant editing and simulation. These stay available on a container using a mounted volume, and are disabled whenever call state is shared.
- Degraded-mode replies do not fabricate appointment confirmations, return numbers or discounts.

## Deployment targets

Vercel is unavailable for this account. See `docs/DEPLOYMENT.md` for the supported
path: a container behind Cloudflare Tunnel on Oracle Free Tier, or Render with a
persistent disk. Cloudflare Workers is an experiment only.

`/api/health` reports `durable_storage_configured`. When it is `false`, call state
does not survive the next request and **no call will be admitted** — that is
deliberate.

## Run locally

Requires Python 3.11+ and dependencies from `requirements.txt`:

```sh
python -m pip install -r requirements.txt
cp .env.example .env
uvicorn app:app --host 127.0.0.1 --port 8080
```

**Environment note:** This app reads process environment variables; copying `.env.example` does not automatically load `.env`. Load values through a trusted process manager or local shell. Never commit live keys. Set `APEX_ADMIN_TOKEN` to a strong secret to access administrative endpoints.

For Docker: `docker build -t apexvoice-ai . && docker run --env-file .env -p 8000:8000 -v apex-data:/data apexvoice-ai` (for local development only; omit `-v` outside development).

## Offline checks

Run every script, which is what CI does:

```sh
python -m compileall -q .
for test_file in test_*.py; do python "$test_file"; done
```

Four of them (`test_call_lifecycle`, `test_redis_lock`, `test_stale_settlement`,
`test_staging_exercise`, plus `test_maintenance_watchdog` and
`test_silent_call_lock`) use a loopback `redis-server` and skip with a clear
message if `redis-server`/`redis-cli` are not installed.

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
- Required Vercel inbound duration watchdog: `POST /api/maintenance/enforce-call-duration`
  (bearer `CRON_SECRET`, requires an **external scheduler at least once a minute**).

The watchdog writes a three-minute heartbeat after a successful check. New Vercel
calls require the heartbeat and a valid budget reservation. Once admitted, a call
owns the slot until a signed terminal callback settles its reservation. A missing
callback holds the slot closed. The one-minute scheduler cadence and upstream
latency affect when an overdue hangup request is sent. Verify the carrier's own
duration and spending controls using the test number before enabling business routing.


## Purchased SignalWire test number (October 29, 2026)

- Number: **+1 (226) 773-2234**, E.164 **+12267732234**
- SignalWire number ID: `8f935d8b-bd61-457b-b421-edddfef247ea`
- Receptionist persona: `tpl_hm_receptionist`; ElevenLabs Rachel (`21m00Tcm4TlvDq8ikWAM`),
  model `eleven_turbo_v2_5` for synthesized speech.
- AI conversational reasoning still uses Hugging Face. **An ElevenLabs API key alone is not enough** for interactive conversation.
- `PUBLIC_URL=https://apex.harbourandmain.com` for a production deployment which accepts provider POST webhooks.
  Deployment Protection must allow only the public signed webhook requests on that hostname;
  all admin data APIs still require `APEX_ADMIN_TOKEN`.

### Activation checklist (do not skip)

1. Verify the number belongs to your SignalWire Space and supports **Voice**.
   The number ID is an inventory ID, **not an API token or Project ID**.
2. Set `SIGNALWIRE_PROJECT_ID`, `SIGNALWIRE_API_TOKEN`,
   `SIGNALWIRE_SIGNING_KEY` (if used), `ELEVENLABS_API_KEY`,
   `HUGGINGFACE_API_KEY`, `UPSTASH_REDIS_REST_URL`,
   `UPSTASH_REDIS_REST_TOKEN`, and a strong `APEX_ADMIN_TOKEN`
   as **encrypted Vercel environment variables**. Never commit actual keys.
3. Verify `GET /api/health` reports `receptionist_provider_ready: true`;
   test ElevenLabs synthesized audio and Hugging Face inference with real credits.
4. Set `RECEPTIONIST_ENABLED=true` only for a controlled short live test.
5. In SignalWire Phone Numbers -> +1 226-773-2234 -> Edit Settings ->
   Inbound Call Settings, configure a **Compatibility API / cXML** incoming
   voice webhook (POST) at:
   `https://apex.harbourandmain.com/webhooks/signalwire/voice`
   and a call status callback (POST) at
   `https://apex.harbourandmain.com/webhooks/signalwire/status`.
   Depending on your SignalWire dashboard, configure a cXML resource using the
   external URL and assign that resource to the number. Do not configure a
   SWML-only handler expecting a SWML response: this application returns cXML.
6. Test greeting, several turns, no-answer path, voicemail details, duration,
   explicit hangup, provider callback signatures, and actual billable usage.
   No human transfer, outbound calls, staff alerts or actual appointment
   booking is implemented. A 20-minute **exact carrier limit is not verified**.


### Vercel FastAPI routing (October 29, 2026)
The project uses Vercel's native FastAPI detection of root `app.py`.
Do not add a catch-all rewrite to `/api/index`, which causes FastAPI to receive
an incorrect path and return HTTP 404 for the main application. The standalone
`api/index.py` is retained as a legacy compatibility entrypoint only.

### Command Center pause control

Set a dedicated `APEX_OPERATIONS_TOKEN` before staging the operations endpoints. The token
must be at least 32 characters and differ from `APEX_ADMIN_TOKEN`. Where Vercel and Upstash
are configured, `GET /api/operations` returns a Redis admission estimate and scheduler heartbeat.
`POST /api/operations/pause` atomically sets `apex:operations:paused` and reads the active-call
slot. It then requests carrier termination when a slot is occupied. Carrier acceptance is
reported separately, and signed status callbacks still reconcile costs. A provider request
already dispatched can run to completion.

To restore service, first verify the carrier has ended any active call and resolve the incident.
Then remove only the `apex:operations:paused` key in the correct Upstash database. The application
still requires its normal inbound configuration and budget eligibility. Use the provider consoles
for actual billing and provider-side caps. The scheduled enforcer heartbeat expires after three
minutes and indicates an authenticated check-in.


### Operations dashboard

`GET /` and `GET /operations` show service status, estimated spend versus the cap, the live call, recent calls, receptionist messages, and error codes after the administrator token is entered. The token stays in tab memory. `GET /api/dashboard` is the same snapshot and requires `Authorization: Bearer <APEX_ADMIN_TOKEN>`. Responses omit secrets and full recording audio. Audio recording is not enabled.

Spoken replies use a cached ElevenLabs clip only after synthesis succeeds. If clip storage or synthesis fails, the cXML uses SignalWire `<Say>`. A call that ends without a model tool call stores the caller's transcript as a voicemail message.

### Staging that cannot place calls

Set `APEX_ENVIRONMENT=staging` on a Vercel preview and a free Redis database (Upstash free tier, or loopback Redis for tests). Staging forces a **$0** monthly cap in code, selects the mock telephony provider, refuses inbound admission, rate-limits webhooks, and does not open a carrier connection. `MONTHLY_BUDGET_LIMIT_USD` and `APEX_TELEPHONY_PROVIDER` cannot override those locks. Outbound PSTN stays disabled. Do not point `+12267732234` or any customer number at this deployment.

`docs/RELEASE.md` lists the environment variable names, Redis keys, and the rollback procedure.

To exercise a staging deployment without a carrier:

```sh
python3 scripts/staging_exercise.py --base-url https://<preview-host>
```

The admin token is read from `APEX_ADMIN_TOKEN` or `--token-file` and is not printed. The route is `POST /api/staging/exercise`. It returns 404 unless `APEX_ENVIRONMENT=staging`.

The carrier-backed checks below are for a later, separate production rehearsal. They are not part of staging and they are not authorized by this branch:

1. Keep `RECEPTIONIST_ENABLED=false` until a human has verified provider accounts, signatures, and spend caps.
2. Run the enforcer every minute only on a host that is allowed to control a real call. Send a POST to `/api/maintenance/enforce-call-duration` with `Authorization: Bearer <CRON_SECRET>`.
3. A hosted call keeps its Redis reservation until the signed terminal callback. Duplicate callbacks must not charge the estimate twice. A missing callback holds the slot.
4. Before rolling back to a build whose call lock expires, pause inbound handling and confirm `apex:active_call_lock` is empty.

Run `python -m compileall -q .` and the `test_*.py` scripts locally. Lifecycle and lock tests start loopback Redis and stub carrier termination.
