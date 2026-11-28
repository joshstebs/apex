"""Container deployment with a mounted SQLite volume must complete a whole call.

This is the primary deployment mode now that Vercel is unavailable: no Redis, a
persistent /data volume, and APEX_HOSTED=1. Admission, a conversation turn and
carrier settlement must all work against one consistent local store.
"""
import os
import tempfile

os.environ.pop("VERCEL", None)
os.environ.pop("CLOUDFLARE_WORKERS", None)
os.environ["APEX_HOSTED"] = "1"
os.environ["APEX_ENVIRONMENT"] = "production"
from config import settings
from database import Database

settings.UPSTASH_REDIS_REST_URL = ""
settings.UPSTASH_REDIS_REST_TOKEN = ""
settings.STAGING = False
settings.APEX_ENVIRONMENT = "production"
settings.TELEPHONY_PROVIDER = "signalwire"
settings.RECEPTIONIST_ENABLED = True
settings.MONTHLY_BUDGET_LIMIT_USD = 5.0
settings.MAX_CALL_DURATION_SECONDS = 1200


def run():
    assert settings.durable_storage_usable() is True, "a container with a volume is durable"
    assert settings.inbound_live_calls_possible() is True

    with tempfile.TemporaryDirectory() as volume:
        db = Database(os.path.join(volume, "voice_agents.db"))
        assert db.uses_shared_state() is False, "a local-volume container uses SQLite"

        call_id = "CA-container-0001"
        record = {
            "id": call_id,
            "status": "in-progress",
            "assistant_id": "tpl_hm_receptionist",
            "phone_number": "+15195550101",
            "direction": "inbound",
            "provider": "signalwire",
        }
        admitted, error, outcome = db.try_acquire_call_slot(record)
        assert admitted is True, (error, outcome)
        assert outcome == "created"
        assert db.get_call(call_id) is not None, "admission must be readable locally"

        # A second call is refused by the single-call limit.
        second, second_error, _ = db.try_acquire_call_slot(
            {**record, "id": "CA-container-0002", "phone_number": "+15195550102"}
        )
        assert second is False and second_error

        # The conversation is stored and readable.
        db.add_transcript_message(call_id, "assistant", "Thank you for calling.")
        db.add_transcript_message(call_id, "human", "I need a quote.")
        transcripts = db.get_call_transcripts(call_id)
        assert [t["message"] for t in transcripts] == ["Thank you for calling.", "I need a quote."]

        db.update_call(call_id, {"duration_seconds": 45, "cost_total": 0.02})
        assert db.get_call(call_id)["duration_seconds"] == 45

        # Local settlement releases the slot so the next caller can be admitted.
        released, release_error, release_outcome = db.release_call_slot(call_id, 0.02)
        assert released is True, release_error
        assert release_outcome == "released"
        db.update_call(call_id, {"status": "completed"})

        third, third_error, third_outcome = db.try_acquire_call_slot(
            {**record, "id": "CA-container-0003", "phone_number": "+15195550103"}
        )
        assert third is True, (third_error, third_outcome)
        assert third_outcome == "created"

        # Recent calls feed the dashboard from the same store.
        assert any(c["id"] == call_id for c in db.list_recent_calls())
    print("PASS: container volume deployment admits, converses, settles and frees the slot")


if __name__ == "__main__":
    run()
