"""Telephony tenant routing and per-tenant Redis keys.

Tenant resolution for an inbound call comes from exactly one place: the
dialed number (the SignalWire To field) looked up in the phone mapping
table. Unknown numbers and numbers belonging to suspended or deleted
tenants are rejected before any business logic runs.

Redis key builders follow the contract pattern apex:t:{tenant_id}:...
exactly, replacing the legacy global keys apex:active_call_lock and
apex:acct for customer traffic.
"""

from .errors import PlanLimitReached, TenantNotActive, UnknownNumber
from .ids import normalize_phone


def config_key(tenant_id):
    return f"apex:t:{tenant_id}:config"


def active_call_lock_key(tenant_id):
    return f"apex:t:{tenant_id}:active_call_lock"


def account_key(tenant_id, period):
    """Monthly account (budget) key. period is yyyymm, for example 202611."""
    return f"apex:t:{tenant_id}:acct:{period}"


def clip_key(tenant_id, clip_id):
    return f"apex:t:{tenant_id}:clip:{clip_id}"


def call_key(tenant_id, call_id):
    return f"apex:t:{tenant_id}:call:{call_id}"


def session_key(session_id):
    return f"apex:session:{session_id}"


class TenantRouter:
    def __init__(self, store):
        self.store = store

    def resolve(self, to_number):
        """Resolve a dialed number to its active Tenant.

        Raises UnknownNumber for unassigned numbers and TenantNotActive
        for suspended or deleted tenants. The returned tenant is the only
        tenant scope the call may touch.
        """
        did = normalize_phone(to_number)
        mapping = self.store.get_phone_mapping(did)
        if mapping is None or mapping.status != "active":
            raise UnknownNumber("this number is not in service")
        tenant = self.store.get_tenant(mapping.tenant_id)
        if tenant is None or tenant.status == "deleted":
            raise UnknownNumber("this number is not in service")
        if tenant.status == "suspended":
            raise TenantNotActive("this business account is suspended")
        return tenant

    def resolve_tenant_id(self, to_number):
        return self.resolve(to_number).id


class CallAdmission:
    """Per-tenant call admission against a redis-like client.

    The client only needs the small surface used here: set(key, value,
    nx=True, ex=seconds), get(key), and delete(key), which matches both
    redis-py and the Upstash REST client shape used by the backend, and
    lets tests pass a fake.

    Admission takes the tenant's own lock key and checks the tenant's own
    remaining budget through a usage meter. One tenant holding its lock or
    exhausting its budget can never block another tenant.
    """

    def __init__(self, redis_client, usage_meter, lock_ttl_seconds=1260):
        self.redis = redis_client
        self.usage = usage_meter
        self.lock_ttl_seconds = lock_ttl_seconds

    def try_admit(self, tenant_id, call_id):
        if self.usage is not None and self.usage.is_hard_stopped(tenant_id):
            raise PlanLimitReached("this business has reached its plan limit")
        lock = active_call_lock_key(tenant_id)
        acquired = self.redis.set(lock, call_id, nx=True, ex=self.lock_ttl_seconds)
        if not acquired:
            return False
        self.redis.set(call_key(tenant_id, call_id), "active", ex=self.lock_ttl_seconds)
        return True

    def release(self, tenant_id, call_id):
        lock = active_call_lock_key(tenant_id)
        if self.redis.get(lock) == call_id:
            self.redis.delete(lock)
        self.redis.delete(call_key(tenant_id, call_id))
