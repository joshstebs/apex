import time
import json
import urllib.parse
import xml.etree.ElementTree as ET
from fastapi.testclient import TestClient

from app import app, db, voice_engine, telephony, settings

# Configure mock secrets to verify both authentication and zero-leakage
TEST_SW_SIGNING_KEY = "sw_secret_signing_key_998877"
TEST_EL_KEY = "xi_secret_elevenlabs_key_112233"
TEST_HF_KEY = "hf_secret_huggingface_token_445566"
TEST_UPSTASH_TOKEN = "upstash_secret_token_778899"

settings.SIGNALWIRE_SIGNING_KEY = TEST_SW_SIGNING_KEY
settings.SIGNALWIRE_API_TOKEN = "sw_api_token_secret_000111"
settings.SIGNALWIRE_PROJECT_ID = "proj_test_123"
settings.ENFORCE_WEBHOOK_SIGNATURE = True
settings.ELEVENLABS_API_KEY = TEST_EL_KEY
settings.HUGGINGFACE_API_KEY = TEST_HF_KEY
settings.UPSTASH_REDIS_REST_URL = "https://mock-upstash.upstash.io"
settings.UPSTASH_REDIS_REST_TOKEN = TEST_UPSTASH_TOKEN

voice_engine.elevenlabs_key = TEST_EL_KEY
voice_engine.hf_token = TEST_HF_KEY
voice_engine.synthesize_speech_elevenlabs = lambda text, voice_id=None, **kw: f"MP3_AUDIO:{text}".encode("utf-8")

# Mock shared Upstash Redis across stateless Vercel instances
shared_redis = {}
def mock_upstash_cmd(cmd):
    op = cmd[0].upper()
    key = cmd[1]
    if op == "GET":
        entry = shared_redis.get(key)
        if not entry:
            return None
        if entry["exp"] and entry["exp"] < time.time():
            del shared_redis[key]
            return None
        return entry["val"]
    elif op == "SET":
        val = cmd[2]
        nx = "NX" in [str(x).upper() for x in cmd[3:]]
        ex = None
        for i, token in enumerate(cmd[3:], start=3):
            if str(token).upper() == "EX" and i + 1 < len(cmd):
                ex = time.time() + float(cmd[i + 1])
        if nx and key in shared_redis and (shared_redis[key]["exp"] is None or shared_redis[key]["exp"] >= time.time()):
            return None
        shared_redis[key] = {"val": val, "exp": ex}
        return "OK"
    elif op == "DEL":
        shared_redis.pop(key, None)
        return 1
    elif op == "INCRBYFLOAT":
        delta = float(cmd[2])
        cur = float(shared_redis.get(key, {"val": "0.0"})["val"])
        new_val = str(round(cur + delta, 4))
        shared_redis[key] = {"val": new_val, "exp": None}
        return new_val
    return None

db._upstash_cmd = mock_upstash_cmd

with db.get_connection() as conn:
    conn.execute("DELETE FROM transcripts")
    conn.execute("DELETE FROM calls")
    conn.execute("DELETE FROM tts_clips")
    conn.commit()

client = TestClient(app)

print("=== 1. TEST SIGNALWIRE WEBHOOK SIGNATURE VERIFICATION ===")
form_params = {"CallSid": "CA_001", "From": "+15195550199", "To": "+12267730802", "Direction": "inbound"}
raw_body = urllib.parse.urlencode(form_params)

# 1a. Missing signature -> 403
res_unauth = client.post("/webhooks/signalwire/voice", content=raw_body, headers={"Content-Type": "application/x-www-form-urlencoded"})
assert res_unauth.status_code == 403, f"Expected 403 for unsigned webhook, got {res_unauth.status_code}"

# 1b. Invalid signature -> 403
res_badsig = client.post(
    "/webhooks/signalwire/voice",
    content=raw_body,
    headers={"Content-Type": "application/x-www-form-urlencoded", "X-SignalWire-Signature": "forged_sig"}
)
assert res_badsig.status_code == 403, "Expected 403 for forged signature"

# 1c. Valid SignalWire Compatibility API signature behind Vercel https proxy headers -> 200
public_voice_url = "https://apexvoice-test.vercel.app/webhooks/signalwire/voice"
valid_sig = telephony.compute_signalwire_laml_signature(TEST_SW_SIGNING_KEY, public_voice_url, form_params)
res_valid = client.post(
    "/webhooks/signalwire/voice",
    content=raw_body,
    headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "apexvoice-test.vercel.app",
        "X-SignalWire-Signature": valid_sig
    }
)
assert res_valid.status_code == 200, f"Valid signature rejected: {res_valid.text}"
print("PASS: SignalWire webhook authentication enforced (unsigned/forged -> 403, valid -> 200).")

