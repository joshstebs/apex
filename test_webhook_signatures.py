"""SignalWire Compatibility API signature fixtures. No network and no carrier account."""
import hashlib
import hmac
import base64
import os
import urllib.parse

os.environ.pop("VERCEL", None)
from fastapi.testclient import TestClient
from app import app, settings, telephony

settings.ENFORCE_WEBHOOK_SIGNATURE = True
settings.SIGNALWIRE_SIGNING_KEY = "fixture-signing-key"
settings.SIGNALWIRE_API_TOKEN = ""
settings.RECEPTIONIST_ENABLED = False
settings.STAGING = False
client = TestClient(app)

URL = "http://testserver/webhooks/signalwire/voice"
PARAMS = {"CallSid": "CA1234567890", "From": "+15195550100", "To": "+12267732234"}


def spec_sha1(key: str, url: str, params: dict) -> str:
    """Documented LaML/Twilio-compatible algorithm: base64(HMAC-SHA1(url + sorted key/value))."""
    material = url + "".join(k + params[k] for k in sorted(params))
    digest = hmac.new(key.encode("utf-8"), material.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def spec_sha256(key: str, url: str, body: str) -> str:
    return hmac.new(key.encode("utf-8"), f"{url}{body}".encode("utf-8"), hashlib.sha256).hexdigest()


def post(body: str, headers: dict):
    return client.post(
        "/webhooks/signalwire/voice",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", **headers},
    )


body = urllib.parse.urlencode(PARAMS)
expected = spec_sha1(settings.SIGNALWIRE_SIGNING_KEY, URL, PARAMS)
assert expected == telephony.compute_signalwire_laml_signature(settings.SIGNALWIRE_SIGNING_KEY, URL, PARAMS)
# Frozen vector for URL + sorted CallSid, From, To using fixture-signing-key.
assert expected == "TU6aQzEyIDPxyR4/oA1KJqEFc30="

assert post(body, {}).status_code == 403
forged = expected[:-1] + ("A" if not expected.endswith("A") else "B")
assert post(body, {"X-SignalWire-Signature": forged}).status_code == 403
wrong_url = spec_sha1(settings.SIGNALWIRE_SIGNING_KEY, URL + "?x=1", PARAMS)
assert post(body, {"X-SignalWire-Signature": wrong_url}).status_code == 403
tampered = urllib.parse.urlencode({**PARAMS, "From": "+19995550100"})
assert post(tampered, {"X-SignalWire-Signature": expected}).status_code == 403

valid = post(body, {"X-SignalWire-Signature": expected})
assert valid.status_code == 200, valid.text
assert "not yet available" in valid.text.lower()

sha256 = spec_sha256(settings.SIGNALWIRE_SIGNING_KEY, URL, body)
signed_sha = post(body, {"X-SignalWire-Sha256-Signature": sha256})
assert signed_sha.status_code == 200, signed_sha.text

settings.SIGNALWIRE_SIGNING_KEY = ""
settings.SIGNALWIRE_API_TOKEN = ""
assert post(body, {"X-SignalWire-Signature": expected}).status_code == 403

print("PASS: unsigned, forged, tampered and valid SignalWire signatures")
