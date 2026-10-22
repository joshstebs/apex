# ApexVoice security patch (2026-10-14)

- Removed permissive cross-origin middleware.
- Protected assistant, call-history, simulator, voice-list, and mutation endpoints with `Authorization: Bearer <APEX_ADMIN_TOKEN>`. Set a long random `APEX_ADMIN_TOKEN` in Vercel. Existing browser UI must be updated to authenticate before administrative functions can be used.
- Redis call admission now uses one Lua EVAL operation for the concurrency lock and a configurable call budget reservation (currently $3/call by default). An owning call's release reconciles that reservation with estimated call cost. These are application estimates, **not** a carrier-side billing cap.
- Production (`VERCEL=1`) refuses new calls unless Upstash Redis is configured; Redis failures fail closed instead of allowing local SQLite admission. Production audio lookup does not silently fall back to local SQLite.
- Existing tests mock Upstash commands but not Lua EVAL, so the original offline suite needs updated mocks before it can pass. No live provider tests performed.

## Remaining blockers before routing a live number

- Verify Upstash Lua EVAL support on the chosen REST plan and test its error/timeout handling.
- Replace remaining local-first call/transcript mutation with Redis-canonical state and atomic turn updates. Multiple Vercel instances may still race or lose transcripts.
- Ensure durable assistant edits and simulator history are implemented; local SQLite is not persistent on Vercel.
- Update the browser UI to support admin bearer authentication without storing the token insecurely.
- Add a real provider-side call termination mechanism and accurate usage reconciliation. Current duration checks are not a guaranteed five-minute cutoff.
- Rework TTS fetch token handling and add request throttling to prevent repeated ElevenLabs synthesis charges.
- Review signature verification against real SignalWire signed webhook fixtures.
- Do not route the live number until these issues and live smoke tests pass.
