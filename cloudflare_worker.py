"""Cloudflare Python Workers entrypoint for the ApexVoice FastAPI app."""
import os

from workers import asgi, env

# FastAPI and the existing modules read settings from process environment at import.
# Copy only the known runtime settings from Cloudflare's encrypted bindings.
_RUNTIME_SETTINGS = (
    "PUBLIC_URL",
    "SIGNALWIRE_SPACE_URL", "SIGNALWIRE_PROJECT_ID", "SIGNALWIRE_API_TOKEN",
    "SIGNALWIRE_SIGNING_KEY", "SIGNALWIRE_PHONE_NUMBER", "SIGNALWIRE_PHONE_NUMBER_ID",
    "ENFORCE_WEBHOOK_SIGNATURE", "RECEPTIONIST_ENABLED", "INBOUND_ASSISTANT_ID",
    "RECEPTIONIST_BUSINESS_NAME", "REQUIRE_MATCHING_INBOUND_NUMBER",
    "ALLOW_INBOUND_ASSISTANT_OVERRIDE", "CRON_SECRET",
    "ELEVENLABS_API_KEY", "ELEVENLABS_DEFAULT_VOICE_ID", "ELEVENLABS_MODEL_ID",
    "HUGGINGFACE_API_KEY", "HUGGINGFACE_ROUTER_URL", "HUGGINGFACE_LLM_MODEL",
    "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN", "KV_REST_API_URL",
    "KV_REST_API_TOKEN", "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN",
    "MAX_CONCURRENT_CALLS", "MAX_CALL_DURATION_SECONDS", "MONTHLY_BUDGET_LIMIT_USD",
    "TTS_CLIP_TTL_SECONDS", "HTTP_UPSTREAM_TIMEOUT_SECONDS", "APEX_MAX_CALL_RESERVE_USD",
    "APEX_ADMIN_TOKEN", "DB_PATH",
)
for _key in _RUNTIME_SETTINGS:
    _value = getattr(env, _key, None)
    if _value is not None:
        os.environ[_key] = str(_value)

os.environ["CLOUDFLARE_WORKERS"] = "1"

from app import app  # noqa: E402
from workers import WorkerEntrypoint  # noqa: E402

_asgi = asgi.entrypoint(app)

class Default(WorkerEntrypoint):
    async def fetch(self, request):
        return await _asgi.fetch(request, self.env)
