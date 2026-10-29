"""Offline staged receptionist tests. No external API requests."""
import os, json, urllib.parse
os.environ["VERCEL"] = "1"
os.environ["APEX_ADMIN_TOKEN"] = "test-admin"
from fastapi.testclient import TestClient
from app import app, db, settings, telephony
from unittest.mock import patch
settings.RECEPTIONIST_ENABLED = False
settings.REQUIRE_MATCHING_INBOUND_NUMBER = True
settings.SIGNALWIRE_PHONE_NUMBER = "+12267732234"
settings.SIGNALWIRE_SIGNING_KEY = "unit-test-signing-key"
settings.ENFORCE_WEBHOOK_SIGNATURE = True
settings.UPSTASH_REDIS_REST_URL = "https://mock.invalid"
settings.UPSTASH_REDIS_REST_TOKEN = "unit-test-redis"
settings.INBOUND_ASSISTANT_ID = "tpl_hm_receptionist"
client = TestClient(app)
headers = {"Authorization": "Bearer test-admin"}
template = db.get_assistant("tpl_hm_receptionist")
assert template and "Harbour & Main" in template["name"]
assert settings.SIGNALWIRE_PHONE_NUMBER == "+12267732234"
assert settings.SIGNALWIRE_PHONE_NUMBER_ID == "8f935d8b-bd61-457b-b421-edddfef247ea"
assert "transcrib" in template["first_message"].lower()
def send_voice(to):
    p = {"CallSid":"12345678-1234-1234-1234-123456789012","From":"+15195550101","To":to}
    url = "http://testserver/webhooks/signalwire/voice"
    sig = telephony.compute_signalwire_laml_signature(settings.SIGNALWIRE_SIGNING_KEY,url,p)
    return client.post("/webhooks/signalwire/voice",content=urllib.parse.urlencode(p),headers={"X-SignalWire-Signature":sig,"Content-Type":"application/x-www-form-urlencoded"})
r=send_voice("+12267732234")
assert r.status_code==200 and "not yet available" in r.text.lower(),r.text
settings.RECEPTIONIST_ENABLED=True
r=send_voice("+15195550000")
assert r.status_code==200 and "not configured" in r.text.lower(),r.text
settings.RECEPTIONIST_ENABLED=False
assert client.post("/api/maintenance/enforce-call-duration").status_code==401
with patch.object(db,"get_call",return_value=None):
    assert client.post("/api/calls/anything/terminate",headers=headers).status_code==404
# Verify exact provider request shape without sending a real request.
settings.SIGNALWIRE_PROJECT_ID = "12345678-1234-1234-1234-123456789012"
settings.SIGNALWIRE_API_TOKEN = "unit-test-carrier-token"
telephony.signalwire_project_id = settings.SIGNALWIRE_PROJECT_ID
telephony.signalwire_token = settings.SIGNALWIRE_API_TOKEN
class Response:
    status = 200
    def __enter__(self): return self
    def __exit__(self,*a): pass
def fake_urlopen(req,timeout=0):
    assert req.get_method()=="POST"
    assert req.data==b"Status=completed"
    assert req.full_url.endswith("/Calls/12345678-1234-1234-1234-123456789012")
    assert req.get_header("Authorization").startswith("Basic ")
    return Response()
with patch("urllib.request.urlopen",fake_urlopen):
    assert telephony.terminate_signalwire_call("12345678-1234-1234-1234-123456789012")
try:
    telephony.terminate_signalwire_call("CA_bad/../../")
    assert False,"unsafe SID allowed"
except ValueError:pass
print("PASS: receptionist template, disabled default, DID restriction, auth and carrier termination payload")
