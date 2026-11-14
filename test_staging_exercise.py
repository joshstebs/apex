"""Staging exercise is admin-only, 404 outside staging, and never calls a provider."""
import json
import os
import shutil
from datetime import datetime, timezone
import socket
import subprocess
import tempfile
import time
from unittest.mock import patch

os.environ.pop("VERCEL", None)
os.environ["APEX_ADMIN_TOKEN"] = "staging-exercise-token"
from fastapi.testclient import TestClient
from app import app, db, settings, telephony

client = TestClient(app)
good = {"Authorization": "Bearer staging-exercise-token"}


def assert_no_providers(opened, synthesize, terminate):
    opened.assert_not_called()
    synthesize.assert_not_called()
    terminate.assert_not_called()


def run_without_redis():
    settings.STAGING = False
    settings.APEX_ENVIRONMENT = "local"
    settings.UPSTASH_REDIS_REST_URL = ""
    settings.UPSTASH_REDIS_REST_TOKEN = ""
    with patch("urllib.request.urlopen") as opened:
        hidden = client.post("/api/staging/exercise")
        assert hidden.status_code == 404, hidden.text
        authed = client.post("/api/staging/exercise", headers=good)
        assert authed.status_code == 404, authed.text
        opened.assert_not_called()
    settings.STAGING = True
    settings.APEX_ENVIRONMENT = "staging"
    assert client.post("/api/staging/exercise").status_code == 401
    assert client.post("/api/staging/exercise", headers={"Authorization": "Bearer wrong"}).status_code == 401
    with (
        patch("urllib.request.urlopen") as opened,
        patch("voice_engine.VoiceEngine.synthesize_speech_elevenlabs") as synthesize,
        patch("telephony.TelephonyGateway.terminate_signalwire_call") as terminate,
    ):
        response = client.post("/api/staging/exercise", headers=good)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["providers_contacted"] is False
    assert body["redis_configured"] is False
    assert body["redis_reachable"] is False
    names = [step["name"] for step in body["steps"]]
    assert names == [
        "redis_round_trip", "inbound", "speech_turn", "message_capture",
        "voicemail", "signed_status", "duplicate_status", "live_admission_refused",
    ]
    by_name = {step["name"]: step for step in body["steps"]}
    assert by_name["inbound"]["speech"] == "say" and by_name["inbound"]["played_audio"] is False
    assert by_name["message_capture"]["tool"] == "save_receptionist_message"
    assert by_name["message_capture"]["redis_round_trip"] is False
    assert by_name["voicemail"]["capture"] == "voicemail"
    assert by_name["signed_status"]["signature_valid"] is True
    assert by_name["signed_status"]["forged_rejected"] is True
    assert by_name["duplicate_status"]["settlement"] == "skipped"
    assert by_name["live_admission_refused"]["ok"] is True
    assert "staging-exercise-token" not in response.text
    assert "staging-drill-signing-key" not in response.text
    assert_no_providers(opened, synthesize, terminate)


def run_with_redis(command):
    settings.STAGING = True
    settings.APEX_ENVIRONMENT = "staging"
    settings.UPSTASH_REDIS_REST_URL = "https://mock.invalid"
    settings.UPSTASH_REDIS_REST_TOKEN = "test"
    command(["FLUSHDB"])
    with (
        patch.object(db, "_upstash_cmd", side_effect=command),
        patch("urllib.request.urlopen") as opened,
        patch("voice_engine.VoiceEngine.synthesize_speech_elevenlabs") as synthesize,
        patch("telephony.TelephonyGateway.terminate_signalwire_call") as terminate,
    ):
        response = client.post("/api/staging/exercise", headers=good)
        assert_no_providers(opened, synthesize, terminate)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["redis_reachable"] is True
    by_name = {step["name"]: step for step in body["steps"]}
    assert by_name["message_capture"]["redis_round_trip"] is True
    assert by_name["signed_status"]["settlement"] == "released"
    assert by_name["duplicate_status"]["settlement"] == "already_released"
    assert by_name["duplicate_status"]["spend_unchanged"] is True
    assert command(["GET", db.ACTIVE_CALL_KEY]) is None
    month = datetime.now(timezone.utc).strftime("apex:spend:%Y-%m")
    assert command(["GET", month]) is None
    # The drill ledger is removed after the response. A leftover live settlement key is a failure.
    leftover = command(["KEYS", "apex:drill:*"])
    assert leftover == [] or leftover is None


def main():
    run_without_redis()
    server_binary = shutil.which("redis-server")
    cli_binary = shutil.which("redis-cli")
    if not server_binary or not cli_binary:
        raise SystemExit("Install redis-server and redis-cli to run the staging exercise test.")
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
            run_with_redis(command)
        finally:
            server.terminate()
            server.wait(timeout=5)
    print("PASS: staging exercise refuses non-staging, skips providers, and settles a drill callback once")


if __name__ == "__main__":
    main()
