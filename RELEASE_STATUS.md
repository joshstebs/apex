# ApexVoice release status (2026-11-28)

## What changed in this pass

- **Container hosting.** Production behaviour was gated on the `VERCEL` variable, so the app could not run correctly anywhere else. `is_serverless_runtime()` / `is_hosted_runtime()` now distinguish an ephemeral filesystem from a long-lived container, and call-state reads and writes follow the configured store. Previously a container with Redis reserved the slot in Redis and then read an empty local SQLite, so a live call was invisible to its own webhook turns.
- **Dockerfile and Render config** added, plus `docs/DEPLOYMENT.md` (Oracle Free Tier + Cloudflare Tunnel, Render). The image runs non-root, mounts `/data`, and has a healthcheck.
- **Duplicate TTS charges fixed.** A failed shared-cache write discarded already-paid audio and the next retry synthesized it again. Clip IDs were random per call, so a retried webhook re-rendered the greeting into a new billable clip; they are now derived from voice + text (truncated SHA-256, still opaque).
- **Silent-call slot retention.** Hosted slot semantics (no TTL until carrier confirmation) were `VERCEL`-only. A silent caller on a container could lose the slot mid-call and be settled against a slot it no longer owned.
- **In-container duration watchdog.** Hosted admission refuses a call when the scheduler heartbeat is over three minutes old, and nothing on a container wrote that heartbeat. An in-process thread now refreshes it, requests carrier termination at the cap, and settles stale reservations.
- **Staging readiness panel.** The drill returned `ok:true` while settlement was skipped for lack of Redis. It now reports `settlement_verified` and the dashboard states plainly when billing was not verified.
- **SQLite lifecycle.** Connections are closed per transaction (PR #6), so handles no longer leak.

## Verification performed

- 27/27 offline scripts pass, including six against a real loopback `redis-server`. GitHub `offline` CI is green on `main`.
- Local and staging smoke tests: `/`, `/api/health`, `/api/dashboard`, `/api/staging/exercise`; unauthenticated admin requests return 401; admin payloads scanned for secret-like values.
- Proxy URL reconstruction verified for `X-Forwarded-*` behind a tunnel.

## Still blocking production

1. **Live provider validation.** No real SignalWire call, ElevenLabs synthesis or Hugging Face completion has been executed. Signature verification, MP3 format, latency and cost are unverified against the providers.
2. **Exact carrier cutoff.** The enforcement cycle runs every 60 seconds, so an over-duration call can exceed the cap by up to one interval. SignalWire `Update a Call` exposes only `Status=canceled|completed`; there is no duration parameter. Only a carrier-side limit gives an instant cutoff.
3. **No deployment yet.** The Docker image was not built in this environment and no host has been provisioned. Oracle SSH rejected the available keys; Render requires an account action and a paid instance for a persistent disk.
4. **Billing reconciliation.** Reservations and spend are application estimates, not provider invoices. There is no reconciliation job against real usage.
5. **Retention and privacy.** Redis holds transcripts and captured messages for up to 24 hours with no operator-facing deletion control.
6. **Human handoff and booking.** The receptionist captures a message for later review. It does not transfer calls, notify staff or book appointments; those remain unimplemented, not merely disabled.

## Safety state

`RECEPTIONIST_ENABLED=false`. Outbound calling is disabled in code and cannot be
enabled by configuration. Staging forces a $0 budget and the mock provider. No
phone number routing was changed.

## Change history

Older entries were removed because they described a Vercel-only architecture and
listed blockers that no longer exist (lock expiry, single-use clips, Vercel
deployment). For traceability use `git log --follow RELEASE_STATUS.md` and the
per-commit messages on `main`; each merge records what was verified and what was
not.
