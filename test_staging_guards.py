"""Staging cannot admit calls, dial a carrier, or raise its budget from the environment."""
import os
import urllib.parse
from unittest.mock import patch

os.environ.pop("VERCEL", None)
from fastapi.testclient import TestClient
from app import app, db, settings, telephony
from config import AppSettings

client = TestClient(app)


def fresh_staging_settings():
    with patch.dict(os.environ, {
        "APEX_ENVIRONMENT": "staging",
        "MONTHLY_BUDGET_LIMIT_USD": "500",
        "APEX_TELEPHONY_PROVIDER": "signalwire",
        "VERCEL": "",
        "OUTBOUND_NUMBER_ALLOWLIST": "+15195550100",
    }, clear=False):
        fresh = AppSettings()
    assert fresh.STAGING is True
    assert fresh.MONTHLY_BUDGET_LIMIT_USD == 0.0
    assert fresh.TELEPHONY_PROVIDER == "mock"
    assert fresh.OUTBOUND_CALLING_ENABLED is False
    assert fresh.inbound_live_calls_possible() is False
    assert fresh.use_carrier_speech() is True


def run():
    fresh_staging_settings()
    settings.STAGING = True
    settings.APEX_ENVIRONMENT = "staging"
    settings.TELEPHONY_PROVIDER = "mock"
    settings.MONTHLY_BUDGET_LIMIT_USD = 0.0
    settings.RECEPTIONIST_ENABLED = True
    settings.ENFORCE_WEBHOOK_SIGNATURE = True
    settings.SIGNALWIRE_SIGNING_KEY = "staging-signing-key"
    settings.STAGING_WEBHOOK_RATE_LIMIT_PER_MINUTE = 2
    settings.UPSTASH_REDIS_REST_URL = ""
    settings.UPSTASH_REDIS_REST_TOKEN = ""
    settings.OUTBOUND_CALLING_ENABLED = False
    db._webhook_times.clear()

    fields = {"CallSid": "CA-staging-0001", "From": "+15195550101", "To": settings.SIGNALWIRE_PHONE_NUMBER}
    body = urllib.parse.urlencode(fields)
    url = "http://testserver/webhooks/signalwire/voice"
    signature = telephony.compute_signalwire_laml_signature(settings.SIGNALWIRE_SIGNING_KEY, url, fields)
    headers = {"Content-Type": "application/x-www-form-urlencoded", "X-SignalWire-Signature": signature}

    with patch.object(db, "try_acquire_call_slot") as acquire, patch("urllib.request.urlopen") as opened:
        for _ in range(2):
            response = client.post("/webhooks/signalwire/voice", content=body, headers=headers)
            assert response.status_code == 200, response.text
            assert "does not accept live calls" in response.text.lower()
        limited = client.post("/webhooks/signalwire/voice", content=body, headers=headers)
        assert "rate limited" in limited.text.lower()
        acquire.assert_not_called()
        opened.assert_not_called()
        assert telephony.terminate_signalwire_call("CA-staging-0001") is False
        opened.assert_not_called()

    blocked = db.try_acquire_call_slot({"id": "CA-staging-0001", "status": "in-progress"})
    assert blocked[0] is False
    assert "budget" in blocked[1].lower() or "staging" in blocked[1].lower()

    denied = client.post(
        "/api/calls/dispatch",
        headers={"Authorization": "Bearer staging-admin"},
        json={"assistant_id": "tpl_hm_receptionist", "phone_number": "+15195550100", "provider": "simulator"},
    )
    os.environ["APEX_ADMIN_TOKEN"] = "staging-admin"
    denied = client.post(
        "/api/calls/dispatch",
        headers={"Authorization": "Bearer staging-admin"},
        json={"assistant_id": "tpl_hm_receptionist", "phone_number": "+15195550100", "provider": "simulator"},
    )
    assert denied.status_code == 403, denied.text
    print("PASS: staging budget, mock carrier, rate limit and outbound refusal")


if __name__ == "__main__":
    run()
