"""Redis call-slot checks: concurrency, lease expiry, and one-time settlement.

Uses a loopback redis-server. Carrier termination is stubbed. No paid provider calls.
"""
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

os.environ["VERCEL"] = "1"
os.environ["CRON_SECRET"] = "redis-lock-scheduler-secret"
os.environ["APEX_MAX_CALL_RESERVE_USD"] = "3.00"
from fastapi.testclient import TestClient
from app import app, db, settings, telephony

settings.UPSTASH_REDIS_REST_URL = "https://mock.invalid"
settings.UPSTASH_REDIS_REST_TOKEN = "test"
settings.SIGNALWIRE_SIGNING_KEY = "redis-lock-signing-key"
settings.ENFORCE_WEBHOOK_SIGNATURE = True
settings.RECEPTIONIST_ENABLED = True
settings.STAGING = False
settings.MONTHLY_BUDGET_LIMIT_USD = 5.0
settings.CRON_SECRET = "redis-lock-scheduler-secret"
settings.TELEPHONY_PROVIDER = "signalwire"
client = TestClient(app)
month_key = datetime.now(timezone.utc).strftime("apex:spend:%Y-%m")


def signed(endpoint, **fields):
    path = "/webhooks/signalwire/" + endpoint
    signature = telephony.compute_signalwire_laml_signature(
        settings.SIGNALWIRE_SIGNING_KEY, "http://testserver" + path, fields
    )
    return client.post(path, content=urllib.parse.urlencode(fields), headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "X-SignalWire-Signature": signature,
    })


def admit(call_id, age=0):
    return db.try_acquire_call_slot({
        "id": call_id,
        "status": "in-progress",
        "assistant_id": "tpl_hm_receptionist",
        "phone_number": "+15195550101",
        "direction": "inbound",
        "provider": "signalwire",
        "started_at": (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat(),
    })


def scenario(command):
    database = tempfile.NamedTemporaryFile(suffix=".db")
    db.db_path = database.name
    db._init_db()
    command(["FLUSHDB"])
    os.environ["VERCEL"] = "1"
    command(["SET", db.SCHEDULER_KEY, "1", "EX", "180"])
    first, second = "call-lock-0001", "call-lock-0002"
    assert admit(first) == (True, None, "created")
    assert command(["TTL", db.ACTIVE_CALL_KEY]) == -1
    rejected = admit(second)
    assert rejected[0] is False
    assert command(["GET", db.ACTIVE_CALL_KEY]) == first
    reserved = float(command(["GET", month_key]))
    assert rejected[0] is False and float(command(["GET", month_key])) == reserved

    command(["DEL", db.ACTIVE_CALL_KEY])
    replay = admit(first)
    assert replay == (True, None, "replay")
    assert float(command(["GET", month_key])) == reserved

    settled = signed("status", CallSid=first, CallStatus="completed", CallDuration="60")
    assert settled.status_code == 200, settled.text
    assert settled.json()["budget_reconciled"] is True
    spent = float(command(["GET", month_key]))
    assert spent < reserved
    again = signed("status", CallSid=first, CallStatus="completed", CallDuration="60")
    assert again.status_code == 200, again.text
    assert float(command(["GET", month_key])) == spent
    assert command(["GET", db.ACTIVE_CALL_KEY]) is None

    command(["DEL", db.SCHEDULER_KEY])
    assert admit(second)[1] == "Call deadline scheduler unavailable"
    command(["SET", db.SCHEDULER_KEY, "1", "EX", "180"])
    overdue = "call-lock-0003"
    assert admit(overdue, age=settings.MAX_CALL_DURATION_SECONDS + 5)[0]
    turn = signed("gather", CallSid=overdue, SpeechResult="")
    assert turn.status_code == 200 and "call time limit" in turn.text.lower()
    assert db.get_call(overdue)["status"] == "ending"
    with patch.object(telephony, "terminate_signalwire_call", return_value=True) as terminate:
        watched = client.post(
            "/api/maintenance/enforce-call-duration",
            headers={"Authorization": "Bearer redis-lock-scheduler-secret"},
        )
        assert watched.status_code == 200, watched.text
        assert watched.json()["termination_requested"] is True
        terminate.assert_called_once_with(overdue)
    assert command(["TTL", db.SCHEDULER_KEY]) > 0

    command(["FLUSHDB"])
    os.environ.pop("VERCEL", None)
    leased = "call-lock-lease"
    assert admit(leased)[0]
    ttl = command(["TTL", db.ACTIVE_CALL_KEY])
    assert 0 < ttl <= settings.MAX_CALL_DURATION_SECONDS + 15
    raw_spend = command(["GET", month_key])
    before = float(raw_spend or 0)
    command(["EXPIRE", db.ACTIVE_CALL_KEY, "1"])
    time.sleep(1.2)
    assert command(["GET", db.ACTIVE_CALL_KEY]) is None
    assert admit(leased)[2] == "replay"
    assert float(command(["GET", month_key])) == before
    database.close()


def main():
    server_binary = shutil.which("redis-server")
    cli_binary = shutil.which("redis-cli")
    if not server_binary or not cli_binary:
        raise SystemExit("Install redis-server and redis-cli to run the Redis lock test.")
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

            def upstash(args):
                return command(args)

            with patch.object(db, "_upstash_cmd", side_effect=upstash):
                scenario(command)
        finally:
            server.terminate()
            server.wait(timeout=5)
    print("PASS: Redis concurrency, lock expiry, scheduler gate and one-time settlement")


if __name__ == "__main__":
    main()
