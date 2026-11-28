"""A failed audio cache write must not cost a second ElevenLabs synthesis.

The clip is already synthesized for this request. If storing it fails, the retry
should reuse what was just paid for instead of buying the same audio again.
"""
import os
import time

os.environ["VERCEL"] = "1"
os.environ["APEX_ADMIN_TOKEN"] = "test-only"
from fastapi.testclient import TestClient
from app import app, db, settings, voice_engine

settings.UPSTASH_REDIS_REST_URL = "https://mock.invalid"
settings.UPSTASH_REDIS_REST_TOKEN = "test"

store = {}


def redis(cmd):
    op = cmd[0]
    if op == "EXISTS":
        return int(cmd[1] in store)
    if op == "GET":
        return store.get(cmd[1])
    if op == "SET":
        if "NX" in cmd and cmd[1] in store:
            return None
        store[cmd[1]] = cmd[2]
        return "OK"
    if op == "DEL":
        return 1 if store.pop(cmd[1], None) is not None else 0
    raise AssertionError(op)


db._upstash_cmd = redis
clip = {"text": "Your table is ready.", "voice_id": "test-voice"}
db.get_tts_clip = lambda _id: clip
syntheses = []


def synth(text, voice_id):
    syntheses.append((text, voice_id))
    return b"ID3-mp3-test"


voice_engine.synthesize_speech_elevenlabs = synth
client = TestClient(app)
url = "/api/tts/clip/clip_failedcache00000.mp3"

# First synthesis is served even though the shared cache write fails.
db.cache_tts_audio = lambda _id, _audio: False
first = client.get(url)
assert first.status_code == 200, first.text
assert first.content == b"ID3-mp3-test"
assert len(syntheses) == 1

# The carrier retries the same clip URL and must not be charged twice.
second = client.get(url)
assert second.status_code == 200, second.text
assert second.content == b"ID3-mp3-test", second.content
assert len(syntheses) == 1, "cache failure caused a duplicate paid synthesis"

# A retried webhook re-renders the same greeting. It must reuse the same clip,
# so the retry is served from the audio cache instead of being billed again.
first_clip = db.create_tts_clip("Thank you for calling.", voice_id="test-voice")
second_clip = db.create_tts_clip("Thank you for calling.", voice_id="test-voice")
assert first_clip == second_clip, "identical speech created a second billable clip"
assert db.create_tts_clip("Thank you for calling.", voice_id="other-voice") != first_clip
assert first_clip.startswith("clip_") and len(first_clip) == len("clip_") + 32
assert "Thank you" not in first_clip

print("PASS: failed audio cache write and webhook retries do not trigger duplicate synthesis")
