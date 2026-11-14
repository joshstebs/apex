"""Vercel dashboard with no Redis must not open SQLite or return HTTP 500."""
import io
import os
import sqlite3
from contextlib import redirect_stderr
from unittest.mock import patch

os.environ["VERCEL"] = "1"
os.environ["APEX_ADMIN_TOKEN"] = "dashboard-no-redis-token"
os.environ["APEX_ENVIRONMENT"] = "staging"
os.environ["DB_PATH"] = "/workspace/readonly-not-created.db"
os.environ["UPSTASH_REDIS_REST_URL"] = ""
os.environ["UPSTASH_REDIS_REST_TOKEN"] = ""
os.environ.pop("KV_REST_API_URL", None)
os.environ.pop("KV_REST_API_TOKEN", None)

from fastapi.testclient import TestClient
from app import app, db, settings

client = TestClient(app)
good = {"Authorization": "Bearer dashboard-no-redis-token"}


def run():
    assert settings.STAGING is True
    assert settings.DB_PATH == "/workspace/readonly-not-created.db"
    assert not os.path.exists(settings.DB_PATH)
    health = client.get("/api/health")
    assert health.status_code == 200, health.text
    body = health.json()
    assert body["redis_configured"] is False
    assert body["redis_reachable"] is False
    assert body["durable_storage_backend"] == "local_sqlite"
    assert "UPSTASH_REDIS_REST_TOKEN=" not in health.text

    assert client.get("/api/dashboard").status_code == 401
    assert client.get("/api/dashboard", headers={"Authorization": "Bearer wrong"}).status_code == 401
    captured = io.StringIO()
    with redirect_stderr(captured):
        response = client.get("/api/dashboard", headers=good)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["budget"]["spend_usd"] is None
    assert "budget" in payload["unavailable"]
    assert any("UPSTASH_REDIS_REST_URL" in note for note in payload["notices"])
    assert not os.path.exists(settings.DB_PATH)
    # A SQLite failure must degrade and be logged, not become an empty 500.
    settings.UPSTASH_REDIS_REST_URL = "https://redis.invalid"
    settings.UPSTASH_REDIS_REST_TOKEN = "present"
    try:
        with redirect_stderr(captured):
            with patch.object(db, "get_monthly_spend", side_effect=sqlite3.OperationalError("no such table: calls")):
                failed = client.get("/api/dashboard", headers=good)
        assert failed.status_code == 200, failed.text
        assert "budget" in failed.json()["unavailable"]
        assert "no such table: calls" in captured.getvalue()
        assert "dashboard-no-redis-token" not in captured.getvalue()
    finally:
        settings.UPSTASH_REDIS_REST_URL = ""
        settings.UPSTASH_REDIS_REST_TOKEN = ""
    print("PASS: dashboard without Redis returns a clear notice and logs SQLite failures")


if __name__ == "__main__":
    run()
