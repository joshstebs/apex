"""A hosted container with Redis must read and write the same call-state store.

Without this, admission reserves the slot in Redis while get_call() reads an empty
local SQLite, so a live call appears missing to its own webhook turns.
"""
import json
import os
import tempfile

os.environ.pop("VERCEL", None)
from config import settings
from database import Database

settings.UPSTASH_REDIS_REST_URL = "https://mock.invalid"
settings.UPSTASH_REDIS_REST_TOKEN = "offline-redis"
settings.MONTHLY_BUDGET_LIMIT_USD = 5.0
settings.MAX_CALL_DURATION_SECONDS = 1200
os.environ["APEX_HOSTED"] = "1"

store = {}


def fake_redis(cmd):
    op = cmd[0]
    if op == "GET":
        return store.get(cmd[1])
    if op == "SET":
        if "NX" in cmd and cmd[1] in store:
            return None
        store[cmd[1]] = cmd[2]
        return "OK"
    if op == "EXISTS":
        return int(cmd[1] in store)
    if op == "DEL":
        store.pop(cmd[1], None)
        return 1
    if op == "PERSIST":
        return 1
    if op == "EXPIRE":
        return 1
    if op == "INCRBYFLOAT":
        store[cmd[1]] = str(float(store.get(cmd[1], 0)) + float(cmd[2]))
        return store[cmd[1]]
    if op in ("LPUSH", "LTRIM", "ZADD", "ZREMRANGEBYRANK", "ZREMRANGEBYSCORE"):
        return 1
    if op == "MGET":
        return [store.get(key) for key in cmd[1:]]
    if op == "EVAL":
        # Minimal stand-in for the admission script: enforce the single slot, then
        # honour the slot and spend writes so a container deployment is checked end to end.
        key_count = int(cmd[2])
        keys = cmd[3:3 + key_count]
        call_id = cmd[-7]
        held = store.get(keys[0])
        if held and held != call_id:
            return 0
        store[keys[0]] = call_id
        store[keys[1]] = str(float(store.get(keys[1], 0)) + float(cmd[-5]))
        return 1
    raise AssertionError(op)


def run():
    with tempfile.TemporaryDirectory() as directory:
        db = Database(os.path.join(directory, "parity.db"))
        original = db._upstash_cmd
        db._upstash_cmd = fake_redis
        call_id = "CA-parity-0001"
        record = {
            "id": call_id,
            "status": "in-progress",
            "assistant_id": "tpl_hm_receptionist",
            "phone_number": "+15195550101",
            "direction": "inbound",
            "provider": "signalwire",
        }

        def state_writer(identifier, payload):
            store[f"apex:call:{identifier}"] = json.dumps(payload)
            return "created"

        db.ensure_durable_call_state = state_writer
        admitted, error, outcome = db.try_acquire_call_slot(record)
        assert admitted is True, (error, outcome)
        assert store.get(Database.ACTIVE_CALL_KEY) == call_id

        # The admission survives in Redis, so the call must be readable there too.
        loaded = db.get_call(call_id)
        assert loaded is not None, "container+Redis reads fell back to empty SQLite"
        assert loaded["id"] == call_id
        assert db.get_call_transcripts(call_id) == []

        # A second concurrent call is still refused while the Redis slot is held.
        rejected, reject_error, _ = db.try_acquire_call_slot(
            {**record, "id": "CA-parity-0002", "phone_number": "+15195550102"}
        )
        assert rejected is False and reject_error
        db._upstash_cmd = original
    print("PASS: container Redis admission is visible to reads and still enforces one call")


if __name__ == "__main__":
    run()
