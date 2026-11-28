"""Cloudflare Python Workers entrypoint for the ApexVoice FastAPI app.

The application reads its configuration from process environment variables at
import time, so Cloudflare bindings are copied into the environment first. The
list of names is parsed from config.py instead of being duplicated here: a
hardcoded copy silently drifts when a new setting is added, and the Worker would
then run with that setting missing.
"""
import os
import re
from pathlib import Path

from workers import asgi, env

# Runtime-provided names are not settings; they come from the platform.
_PLATFORM_VARS = {
    "VERCEL", "VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL", "CF_PAGES",
    "HOST", "PORT", "CLOUDFLARE_WORKERS",
}


def _configured_names() -> list:
    """Every environment name the application reads directly.

    config.py holds settings, but app.py reads the admin and operations tokens
    straight from the environment, so both files are scanned.
    """
    names = set()
    for module in ("config.py", "app.py"):
        source = Path(__file__).with_name(module).read_text(encoding="utf-8")
        names.update(re.findall(r'os\.getenv\(\s*"([A-Z][A-Z0-9_]*)"', source))
    return sorted(name for name in names if name not in _PLATFORM_VARS)


for _key in _configured_names():
    _value = getattr(env, _key, None)
    if _value is not None:
        os.environ[_key] = str(_value)

# Marks an ephemeral, serverless filesystem: call state requires a remote store.
os.environ["CLOUDFLARE_WORKERS"] = "1"

from app import app  # noqa: E402

Default = asgi.entrypoint(app)
