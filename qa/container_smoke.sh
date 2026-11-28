#!/usr/bin/env bash
set -euo pipefail

platform=${1:-linux/arm64}
image="apexvoice-qa:${platform##*/}"
docker build --platform "$platform" -t "$image" .
cid=$(docker run -d --platform "$platform" --network none \
  -e APEX_ENVIRONMENT=staging -e APEX_HOSTED=1 -e RECEPTIONIST_ENABLED=false "$image")
trap 'docker rm -f "$cid" >/dev/null' EXIT

docker exec -i "$cid" python - "${platform##*/}" <<'PY'
import json
import os
from pathlib import Path
import platform
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

expected = {"arm64": "aarch64", "amd64": "x86_64"}[sys.argv[1]]
assert platform.machine() == expected, platform.machine()
assert os.getuid() == 10001
assert not Path("/app/.git").exists()
assert not Path("/app/.env").exists()
assert not Path("/app/.env.example").exists()
assert os.access("/data", os.W_OK)
for _ in range(30):
    try:
        with urlopen("http://127.0.0.1:8000/api/health", timeout=2) as response:
            health = json.load(response)
        break
    except (URLError, TimeoutError):
        time.sleep(1)
else:
    raise SystemExit("Container health endpoint never became reachable")
assert health["staging"] is True
assert health["telephony_provider"] == "mock"
assert health["inbound_live_calls_possible"] is False
assert health["monthly_budget_limit_usd"] == 0
print(f"PASS: {expected} starts as non-root in offline staging")
PY
