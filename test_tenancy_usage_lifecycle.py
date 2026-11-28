"""Usage caps, Redis key separation, lifecycle, and migration tests.

Proves: plan caps are enforced per tenant (exhausting tenant A never
changes tenant B), per-tenant Redis keys never collide, suspension blocks
routing, deletion purges one tenant and leaves the other intact, and the
single-tenant migration produces a working Harbour & Main tenant.
"""

import unittest

from tenancy import (
    CallAdmission, PermissionDenied, PlanLimitReached, TenantLifecycle,
    TenantNotActive, TenantPrincipal, TenantRouter, UnknownNumber,
    UsageMeter, migrate_single_tenant,
)
from tenancy import routing
from tenancy.errors import Conflict
from tenancy_fixtures import (
    DID_A, OPERATOR, STORE_KINDS, build_two_tenants, make_store,
)


class FakeRedis:
    """Minimal redis-like client with SET NX / GET / DELETE semantics."""

    def __init__(self):
        self.data = {}
        self.expired = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        if ex is not None:
            self.expired[key] = ex
        return True

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        return 1 if self.data.pop(key, None) is not None else 0


class UsageMixin:
    store_kind = None

    def setUp(self):
        self.store = make_store(self.store_kind)
        self.world = build_two_tenants(self.store)
        self.meter = UsageMeter(self.store)

    def test_plan_limits_match_tiers(self):
        # ten_alpha is starter (120), ten_beta is professional (350).
        self.assertEqual(self.meter.plan_limit_minutes("ten_alpha"), 120)
        self.assertEqual(self.meter.plan_limit_minutes("ten_beta"), 350)

    def test_billable_minutes_round_up_per_call(self):
        self.meter.record_call("ten_alpha", 61, period="202611")
        self.assertEqual(self.meter.summary("ten_alpha", "202611")["used_minutes"], 2.0)

    def test_exhausting_tenant_a_does_not_change_tenant_b(self):
        self.meter.record("ten_alpha", minutes=120, calls=40, period="202611")
        self.assertTrue(self.meter.is_hard_stopped("ten_alpha", "202611"))
        self.assertEqual(self.meter.remaining_minutes("ten_alpha", "202611"), 0.0)
        with self.assertRaises(PlanLimitReached):
            self.meter.check_hard_stop("ten_alpha", "202611")
        # Tenant B is completely unaffected.
        self.assertFalse(self.meter.is_hard_stopped("ten_beta", "202611"))
        self.assertEqual(self.meter.remaining_minutes("ten_beta", "202611"), 350.0)
        self.assertEqual(self.meter.summary("ten_beta", "202611")["used_minutes"], 0.0)
        self.assertTrue(self.meter.check_hard_stop("ten_beta", "202611"))

    def test_overage_is_computed_per_tenant(self):
        self.meter.record("ten_alpha", minutes=135, calls=45, period="202611")
        self.assertEqual(self.meter.overage_minutes("ten_alpha", "202611"), 15.0)
        self.assertEqual(self.meter.overage_minutes("ten_beta", "202611"), 0.0)

    def test_spend_estimate_uses_rates_and_is_per_tenant(self):
        self.meter.record("ten_alpha", minutes=10, calls=3, tts_characters=5000,
                          stt_seconds=600, period="202611")
        summary = self.meter.summary("ten_alpha", "202611")
        self.assertEqual(summary["estimated_cost_cents"],
                         self.meter.estimate_cost_cents(
                             minutes=10, calls=3, tts_characters=5000, stt_seconds=600))
        self.assertGreater(summary["estimated_cost_cents"], 0)
        self.assertEqual(self.meter.summary("ten_beta", "202611")["estimated_cost_cents"], 0)


class TestUsageInMemory(UsageMixin, unittest.TestCase):
    store_kind = "memory"


class TestUsageSQLite(UsageMixin, unittest.TestCase):
    store_kind = "sqlite"


