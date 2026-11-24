"""Offline checks for durable pause and cost status."""
import os
from unittest.mock import patch
from fastapi.testclient import TestClient

os.environ["VERCEL"] = "1"
os.environ["APEX_ADMIN_TOKEN"] = "test-admin"
os.environ["APEX_OPERATIONS_TOKEN"] = "test-operations-token-32-characters"
from app import app, db, settings, telephony

settings.UPSTASH_REDIS_REST_URL = "https://mock.invalid"
settings.UPSTASH_REDIS_REST_TOKEN = "test"
client = TestClient(app)
headers = {"Authorization": "Bearer " + os.environ["APEX_OPERATIONS_TOKEN"]}
state = {"apex:active_call_lock": "test-call", "apex:operations:scheduler_at": "1"}

def redis(command):
    op = command[0]
    if op == "MGET":
        return [state.get(key) for key in command[1:]]
    if op == "EXISTS":
        return int(command[1] in state)
    if op == "EVAL" and command[2] == "2":
        state[command[3]] = "1"
        return state.get(command[4])
    if op == "EVAL" and command[2] == "7":
        assert command[8] == db.CALL_PAUSE_KEY
        assert "KEYS[6]" in command[1] and "KEYS[7]" in command[1] and command[8] in state
        return 6
    raise AssertionError(op)

with patch.object(db, "_upstash_cmd", side_effect=redis):
    assert client.get("/api/operations").status_code == 401
    assert client.post("/api/operations/pause", headers={"Authorization": "Bearer test-admin"}).status_code == 401
    status = client.get("/api/operations", headers=headers)
    assert status.json() == {"paused": False, "estimatedSpendUsd": 0, "budgetUsd": settings.MONTHLY_BUDGET_LIMIT_USD,
                             "schedulerRecentlySeen": True, "carrierBillingCapVerified": None}
    with patch.object(telephony, "terminate_signalwire_call", return_value=False) as carrier:
        response = client.post("/api/operations/pause", headers=headers)
        assert response.json() == {"paused": True, "carrierTermination": "unconfirmed"}
        carrier.assert_called_once_with("test-call")
    assert client.get("/api/operations", headers=headers).json()["paused"]
    assert db.try_acquire_call_slot({"id": "other-test-call"}) == (False, "Call handling is paused", "paused")
    assert client.get("/api/tts/clip/test.mp3").status_code == 503

with patch.object(db, "_upstash_cmd", side_effect=RuntimeError):
    assert client.get("/api/operations", headers=headers).status_code == 503
    assert client.post("/api/operations/pause", headers=headers).status_code == 503

print("PASS: dedicated authentication, persisted pause, atomic admission, audio gate and Redis failure")
