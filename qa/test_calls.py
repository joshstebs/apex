from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
import time
from unittest.mock import patch
from xml.etree import ElementTree

import pytest

from qa.call_harness import (
    ADMIN, APPOINTMENT_REQUEST_REPLY, CALLER, DID, MOCK_MP3, OPERATIONS,
    SCHEDULER, SIGNING_KEY, simulate,
)

SID = "CA-qa-synthetic-0001"
OTHER_SID = "CA-qa-synthetic-0002"
OPERATIONS_ROUTE = "/api/operations"
MAINTENANCE_ROUTE = "/api/maintenance/enforce-call-duration"


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def xml(response):
    assert response.status_code == 200, response.text
    return ElementTree.fromstring(response.text)


@pytest.fixture
def call(tmp_path):
    with simulate(tmp_path) as harness:
        yield harness


@pytest.fixture
def redis_command(tmp_path):
    socket_path = Path(tmp_path) / "redis.sock"
    cli = shutil.which("redis-cli")
    assert cli, "Install redis-cli to run Redis lifecycle tests"
    redis = subprocess.Popen(
        ["redis-server", "--port", "0", "--unixsocket", str(socket_path), "--unixsocketperm", "700",
         "--save", "", "--appendonly", "no", "--dir", str(tmp_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def command(args):
        result = subprocess.run(
            [cli, "-s", str(socket_path), "--json", *args],
            check=True, capture_output=True, text=True, timeout=3,
        )
        if result.stdout.startswith("error:"):
            raise RuntimeError("Local QA Redis rejected a command")
        return json.loads(result.stdout)

    try:
        for _ in range(60):
            try:
                if command(["PING"]) == "PONG":
                    break
            except subprocess.CalledProcessError:
                if redis.poll() is not None:
                    pytest.fail("Local Redis exited before responding")
            time.sleep(0.05)
        else:
            pytest.fail("Local Redis did not respond")
        yield command
    finally:
        redis.terminate()
        try:
            redis.wait(timeout=5)
        except subprocess.TimeoutExpired:
            redis.kill()
            redis.wait(timeout=5)


ADMIN_ROUTES = [
    ("GET", "/api/assistants"),
    ("GET", "/api/assistants/qa"),
    ("POST", "/api/assistants"),
    ("GET", "/api/templates"),
    ("GET", "/api/calls"),
    ("GET", f"/api/calls/{SID}"),
    ("POST", "/api/calls/dispatch"),
    ("POST", f"/api/calls/{SID}/approve"),
    ("POST", f"/api/calls/{SID}/terminate"),
    ("GET", "/api/receptionist/messages"),
    ("POST", "/api/staging/exercise"),
    ("POST", "/api/simulate/turn"),
    ("GET", "/api/dashboard"),
    ("GET", "/api/voices"),
    ("GET", "/api/cost/calculate"),
]


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_admin_routes_reject_missing_and_wrong_roles(call, method, path):
    call.module.settings.STAGING = True
    for headers in ({}, bearer("synthetic-wrong-role"), bearer(OPERATIONS), bearer(SCHEDULER)):
        response = call.client.request(method, path, headers=headers, json={} if method == "POST" else None)
        assert response.status_code == 401
    assert not call.actions


def test_authentication_matrix_and_sensitive_health_fields(call):
    for method, route in (("GET", OPERATIONS_ROUTE), ("POST", OPERATIONS_ROUTE + "/pause")):
        for headers in ({}, bearer(ADMIN), bearer(SCHEDULER)):
            assert call.client.request(method, route, headers=headers).status_code == 401
        assert call.client.request(method, route, headers=bearer(OPERATIONS)).status_code == 503
    for headers in ({}, bearer(ADMIN), bearer(OPERATIONS)):
        assert call.client.post(MAINTENANCE_ROUTE, headers=headers).status_code == 401
    assert call.client.post(MAINTENANCE_ROUTE, headers=bearer(SCHEDULER)).status_code == 503

    for endpoint in ("/api/health", "/api/settings"):
        response = call.client.get(endpoint)
        assert response.status_code == 200
        for secret in (ADMIN, OPERATIONS, SCHEDULER, SIGNING_KEY):
            assert secret not in response.text
    for endpoint in ("/api/dashboard", "/api/receptionist/messages"):
        response = call.client.get(endpoint, headers=bearer(ADMIN))
        assert response.status_code == 200
        assert "no-store" in response.headers["Cache-Control"]

    response = call.client.post("/api/calls/dispatch", headers=bearer(ADMIN), json={
        "assistant_id": "tpl_hm_receptionist", "phone_number": CALLER, "provider": "signalwire",
    })
    assert response.status_code == 403
    assert not call.actions


def test_unsigned_callbacks_are_rejected_before_side_effects(call):
    fields = {"CallSid": SID, "From": CALLER, "To": DID,
              "CallStatus": "completed", "CallDuration": "18"}
    for event in ("voice", "gather", "status"):
        assert call.callback(event, authenticated=False, **fields).status_code == 403
    assert call.module.db.get_call(SID) is None
    assert not call.actions


@pytest.mark.parametrize("speech", ["", "   "])
def test_silence_hangs_up_without_model_or_message(call, speech):
    assert xml(call.inbound(SID)).find("Gather") is not None
    assert xml(call.turn(SID, speech)).find("Hangup") is not None
    assert call.end(SID).status_code == 200
    assert call.module.db.list_receptionist_messages() == []
    assert call.actions == []


def test_partial_and_noisy_transcripts_remain_caller_data(call):
    assert xml(call.inbound(SID)).find("Gather") is not None
    inputs = ["I was hoping to ask about", "[background noise] hours, please."]
    for words in inputs:
        assert xml(call.turn(SID, words)).findtext("Gather/Say") == APPOINTMENT_REQUEST_REPLY
    assert call.model_requests[-1][-1] == {"role": "user", "content": inputs[-1]}
    assert {"role": "user", "content": inputs[0]} in call.model_requests[-1][1:-1]
    assert call.end(SID, status="failed").status_code == 200
    assert call.module.db.get_call(SID)["status"] == "failed"


@pytest.mark.parametrize("failure", ["timeout", "rate-limit", "malformed"])
def test_unavailable_model_cannot_claim_booking_or_delivery(call, failure):
    call.failures["llm"] = failure
    assert xml(call.inbound(SID)).find("Gather") is not None
    response = xml(call.turn(SID, "Can you book an appointment tomorrow and email the confirmation?"))
    assert "can't confirm any appointments" in response.findtext("Gather/Say")
    stored = call.module.db.get_call(SID)
    assert not stored.get("extracted_data")
    assert not call.module.db.list_receptionist_messages()
    assert call.actions == ["llm"]


def test_appointment_request_creates_no_confirmation_or_delivery(call):
    assert xml(call.inbound(SID)).find("Gather") is not None
    response = call.turn(SID, "I'd like a Tuesday appointment, please.")
    assert xml(response).findtext("Gather/Say") == APPOINTMENT_REQUEST_REPLY
    assert call.actions == ["llm"]
    assert not call.module.db.get_call(SID).get("extracted_data")


@pytest.mark.parametrize("failure", ["timeout", "rate-limit"])
def test_tts_failure_uses_carrier_speech(tmp_path, failure):
    with simulate(tmp_path, tts=True) as call:
        call.failures["tts"] = failure
        greeting = xml(call.inbound(SID))
        assert greeting.find("Gather/Play") is None
        assert greeting.findtext("Gather/Say")
        assert call.actions == ["tts"]


def test_audio_retry_reuses_synthesis(tmp_path):
    with simulate(tmp_path, tts=True) as call:
        greeting = call.inbound(SID)
        assert greeting.status_code == 200
        for _ in range(2):
            audio = call.audio(greeting.text)
            assert audio.status_code == 200
            assert audio.content == MOCK_MP3
            assert "no-store" in audio.headers["Cache-Control"]
        assert call.actions == ["tts"]


def test_redis_outage_refuses_admission(tmp_path):
    with simulate(tmp_path, hosted=True) as call:
        with patch.object(call.module.db, "_upstash_cmd", side_effect=RuntimeError("Synthetic Redis outage")):
            response = xml(call.inbound(SID))
            assert response.find("Hangup") is not None
            assert response.find("Gather") is None
        assert call.actions == []


def test_concurrent_calls_failed_hangup_and_late_callback(tmp_path, redis_command):
    with simulate(tmp_path, hosted=True) as call:
        db = call.module.db
        with patch.object(db, "_upstash_cmd", side_effect=redis_command):
            redis_command(["SET", db.SCHEDULER_KEY, "1", "EX", "180"])
            with ThreadPoolExecutor(max_workers=2) as executor:
                a, b = executor.map(call.inbound, (SID, OTHER_SID))
            assert sum(xml(response).find("Gather") is not None for response in (a, b)) == 1
            owner = redis_command(["GET", db.ACTIVE_CALL_KEY])
            assert owner in {SID, OTHER_SID}
            assert xml(call.inbound(owner)).find("Gather") is not None
            assert len(db.get_call_transcripts(owner)) == 1

            call.failures["carrier-hangup"] = "timeout"
            now = datetime.now(timezone.utc)
            cap = call.module.settings.MAX_CALL_DURATION_SECONDS
            grace = call.module.settings.STALE_SETTLEMENT_GRACE_SECONDS
            def set_fixture_age(seconds):
                key = f"apex:call:{owner}"
                state = json.loads(redis_command(["GET", key]))
                state["call"]["started_at"] = (now - timedelta(seconds=seconds)).isoformat()
                assert redis_command(["SET", key, json.dumps(state), "XX", "KEEPTTL"]) == "OK"

            set_fixture_age(cap + 5)
            response = call.client.post(MAINTENANCE_ROUTE, headers=bearer(SCHEDULER))
            assert response.status_code == 502
            assert redis_command(["GET", db.ACTIVE_CALL_KEY]) == owner
            assert db.get_call(owner)["status"] == "in-progress"

            set_fixture_age(cap + grace + 5)
            response = call.client.post(MAINTENANCE_ROUTE, headers=bearer(SCHEDULER))
            assert response.status_code == 200, response.text
            assert response.json()["stale_settled"] == 1
            assert redis_command(["GET", db.ACTIVE_CALL_KEY]) is None
            assert db.get_call(owner)["status"] == "stale_unsettled"

            month = now.strftime("apex:spend:%Y-%m")
            assert call.end(owner).json()["settlement"] == "adjusted"
            spend = float(redis_command(["GET", month]))
            assert call.end(owner).json()["settlement"] == "already_released"
            assert float(redis_command(["GET", month])) == spend
            assert db.get_call(owner)["duration_seconds"] == 18
            assert call.actions == ["carrier-hangup"]


def test_staging_limit_refuses_admission_even_when_operator_enables_it(call):
    call.module.settings.STAGING = True
    call.module.settings.STAGING_WEBHOOK_RATE_LIMIT_PER_MINUTE = 2
    for sid in (SID, OTHER_SID):
        assert "does not accept live calls" in xml(call.inbound(sid)).findtext("Say")
    assert "rate limited" in xml(call.inbound(SID)).findtext("Say").lower()
    assert call.module.db.get_call(SID) is None
    assert not call.actions


def test_emergency_and_handoff_in_offline_call_contract(call):
    assert xml(call.inbound(SID)).find("Gather") is not None
    scenarios = [
        ("I think the building is on fire.", "If anyone is in danger, call 911 now."),
        ("Can I speak to a person?", "I can take a message for the team to review."),
    ]
    for caller_words, safe_reply in scenarios:
        call.model_reply = safe_reply
        turn = xml(call.turn(SID, caller_words))
        assert turn.findtext("Gather/Say") == safe_reply
        assert turn.find(".//Dial") is None
    assert call.actions == ["llm", "llm"]
