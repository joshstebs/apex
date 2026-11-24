"""Operations dashboard is admin-gated and does not echo secrets."""
import os
import tempfile

os.environ.pop("VERCEL", None)
os.environ["APEX_ADMIN_TOKEN"] = "dashboard-admin-token"
from fastapi.testclient import TestClient
from app import app, db, seed_default_assistants, settings

settings.STAGING = False
settings.APEX_ENVIRONMENT = "local"
settings.TELEPHONY_PROVIDER = "signalwire"
settings.UPSTASH_REDIS_REST_URL = ""
settings.UPSTASH_REDIS_REST_TOKEN = ""
settings.MONTHLY_BUDGET_LIMIT_USD = 5.0
settings.RECEPTIONIST_ENABLED = False
client = TestClient(app)
headers = {"Authorization": "Bearer dashboard-admin-token"}


def run():
    database = tempfile.NamedTemporaryFile(suffix=".db")
    db.db_path = database.name
    db._init_db()
    seed_default_assistants()
    db.create_call({
        "id": "call_dashboard_1",
        "assistant_id": "tpl_hm_receptionist",
        "phone_number": "+15195550199",
        "direction": "inbound",
        "provider": "signalwire",
        "status": "completed",
        "goal": "Take a message",
        "dynamic_vars_applied": {"caller_number": "+15195550199"},
    })
    db.update_call("call_dashboard_1", {
        "status": "completed",
        "outcome_status": "recorded_for_followup",
        "extracted_data": {"save_receptionist_message": {
            "caller_name": "Sam",
            "callback_number": "+15195550199",
            "reason": "Dock question",
            "preferred_contact_time": "morning",
            "api_key": "must-not-leak",
        }},
    })
    db.note_ops_error("tts_synthesis_failed")

    page = client.get("/")
    operations = client.get("/operations")
    assert page.status_code == 200 and operations.text == page.text
    for label in ("Budget", "Live call", "Recent calls", "Messages", "Errors"):
        assert label in page.text
    assert "dashboard-admin-token" not in page.text
    assert "must-not-leak" not in page.text
    assert "cfg_elevenlabs_key" not in page.text

    assert client.get("/api/dashboard").status_code == 401
    payload = client.get("/api/dashboard", headers=headers)
    assert payload.status_code == 200, payload.text
    assert payload.headers["cache-control"] == "private, no-store"
    body = payload.json()
    assert body["budget"]["cap_usd"] == 5.0
    assert body["outbound_calling_enabled"] is False
    assert body["live_call"] is None
    assert any(call["id"] == "call_dashboard_1" for call in body["recent_calls"])
    message = body["messages"][0]["message"]
    assert message["reason"] == "Dock question"
    assert "api_key" not in message
    assert any(error["code"] == "tts_synthesis_failed" for error in body["errors"])
    rendered = payload.text
    for secret in ("dashboard-admin-token", "must-not-leak", "SIGNALWIRE_API_TOKEN", "ELEVENLABS_API_KEY"):
        assert secret not in rendered
    database.close()
    print("PASS: admin dashboard shows calls, messages, errors and budget without secrets")


if __name__ == "__main__":
    run()
