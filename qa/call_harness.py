"""ASGI call simulation using temporary state and synthetic provider replies."""

from collections import defaultdict
from contextlib import ExitStack, contextmanager
from importlib import import_module
import base64
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from unittest.mock import patch
from xml.etree import ElementTree

from fastapi.testclient import TestClient

BASE_URL = "https://qa.invalid"
CALLER = "+12025550101"
DID = "+12025550102"
SIGNING_KEY = "synthetic-apex-qa-signing-key"
ADMIN = "synthetic-apex-qa-admin"
OPERATIONS = "synthetic-apex-qa-operations-token"
SCHEDULER = "synthetic-apex-qa-scheduler"
APPOINTMENT_REQUEST_REPLY = "I can take an appointment request for the team to review."
MOCK_MP3 = b"ID3synthetic-audio"


class SimulatedResponse(io.BytesIO):
    status = 200


class CallHarness:
    def __init__(self, module, client):
        self.module = module
        self.client = client
        self.model_reply = APPOINTMENT_REQUEST_REPLY
        self.model_requests = []
        self.actions = []
        self.failures = {}
        self.latency_ms = defaultdict(list)
        self.provider_delays_ms = {}

    def provider(self, request, *, timeout):
        endpoint = urlsplit(request.full_url)
        stages = {
            "qa-model.invalid": "llm",
            "api.elevenlabs.io": "tts",
            "offline-qa.signalwire.com": "carrier-hangup",
        }
        if endpoint.hostname not in stages:
            raise AssertionError("Unexpected upstream request in offline simulation")
        stage = stages[endpoint.hostname]
        started = time.perf_counter()
        self.actions.append(stage)
        try:
            time.sleep(self.provider_delays_ms.get(stage, 0) / 1000)
            failure = self.failures.get(stage)
            if failure == "timeout":
                raise TimeoutError("Synthetic upstream timeout")
            if failure == "rate-limit":
                raise HTTPError(request.full_url, 429, "Synthetic rate limit", {}, None)
            if stage == "llm":
                self.model_requests.append(json.loads(request.data)["messages"])
                if failure == "malformed":
                    return SimulatedResponse(b'{"choices":[null]}')
                content = {"choices": [{"message": {"content": self.model_reply}}]}
                return SimulatedResponse(json.dumps(content).encode())
            if stage == "tts":
                return SimulatedResponse(MOCK_MP3)
            return SimulatedResponse(b"")
        finally:
            self.latency_ms[stage].append((time.perf_counter() - started) * 1000)

    def callback(self, event, /, *, authenticated=True, **fields):
        path = f"/webhooks/signalwire/{event}"
        canonical = BASE_URL + path + "".join(key + fields[key] for key in sorted(fields))
        digest = hmac.new(SIGNING_KEY.encode(), canonical.encode(), hashlib.sha1).digest()
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if authenticated:
            headers["X-SignalWire-Signature"] = base64.b64encode(digest).decode("ascii")
        started = time.perf_counter()
        response = self.client.post(path, headers=headers, content=urlencode(fields))
        self.latency_ms[event].append((time.perf_counter() - started) * 1000)
        return response

    def inbound(self, sid):
        return self.callback("voice", CallSid=sid, From=CALLER, To=DID)

    def turn(self, sid, speech):
        return self.callback("gather", CallSid=sid, SpeechResult=speech)

    def end(self, sid, status="completed", duration=18):
        return self.callback("status", CallSid=sid, CallStatus=status, CallDuration=str(duration))

    def audio(self, cxml):
        audio_url = ElementTree.fromstring(cxml).findtext("Gather/Play")
        if not audio_url or not audio_url.startswith(BASE_URL + "/api/tts/clip/"):
            raise AssertionError("Expected an opaque QA audio URL")
        started = time.perf_counter()
        response = self.client.get(audio_url)
        self.latency_ms["audio-fetch"].append((time.perf_counter() - started) * 1000)
        return response


@contextmanager
def simulate(directory: Path, *, tts=False, hosted=False):
    # Remove host configuration before the first application import.
    env = {
        "DB_PATH": str(directory / "calls.db"),
        "PUBLIC_URL": BASE_URL,
        "SIGNALWIRE_SPACE_URL": "offline-qa.signalwire.com",
        "SIGNALWIRE_PROJECT_ID": "synthetic",
        "SIGNALWIRE_API_TOKEN": "synthetic",
        "SIGNALWIRE_SIGNING_KEY": SIGNING_KEY,
        "SIGNALWIRE_PHONE_NUMBER": DID,
        "HUGGINGFACE_ROUTER_URL": "https://qa-model.invalid/chat",
        "HUGGINGFACE_API_KEY": "synthetic",
        "ELEVENLABS_API_KEY": "synthetic" if tts or hosted else "",
        "APEX_TTS_PROVIDER": "elevenlabs" if tts else "carrier",
        "APEX_ENVIRONMENT": "local",
        "APEX_ADMIN_TOKEN": ADMIN,
        "APEX_OPERATIONS_TOKEN": OPERATIONS,
        "CRON_SECRET": SCHEDULER,
        "APEX_MAX_CALL_RESERVE_USD": "1",
        "RECEPTIONIST_ENABLED": "true",
    }
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, env, clear=True))
        open_url = stack.enter_context(patch("urllib.request.urlopen"))
        open_url.side_effect = AssertionError("Provider request during QA initialization")
        module = import_module("app")
        fresh = import_module("config").AppSettings()
        stack.enter_context(patch.dict(vars(module.settings), vars(fresh), clear=True))
        stack.enter_context(patch.object(module, "db", module.Database(fresh.DB_PATH)))
        stack.enter_context(patch.object(module, "telephony", module.TelephonyGateway()))
        stack.enter_context(patch.object(module, "voice_engine", module.VoiceEngine()))
        module.seed_default_assistants()
        if hosted:
            os.environ["VERCEL"] = "1"
            module.settings.UPSTASH_REDIS_REST_URL = "https://qa-redis.invalid"
            module.settings.UPSTASH_REDIS_REST_TOKEN = "synthetic"

        with TestClient(module.app, base_url=BASE_URL) as client:
            harness = CallHarness(module, client)
            open_url.side_effect = harness.provider
            yield harness
