"""A container must cut off an over-duration call without an external scheduler.

Admission on a container requires a scheduler heartbeat, so without an in-process
watchdog a deployment either refuses every call or never enforces the cap. This
checks the watchdog actually requests carrier termination end to end.
"""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

os.environ.pop("VERCEL", None)
os.environ["APEX_HOSTED"] = "1"
os.environ["APEX_MAX_CALL_RESERVE_USD"] = "3.00"
from config import settings
from database import Database

settings.UPSTASH_REDIS_REST_URL = "https://mock.invalid"
settings.UPSTASH_REDIS_REST_TOKEN = "test"
settings.MONTHLY_BUDGET_LIMIT_USD = 5.0
settings.RECEPTIONIST_ENABLED = True
settings.STAGING = False
settings.TELEPHONY_PROVIDER = "signalwire"
settings.MAX_CALL_DURATION_SECONDS = 60
settings.STALE_SETTLEMENT_GRACE_SECONDS = 60
settings.AUTO_MAINTENANCE = True
settings.MAINTENANCE_INTERVAL_SECONDS = 15


def start_redis():
    server_binary = shutil.which("redis-server")
    cli_binary = shutil.which("redis-cli")
    if not server_binary or not cli_binary:
        raise SystemExit("Install redis-server and redis-cli to run the watchdog test.")
    state = tempfile.TemporaryDirectory()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = str(listener.getsockname()[1])
    server = subprocess.Popen(
        [server_binary, "--bind", "127.0.0.1", "--port", port, "--dir", state.name,
         "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    def command(args):
        execution = subprocess.run(
            [cli_binary, "-p", port, "--json", *args],
            check=True, capture_output=True, text=True, timeout=3,
        )
        return json.loads(execution.stdout) if execution.stdout.strip() else None

    for _ in range(50):
        try:
            if command(["PING"]) == "PONG":
                break
        except subprocess.CalledProcessError:
            time.sleep(0.05)
    else:
        raise RuntimeError("Isolated Redis failed to start")
    return server, state, command


def main():
    server, state, command = start_redis()
    try:
        db = Database.__new__(Database)
        db.db_path = os.path.join(state.name, "watchdog.db")
        db._recent_errors = []
        db._local_tts_audio = {}
        db._webhook_times = []
        db._upstash_cmd = command
        db._init_db()

        import app as apex

        apex.db = db
        apex.telephony.signalwire_project_id = "project"
        apex.telephony.signalwire_token = "token"

        # An overdue call is already holding the slot when the process starts.
        overdue = "call-watchdog-0001"
        command(["SET", db.ACTIVE_CALL_KEY, overdue])
        command(["SET", db.SCHEDULER_KEY, "1", "EX", "180"])
        overdue_record = {
            "id": overdue,
            "status": "in-progress",
            "assistant_id": "tpl_hm_receptionist",
            "phone_number": "+15195550101",
            "direction": "inbound",
            "provider": "signalwire",
            "started_at": (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat(),
        }
        command(["SET", f"apex:call:{overdue}", json.dumps({
            "call": overdue_record, "transcripts": [],
        })])

        terminated = []

        def fake_terminate(call_sid):
            terminated.append(call_sid)
            return True

        stop = threading.Event()
        with patch.object(apex.telephony, "terminate_signalwire_call", side_effect=fake_terminate), \
             patch.object(settings, "MAINTENANCE_INTERVAL_SECONDS", 0.1):
            thread = threading.Thread(target=apex._watchdog_loop, args=(stop, apex.run_maintenance_cycle))
            thread.start()
            deadline = time.time() + 5
            while time.time() < deadline and not terminated:
                time.sleep(0.05)
            stop.set()
            thread.join(timeout=3)
            assert not thread.is_alive(), "watchdog did not stop cleanly"

        assert terminated == [overdue], f"watchdog did not terminate the overdue call: {terminated}"
        # The heartbeat was refreshed, so admission is not blocked by a stale scheduler.
        assert command(["TTL", db.SCHEDULER_KEY]) > 0

        # A fresh call is not terminated early.
        fresh = "call-watchdog-0002"
        command(["SET", db.ACTIVE_CALL_KEY, fresh])
        fresh_record = {
            "id": fresh, "status": "in-progress", "assistant_id": "tpl_hm_receptionist",
            "phone_number": "+15195550102", "direction": "inbound", "provider": "signalwire",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        command(["SET", f"apex:call:{fresh}", json.dumps({"call": fresh_record, "transcripts": []})])
        terminated.clear()
        cycle_result = apex.run_maintenance_cycle()
        assert terminated == [], "a call inside the limit was terminated early"
        assert cycle_result["active"] is True and cycle_result["termination_requested"] is False
    finally:
        server.terminate()
        server.wait(timeout=5)
        state.cleanup()
    print("PASS: container watchdog enforces the duration cap and leaves fresh calls alone")


if __name__ == "__main__":
    main()
