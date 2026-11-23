# ApexVoice Cloudflare migration

ApexVoice remains a FastAPI application. This branch packages it as a Cloudflare Python Worker using the official ASGI adapter. The existing Vercel configuration stays in place while the Cloudflare Worker is built and checked.

## Runtime setup

- Python dependencies are managed by `pyproject.toml` and Pywrangler.
- FastAPI is exposed through `cloudflare_worker.py`.
- Worker runtime values and encrypted secrets are read from Cloudflare bindings before the app modules load.
- The Cloudflare marker makes the app use its fail-closed serverless behavior: Redis is required for call state and local SQLite is not treated as durable storage.
- The small operations dashboard is bundled as Python source so the Worker does not depend on local disk reads.

## Required Cloudflare secrets

Set these as encrypted Worker secrets before live provider tests:

- `SIGNALWIRE_PROJECT_ID`
- `SIGNALWIRE_API_TOKEN`
- `SIGNALWIRE_SIGNING_KEY` (if different from the API token)
- `ELEVENLABS_API_KEY`
- `HUGGINGFACE_API_KEY`
- `UPSTASH_REDIS_REST_URL`
- `UPSTASH_REDIS_REST_TOKEN`
- `APEX_ADMIN_TOKEN`
- `CRON_SECRET`

Set `PUBLIC_URL` to the production Worker hostname for webhook signature validation. Keep `RECEPTIONIST_ENABLED=false` until provider tests pass.

## Cutover

1. Deploy to the Worker preview hostname and verify health, dashboard, and provider callbacks.
2. Add the custom domain `apex.harbourandmain.com` to the Cloudflare Worker only after the preview passes.
3. Reconfigure the SignalWire voice and status webhooks only after the custom-domain Worker has passed a real signed-callback test.
4. Preserve Vercel as rollback until the Cloudflare path has passed a controlled call and billing review.

No production domain or phone-number route is changed by this branch.
