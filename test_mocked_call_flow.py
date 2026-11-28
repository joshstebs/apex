"""Simulated inbound call: speech fallback, message capture, voicemail, hangup, history.

SQLite only. The model, TTS and carrier HTTP client are stubbed.
"""
import os
import tempfile
import urllib.parse
from unittest.mock import patch
from xml.etree import ElementTree

os.environ.pop("VERCEL", None)
os.environ["APEX_ADMIN_TOKEN"] = "flow-admin-token"
from fastapi.testclient import TestClient
from app import app, db, seed_default_assistants, settings, telephony, voice_engine

settings.STAGING = False
settings.APEX_ENVIRONMENT = "local"
settings.TELEPHONY_PROVIDER = "signalwire"
settings.UPSTASH_REDIS_REST_URL = ""
settings.UPSTASH_REDIS_REST_TOKEN = ""
settings.TURSO_DATABASE_URL = ""
settings.TURSO_AUTH_TOKEN = ""
settings.RECEPTIONIST_ENABLED = True
settings.ENFORCE_WEBHOOK_SIGNATURE = True
settings.SIGNALWIRE_SIGNING_KEY = "flow-signing-key"
settings.REQUIRE_MATCHING_INBOUND_NUMBER = True
settings.MONTHLY_BUDGET_LIMIT_USD = 5.0
settings.MAX_CONCURRENT_CALLS = 1
voice_engine.elevenlabs_key = ""
voice_engine.hf_token = ""
client = TestClient(app)
admin = {"Authorization": "Bearer flow-admin-token"}
histories = []


def signed(endpoint, **fields):
    path = "/webhooks/signalwire/" + endpoint
    url = "http://testserver" + path
    signature = telephony.compute_signalwire_laml_signature(settings.SIGNALWIRE_SIGNING_KEY, url, fields)
    return client.post(path, content=urllib.parse.urlencode(fields), headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "X-SignalWire-Signature": signature,
    })


def answer(system_prompt, conversation_history, new_human_input, temperature=0.4, tools=None):
    histories.append(list(conversation_history))
    if "dock" in new_human_input.lower():
        return {
            "text": "I have the message for the team.",
            "latency_ms": 5,
            "tool_call": {
                "tool": "save_receptionist_message",
                "parameters": {
                    "caller_name": "Sam",
                    "callback_number": "+15195550100",
                    "reason": "Dock question",
                    "preferred_contact_time": "morning",
                },
            },
        }
    return {"text": "Thank you for calling Harbour and Main.", "latency_ms": 4, "tool_call": None}


def run():
    database = tempfile.TemporaryDirectory()
    db.db_path = os.path.join(database.name, "call-flow.db")
    db._init_db()
    seed_default_assistants()
    sid = "CA-flow-000000000001"
    caller = "+15195550100"
    dialed = settings.SIGNALWIRE_PHONE_NUMBER

    with patch.object(voice_engine, "generate_chat_response", side_effect=answer), patch("urllib.request.urlopen") as opened:
        greeting = signed("voice", CallSid=sid, From=caller, To=dialed)
        assert greeting.status_code == 200, greeting.text
        greeting_xml = ElementTree.fromstring(greeting.text)
        assert greeting_xml.find("Gather/Play") is None
        assert "Harbour" in greeting_xml.findtext("Gather/Say")
        opened.assert_not_called()

        spoken = signed(
            "gather?call_id=%s&assistant_id=tpl_hm_receptionist" % sid,
            CallSid=sid,
            SpeechResult="This is Sam. Please call me about the dock.",
        )
        assert spoken.status_code == 200, spoken.text
        spoken_xml = ElementTree.fromstring(spoken.text)
        assert spoken_xml.findtext("Gather/Say") == "I have the message for the team."
        assert "```" not in spoken.text
        captured = db.get_call(sid)["extracted_data"]["save_receptionist_message"]
        assert captured["caller_name"] == "Sam"
        assert captured["reason"] == "Dock question"

        goodbye = signed(
            "gather?call_id=%s&assistant_id=tpl_hm_receptionist" % sid,
            CallSid=sid,
            SpeechResult="Goodbye.",
        )
        assert goodbye.status_code == 200 and goodbye.text.find("<Hangup") != -1
        model_history = histories[-1]
        assert any(turn["content"].startswith("Thank you for calling") or "Harbour" in turn["content"] for turn in model_history)
        assert all("Details captured" not in turn["content"] for turn in model_history)
        assert all(turn["role"] in ("assistant", "user") for turn in model_history)
        assert db.get_call(sid)["status"] == "completed"
        assert db.list_receptionist_messages()[0]["message"]["caller_name"] == "Sam"

        terminated = client.post("/api/calls/%s/terminate" % sid, headers=admin)
        assert terminated.status_code == 200, terminated.text
        opened.assert_not_called()

        voicemail_sid = "CA-flow-000000000002"
        left = signed("voice", CallSid=voicemail_sid, From=caller, To=dialed)
        assert left.status_code == 200, left.text
        signed(
            "gather?call_id=%s&assistant_id=tpl_hm_receptionist" % voicemail_sid,
            CallSid=voicemail_sid,
            SpeechResult="Please tell the team the shipment is at the side door.",
        )
        closing = signed(
            "gather?call_id=%s&assistant_id=tpl_hm_receptionist" % voicemail_sid,
            CallSid=voicemail_sid,
            SpeechResult="Goodbye",
        )
        assert "<Hangup" in closing.text
        voicemail = db.get_call(voicemail_sid)["extracted_data"]["save_receptionist_message"]
        assert voicemail["capture"] == "voicemail"
        assert "side door" in voicemail["reason"]
        assert voicemail["callback_number"] == caller

        status = signed("status", CallSid=voicemail_sid, CallStatus="completed", CallDuration="45")
        assert status.status_code == 200, status.text
        assert db.get_call(voicemail_sid)["status"] == "completed"
        transcripts = db.get_call_transcripts(voicemail_sid)
        speakers = [item["speaker"] for item in transcripts]
        assert "human" in speakers and "assistant" in speakers
        again = signed("status", CallSid=voicemail_sid, CallStatus="completed", CallDuration="45")
        assert again.status_code == 200
        assert db.get_call(voicemail_sid)["duration_seconds"] == 45
        opened.assert_not_called()

    database.cleanup()
    print("PASS: mocked inbound call captured a message, voicemail, hangup and history")


if __name__ == "__main__":
    run()
