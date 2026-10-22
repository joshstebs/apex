"""Offline checks for invented confirmations and Redis durability failures."""
import os
import json
import tempfile
from unittest.mock import patch

from voice_engine import VoiceEngine
from database import Database
from config import settings

engine = VoiceEngine(hf_token="", elevenlabs_key="")
for phrase in ["Thursday 2:30 is confirmed", "your RMA is RMA-123", "You have a $30 credit"]:
    with patch.object(engine, "hf_token", ""):
        result = engine.generate_chat_response("You book appointments and negotiate bills", [], phrase)
    assert result["tool_call"] is None
    assert "can't confirm" in result["text"]
    assert "RMA-" not in result["text"]

with tempfile.TemporaryDirectory() as tmp:
    with patch.dict(os.environ, {"VERCEL": ""}):
        db = Database(f"{tmp}/test.db")
        with db.get_connection() as con:
            assert con.execute("PRAGMA synchronous").fetchone()[0] >= 1

with patch.object(settings, "UPSTASH_REDIS_REST_URL", "https://mock.invalid"), \
     patch.object(settings, "UPSTASH_REDIS_REST_TOKEN", "mock-token"):
    with patch.object(Database, "_upstash_cmd", lambda *args, **kwargs: None):
        db = object.__new__(Database)
        try:
            db.save_durable_call_state("call_1", {"call": {"id": "call_1"}, "transcripts": []})
            raise AssertionError("Redis NX failure must raise")
        except RuntimeError:
            pass
print("PASS: no fabricated fallback results, local SQLite sync, Redis state NX failure")