print("\n=== 2. TEST OPAQUE AUDIO CLIP URL (ZERO CONVERSATION TEXT IN URL) ===")
root = ET.fromstring(res_valid.text)
gather = root.find("Gather")
play_url = gather.find("Play").text
action_url = gather.attrib["action"]
assert "/api/tts/clip/clip_" in play_url and ".mp3" in play_url, f"Unexpected Play URL: {play_url}"
assert "text=" not in play_url and "Josh" not in play_url and "automated" not in play_url, f"Text leaked in Play URL: {play_url}"
assert "state=" not in action_url and "Josh" not in action_url, f"State leaked in Gather action URL: {action_url}"
print(f"PASS: Play URL is strictly opaque ({play_url.split('/')[-1]}) with zero conversation text.")

print("\n=== 3. TEST DURABLE CONCURRENCY LOCK & STATE ACROSS VERCEL COLD STARTS ===")
# Wipe local SQLite completely to simulate Container #2 cold start
with db.get_connection() as conn:
    conn.execute("DELETE FROM transcripts")
    conn.execute("DELETE FROM calls")
    conn.execute("DELETE FROM tts_clips")
    conn.commit()

# 3a. Second simultaneous inbound call on Container #2 must be blocked by Upstash atomic lock
form_params_2 = {"CallSid": "CA_002", "From": "+15195550122", "To": "+12267730802", "Direction": "inbound"}
raw_body_2 = urllib.parse.urlencode(form_params_2)
sig_2 = telephony.compute_signalwire_laml_signature(TEST_SW_SIGNING_KEY, public_voice_url, form_params_2)
res_concurrent = client.post(
    "/webhooks/signalwire/voice",
    content=raw_body_2,
    headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "apexvoice-test.vercel.app",
        "X-SignalWire-Signature": sig_2
    }
)
assert "<Hangup" in res_concurrent.text and "Gather" not in res_concurrent.text, "Atomic Redis lock failed to block 2nd call!"

# 3b. Opaque TTS clip served from shared Upstash Redis on Container #2 (after local SQLite was wiped)
clip_path = urllib.parse.urlsplit(play_url).path
res_clip = client.get(clip_path)
assert res_clip.status_code == 200 and res_clip.content.startswith(b"MP3_AUDIO:Hello!"), f"Opaque clip failed on Container #2: {res_clip.text}"

# 3c. Multi-turn Gather on Container #3 (rehydrating call state from shared Upstash Redis without URL state)
parsed_action = urllib.parse.urlsplit(action_url)
gather_path_qs = f"{parsed_action.path}?{parsed_action.query}"
public_gather_url = f"https://apexvoice-test.vercel.app{gather_path_qs}"
gather_params = {"SpeechResult": "We have Thursday at 2:30 PM open with Dr. Harris."}
gather_raw = urllib.parse.urlencode(gather_params)
gather_sig = telephony.compute_signalwire_laml_signature(TEST_SW_SIGNING_KEY, public_gather_url, gather_params)
res_gather = client.post(
    gather_path_qs,
    content=gather_raw,
    headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "apexvoice-test.vercel.app",
        "X-SignalWire-Signature": gather_sig
    }
)
assert res_gather.status_code == 200 and "/api/tts/clip/clip_" in res_gather.text
print("PASS: Atomic concurrency lock, opaque clip fetch, and durable state rehydration verified across cold-start instances.")

print("\n=== 4. TEST HUGGING FACE ROUTER ENDPOINT & MODEL CONFIG ===")
assert settings.HUGGINGFACE_ROUTER_URL == "https://router.huggingface.co/v1/chat/completions"
assert settings.HUGGINGFACE_LLM_MODEL == "meta-llama/Llama-3.1-8B-Instruct"
print(f"PASS: Hugging Face configured for {settings.HUGGINGFACE_ROUTER_URL} ({settings.HUGGINGFACE_LLM_MODEL}).")

print("\n=== 5. TEST OUTBOUND CALLING COMPLETELY DISABLED ===")
for prov in ["signalwire", "telnyx", "twilio"]:
    r_out = client.post("/api/calls/dispatch", json={"assistant_id": "tpl_appointment_booking", "phone_number": "+15195550199", "provider": prov})
    assert r_out.status_code == 403, f"Provider {prov} was not blocked!"
r_app = client.post("/api/calls/call_123/approve")
assert r_app.status_code == 403
print("PASS: Outbound calling and approval endpoints are completely disabled (403 Forbidden).")

print("\n=== 6. TEST HEALTH & SETTINGS ENDPOINTS NEVER EXPOSE SECRETS ===")
for ep in ["/api/health", "/api/settings"]:
    r_sec = client.get(ep)
    assert r_sec.status_code == 200
    body_str = r_sec.text
    for secret_val in [TEST_SW_SIGNING_KEY, "sw_api_token_secret_000111", TEST_EL_KEY, TEST_HF_KEY, TEST_UPSTASH_TOKEN, "mock-upstash"]:
        assert secret_val not in body_str, f"Secret '{secret_val}' leaked in {ep}!"
r_post_set = client.post("/api/settings", json={"elevenlabs_api_key": "override"})
assert r_post_set.status_code == 405, "POST /api/settings must be disabled"
print("PASS: /api/health and /api/settings expose zero secrets and reject runtime mutation.")

print("\n>>> ALL 6 FINAL VERCEL PRE-DEPLOYMENT VERIFICATION SUITES PASSED! <<<")
