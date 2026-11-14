"""ApexVoice lifecycle regressions using an isolated real Redis process."""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

os.environ["VERCEL"] = "1"
os.environ["CRON_SECRET"] = "test-only-scheduler-secret"
os.environ["APEX_MAX_CALL_RESERVE_USD"] = "3.00"
from app import app, db, settings, telephony

settings.UPSTASH_REDIS_REST_URL = "https://mock.invalid"
settings.UPSTASH_REDIS_REST_TOKEN = "test"
settings.SIGNALWIRE_SIGNING_KEY = "test-signing-key"
client = TestClient(app)
maintenance_url = "/api/maintenance/enforce-call-duration"
scheduler_headers = {"Authorization": "Bearer test-only-scheduler-secret"}
monthly_key = datetime.now(timezone.utc).strftime("apex:spend:%Y-%m")
first = "call-test-0001"
second = "call-test-0002"


def signed_post(endpoint, **fields):
    path = "/webhooks/signalwire/" + endpoint
    signature = telephony.compute_signalwire_laml_signature(
        settings.SIGNALWIRE_SIGNING_KEY, "http://testserver" + path, fields
    )
    return client.post(path, content=urllib.parse.urlencode(fields), headers={
        "X-SignalWire-Signature": signature, "Content-Type": "application/x-www-form-urlencoded"
    })


def check_lifecycle(command):
    def admit(call_id, age=0):
        return db.try_acquire_call_slot({
            "id": call_id, "status": "in-progress",
            "started_at": (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat(),
        })

    with patch.object(db, "_upstash_cmd", side_effect=command):
        assert admit(first)[1] == "Call deadline scheduler unavailable"
        with patch.dict(os.environ, {"APEX_MAX_CALL_RESERVE_USD": "nan"}):
            assert admit(first)[1] == "Invalid call budget reservation"
        no_call = client.post(maintenance_url, headers=scheduler_headers)
        assert no_call.json() == {"checked": True, "active": False, "termination_requested": False}
        assert 0 < command(["TTL", db.SCHEDULER_KEY]) <= 180

        assert admit(first) == (True, None, "created")
        assert command(["TTL", db.ACTIVE_CALL_KEY]) == -1
        assert admit(first) == (True, None, "replay")
        assert float(command(["GET", monthly_key])) == 3

        ending = signed_post("gather", CallSid=first)
        assert ending.status_code == 200 and "<Hangup" in ending.text
        assert db.get_call(first)["status"] == "ending"
        assert admit(first)[2] == "duplicate"
        assert not admit(second)[0]
        assert command(["GET", db.ACTIVE_CALL_KEY]) == first
        assert float(command(["GET", monthly_key])) == 3
        assert signed_post("status", CallSid=first).status_code == 200
        assert signed_post("status", CallSid=first, CallStatus="completed").status_code == 400
        assert signed_post("status", CallSid=first, CallStatus="completed", CallDuration="60").json()["budget_reconciled"]
        assert command(["GET", db.ACTIVE_CALL_KEY]) is None
        db.mark_call_ending(first)
        assert db.get_call(first)["status"] == "completed"
        spend = float(command(["GET", monthly_key]))
        assert abs(spend - 0.0268) < 1e-8
        assert signed_post("status", CallSid=first, CallStatus="completed", CallDuration="60").status_code == 200
        assert float(command(["GET", monthly_key])) == spend
        assert signed_post("status", CallSid="declined-call", CallStatus="busy").json()["tracked"] is False
        command(["SET", monthly_key, "unusable"])
        assert not admit(second)[0]
        assert command(["GET", db.ACTIVE_CALL_KEY]) is None
        command(["SET", monthly_key, str(spend)])

        assert admit(second, settings.MAX_CALL_DURATION_SECONDS + 90)[0]
        command(["EXPIRE", db.ACTIVE_CALL_KEY, "15"])
        command(["DEL", db.SCHEDULER_KEY])
        with patch.object(telephony, "terminate_signalwire_call", return_value=False) as terminate:
            assert client.post(maintenance_url, headers=scheduler_headers).status_code == 502
            terminate.assert_called_once_with(second)
        assert command(["TTL", db.ACTIVE_CALL_KEY]) == -1
        assert command(["GET", db.SCHEDULER_KEY]) is None
        with patch.object(telephony, "terminate_signalwire_call", return_value=True) as terminate:
            assert client.post(maintenance_url, headers=scheduler_headers).json()["termination_requested"] is True
            terminate.assert_called_once_with(second)
        assert command(["GET", db.ACTIVE_CALL_KEY]) == second

        def failed_settlement(args):
            if args[0] == "EVAL" and "INCRBYFLOAT" in args[1]:
                raise RuntimeError("Fixture store failure")
            return command(args)

        with patch.object(db, "_upstash_cmd", side_effect=failed_settlement):
            assert signed_post("status", CallSid=second, CallStatus="completed", CallDuration="75").status_code == 503
        assert command(["GET", db.ACTIVE_CALL_KEY]) == second
        assert signed_post("status", CallSid=second, CallStatus="completed", CallDuration="75").status_code == 200
        assert command(["GET", db.ACTIVE_CALL_KEY]) is None


def main():
    server_binary = shutil.which("redis-server")
    cli_binary = shutil.which("redis-cli")
    if not server_binary or not cli_binary:
        raise SystemExit("Install redis-server and redis-cli to run the call lifecycle integration test.")
    with tempfile.TemporaryDirectory() as state:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = str(listener.getsockname()[1])
        server = subprocess.Popen([
            server_binary, "--bind", "127.0.0.1", "--port", port, "--dir", state,
            "--save", "", "--appendonly", "no"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            def command(args):
                execution = subprocess.run([cli_binary, "-p", port, "--json", *args],
                                           check=True, capture_output=True, text=True, timeout=3)
                return json.loads(execution.stdout)

            for _ in range(50):
                try:
                    if command(["PING"]) == "PONG":
                        break
                except subprocess.CalledProcessError:
                    time.sleep(0.05)
            else:
                raise RuntimeError("Isolated Redis failed to start")
            check_lifecycle(command)
        finally:
            server.terminate()
            server.wait(timeout=5)
    print("PASS: Redis admission, durable slot, scheduler recovery and signed settlement")


if __name__ == "__main__":
    main()