class TestRedisKeysAndAdmission(unittest.TestCase):
    def setUp(self):
        self.store = make_store("memory")
        self.world = build_two_tenants(self.store)
        self.meter = UsageMeter(self.store)
        self.redis = FakeRedis()
        self.admission = CallAdmission(self.redis, self.meter)

    def test_key_builders_follow_contract_and_never_collide(self):
        self.assertEqual(routing.active_call_lock_key("ten_alpha"),
                         "apex:t:ten_alpha:active_call_lock")
        self.assertEqual(routing.account_key("ten_alpha", "202611"),
                         "apex:t:ten_alpha:acct:202611")
        self.assertEqual(routing.clip_key("ten_alpha", "clip_1"),
                         "apex:t:ten_alpha:clip:clip_1")
        self.assertEqual(routing.call_key("ten_alpha", "call_1"),
                         "apex:t:ten_alpha:call:call_1")
        self.assertEqual(routing.config_key("ten_alpha"), "apex:t:ten_alpha:config")
        builders = (routing.active_call_lock_key,
                    lambda t: routing.account_key(t, "202611"),
                    lambda t: routing.clip_key(t, "clip_1"),
                    lambda t: routing.call_key(t, "call_1"),
                    routing.config_key)
        for builder in builders:
            self.assertNotEqual(builder("ten_alpha"), builder("ten_beta"))

    def test_locks_are_per_tenant(self):
        self.assertTrue(self.admission.try_admit("ten_alpha", "call_a1"))
        # Tenant A's held lock does not block tenant B at all.
        self.assertTrue(self.admission.try_admit("ten_beta", "call_b1"))
        # But a second simultaneous call for tenant A is refused its lock.
        self.assertFalse(self.admission.try_admit("ten_alpha", "call_a2"))
        self.admission.release("ten_alpha", "call_a1")
        self.assertTrue(self.admission.try_admit("ten_alpha", "call_a2"))
        # Releasing A never released B.
        self.assertEqual(self.redis.get(routing.active_call_lock_key("ten_beta")), "call_b1")

    def test_budget_hard_stop_is_per_tenant_at_admission(self):
        self.meter.record("ten_alpha", minutes=120, calls=40, period=None)
        with self.assertRaises(PlanLimitReached):
            self.admission.try_admit("ten_alpha", "call_late")
        self.assertTrue(self.admission.try_admit("ten_beta", "call_b1"))


class LifecycleMixin:
    store_kind = None

    def setUp(self):
        self.store = make_store(self.store_kind)
        self.world = build_two_tenants(self.store)
        self.lifecycle = TenantLifecycle(self.store)
        self.router = TenantRouter(self.store)

    def test_create_tenant_end_to_end(self):
        tenant, owner = self.lifecycle.create_tenant(
            OPERATOR, "New Biz Inc.", "new@example.com", "new-owner-password-1",
            plan_tier="business", config=None, did="+15195550109")
        self.assertTrue(tenant.id.startswith("ten_"))
        self.assertEqual(self.router.resolve("+15195550109").id, tenant.id)
        token, session, user = self.world["auth"].login("new@example.com", "new-owner-password-1")
        self.assertEqual(session.tenant_id, tenant.id)
        actions = [e["action"] for e in self.store.list_audit(tenant.id)]
        self.assertIn("tenant.created", actions)

    def test_create_tenant_is_platform_only(self):
        owner_a = TenantPrincipal.from_user(self.world["a"]["owner"])
        with self.assertRaises(PermissionDenied):
            self.lifecycle.create_tenant(
                owner_a, "Sneaky Inc.", "sneak@example.com", "sneaky-password-1")

    def test_suspend_blocks_routing_and_reactivate_restores(self):
        self.lifecycle.suspend_tenant(OPERATOR, "ten_alpha")
        with self.assertRaises(TenantNotActive):
            self.router.resolve(DID_A)
        # Tenant B still routes.
        self.assertEqual(self.router.resolve(self.world["b"]["did"]).id, "ten_beta")
        self.lifecycle.reactivate_tenant(OPERATOR, "ten_alpha")
        self.assertEqual(self.router.resolve(DID_A).id, "ten_alpha")

    def test_owner_can_suspend_own_but_not_other_tenant(self):
        owner_a = TenantPrincipal.from_user(self.world["a"]["owner"])
        with self.assertRaises(PermissionDenied):
            self.lifecycle.suspend_tenant(owner_a, "ten_beta")
        self.lifecycle.suspend_tenant(owner_a, "ten_alpha")
        self.assertEqual(self.store.get_tenant("ten_alpha").status, "suspended")

    def test_delete_purges_one_tenant_and_preserves_the_other(self):
        self.lifecycle.delete_tenant(OPERATOR, "ten_alpha")
        self.assertIsNone(self.store.get_tenant("ten_alpha"))
        self.assertIsNone(self.store.get_config("ten_alpha"))
        self.assertIsNone(self.store.get_phone_mapping(DID_A))
        self.assertEqual(self.store.list_users("ten_alpha"), [])
        for kind in ("calls", "messages", "appointments", "transcripts", "customers", "usage"):
            self.assertEqual(self.store.list_records("ten_alpha", kind), [], kind)
        with self.assertRaises(UnknownNumber):
            self.router.resolve(DID_A)
        # Tenant B is fully intact.
        self.assertIsNotNone(self.store.get_tenant("ten_beta"))
        self.assertIsNotNone(self.store.get_config("ten_beta"))
        self.assertEqual(len(self.store.list_records("ten_beta", "calls")), 1)
        self.assertEqual(self.router.resolve(self.world["b"]["did"]).id, "ten_beta")
        # The deletion itself remains auditable on the platform side.
        actions = [e["action"] for e in self.store.list_audit("ten_alpha")]
        self.assertIn("tenant.deleted", actions)

    def test_owner_delete_of_other_tenant_is_denied(self):
        owner_b = TenantPrincipal.from_user(self.world["b"]["owner"])
        with self.assertRaises(PermissionDenied):
            self.lifecycle.delete_tenant(owner_b, "ten_alpha")
        self.assertIsNotNone(self.store.get_tenant("ten_alpha"))


