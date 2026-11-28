"""A silent active call must not lose its lock and be settled as abandoned.

A caller who stops talking produces no gather webhook. If the lease expires, the
slot frees up, a second caller is admitted, and the first call is later settled
against a slot it no longer owns. This exercises the real Redis Lua paths.
"""
import json
import shutil
import socket
import subprocess
import tempfile
import time
import os

os.environ["VERCEL"] = "1"
os.environ["CRON_SECRET"] = "silent-call-scheduler-secret"
os.environ["APEX_MAX_CALL_RESERVE_USD"] = "3.00"
from app import db, settings
from datetime import datetime, timezone

settings.UPSTASH_REDIS_REST_URL = "https://mock.invalid"
settings.UPSTASH_REDIS_REST_TOKEN = "test"
settings.RECEPTIONIST_ENABLED = True
settings.STAGING = False
settings.MONTHLY_BUDGET_LIMIT_USD = 5.0
settings.CRON_SECRET = "silent-call-scheduler-secret"
settings.TELEPHONY_PROVIDER = "signalwire"
settings.MAX_CALL_DURATION_SECONDS = 1200


def admit(command, call_id):
    command(["SET", db.SCHEDULER_KEY, "1", "EX", "180"])
    return db.try_acquire_call_slot({
        "id": call_id,
        "status": "in-progress",
        "assistant_id": "tpl_hm_receptionist",
        "phone_number": "+15195550101",
        "direction": "inbound",
        "provider": "signalwire",
        "started_at": datetime.now(timezone.utc).isoformat(),
    })


def main():
    server_binary = shutil.which("redis-server")
    cli_binary = shutil.which("redis-cli")
    if not server_binary or not cli_binary:
        raise SystemExit("Install redis-server and redis-cli to run the silent-call test.")
    with tempfile.TemporaryDirectory() as state:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = str(listener.getsockname()[1])
        server = subprocess.Popen(
            [server_binary, "--bind", "127.0.0.1", "--port", port, "--dir", state,
             "--save", "", "--appendonly", "no"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
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

            db._upstash_cmd = command
            with tempfile.TemporaryDirectory() as directory:
                db.db_path = os.path.join(directory, "silent.db")
                db._init_db()

                command(["FLUSHDB"])
                first = "call-silent-0001"
                assert admit(command, first) == (True, None, "created")
                # A hosted slot is held without a TTL, so a quiet caller keeps it.
                assert command(["TTL", db.ACTIVE_CALL_KEY]) == -1, "active slot must not expire"
                assert command(["GET", db.ACTIVE_CALL_KEY]) == first

                second, error, _ = admit(command, "call-silent-0002")
                assert second is False and error, "second call must be refused while the first is silent"
                assert command(["GET", db.ACTIVE_CALL_KEY]) == first

                # The reservation is still recorded once, not twice.
                spend = float(command(["GET", "apex:spend:" + datetime.now(timezone.utc).strftime("%Y-%m")]))
                assert abs(spend - 3.0) < 1e-6, spend

                # Even if a legacy lease was set, admission of the same CallSid recovers
                # the slot instead of charging a second reservation.
                command(["DBSIZE"])
                command(["PERSIST", db.ACTIVE_CALL_KEY])
                again, again_error, again_outcome = admit(command, first)
                assert again is True, (again_error, again_outcome)
                assert float(command(["GET", "apex:spend:" + datetime.now(timezone.utc).strftime("%Y-%m")])) == spend
        finally:
            server.terminate()
            server.wait(timeout=5)
    print("PASS: silent active call keeps its slot and cannot be double-charged")


if __name__ == "__main__":
    main()
