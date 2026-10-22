"""
Durable Database & State Layer for ApexVoice AI (Vercel Serverless + Local SQLite)
Supports:
1. Upstash Redis / Vercel Marketplace KV (Atomic SET NX concurrency locks, INCRBYFLOAT spend counters, EX TTL clips)
2. Turso Cloud HTTP SQLite (/v2/pipeline transactional SQL over HTTPS)
3. Local SQLite with BEGIN IMMEDIATE transaction locking for local dev/testing
"""
import sqlite3
import json
import time
import secrets
import os
import urllib.request
import urllib.parse
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from config import settings

class Database:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or settings.DB_PATH
        if not os.getenv("VERCEL"):
            self._init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS assistants (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                category TEXT,
                system_prompt TEXT NOT NULL,
                first_message TEXT NOT NULL,
                voice_provider TEXT DEFAULT 'elevenlabs',
                voice_id TEXT DEFAULT '21m00Tcm4TlvDq8ikWAM',
                voice_settings TEXT,
                llm_provider TEXT DEFAULT 'huggingface',
                llm_model TEXT DEFAULT 'meta-llama/Llama-3.1-8B-Instruct',
                temperature REAL DEFAULT 0.4,
                dynamic_variables TEXT,
                tools TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY,
                assistant_id TEXT,
                phone_number TEXT NOT NULL,
                direction TEXT DEFAULT 'inbound',
                provider TEXT DEFAULT 'signalwire',
                status TEXT DEFAULT 'pending',
                goal TEXT,
                dynamic_vars_applied TEXT,
                started_at TIMESTAMP,
                ended_at TIMESTAMP,
                duration_seconds INTEGER DEFAULT 0,
                cost_telephony REAL DEFAULT 0.0,
                cost_llm REAL DEFAULT 0.0,
                cost_tts REAL DEFAULT 0.0,
                cost_total REAL DEFAULT 0.0,
                sentiment_score REAL DEFAULT 0.0,
                outcome_status TEXT,
                extracted_data TEXT,
                recording_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_id TEXT NOT NULL,
                speaker TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                latency_ms INTEGER DEFAULT 0
            )
            """)

            # Short-lived opaque TTS clip table (stores text server-side only, never in URLs)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS tts_clips (
                clip_id TEXT PRIMARY KEY,
                text_content TEXT NOT NULL,
                voice_id TEXT NOT NULL,
                expires_at REAL NOT NULL,
                created_at REAL NOT NULL
            )
            """)
            conn.commit()

    # -------------------------------------------------------------------------
    # UPSTASH REDIS / TURSO CLOUD DURABLE HELPERS
    # -------------------------------------------------------------------------
    def _upstash_cmd(self, command: List[Any]) -> Any:
        if not (settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN):
            return None
        url = settings.UPSTASH_REDIS_REST_URL.rstrip("/")
        req = urllib.request.Request(
            url,
            data=json.dumps(command).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.UPSTASH_REDIS_REST_TOKEN}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                if resp.status == 200:
                    payload = json.loads(resp.read().decode("utf-8"))
                    if payload.get("error"):
                        raise RuntimeError("Durable Redis command rejected")
                    return payload.get("result")
        except Exception as e:
            raise RuntimeError("Durable Redis request failed") from e
        raise RuntimeError("Durable Redis returned an unsuccessful response")

    def _turso_pipeline(self, statements: List[Dict[str, Any]]) -> Optional[List[Any]]:
        if not (settings.TURSO_DATABASE_URL and settings.TURSO_AUTH_TOKEN):
            return None
        http_url = settings.TURSO_DATABASE_URL.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
        requests_list = [{"type": "execute", "stmt": s} for s in statements] + [{"type": "close"}]
        req = urllib.request.Request(
            http_url,
            data=json.dumps({"requests": requests_list}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.TURSO_AUTH_TOKEN}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8")).get("results", [])
        except Exception as e:
            print(f"[Database] Turso pipeline error: {e}")
        return None

    # -------------------------------------------------------------------------
    # SHORT-LIVED OPAQUE AUDIO CLIPS (ZERO CONVERSATION TEXT IN URLS)
    # -------------------------------------------------------------------------
    def create_tts_clip(self, text: str, voice_id: str, ttl_seconds: Optional[int] = None) -> str:
        """
        Stores spoken text under a short-lived cryptographic opaque ID (clip_...).
        Conversation text never appears in any URL.
        """
        ttl = ttl_seconds or settings.TTS_CLIP_TTL_SECONDS
        clip_id = f"clip_{secrets.token_urlsafe(18)}"
        now = time.time()
        expires_at = now + ttl
        payload = {"text": text, "voice_id": voice_id, "expires_at": expires_at}

        # 1. Durable Upstash Redis with native EX expiration
        if settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN:
            self._upstash_cmd(["SET", f"tts_clip:{clip_id}", json.dumps(payload), "EX", str(int(ttl))])

        # 2. Durable Turso HTTP SQLite
        if settings.TURSO_DATABASE_URL and settings.TURSO_AUTH_TOKEN:
            self._turso_pipeline([
                {"sql": "CREATE TABLE IF NOT EXISTS tts_clips (clip_id TEXT PRIMARY KEY, payload TEXT, expires_at REAL)"},
                {
                    "sql": "INSERT OR REPLACE INTO tts_clips (clip_id, payload, expires_at) VALUES (?, ?, ?)",
                    "args": [
                        {"type": "text", "value": clip_id},
                        {"type": "text", "value": json.dumps(payload)},
                        {"type": "float", "value": expires_at}
                    ]
                }
            ])

        # A production clip must be accessible to another invocation.
        if os.getenv("VERCEL"):
            if not (settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN):
                raise RuntimeError("Shared Redis clip storage is required")
            return clip_id
        # 3. Local SQLite
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tts_clips WHERE expires_at < ?", (now,))
            cursor.execute(
                "INSERT OR REPLACE INTO tts_clips (clip_id, text_content, voice_id, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
                (clip_id, text, voice_id, expires_at, now)
            )
            conn.commit()

        return clip_id

    def get_tts_clip(self, clip_id: str) -> Optional[Dict[str, str]]:
        """Retrieves a non-expired TTS clip by its opaque ID."""
        if not clip_id or not clip_id.startswith("clip_"):
            return None
        now = time.time()

        # 1. Check Upstash Redis
        if settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN:
            raw = self._upstash_cmd(["GET", f"tts_clip:{clip_id}"])
            if raw:
                try:
                    data = json.loads(raw)
                    if float(data.get("expires_at", 0)) >= now:
                        return {"text": data["text"], "voice_id": data["voice_id"]}
                except Exception:
                    pass

        # 2. Check Turso HTTP SQLite
        if settings.TURSO_DATABASE_URL and settings.TURSO_AUTH_TOKEN:
            res = self._turso_pipeline([
                {
                    "sql": "SELECT payload, expires_at FROM tts_clips WHERE clip_id = ?",
                    "args": [{"type": "text", "value": clip_id}]
                }
            ])
            if res and len(res) > 0:
                rows = res[0].get("response", {}).get("result", {}).get("rows", [])
                if rows:
                    try:
                        payload_str = rows[0][0].get("value")
                        exp_val = float(rows[0][1].get("value", 0))
                        if exp_val >= now:
                            data = json.loads(payload_str)
                            return {"text": data["text"], "voice_id": data["voice_id"]}
                    except Exception:
                        pass

        # Never serve instance-local clips in a serverless deployment.
        if os.getenv("VERCEL"):
            return None
        # 3. Check Local SQLite
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT text_content, voice_id, expires_at FROM tts_clips WHERE clip_id = ?", (clip_id,))
            row = cursor.fetchone()
            if row and float(row["expires_at"]) >= now:
                return {"text": row["text_content"], "voice_id": row["voice_id"]}
        return None

    # -------------------------------------------------------------------------
    # ATOMIC CONCURRENCY LOCK & SPENDING COUNTERS ACROSS VERCEL INSTANCES
    # -------------------------------------------------------------------------
    def try_acquire_call_slot(self, call_record: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Atomically checks $5.00 monthly budget cap and 1-concurrent-call limit across instances,
        and registers the call as active if permitted.
        """
        call_id = call_record["id"]
        month_key = datetime.utcnow().strftime("%Y-%m")

        # A single Redis Lua operation checks budget and acquires the slot atomically.
        # Reserve a conservative full-call allowance before allowing another call.
        if os.getenv("VERCEL") and settings.durable_storage_backend() != "upstash_redis":
            return False, "Upstash Redis is required for live Vercel calls"
        if settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN:
            reserve = float(os.getenv("APEX_MAX_CALL_RESERVE_USD", "3.00"))
            # Fail closed if a full-duration call cannot fit the configured budget reserve.
            if reserve <= 0 or reserve > settings.MONTHLY_BUDGET_LIMIT_USD:
                return False, "Invalid call budget reservation"
            script = """
            local spent = tonumber(redis.call('GET', KEYS[2]) or '0')
            if spent + tonumber(ARGV[3]) > tonumber(ARGV[4]) then return 0 end
            if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
            redis.call('SET', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[2]))
            redis.call('INCRBYFLOAT', KEYS[2], ARGV[3])
            return 1
            """
            try:
                ok = self._upstash_cmd(["EVAL", script, "2", "apex:active_call_lock",
                                        f"apex:spend:{month_key}", call_id,
                                        str(settings.MAX_CALL_DURATION_SECONDS + 15),
                                        str(reserve), str(settings.MONTHLY_BUDGET_LIMIT_USD)])
            except RuntimeError:
                return False, "Durable budget/lock store unavailable"
            if ok != 1:
                return False, "Concurrent call or budget limit reached"

        if os.getenv("VERCEL"):
            try:
                self.save_durable_call_state(call_id, {"call": call_record, "transcripts": []})
            except Exception:
                # Do not allow a call to proceed without shared state.
                self.release_call_slot(call_id)
                return False, "Durable call state unavailable"
            return True, None

        # 2. Local SQLite BEGIN IMMEDIATE atomic check + insert
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            try:
                cursor.execute("SELECT COALESCE(SUM(cost_total), 0.0) as total FROM calls")
                spend = float(cursor.fetchone()["total"])
                if settings.durable_storage_backend() != "upstash_redis" and spend >= settings.MONTHLY_BUDGET_LIMIT_USD:
                    conn.rollback()
                    return False, f"Monthly budget limit of ${settings.MONTHLY_BUDGET_LIMIT_USD:.2f} USD reached."

                cursor.execute(
                    "SELECT COUNT(*) as cnt FROM calls WHERE status IN ('ringing', 'in-progress') AND id != ?",
                    (call_id,)
                )
                active_cnt = int(cursor.fetchone()["cnt"])
                if settings.durable_storage_backend() != "upstash_redis" and active_cnt >= settings.MAX_CONCURRENT_CALLS:
                    conn.rollback()
                    return False, f"Maximum concurrent call limit ({settings.MAX_CONCURRENT_CALLS}) reached."

                cursor.execute("""
                INSERT OR REPLACE INTO calls (
                    id, assistant_id, phone_number, direction, provider, status,
                    goal, dynamic_vars_applied, started_at, duration_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """, (
                    call_id,
                    call_record.get("assistant_id"),
                    call_record["phone_number"],
                    call_record.get("direction", "inbound"),
                    call_record.get("provider", "signalwire"),
                    call_record.get("status", "in-progress"),
                    call_record.get("goal", ""),
                    json.dumps(call_record.get("dynamic_vars_applied", {})),
                    datetime.utcnow().isoformat()
                ))
                conn.commit()
            except Exception as e:
                conn.rollback()
                if settings.durable_storage_backend() == "upstash_redis":
                    self.release_call_slot(call_id)
                return False, str(e)

        # Persist initial durable state
        self.save_durable_call_state(call_id, {
            "call": call_record,
            "transcripts": []
        })
        return True, None

    def release_call_slot(self, call_id: str, cost_delta: float = 0.0):
        """Release only the owning call's slot; refund unused reserved budget once."""
        if settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN:
            month_key = datetime.utcnow().strftime("%Y-%m")
            reserve = float(os.getenv("APEX_MAX_CALL_RESERVE_USD", "3.00"))
            # Fail closed if a full-duration call cannot fit the configured budget reserve.
            if reserve <= 0 or reserve > settings.MONTHLY_BUDGET_LIMIT_USD:
                return False, "Invalid call budget reservation"
            script = """
            if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
            redis.call('DEL', KEYS[1])
            redis.call('INCRBYFLOAT', KEYS[2], ARGV[2])
            return 1
            """
            try:
                self._upstash_cmd(["EVAL", script, "2", "apex:active_call_lock",
                                   f"apex:spend:{month_key}", call_id,
                                   str(max(0.0, cost_delta) - reserve)])
            except RuntimeError:
                # Do not permit another call if durable accounting cannot be updated.
                pass

    def save_durable_call_state(self, call_id: str, state_payload: Dict[str, Any]):
        """Creates initial state; subsequent mutations use atomic Redis updates."""
        if settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN:
            created = self._upstash_cmd(["SET", f"apex:call:{call_id}", json.dumps(state_payload), "EX", "86400", "NX"])
            if created != "OK":
                raise RuntimeError("Could not create unique durable call state")
        if settings.TURSO_DATABASE_URL and settings.TURSO_AUTH_TOKEN:
            self._turso_pipeline([
                {"sql": "CREATE TABLE IF NOT EXISTS durable_calls (call_id TEXT PRIMARY KEY, state_json TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"},
                {
                    "sql": "INSERT OR REPLACE INTO durable_calls (call_id, state_json, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                    "args": [
                        {"type": "text", "value": call_id},
                        {"type": "text", "value": json.dumps(state_payload)}
                    ]
                }
            ])

    def _atomic_update_state(self, call_id: str, updates=None, transcript=None):
        if not (settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN):
            raise RuntimeError("Shared Redis is required for production call state")
        script = """
        local raw = redis.call('GET', KEYS[1])
        if not raw then return 0 end
        local state = cjson.decode(raw)
        local updates = cjson.decode(ARGV[1])
        for k,v in pairs(updates) do state.call[k] = v end
        if ARGV[2] ~= '' then
          local msg = cjson.decode(ARGV[2])
          table.insert(state.transcripts, msg)
        end
        redis.call('SET', KEYS[1], cjson.encode(state), 'EX', 86400)
        return 1
        """
        result = self._upstash_cmd(["EVAL", script, "1", f"apex:call:{call_id}",
                                   json.dumps(updates or {}), json.dumps(transcript) if transcript else ""])
        if result != 1:
            raise RuntimeError("Call state missing; refusing unsafe local fallback")

    def load_durable_call_state(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Loads durable call state across Vercel instances if local SQLite does not have it."""
        if settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN:
            raw = self._upstash_cmd(["GET", f"apex:call:{call_id}"])
            if raw:
                try:
                    return json.loads(raw)
                except Exception:
                    pass
        if settings.TURSO_DATABASE_URL and settings.TURSO_AUTH_TOKEN:
            res = self._turso_pipeline([
                {
                    "sql": "SELECT state_json FROM durable_calls WHERE call_id = ?",
                    "args": [{"type": "text", "value": call_id}]
                }
            ])
            if res and len(res) > 0:
                rows = res[0].get("response", {}).get("result", {}).get("rows", [])
                if rows:
                    try:
                        return json.loads(rows[0][0].get("value"))
                    except Exception:
                        pass
        return None

    # -------------------------------------------------------------------------
    # STANDARD CRUD OPERATIONS
    # -------------------------------------------------------------------------
    def create_or_update_assistant(self, assistant_data: Dict[str, Any]) -> str:
        if os.getenv("VERCEL"):
            raise RuntimeError("Assistant editing disabled in serverless mode; edit version-controlled prompt templates")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO assistants (
                id, name, description, category, system_prompt, first_message,
                voice_provider, voice_id, voice_settings, llm_provider, llm_model,
                temperature, dynamic_variables, tools, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                description=excluded.description,
                category=excluded.category,
                system_prompt=excluded.system_prompt,
                first_message=excluded.first_message,
                voice_provider=excluded.voice_provider,
                voice_id=excluded.voice_id,
                voice_settings=excluded.voice_settings,
                llm_provider=excluded.llm_provider,
                llm_model=excluded.llm_model,
                temperature=excluded.temperature,
                dynamic_variables=excluded.dynamic_variables,
                tools=excluded.tools,
                updated_at=CURRENT_TIMESTAMP
            """, (
                assistant_data["id"],
                assistant_data["name"],
                assistant_data.get("description", ""),
                assistant_data.get("category", "custom"),
                assistant_data["system_prompt"],
                assistant_data.get("first_message", "Hello!"),
                assistant_data.get("voice_provider", "elevenlabs"),
                assistant_data.get("voice_id", "21m00Tcm4TlvDq8ikWAM"),
                json.dumps(assistant_data.get("voice_settings", {"stability": 0.5, "similarity_boost": 0.75})),
                assistant_data.get("llm_provider", "huggingface"),
                assistant_data.get("llm_model", "meta-llama/Llama-3.1-8B-Instruct"),
                assistant_data.get("temperature", 0.4),
                json.dumps(assistant_data.get("dynamic_variables", [])),
                json.dumps(assistant_data.get("tools", []))
            ))
            conn.commit()
            return assistant_data["id"]

    def get_assistant(self, assistant_id: str) -> Optional[Dict[str, Any]]:
        if os.getenv("VERCEL"):
            return next((a for a in self.list_assistants() if a.get("id") == assistant_id), None)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM assistants WHERE id = ?", (assistant_id,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                d["voice_settings"] = json.loads(d["voice_settings"]) if d["voice_settings"] else {}
                d["dynamic_variables"] = json.loads(d["dynamic_variables"]) if d["dynamic_variables"] else []
                d["tools"] = json.loads(d["tools"]) if d["tools"] else []
                return d
            return None

    def list_assistants(self) -> List[Dict[str, Any]]:
        if os.getenv("VERCEL"):
            from pathlib import Path
            return [json.loads(f.read_text()) for f in sorted((Path(__file__).parent / "prompts").glob("*.json"))]
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM assistants ORDER BY updated_at DESC")
            results = []
            for row in cursor.fetchall():
                d = dict(row)
                d["voice_settings"] = json.loads(d["voice_settings"]) if d["voice_settings"] else {}
                d["dynamic_variables"] = json.loads(d["dynamic_variables"]) if d["dynamic_variables"] else []
                d["tools"] = json.loads(d["tools"]) if d["tools"] else []
                results.append(d)
            return results

    def create_call(self, call_data: Dict[str, Any]) -> str:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO calls (
                id, assistant_id, phone_number, direction, provider, status,
                goal, dynamic_vars_applied, started_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                call_data["id"],
                call_data.get("assistant_id"),
                call_data["phone_number"],
                call_data.get("direction", "inbound"),
                call_data.get("provider", "signalwire"),
                call_data.get("status", "in-progress"),
                call_data.get("goal", ""),
                json.dumps(call_data.get("dynamic_vars_applied", {})),
                datetime.utcnow().isoformat()
            ))
            conn.commit()
            return call_data["id"]

    def update_call(self, call_id: str, updates: Dict[str, Any]):
        if os.getenv("VERCEL"):
            allowed = {"status", "ended_at", "duration_seconds", "cost_telephony", "cost_llm", "cost_tts", "cost_total", "extracted_data", "outcome_status"}
            if set(updates) - allowed:
                raise ValueError("Invalid call update field")
            self._atomic_update_state(call_id, updates=updates)
            return
        fields = []
        params = []
        for k, v in updates.items():
            if k in ["dynamic_vars_applied", "extracted_data"] and isinstance(v, (dict, list)):
                v = json.dumps(v)
            fields.append(f"{k} = ?")
            params.append(v)
        params.append(call_id)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE calls SET {', '.join(fields)} WHERE id = ?", params)
            conn.commit()

    def get_call(self, call_id: str) -> Optional[Dict[str, Any]]:
        if os.getenv("VERCEL"):
            state = self.load_durable_call_state(call_id)
            return state.get("call") if state else None
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            for key in ("dynamic_vars_applied", "extracted_data"):
                data[key] = json.loads(data[key]) if data.get(key) else {}
            return data

    def list_calls(self, limit: int = 50) -> List[Dict[str, Any]]:
        if os.getenv("VERCEL"):
            raise RuntimeError("Call listing requires a durable indexed store; not implemented")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT c.*, a.name as assistant_name 
            FROM calls c
            LEFT JOIN assistants a ON c.assistant_id = a.id
            ORDER BY c.created_at DESC LIMIT ?
            """, (limit,))
            results = []
            for row in cursor.fetchall():
                d = dict(row)
                d["dynamic_vars_applied"] = json.loads(d["dynamic_vars_applied"]) if d["dynamic_vars_applied"] else {}
                d["extracted_data"] = json.loads(d["extracted_data"]) if d["extracted_data"] else {}
                results.append(d)
            return results

    def add_transcript_message(self, call_id: str, speaker: str, message: str, latency_ms: int = 0):
        if os.getenv("VERCEL"):
            self._atomic_update_state(call_id, transcript={"speaker": speaker, "message": message, "latency_ms": latency_ms, "timestamp": datetime.utcnow().isoformat()})
            return
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO transcripts (call_id, speaker, message, latency_ms)
            VALUES (?, ?, ?, ?)
            """, (call_id, speaker, message, latency_ms))
            conn.commit()

    def get_call_transcripts(self, call_id: str) -> List[Dict[str, Any]]:
        if os.getenv("VERCEL"):
            state = self.load_durable_call_state(call_id)
            return state.get("transcripts", []) if state else []
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transcripts WHERE call_id = ? ORDER BY id ASC", (call_id,))
            return [dict(r) for r in cursor.fetchall()]

    def count_active_calls(self) -> int:
        if settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN:
            holder = self._upstash_cmd(["GET", "apex:active_call_lock"])
            return 1 if holder else 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM calls WHERE status IN ('ringing', 'in-progress')")
            row = cursor.fetchone()
            return int(row["cnt"]) if row else 0

    def get_monthly_spend(self) -> float:
        month_key = datetime.utcnow().strftime("%Y-%m")
        if settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN:
            spend_raw = self._upstash_cmd(["GET", f"apex:spend:{month_key}"])
            if spend_raw is not None:
                return round(float(spend_raw), 4)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COALESCE(SUM(cost_total), 0.0) as total FROM calls")
            row = cursor.fetchone()
            return round(float(row["total"]), 4) if row else 0.0
