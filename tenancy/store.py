"""Tenant-scoped storage for the ApexVoice tenancy layer.

Two implementations with identical behaviour:

- InMemoryStore for tests and local development.
- SQLiteStore for durable standalone use and migration rehearsal.

Isolation rule: every record read, list, update, and delete takes an
explicit tenant_id and filters by it. A record that exists under another
tenant is indistinguishable from a record that does not exist, so
cross-tenant identifier guessing returns not found, never data.

The SQLite design keeps tenants, configs, phone mappings, users, and
sessions in their own tables, and all tenant-owned records in one generic
records table. Every table that holds tenant data has a tenant_id column
with an index, and record lookups are always (tenant_id, kind, id).
"""

import copy
import json
import os
import sqlite3
from contextlib import contextmanager

from .errors import Conflict, NotFound
from .models import (
    RECORD_KINDS, PhoneMapping, Session, Tenant, TenantConfig, User, now_iso,
)


class TenantStore:
    """Protocol describing the store surface. Not instantiated directly."""

    # tenants (platform level: the tenants table is the registry itself)
    def create_tenant(self, tenant): raise NotImplementedError
    def get_tenant(self, tenant_id): raise NotImplementedError
    def update_tenant(self, tenant): raise NotImplementedError
    def list_tenants(self, status=None): raise NotImplementedError
    def purge_tenant(self, tenant_id): raise NotImplementedError

    # configuration
    def put_config(self, tenant_config): raise NotImplementedError
    def get_config(self, tenant_id): raise NotImplementedError

    # phone mappings
    def add_phone_mapping(self, mapping): raise NotImplementedError
    def get_phone_mapping(self, did): raise NotImplementedError
    def list_phone_mappings(self, tenant_id): raise NotImplementedError
    def remove_phone_mapping(self, tenant_id, did): raise NotImplementedError

    # users and sessions
    def create_user(self, user): raise NotImplementedError
    def get_user(self, tenant_id, user_id): raise NotImplementedError
    def get_user_by_email(self, tenant_id, email): raise NotImplementedError
    def find_user_by_email(self, email): raise NotImplementedError
    def list_users(self, tenant_id): raise NotImplementedError
    def update_user(self, user): raise NotImplementedError
    def delete_user(self, tenant_id, user_id): raise NotImplementedError
    def put_session(self, session): raise NotImplementedError
    def get_session_by_token_hash(self, token_hash): raise NotImplementedError
    def update_session(self, session): raise NotImplementedError
    def delete_sessions_for_user(self, tenant_id, user_id): raise NotImplementedError

    # generic tenant-owned records
    def put_record(self, kind, record): raise NotImplementedError
    def get_record(self, tenant_id, kind, record_id): raise NotImplementedError
    def list_records(self, tenant_id, kind): raise NotImplementedError
    def update_record(self, tenant_id, kind, record): raise NotImplementedError
    def delete_record(self, tenant_id, kind, record_id): raise NotImplementedError

    # platform audit log
    def append_audit(self, entry): raise NotImplementedError
    def list_audit(self, tenant_id=None): raise NotImplementedError


def _record_class(kind):
    if kind not in RECORD_KINDS:
        raise ValueError(f"unknown record kind: {kind}")
    return RECORD_KINDS[kind]