class TestLifecycleInMemory(LifecycleMixin, unittest.TestCase):
    store_kind = "memory"


class TestLifecycleSQLite(LifecycleMixin, unittest.TestCase):
    store_kind = "sqlite"


class MigrationMixin:
    store_kind = None

    def test_migrate_from_env_style_config(self):
        store = make_store(self.store_kind)
        env = {
            "BUSINESS_NAME": "Harbour & Main",
            "BUSINESS_PHONE": "+12267732234",
            "BUSINESS_SERVICES": "Web design, AI receptionist",
            "BUSINESS_HOURS": "Mon-Fri 9am-5pm",
            "BUSINESS_TIMEZONE": "America/Toronto",
        }
        tenant, owner = migrate_single_tenant(
            store, env, "+12267732234", "josh@harbourandmain.com", "migration-password-1")
        self.assertEqual(tenant.id, "ten_harbour_main")
        router = TenantRouter(store)
        self.assertEqual(router.resolve("+12267732234").id, "ten_harbour_main")
        config = store.get_config("ten_harbour_main")
        self.assertEqual(config.config["businessName"], "Harbour & Main")
        service_names = [s["name"] for s in config.config["services"]]
        self.assertEqual(service_names, ["Web design", "AI receptionist"])
        from tenancy import AuthService
        token, session, user = AuthService(store).login(
            "josh@harbourandmain.com", "migration-password-1")
        self.assertEqual(session.tenant_id, "ten_harbour_main")
        self.assertEqual(user.role, "owner")

    def test_migrate_from_full_business_config(self):
        store = make_store(self.store_kind)
        from tenancy_fixtures import valid_config
        config = valid_config("Harbour & Main", "josh@harbourandmain.com", "+12267732234")
        tenant, owner = migrate_single_tenant(
            store, config, "+12267732234", "josh@harbourandmain.com", "migration-password-1")
        stored = store.get_config("ten_harbour_main")
        self.assertEqual(stored.config, config)
        self.assertEqual(TenantRouter(store).resolve("+12267732234").id, "ten_harbour_main")


class TestMigrationInMemory(MigrationMixin, unittest.TestCase):
    store_kind = "memory"


class TestMigrationSQLite(MigrationMixin, unittest.TestCase):
    store_kind = "sqlite"


if __name__ == "__main__":
    unittest.main()
