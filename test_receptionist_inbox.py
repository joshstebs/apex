import json
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app, db, settings


def run():
    client = TestClient(app)
    message = {"call_id": "example", "message": {"caller_name": "Sam"}}
    headers = {"Authorization": "Bearer offline-admin"}
    with (
        patch.dict(os.environ, {"APEX_ADMIN_TOKEN": "offline-admin"}),
        patch.object(settings, "UPSTASH_REDIS_REST_URL", "https://redis.invalid"),
        patch.object(settings, "UPSTASH_REDIS_REST_TOKEN", "offline-redis"),
        patch.object(db, "_upstash_cmd", return_value=[json.dumps(message)]) as command,
    ):
        assert client.get("/api/receptionist/messages").status_code == 401
        command.assert_not_called()
        response = client.get("/api/receptionist/messages", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json() == {"messages": [message]}
        assert response.headers["Cache-Control"] == "private, no-store"
        command.side_effect = RuntimeError("Redis unavailable")
        assert client.get("/api/receptionist/messages", headers=headers).status_code == 503

    with (
        patch.object(settings, "UPSTASH_REDIS_REST_URL", "https://redis.invalid"),
        patch.object(settings, "UPSTASH_REDIS_REST_TOKEN", "offline-redis"),
        patch.object(db, "_upstash_cmd", return_value=1) as command,
    ):
        db._atomic_update_state("example", updates={"extracted_data": {"save_receptionist_message": {"reason": "Call back"}}})
        args = command.call_args.args[0]
        assert args[2:5] == ["2", "apex:call:example", "apex:receptionist_messages"]
        assert json.loads(args[5])["extracted_data"]["save_receptionist_message"]["reason"] == "Call back"


if __name__ == "__main__":
    run()
    print("PASS: authenticated receptionist inbox and atomic index wiring")