class InMemoryStore(TenantStore):
    def __init__(self):
        self._tenants = {}
        self._configs = {}
        self._phones = {}
        self._users = {}
        self._sessions = {}
        self._records = {}
        self._audit = []

    # tenants
    def create_tenant(self, tenant):
        if tenant.id in self._tenants:
            raise Conflict("tenant already exists")
        self._tenants[tenant.id] = copy.deepcopy(tenant)
        return tenant

    def get_tenant(self, tenant_id):
        found = self._tenants.get(tenant_id)
        return copy.deepcopy(found) if found else None

    def update_tenant(self, tenant):
        if tenant.id not in self._tenants:
            raise NotFound("tenant not found")
        tenant.updated_at = now_iso()
        self._tenants[tenant.id] = copy.deepcopy(tenant)
        return tenant

    def list_tenants(self, status=None):
        out = [copy.deepcopy(t) for t in self._tenants.values()
               if status is None or t.status == status]
        return sorted(out, key=lambda t: t.id)

    def purge_tenant(self, tenant_id):
        self._tenants.pop(tenant_id, None)
        self._configs.pop(tenant_id, None)
        self._phones = {d: m for d, m in self._phones.items() if m.tenant_id != tenant_id}
        self._users = {k: u for k, u in self._users.items() if u.tenant_id != tenant_id}
        self._sessions = {k: s for k, s in self._sessions.items() if s.tenant_id != tenant_id}
        self._records = {k: r for k, r in self._records.items() if r.tenant_id != tenant_id}

    # configuration
    def put_config(self, tenant_config):
        self._configs[tenant_config.tenant_id] = copy.deepcopy(tenant_config)
        return tenant_config

    def get_config(self, tenant_id):
        found = self._configs.get(tenant_id)
        return copy.deepcopy(found) if found else None

    # phone mappings
    def add_phone_mapping(self, mapping):
        existing = self._phones.get(mapping.did)
        if existing and existing.tenant_id != mapping.tenant_id:
            raise Conflict("phone number already assigned to another tenant")
        self._phones[mapping.did] = copy.deepcopy(mapping)
        return mapping

    def get_phone_mapping(self, did):
        found = self._phones.get(did)
        return copy.deepcopy(found) if found else None

    def list_phone_mappings(self, tenant_id):
        return [copy.deepcopy(m) for m in self._phones.values() if m.tenant_id == tenant_id]

    def remove_phone_mapping(self, tenant_id, did):
        found = self._phones.get(did)
        if not found or found.tenant_id != tenant_id:
            return False
        del self._phones[did]
        return True

    # users and sessions
    def create_user(self, user):
        key = (user.tenant_id, user.id)
        if key in self._users:
            raise Conflict("user already exists")
        for other in self._users.values():
            if other.tenant_id == user.tenant_id and other.email == user.email:
                raise Conflict("email already registered for this tenant")
        self._users[key] = copy.deepcopy(user)
        return user

    def get_user(self, tenant_id, user_id):
        found = self._users.get((tenant_id, user_id))
        return copy.deepcopy(found) if found else None

    def get_user_by_email(self, tenant_id, email):
        email = email.strip().lower()
        for user in self._users.values():
            if user.tenant_id == tenant_id and user.email == email:
                return copy.deepcopy(user)
        return None

    def find_user_by_email(self, email):
        email = email.strip().lower()
        matches = [u for u in self._users.values() if u.email == email]
        return copy.deepcopy(matches[0]) if matches else None

    def list_users(self, tenant_id):
        return [copy.deepcopy(u) for u in self._users.values() if u.tenant_id == tenant_id]

    def update_user(self, user):
        key = (user.tenant_id, user.id)
        if key not in self._users:
            raise NotFound("user not found")
        self._users[key] = copy.deepcopy(user)
        return user

    def delete_user(self, tenant_id, user_id):
        return self._users.pop((tenant_id, user_id), None) is not None

    def put_session(self, session):
        self._sessions[session.token_hash] = copy.deepcopy(session)
        return session

    def get_session_by_token_hash(self, token_hash):
        found = self._sessions.get(token_hash)
        return copy.deepcopy(found) if found else None

    def update_session(self, session):
        if session.token_hash not in self._sessions:
            raise NotFound("session not found")
        self._sessions[session.token_hash] = copy.deepcopy(session)
        return session

    def delete_sessions_for_user(self, tenant_id, user_id):
        keys = [k for k, s in self._sessions.items()
                if s.tenant_id == tenant_id and s.user_id == user_id]
        for key in keys:
            del self._sessions[key]
        return len(keys)

    # generic records
    def put_record(self, kind, record):
        _record_class(kind)
        self._records[(record.tenant_id, kind, record.id)] = copy.deepcopy(record)
        return record

    def get_record(self, tenant_id, kind, record_id):
        found = self._records.get((tenant_id, kind, record_id))
        return copy.deepcopy(found) if found else None

    def list_records(self, tenant_id, kind):
        out = [copy.deepcopy(r) for (tid, k, _), r in self._records.items()
               if tid == tenant_id and k == kind]
        return sorted(out, key=lambda r: r.id)

    def update_record(self, tenant_id, kind, record):
        key = (tenant_id, kind, record.id)
        if key not in self._records or record.tenant_id != tenant_id:
            return False
        self._records[key] = copy.deepcopy(record)
        return True

    def delete_record(self, tenant_id, kind, record_id):
        return self._records.pop((tenant_id, kind, record_id), None) is not None

    # audit
    def append_audit(self, entry):
        self._audit.append(copy.deepcopy(entry))
        return entry

    def list_audit(self, tenant_id=None):
        return [copy.deepcopy(e) for e in self._audit
                if tenant_id is None or e.get("tenant_id") == tenant_id]


