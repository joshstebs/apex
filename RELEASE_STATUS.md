# ApexVoice security and serverless repair status (2026-10-14)

## Implemented in this revision
- Browser UI replaced with a minimal, same-origin operational dashboard. No API keys are collected or stored in browser localStorage. Administrator token stays in tab memory only.
- Administrative APIs require a configured bearer token. CORS is not permissively enabled.
- Production Vercel calls require Redis. Atomic Redis admission uses a Lua budget reservation and single active-call lock. A Redis outage rejects new inbound calls instead of silently falling back to SQLite.
- Serverless call state and transcripts are read from Redis and mutated via atomic Lua operations; local SQLite is not used as the authoritative production state. Production assistant templates are version-controlled and read-only. Unsupported editing, simulations and history listing explicitly return 503 rather than pretending temporary SQLite is durable.
- First inbound webhook uses the signed provider CallSid. The follow-up handler checks the current Redis lock owner. Duration checks use wall-clock start time rather than a fabricated 20 seconds per turn.
- Opaque TTS URLs do not contain conversation text. Production requires shared Redis for clip metadata. Each clip can be redeemed once, reducing repeated paid ElevenLabs synthesis from URL replay. A retry after redemption will receive 410; production-grade shared MP3 caching would be preferable for carrier retries.
- Outbound PSTN calls remain disabled.

## Local verification
`python test_security_regressions.py` passes using a deterministic in-memory Redis mock and FastAPI TestClient. `python -m compileall -q .` passes. No live provider calls or Vercel deployment have been tested. The older `test_final_vercel_corrections.py` is incompatible with the atomic Lua-based Redis mock and does not pass; it is retained for reference only.

## Critical unresolved prerequisites, do not switch the live number yet
1. **Five-minute carrier-side hard termination:** the webhook's elapsed-time check only acts at the next speech turn. A carrier-side timer or authenticated call-update termination must be implemented and tested with SignalWire. The administrative terminate endpoint is intentionally disabled on Vercel rather than falsely claiming carrier termination.
2. **Provider integration:** validate webhook signature using real SignalWire callbacks, confirm signed callback URL/proxy normalization, actual Hugging Face model availability, and ElevenLabs MP3 response format, latency and quotas.
3. **Spending:** Redis reserves an estimated $3 per admitted call by default (`APEX_MAX_CALL_RESERVE_USD`, configurable) and reconciles an estimated cost. This is not a provider billing cap. ElevenLabs credits, carrier billing, inbound STT and provider costs are not reconciled against real usage. Explicit provider spending alerts/caps and a reconciliation job are needed.
4. **Redis lifecycle:** 315-second active-call lock can expire while a call remains active; refresh/heartbeat or carrier-enforced termination is required before routing live traffic. Upstash REST EVAL support and atomic scripts need a real integration test.
5. **Audio delivery:** single-use clip redemption blocks repeated charges but a provider retry may fail; production needs shared, encrypted/controlled cached audio bytes with a short TTL and idempotent GET behavior.
6. **Production administration:** editing and call listing are deliberately disabled rather than relying on ephemeral storage. Implement durable indexes and authenticated mutation if those features are required.
7. **Deployment:** no verified GitHub push, Vercel build, environment variables or publicly accessible HTTPS smoke test yet.

This release is a **security and durability improvement, not production-ready live telephony**. No phone number routing was modified.

## Additional update: 20-minute calls
- Default `MAX_CALL_DURATION_SECONDS` is now 1200 (20 minutes). `.env.example` documents it and a suggested $3 call budget reservation, which must be adjusted to actual provider charges.
- The voice prompt uses the configured duration rather than claiming five minutes.
- The Redis active-call lease is based on the configured maximum plus 15 seconds, so it no longer expires at 315 seconds on 20-minute calls. **This is not a carrier-side cutoff or a heartbeat.**
- Webhook-level duration enforcement only executes when SignalWire sends another gather callback. Real carrier-side termination, provider cost reconciliation, and live integrations remain outstanding.
- Local security regression suite and compilation pass after the changes.

## 2026-10-14 additional hardening
- Added short-lived shared Redis MP3 cache and synthesis lock for retry-safe GETs, reducing repeat ElevenLabs synthesis on carrier retries. Concurrent first requests receive HTTP 503 Retry-After instead of an unrecoverable 410. Audio remains stored in Redis as base64 and should be reviewed for size/quota/privacy suitability before production.
- Gather callback now uses authenticated POST CallSid as source of truth and rejects a mismatched query call_id.
- Status callback no longer truncates carrier-reported duration to the configured maximum.
- Protected and validated cost estimator input.
- Added test_audio_retries.py; both this test and test_security_regressions.py pass offline; compilation passes.
- No carrier-side hard cutoff, live Redis/SignalWire/ElevenLabs/HF testing, billing reconciliation, GitHub push, or Vercel deployment has been completed. Keep live routing unchanged.

## 2026-10-22 code-review adjustments
- Eliminated conflicting 300-second sample duration; the documented default is 1200 seconds (still NOT carrier-enforced).
- Degraded-mode AI fallback can no longer invent booking confirmations, RMA codes, prices, or savings, and never triggers extraction tools.
- Local SQLite no longer disables synchronous durability; Vercel no longer initializes an unnecessary instance-local database.
- Redis `SET NX` failure for durable state creation now fails closed, and provider gather outage returns an XML hangup instead of HTTP 500.
- Sample config includes `APEX_ADMIN_TOKEN`; added `.gitignore` for secrets/runtime state; README now accurately labels prototype and unverified features.
- Renamed obsolete failing test suite to `legacy_vercel_corrections_reference.py` rather than presenting it as a valid regression test.
- Added `test_safe_fallbacks.py`. Actual provider-integrated behavior remains untested.
- Vercel deployments now force webhook signature enforcement regardless of an accidentally insecure `ENFORCE_WEBHOOK_SIGNATURE` environment override; health readouts no longer treat Turso-only storage as production-call-ready.
