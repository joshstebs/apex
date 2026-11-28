"""Fail closed until each live-production requirement has reviewed evidence."""

import json
from pathlib import Path
from urllib.parse import urlsplit


REQUIREMENTS = {
    "credential_history": "Resolve all historical credential alerts and record rotation or fixture verification.",
    "webhook_controls": "Demonstrate freshness, gather idempotency and enforced ingress limits.",
    "model_boundaries": "Demonstrate deterministic confidentiality and action/receipt boundaries.",
    "emergency_handoff": "Verify emergency guidance and staffed handoff or explicit fallback.",
    "customer_data": "Verify retention/deletion, cache limits and log redaction with synthetic data.",
    "provider_readiness": "Verify carrier cutoff, callback compatibility, billing limits and alerts.",
    "oracle_soak": "Meet the native ARM64 memory, file descriptor and service latency budgets.",
}


def main():
    path = Path(__file__).with_name("production-evidence.json")
    evidence = json.loads(path.read_text())
    if set(evidence) != set(REQUIREMENTS):
        raise SystemExit("Production evidence must cover exactly the required checks")
    blocked = []
    for check, requirement in REQUIREMENTS.items():
        entry = evidence[check]
        link = urlsplit(entry.get("evidence", ""))
        if entry.get("status") != "verified" or link.scheme != "https" or not link.hostname:
            blocked.append(f"{check}: {requirement}")
    if blocked:
        raise SystemExit("Production promotion is blocked\n" + "\n".join(blocked))
    print("Every production readiness requirement has recorded evidence")


if __name__ == "__main__":
    main()