class SQLiteStore(TenantStore):
    """SQLite implementation. Same semantics as InMemoryStore.

    Tables: tenants, tenant_configs, phone_mappings, tenant_users,
    sessions, records (generic, payload JSON), audit_log. tenant_id is a
    column with an index on every tenant-owned table.
    """

    def __init__(self, db_path=":memory:"):
        self.db_path = db_path
        self._memory_conn = None
        if db_path == ":memory:":
            # A named in-memory database vanishes when its connection
            # closes, so in-memory stores hold one shared connection.
            self._memory_conn = sqlite3.connect(":memory:")
            self._memory_conn.row_factory = sqlite3.Row
        elif db_path:
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self):
        if self._memory_conn is not None:
            with self._memory_conn:
                yield self._memory_conn
            return
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS tenants (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tenant_configs (
                tenant_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                version INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS phone_mappings (
                did TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_phones_tenant ON phone_mappings(tenant_id);
            CREATE TABLE IF NOT EXISTS tenant_users (
                tenant_id TEXT NOT NULL, id TEXT NOT NULL, email TEXT NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY (tenant_id, id));
            CREATE INDEX IF NOT EXISTS idx_users_tenant ON tenant_users(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_users_email ON tenant_users(email);
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                user_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_sessions_tenant ON sessions(tenant_id);
            CREATE TABLE IF NOT EXISTS records (
                tenant_id TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL,
                payload TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, kind, id));
            CREATE INDEX IF NOT EXISTS idx_records_tenant_kind ON records(tenant_id, kind);
            CREATE TABLE IF NOT EXISTS audit_log (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT,
                payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log(tenant_id);
            """)

    @staticmethod
    def _dump(obj):
        return json.dumps(obj.to_dict())

    # tenants
    def create_tenant(self, tenant):
        with self._conn() as conn:
            if conn.execute("SELECT 1 FROM tenants WHERE id=?", (tenant.id,)).fetchone():
                raise Conflict("tenant already exists")
            conn.execute("INSERT INTO tenants VALUES (?,?,?,?)",
                         (tenant.id, self._dump(tenant), tenant.status, tenant.created_at))
        return tenant

    def get_tenant(self, tenant_id):
        with self._conn() as conn:
            row = conn.execute("SELECT payload FROM tenants WHERE id=?", (tenant_id,)).fetchone()
        return Tenant.from_dict(json.loads(row["payload"])) if row else None

    def update_tenant(self, tenant):
        tenant.updated_at = now_iso()
        with self._conn() as conn:
            cur = conn.execute("UPDATE tenants SET payload=?, status=? WHERE id=?",
                               (self._dump(tenant), tenant.status, tenant.id))
            if cur.rowcount == 0:
                raise NotFound("tenant not found")
        return tenant

    def list_tenants(self, status=None):
        with self._conn() as conn:
            if status is None:
                rows = conn.execute("SELECT payload FROM tenants ORDER BY id").fetchall()
            else:
                rows = conn.execute("SELECT payload FROM tenants WHERE status=? ORDER BY id",
                                    (status,)).fetchall()
        return [Tenant.from_dict(json.loads(r["payload"])) for r in rows]

    def purge_tenant(self, tenant_id):
        with self._conn() as conn:
            conn.execute("DELETE FROM tenants WHERE id=?", (tenant_id,))
            conn.execute("DELETE FROM tenant_configs WHERE tenant_id=?", (tenant_id,))
            conn.execute("DELETE FROM phone_mappings WHERE tenant_id=?", (tenant_id,))
            conn.execute("DELETE FROM tenant_users WHERE tenant_id=?", (tenant_id,))
            conn.execute("DELETE FROM sessions WHERE tenant_id=?", (tenant_id,))
            conn.execute("DELETE FROM records WHERE tenant_id=?", (tenant_id,))

    # configuration
    def put_config(self, tenant_config):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO tenant_configs VALUES (?,?,?)",
                (tenant_config.tenant_id, self._dump(tenant_config), tenant_config.version))
        return tenant_config

    def get_config(self, tenant_id):
        with self._conn() as conn:
            row = conn.execute("SELECT payload FROM tenant_configs WHERE tenant_id=?",
                               (tenant_id,)).fetchone()
        return TenantConfig.from_dict(json.loads(row["payload"])) if row else None

    # phone mappings
    def add_phone_mapping(self, mapping):
        with self._conn() as conn:
            row = conn.execute("SELECT tenant_id FROM phone_mappings WHERE did=?",
                               (mapping.did,)).fetchone()
            if row and row["tenant_id"] != mapping.tenant_id:
                raise Conflict("phone number already assigned to another tenant")
            conn.execute("INSERT OR REPLACE INTO phone_mappings VALUES (?,?,?)",
                         (mapping.did, mapping.tenant_id, self._dump(mapping)))
        return mapping

    def get_phone_mapping(self, did):
        with self._conn() as conn:
            row = conn.execute("SELECT payload FROM phone_mappings WHERE did=?", (did,)).fetchone()
        return PhoneMapping.from_dict(json.loads(row["payload"])) if row else None

    def list_phone_mappings(self, tenant_id):
        with self._conn() as conn:
            rows = conn.execute("SELECT payload FROM phone_mappings WHERE tenant_id=?",
                                (tenant_id,)).fetchall()
        return [PhoneMapping.from_dict(json.loads(r["payload"])) for r in rows]

    def remove_phone_mapping(self, tenant_id, did):
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM phone_mappings WHERE did=? AND tenant_id=?",
                               (did, tenant_id))
            return cur.rowcount > 0

    # users and sessions
    def create_user(self, user):
        with self._conn() as conn:
            if conn.execute("SELECT 1 FROM tenant_users WHERE tenant_id=? AND id=?",
                            (user.tenant_id, user.id)).fetchone():
                raise Conflict("user already exists")
            if conn.execute("SELECT 1 FROM tenant_users WHERE tenant_id=? AND email=?",
                            (user.tenant_id, user.email)).fetchone():
                raise Conflict("email already registered for this tenant")
            conn.execute("INSERT INTO tenant_users VALUES (?,?,?,?)",
                         (user.tenant_id, user.id, user.email, self._dump(user)))
        return user

    def get_user(self, tenant_id, user_id):
        with self._conn() as conn:
            row = conn.execute("SELECT payload FROM tenant_users WHERE tenant_id=? AND id=?",
                               (tenant_id, user_id)).fetchone()
        return User.from_dict(json.loads(row["payload"])) if row else None

    def get_user_by_email(self, tenant_id, email):
        with self._conn() as conn:
            row = conn.execute("SELECT payload FROM tenant_users WHERE tenant_id=? AND email=?",
                               (tenant_id, email.strip().lower())).fetchone()
        return User.from_dict(json.loads(row["payload"])) if row else None

    def find_user_by_email(self, email):
        with self._conn() as conn:
            row = conn.execute("SELECT payload FROM tenant_users WHERE email=? ORDER BY tenant_id LIMIT 1",
                               (email.strip().lower(),)).fetchone()
        return User.from_dict(json.loads(row["payload"])) if row else None

    def list_users(self, tenant_id):
        with self._conn() as conn:
            rows = conn.execute("SELECT payload FROM tenant_users WHERE tenant_id=?",
                                (tenant_id,)).fetchall()
        return [User.from_dict(json.loads(r["payload"])) for r in rows]

    def update_user(self, user):
        with self._conn() as conn:
            cur = conn.execute("UPDATE tenant_users SET email=?, payload=? WHERE tenant_id=? AND id=?",
                               (user.email, self._dump(user), user.tenant_id, user.id))
            if cur.rowcount == 0:
                raise NotFound("user not found")
        return user

    def delete_user(self, tenant_id, user_id):
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM tenant_users WHERE tenant_id=? AND id=?",
                               (tenant_id, user_id))
            return cur.rowcount > 0

    def put_session(self, session):
        with self._conn() as conn:
            conn.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?)",
                         (session.token_hash, session.tenant_id, session.user_id, self._dump(session)))
        return session

    def get_session_by_token_hash(self, token_hash):
        with self._conn() as conn:
            row = conn.execute("SELECT payload FROM sessions WHERE token_hash=?",
                               (token_hash,)).fetchone()
        return Session.from_dict(json.loads(row["payload"])) if row else None

    def update_session(self, session):
        with self._conn() as conn:
            cur = conn.execute("UPDATE sessions SET payload=? WHERE token_hash=?",
                               (self._dump(session), session.token_hash))
            if cur.rowcount == 0:
                raise NotFound("session not found")
        return session

    def delete_sessions_for_user(self, tenant_id, user_id):
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE tenant_id=? AND user_id=?",
                               (tenant_id, user_id))
            return cur.rowcount

    # generic records
    def put_record(self, kind, record):
        _record_class(kind)
        with self._conn() as conn:
            conn.execute("INSERT OR REPLACE INTO records VALUES (?,?,?,?,?)",
                         (record.tenant_id, kind, record.id, self._dump(record), record.created_at))
        return record

    def get_record(self, tenant_id, kind, record_id):
        cls = _record_class(kind)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload FROM records WHERE tenant_id=? AND kind=? AND id=?",
                (tenant_id, kind, record_id)).fetchone()
        return cls.from_dict(json.loads(row["payload"])) if row else None

    def list_records(self, tenant_id, kind):
        cls = _record_class(kind)
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT payload FROM records WHERE tenant_id=? AND kind=? ORDER BY id",
                (tenant_id, kind)).fetchall()
        return [cls.from_dict(json.loads(r["payload"])) for r in rows]

    def update_record(self, tenant_id, kind, record):
        _record_class(kind)
        if record.tenant_id != tenant_id:
            return False
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE records SET payload=? WHERE tenant_id=? AND kind=? AND id=?",
                (self._dump(record), tenant_id, kind, record.id))
            return cur.rowcount > 0

    def delete_record(self, tenant_id, kind, record_id):
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM records WHERE tenant_id=? AND kind=? AND id=?",
                (tenant_id, kind, record_id))
            return cur.rowcount > 0

    # audit
    def append_audit(self, entry):
        with self._conn() as conn:
            conn.execute("INSERT INTO audit_log (tenant_id, payload) VALUES (?,?)",
                         (entry.get("tenant_id"), json.dumps(entry)))
        return entry

    def list_audit(self, tenant_id=None):
        with self._conn() as conn:
            if tenant_id is None:
                rows = conn.execute("SELECT payload FROM audit_log ORDER BY seq").fetchall()
            else:
                rows = conn.execute("SELECT payload FROM audit_log WHERE tenant_id=? ORDER BY seq",
                                    (tenant_id,)).fetchall()
        return [json.loads(r["payload"]) for r in rows]
