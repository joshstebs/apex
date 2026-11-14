"""Missing carrier callbacks are settled once, then a late callback only adjusts the difference."""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

os.environ["VERCEL"] = "1"
os.environ["CRON_SECRET"] = "stale-scheduler-secret"
os.environ["APEX_MAX_CALL_RESERVE_USD"] = "3.00"
from fastapi.testclient import TestClient
from app import app, db, settings, telephony
from voice_engine import VoiceEngine

settings.UPSTASH_REDIS_REST_URL = "https://mock.invalid"
settings.UPSTASH_REDIS_REST_TOKEN = "test"
settings.SIGNALWIRE_SIGNING_KEY = "stale-signing-key"
settings.ENFORCE_WEBHOOK_SIGNATURE = True
settings.RECEPTIONIST_ENABLED = True
settings.STAGING = False
settings.MONTHLY_BUDGET_LIMIT_USD = 5.0
settings.CRON_SECRET = "stale-scheduler-secret"
settings.TELEPHONY_PROVIDER = "signalwire"
settings.MAX_CALL_DURATION_SECONDS = 120
settings.STALE_SETTLEMENT_GRACE_SECONDS = 60
client = TestClient(app)
month_key = datetime.now(timezone.utc).strftime("apex:spend:%Y-%m")
headers = {"Authorization": "Bearer stale-scheduler-secret"}


def signed(endpoint, **fields):
    path = "/webhooks/signalwire/" + endpoint
    signature = telephony.compute_signalwire_laml_signature(
        settings.SIGNALWIRE_SIGNING_KEY, "http://testserver" + path, fields
    )
    return client.post(path, content=urllib.parse.urlencode(fields), headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "X-SignalWire-Signature": signature,
    })


def admit(call_id, age):
    return db.try_acquire_call_slot({
        "id": call_id, "status": "in-progress", "assistant_id": "tpl_hm_receptionist",
        "phone_number": "+15195550101", "direction": "inbound", "provider": "signalwire",
        "started_at": (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat(),
    })


def spend(command):
    raw = command(["GET", month_key])
    return float(raw or 0)


def scenario(command):
    command(["FLUSHDB"])
    os.environ["VERCEL"] = "1"
    command(["SET", db.SCHEDULER_KEY, "1", "EX", "180"])
    young = "call-stale-young01"
    assert admit(young, settings.MAX_CALL_DURATION_SECONDS + 5)[0]
    with patch.object(telephony, "terminate_signalwire_call", return_value=True):
        waiting = client.post("/api/maintenance/enforce-call-duration", headers=headers)
    assert waiting.status_code == 200, waiting.text
    assert waiting.json()["stale_settled"] == 0
    assert command(["GET", db.ACTIVE_CALL_KEY]) == young
    reserved = spend(command)

    command(["FLUSHDB"])
    command(["SET", db.SCHEDULER_KEY, "1", "EX", "180"])
    stale_id = "call-stale-000001"
    age = settings.MAX_CALL_DURATION_SECONDS + settings.STALE_SETTLEMENT_GRACE_SECONDS + 5
    assert admit(stale_id, age)[0]
    with patch.object(telephony, "terminate_signalwire_call", return_value=False):
        swept = client.post("/api/maintenance/enforce-call-duration", headers=headers)
    assert swept.status_code == 200, swept.text
    assert swept.json()["stale_settled"] == 1
    assert db.get_call(stale_id)["status"] == "stale_unsettled"
    assert command(["GET", db.ACTIVE_CALL_KEY]) is None
    estimate = VoiceEngine.calculate_call_cost(settings.MAX_CALL_DURATION_SECONDS)["cost_total"]
    assert abs(spend(command) - estimate) < 1e-4
    again = client.post("/api/maintenance/enforce-call-duration", headers=headers)
    assert again.json()["stale_settled"] == 0
    assert abs(spend(command) - estimate) < 1e-4

    late = signed("status", CallSid=stale_id, CallStatus="completed", CallDuration="30")
    assert late.status_code == 200, late.text
    assert late.json()["settlement"] == "adjusted"
    carrier = VoiceEngine.calculate_call_cost(30)["cost_total"]
    assert abs(spend(command) - carrier) < 1e-4
    assert db.get_call(stale_id)["status"] == "completed"
    duplicate = signed("status", CallSid=stale_id, CallStatus="completed", CallDuration="90")
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["settlement"] == "already_released"
    assert abs(spend(command) - carrier) < 1e-4
    assert reserved >= estimate

    command(["FLUSHDB"])
    command(["SET", db.SCHEDULER_KEY, "1", "EX", "180"])
    raced = "call-stale-race001"
    assert admit(raced, age)[0]
    barrier = threading.Barrier(2)
    errors = []

    def sweep():
        try:
            barrier.wait(timeout=5)
            with patch.object(telephony, "terminate_signalwire_call", return_value=False):
                response = client.post("/api/maintenance/enforce-call-duration", headers=headers)
            if response.status_code != 200:
                errors.append(response.text)
        except Exception as exc:
            errors.append(repr(exc))

    def callback():
        try:
            barrier.wait(timeout=5)
            response = signed("status", CallSid=raced, CallStatus="completed", CallDuration="45")
            if response.status_code != 200:
                errors.append(response.text)
        except Exception as exc:
            errors.append(repr(exc))

    threads = [threading.Thread(target=sweep), threading.Thread(target=callback)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not errors, errors
    expected = VoiceEngine.calculate_call_cost(45)["cost_total"]
    assert abs(spend(command) - expected) < 1e-4, spend(command)
    assert command(["GET", "apex:settle:" + raced]) == "carrier"


def main():
    server_binary = shutil.which("redis-server")
    cli_binary = shutil.which("redis-cli")
    if not server_binary or not cli_binary:
        raise SystemExit("Install redis-server and redis-cli to run stale settlement tests.")
    with tempfile.TemporaryDirectory() as state:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = str(listener.getsockname()[1])
        server = subprocess.Popen(
            [server_binary, "--bind", "127.0.0.1", "--port", port, "--dir", state, "--save", "", "--appendonly", "no"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            def command(args):
                execution = subprocess.run(
                    [cli_binary, "-p", port, "--json", *args],
                    check=True, capture_output=True, text=True, timeout=3,
                )
                if not execution.stdout.strip():
                    return None
                return json.loads(execution.stdout)

            for _ in range(50):
                try:
                    if command(["PING"]) == "PONG":
                        break
                except subprocess.CalledProcessError:
                    time.sleep(0.05)
            else:
                raise RuntimeError("Isolated Redis failed to start")
            database = tempfile.NamedTemporaryFile(suffix=".db")
            db.db_path = database.name
            db._init_db()
            with patch.object(db, "_upstash_cmd", side_effect=command):
                scenario(command)
            database.close()
        finally:
            server.terminate()
            server.wait(timeout=5)
    print("PASS: stale sweep, late adjustment, duplicate callback, and concurrent settlement")


if __name__ == "__main__":
    main()
