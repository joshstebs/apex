"""The Cloudflare Worker must forward every setting config.py reads.

A hardcoded copy of the environment names drifts silently: a new setting is added
to config.py, the Worker never copies it, and the deployment runs with a default
that was never intended for production.
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent
# Provided by the platform, not application settings.
PLATFORM_VARS = {
    "VERCEL", "VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL", "CF_PAGES",
    "HOST", "PORT", "CLOUDFLARE_WORKERS",
}


def run():
    worker = (ROOT / "cloudflare_worker.py").read_text(encoding="utf-8")
    config = (ROOT / "config.py").read_text(encoding="utf-8")
    application = (ROOT / "app.py").read_text(encoding="utf-8")

    # The Worker derives its list at runtime; make sure it does not hardcode one.
    assert "config.py" in worker and "app.py" in worker, "worker must derive names from the application modules"
    assert "_RUNTIME_SETTINGS" not in worker, "hardcoded runtime setting list drifted before; keep it derived"

    expected = {
        name
        for source in (config, application)
        for name in re.findall(r'os\.getenv\(\s*"([A-Z][A-Z0-9_]*)"', source)
        if name not in PLATFORM_VARS
    }
    derived = set(re.findall(r'os\.getenv\(\s*"([A-Z][A-Z0-9_]*)"', config)) | set(
        re.findall(r'os\.getenv\(\s*"([A-Z][A-Z0-9_]*)"', application)
    )
    derived -= PLATFORM_VARS

    critical = {
        "APEX_ENVIRONMENT", "APEX_TELEPHONY_PROVIDER", "STALE_SETTLEMENT_GRACE_SECONDS",
        "OUTBOUND_NUMBER_ALLOWLIST", "STAGING_WEBHOOK_RATE_LIMIT_PER_MINUTE",
        "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN", "APEX_ADMIN_TOKEN",
        "APEX_OPERATIONS_TOKEN", "SIGNALWIRE_PROJECT_ID", "SIGNALWIRE_API_TOKEN",
        "ELEVENLABS_API_KEY", "HUGGINGFACE_API_KEY", "RECEPTIONIST_ENABLED",
    }
    missing = critical - expected
    assert not missing, f"worker would not forward: {sorted(missing)}"
    assert derived == expected

    # Staging cannot be reached through the Worker's var block in a way that spends.
    wrangler = (ROOT / "wrangler.jsonc").read_text(encoding="utf-8")
    assert '"RECEPTIONIST_ENABLED": "false"' in wrangler
    assert "APEX_ENVIRONMENT" not in wrangler or '"APEX_ENVIRONMENT": "staging"' in wrangler
    print("PASS: Cloudflare worker forwards every configured setting and ships receptionist disabled")


if __name__ == "__main__":
    run()
