"""Check ElevenLabs request and purchased SignalWire number without external calls."""
import json
from unittest.mock import patch
from config import settings
from telephony import TelephonyGateway
from voice_engine import VoiceEngine

assert settings.SIGNALWIRE_PHONE_NUMBER == "+12267732234"
assert settings.SIGNALWIRE_PHONE_NUMBER_ID == "8f935d8b-bd61-457b-b421-edddfef247ea"
assert settings.ELEVENLABS_DEFAULT_VOICE_ID == "21m00Tcm4TlvDq8ikWAM"
assert settings.RECEPTIONIST_ENABLED is False
engine = VoiceEngine(hf_token="test-hf",elevenlabs_key="test-elevenlabs")
class Response:
    status=200
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self):return b"FAKE_MP3_DATA"
def fake_urlopen(req, timeout=0):
    assert req.get_method()=="POST"
    assert req.full_url=="https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM"
    assert req.get_header("Xi-api-key")=="test-elevenlabs"
    body=json.loads(req.data)
    assert body["model_id"]=="eleven_turbo_v2_5"
    assert body["text"]=="Thank you for calling Harbour and Main."
    return Response()
with patch("urllib.request.urlopen",fake_urlopen):
    assert engine.synthesize_speech_elevenlabs("Thank you for calling Harbour and Main.")==b"FAKE_MP3_DATA"
cxml=TelephonyGateway(public_url="https://apex-stebs-co.vercel.app").build_signalwire_cxml_gather(
    "sample-callsid","tpl_hm_receptionist","Hello",clip_id="opaque-clip"
)
assert "https://apex-stebs-co.vercel.app/api/tts/clip/opaque-clip.mp3" in cxml
assert "/webhooks/signalwire/gather?" in cxml
assert "&amp;assistant_id" in cxml
print("PASS: test number, ElevenLabs voice request, opaque clip and signed callback URL shape")
