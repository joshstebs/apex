# ApexVoice release and rollback

This document covers the integrated staging candidate: webhook admission from `main`, pause / deadlines / budget settlement from pull request 2, and message capture / carrier speech fallback from pull request 3, plus the staging lock, operations dashboard, and voicemail transcript repair.

Production routing of the Harbour & Main number is still not approved. Do not change the live SignalWire voice webhook, do not set `RECEPTIONIST_ENABLED=true` on a public deployment, and do not buy credits from this change.

## What a deploy changes

- Inbound cXML now keeps a hosted call slot until a signed terminal status callback. A gather hangup marks the call `ending` and does not treat that instruction as a paid settlement.
- New hosted admissions require a scheduler heartbeat at `apex:operations:scheduler_at` (about three minutes). `POST /api/maintenance/enforce-call-duration` with `Authorization: Bearer <CRON_SECRET>` writes it and requests carrier hangup when a call is paused or past `MAX_CALL_DURATION_SECONDS`.
- Speech uses ElevenLabs only after the MP3 is cached. Storage or synthesis failure returns SignalWire `<Say>` instead of a `<Play>` URL that would be silent on HTTP 503.
- Customer words are stored as `save_receptionist_message`. A model tool call wins. If the model never emits one, the caller's transcript is stored as voicemail when the call ends. Audio recording stays off.
- `GET /` and `GET /operations` are the operations dashboard. `GET /api/dashboard` requires `Authorization: Bearer <APEX_ADMIN_TOKEN>`.
- `APEX_ENVIRONMENT=staging` forces a $0 budget, the mock telephony provider, carrier `<Say>`, and a webhook rate limit. That process cannot admit a call or open a carrier HTTP connection.

## Environment variables

Names only. Set them in the host's secret store. Never commit values.

| Name | Role |
| --- | --- |
| `APEX_ENVIRONMENT` | `local`, `staging`, or `production`. Staging forces the locks below. |
| `APEX_TELEPHONY_PROVIDER` | `signalwire` or `mock`. Ignored in staging, which is always `mock`. |
| `APEX_TTS_PROVIDER` | `elevenlabs` (default) or `carrier` for `<Say>` only. |
| `STAGING_WEBHOOK_RATE_LIMIT_PER_MINUTE` | Staging webhook ceiling, 1 to 60. Default 10. |
| `OUTBOUND_NUMBER_ALLOWLIST` | Documented only. Outbound PSTN stays disabled in code. |
| `RECEPTIONIST_ENABLED` | Must stay `false` until a human finishes the live checklist. |
| `SIGNALWIRE_SPACE_URL` | Space hostname. |
| `SIGNALWIRE_PROJECT_ID` | Project id. Not the phone-number inventory id. |
| `SIGNALWIRE_API_TOKEN` | REST token. Used as a signature fallback. |
| `SIGNALWIRE_SIGNING_KEY` | Preferred webhook HMAC key. |
| `SIGNALWIRE_PHONE_NUMBER` | E.164 DID the webhook will answer. |
| `SIGNALWIRE_PHONE_NUMBER_ID` | Inventory id. Not a secret and not used to authenticate calls. |
| `PUBLIC_URL` | HTTPS origin embedded in cXML. No preview login wall. |
| `ELEVENLABS_API_KEY` | TTS and voice listing. Unused while staging uses carrier speech. |
| `ELEVENLABS_DEFAULT_VOICE_ID` | Default Rachel: `21m00Tcm4TlvDq8ikWAM`. |
| `ELEVENLABS_MODEL_ID` | Default `eleven_turbo_v2_5`. |
| `HUGGINGFACE_API_KEY` | Chat completions. Heuristic text is used when this is empty. |
| `HUGGINGFACE_ROUTER_URL` | Default router chat-completions URL. |
| `HUGGINGFACE_LLM_MODEL` | Default `meta-llama/Llama-3.1-8B-Instruct`. |
| `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` | Or `KV_REST_API_URL` / `KV_REST_API_TOKEN`. Required for hosted call state. |
| `CRON_SECRET` | Scheduler bearer token. |
| `APEX_ADMIN_TOKEN` | Dashboard and admin bearer token. |
| `APEX_OPERATIONS_TOKEN` | Optional pause token. At least 32 characters and different from the admin token. |
| `APEX_MAX_CALL_RESERVE_USD` | Per-call hold. Must be greater than 0 and no larger than the monthly cap. Staging's cap is $0, so the hold can never succeed. |
| `MONTHLY_BUDGET_LIMIT_USD` | Monthly estimate cap. Ignored in staging, where the cap is $0 in code. |
| `MAX_CALL_DURATION_SECONDS` | Hard duration checked on the next webhook and by the scheduler. Default 1200. |
| `MAX_CONCURRENT_CALLS` | Default 1. |
| `ENFORCE_WEBHOOK_SIGNATURE` | Forced on when `VERCEL` is set. |

There is no database migration. Redis gains these keys when the new code runs: `apex:operations:paused`, `apex:operations:scheduler_at`, `apex:receptionist_messages`, `apex:recent_calls`, `apex:ops:errors`, and `apex:staging:webhook_rate`. Existing `apex:call:*`, `apex:acct:*`, and `apex:spend:*` records stay compatible. Old call state simply has no message index until the next update.

## Free staging infrastructure

Do not create a paid Redis, a paid Vercel plan, or a SignalWire / ElevenLabs credit purchase for this candidate.

1. Vercel Hobby preview for this branch. Leave `RECEPTIONIST_ENABLED` unset or `false`.
2. Upstash Redis free tier, or another free Redis REST endpoint, in its own database. Local tests use loopback `redis-server` and do not need Upstash.
3. No carrier webhook change. The preview must not be attached to `+12267732234`.
4. Set `APEX_ENVIRONMENT=staging`. Confirm `GET /api/health` shows `staging: true`, `telephony_provider: "mock"`, `inbound_live_calls_possible: false`, and `monthly_budget_limit_usd: 0.0`.

Human steps that cannot be done from this repository are listed in the pull request.

## Rollback

1. In the Vercel project, open Deployments and promote the previous production deployment. Do not promote this branch.
2. Set `RECEPTIONIST_ENABLED=false` on every environment that might have been toggled.
3. Leave the SignalWire number's voice and status URLs on their current values. This release does not change them. If a human pointed them at a preview, point them back only after reading the carrier's current webhook screen. Do that in the SignalWire dashboard, not from this app.
4. Optional Redis cleanup in the staging database only: delete `apex:operations:paused` and `apex:staging:webhook_rate` if you want the next boot to start from an empty pause/rate state. Do not delete `apex:acct:*` or `apex:spend:*` for a call that might still be open. A missing terminal callback is supposed to hold the slot.
5. Confirm rollback with `GET /api/health` on the restored deployment: `receptionist_enabled` is false and the previous code no longer reports `staging` if that field did not exist yet.
6. To roll back the Git branch without merging, close this pull request. The earlier pull requests 2 and 3 stay open and are not force-pushed.

Hosted call slots from this build do not expire on their own. After rollback to a build whose lock has a TTL, pause inbound handling and confirm `apex:active_call_lock` is empty before serving traffic again.
