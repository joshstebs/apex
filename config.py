"""
Configuration for ApexVoice AI (Vercel Serverless + SignalWire + ElevenLabs + Hugging Face)
All secrets are read strictly from environment variables and never exposed via API responses.
"""
import os

class AppSettings:
    def __init__(self):
        self.HOST: str = os.getenv("HOST", "0.0.0.0")
        self.PORT: int = int(os.getenv("PORT", "8080"))
        vercel_url = os.getenv("VERCEL_PROJECT_PRODUCTION_URL") or os.getenv("VERCEL_URL")
        default_pub = f"https://{vercel_url}" if vercel_url else "http://localhost:8080"
        self.PUBLIC_URL: str = os.getenv("PUBLIC_URL", default_pub)
        
        self.DEFAULT_TELEPHONY_PROVIDER: str = "signalwire"
        
        # SignalWire Configuration (Harbour and Main)
        self.SIGNALWIRE_SPACE_URL: str = os.getenv("SIGNALWIRE_SPACE_URL", "harbour-and-main.signalwire.com")
        self.SIGNALWIRE_PROJECT_ID: str = os.getenv("SIGNALWIRE_PROJECT_ID", "")
        self.SIGNALWIRE_API_TOKEN: str = os.getenv("SIGNALWIRE_API_TOKEN", "")
        self.SIGNALWIRE_SIGNING_KEY: str = os.getenv("SIGNALWIRE_SIGNING_KEY", "")
        self.SIGNALWIRE_PHONE_NUMBER: str = os.getenv("SIGNALWIRE_PHONE_NUMBER", "+12267732234")
        # SignalWire inventory ID is used for number administration, not call authentication.
        self.SIGNALWIRE_PHONE_NUMBER_ID: str = os.getenv(
            "SIGNALWIRE_PHONE_NUMBER_ID", "8f935d8b-bd61-457b-b421-edddfef247ea"
        )
        self.INBOUND_ASSISTANT_ID: str = os.getenv("INBOUND_ASSISTANT_ID", "tpl_hm_receptionist")
        # Disable unauthorized selection of a different assistant from a public webhook URL.
        self.ALLOW_INBOUND_ASSISTANT_OVERRIDE: bool = os.getenv("ALLOW_INBOUND_ASSISTANT_OVERRIDE", "false").lower() == "true"
        self.REQUIRE_MATCHING_INBOUND_NUMBER: bool = os.getenv("REQUIRE_MATCHING_INBOUND_NUMBER", "true").lower() == "true"
        self.RECEPTIONIST_BUSINESS_NAME: str = os.getenv("RECEPTIONIST_BUSINESS_NAME", "Harbour & Main")
        # External scheduler must be configured separately. Never assume a scheduler exists.
        self.CRON_SECRET: str = os.getenv("CRON_SECRET", "")
        self.RECEPTIONIST_ENABLED: bool = os.getenv("RECEPTIONIST_ENABLED", "false").lower() == "true"
        # Enforce webhook signature verification (enabled by default in production)
        # Production cannot disable provider-authenticated webhooks by mistake.
        self.ENFORCE_WEBHOOK_SIGNATURE: bool = bool(os.getenv("VERCEL")) or os.getenv("ENFORCE_WEBHOOK_SIGNATURE", "true").lower() == "true"
        
        # ElevenLabs Configuration
        self.ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
        self.ELEVENLABS_DEFAULT_VOICE_ID: str = os.getenv("ELEVENLABS_DEFAULT_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel
        self.ELEVENLABS_MODEL_ID: str = os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5")
        
        # Hugging Face Inference Providers Router (2026 Current Supported Endpoint & Model)
        self.HUGGINGFACE_API_KEY: str = os.getenv("HUGGINGFACE_API_KEY", "")
        self.HUGGINGFACE_ROUTER_URL: str = os.getenv(
            "HUGGINGFACE_ROUTER_URL",
            "https://router.huggingface.co/v1/chat/completions"
        )
        self.HUGGINGFACE_LLM_MODEL: str = os.getenv(
            "HUGGINGFACE_LLM_MODEL",
            "meta-llama/Llama-3.1-8B-Instruct"
        )
        
        # Durable Serverless Storage Providers (Upstash Redis / Vercel KV or Turso Cloud HTTP SQLite)
        self.UPSTASH_REDIS_REST_URL: str = os.getenv("UPSTASH_REDIS_REST_URL") or os.getenv("KV_REST_API_URL", "")
        self.UPSTASH_REDIS_REST_TOKEN: str = os.getenv("UPSTASH_REDIS_REST_TOKEN") or os.getenv("KV_REST_API_TOKEN", "")
        self.TURSO_DATABASE_URL: str = os.getenv("TURSO_DATABASE_URL", "")
        self.TURSO_AUTH_TOKEN: str = os.getenv("TURSO_AUTH_TOKEN", "")
        
        # Hard Budget, Concurrency, Duration & Outbound Lock Guardrails
        self.MAX_CONCURRENT_CALLS: int = int(os.getenv("MAX_CONCURRENT_CALLS", "1"))
        self.MAX_CALL_DURATION_SECONDS: int = int(os.getenv("MAX_CALL_DURATION_SECONDS", "1200"))  # 20 minutes, webhook-level guard only
        self.MONTHLY_BUDGET_LIMIT_USD: float = float(os.getenv("MONTHLY_BUDGET_LIMIT_USD", "5.00"))
        self.TTS_CLIP_TTL_SECONDS: int = int(os.getenv("TTS_CLIP_TTL_SECONDS", "120"))  # Short-lived 120s TTL
        self.HTTP_UPSTREAM_TIMEOUT_SECONDS: float = float(os.getenv("HTTP_UPSTREAM_TIMEOUT_SECONDS", "5.5"))
        
        # Outbound calling is completely disabled
        self.OUTBOUND_CALLING_ENABLED: bool = False
        
        default_db = "/tmp/voice_agents.db" if os.getenv("VERCEL") else "voice_agents.db"
        self.DB_PATH: str = os.getenv("DB_PATH", default_db)

    def get_webhook_signing_key(self) -> str:
        """Returns the configured SignalWire Signing Key (or API Token fallback)."""
        return self.SIGNALWIRE_SIGNING_KEY or self.SIGNALWIRE_API_TOKEN

    def durable_storage_backend(self) -> str:
        if self.UPSTASH_REDIS_REST_URL and self.UPSTASH_REDIS_REST_TOKEN:
            return "upstash_redis"
        if self.TURSO_DATABASE_URL and self.TURSO_AUTH_TOKEN:
            return "turso_libsql"
        return "local_sqlite"

settings = AppSettings()
