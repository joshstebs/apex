from datetime import datetime, timezone
from unittest.mock import patch
from xml.etree import ElementTree

from app import (
    db,
    handle_signalwire_gather_turn,
    handle_signalwire_inbound_or_connect,
    settings,
    voice_engine,
)


def run():
    call_id = "test-voice-clip"
    assistant = {"id": "test", "first_message": "Hello & welcome.", "system_prompt": "Be concise."}
    call = {"assistant_id": "test", "status": "in-progress", "started_at": datetime.now(timezone.utc).isoformat()}
    reply = {"text": "I can help with that.", "latency_ms": 1}
    params = {"CallSid": call_id, "To": settings.SIGNALWIRE_PHONE_NUMBER}

    with (
        patch.object(settings, "RECEPTIONIST_ENABLED", True),
        patch.object(settings, "ELEVENLABS_API_KEY", "test"),
        patch.object(settings, "HUGGINGFACE_API_KEY", "test"),
        patch.object(settings, "UPSTASH_REDIS_REST_URL", "https://redis.invalid"),
        patch.object(settings, "UPSTASH_REDIS_REST_TOKEN", "test"),
        patch.object(settings, "SIGNALWIRE_SIGNING_KEY", "test"),
        patch.object(voice_engine, "elevenlabs_key", "test"),
        patch.object(db, "get_assistant", return_value=assistant),
        patch.object(db, "get_call", return_value=call),
        patch.object(db, "_upstash_cmd", return_value=call_id),
        patch.object(db, "try_acquire_call_slot", return_value=(True, None, "admitted")),
        patch.object(db, "add_transcript_message"),
        patch.object(db, "get_call_transcripts", return_value=[]),
        patch.object(db, "update_call"),
        patch.object(voice_engine, "generate_chat_response", return_value=reply),
        patch("app.release_call_slot_safely"),
        patch.object(db, "create_tts_clip", side_effect=RuntimeError("storage unavailable")) as create_clip,
    ):
        greeting = ElementTree.fromstring(handle_signalwire_inbound_or_connect(params, {}))
        assert greeting.findtext("Gather/Say") == assistant["first_message"]
        turn = ElementTree.fromstring(handle_signalwire_gather_turn({**params, "SpeechResult": "Hello"}, {}))
        assert turn.findtext("Gather/Say") == reply["text"]
        goodbye = ElementTree.fromstring(handle_signalwire_gather_turn({**params, "SpeechResult": "Goodbye"}, {}))
        assert goodbye.findtext("Say") == reply["text"]
        assert goodbye.find("Hangup") is not None

        create_clip.side_effect = None
        create_clip.return_value = "clip_opaque"
        greeting = ElementTree.fromstring(handle_signalwire_inbound_or_connect(params, {}))
        assert greeting.findtext("Gather/Play").endswith("/api/tts/clip/clip_opaque.mp3")


if __name__ == "__main__":
    run()
    print("PASS: carrier speech fallback for greetings, replies and goodbyes")
