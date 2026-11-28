"""Cross-tenant isolation tests.

For both store implementations: tenant B must not be able to read, list,
update, or delete tenant A's configuration, calls, messages, appointments,
transcripts, customers, or usage, by direct ID or by list query. A record
under another tenant must look exactly like a record that does not exist.
"""

import unittest

from tenancy import (
    CallRecord, TenantConfig, TenantRouter, UnknownNumber, UsageMeter,
)
from tenancy_fixtures import STORE_KINDS, build_two_tenants, make_store, valid_config

KINDS_AND_IDS = (
    ("calls", "call_a1"),
    ("messages", "msg_a1"),
    ("appointments", "appt_a1"),
    ("transcripts", "tr_a1"),
    ("customers", "cust_a1"),
)


class IsolationMixin:
    store_kind = None

    def setUp(self):
        self.store = make_store(self.store_kind)
        self.world = build_two_tenants(self.store)
        self.a = self.world["a"]
        self.b = self.world["b"]

    def test_own_records_are_visible(self):
        for kind, record_id in KINDS_AND_IDS:
            found = self.store.get_record("ten_alpha", kind, record_id)
            self.assertIsNotNone(found, f"{kind} should be visible to its owner tenant")
            self.assertEqual(found.tenant_id, "ten_alpha")

    def test_cross_tenant_get_by_id_returns_none(self):
        for kind, record_id in KINDS_AND_IDS:
            found = self.store.get_record("ten_beta", kind, record_id)
            self.assertIsNone(found, f"tenant B must not read tenant A {kind} by ID")

    def test_cross_tenant_lists_are_empty_of_other_tenant(self):
        for kind, _ in KINDS_AND_IDS:
            listed_b = self.store.list_records("ten_beta", kind)
            ids_b = {r.id for r in listed_b}
            self.assertTrue(all(r.tenant_id == "ten_beta" for r in listed_b))
            self.assertNotIn(dict(KINDS_AND_IDS)[kind], ids_b)
            listed_a = self.store.list_records("ten_alpha", kind)
            self.assertTrue(all(r.tenant_id == "ten_alpha" for r in listed_a))

    def test_cross_tenant_update_is_refused_and_data_unchanged(self):
        stolen = self.store.get_record("ten_alpha", "calls", "call_a1")
        stolen.tenant_id = "ten_beta"
        stolen.summary = "tampered by tenant B"
        self.assertFalse(self.store.update_record("ten_beta", "calls", stolen))
        # Even claiming the victim tenant while holding a foreign record id
        # scoped to B's own key space must not reach A's record.
        reread = self.store.get_record("ten_alpha", "calls", "call_a1")
        self.assertEqual(reread.summary, "Summary for a")

    def test_cross_tenant_update_with_victim_scope_but_wrong_owner_fails(self):
        record = CallRecord(id="call_a1", tenant_id="ten_beta", summary="forged")
        self.assertFalse(self.store.update_record("ten_alpha", "calls", record))
        reread = self.store.get_record("ten_alpha", "calls", "call_a1")
        self.assertEqual(reread.summary, "Summary for a")

    def test_cross_tenant_delete_is_refused(self):
        for kind, record_id in KINDS_AND_IDS:
            self.assertFalse(self.store.delete_record("ten_beta", kind, record_id))
            self.assertIsNotNone(self.store.get_record("ten_alpha", kind, record_id))

    def test_config_is_tenant_scoped(self):
        config_a = self.store.get_config("ten_alpha")
        config_b = self.store.get_config("ten_beta")
        self.assertEqual(config_a.config["businessName"], "Business A")
        self.assertEqual(config_b.config["businessName"], "Business B")
        self.assertIsNone(self.store.get_config("ten_nonexistent"))

    def test_config_overwrite_only_affects_own_tenant(self):
        new_config = valid_config("Business B Renamed", "owner-b@example.com", "+15195550102")
        self.store.put_config(TenantConfig(tenant_id="ten_beta", config=new_config, version=2))
        self.assertEqual(self.store.get_config("ten_beta").config["businessName"],
                         "Business B Renamed")
        self.assertEqual(self.store.get_config("ten_alpha").config["businessName"], "Business A")

    def test_users_are_tenant_scoped(self):
        owner_a_id = self.a["owner"].id
        self.assertIsNotNone(self.store.get_user("ten_alpha", owner_a_id))
        self.assertIsNone(self.store.get_user("ten_beta", owner_a_id))
        self.assertEqual([u.tenant_id for u in self.store.list_users("ten_beta")],
                         ["ten_beta"])
        self.assertIsNone(self.store.get_user_by_email("ten_beta", "owner-a@example.com"))
        self.assertFalse(self.store.delete_user("ten_beta", owner_a_id))
        self.assertIsNotNone(self.store.get_user("ten_alpha", owner_a_id))

    def test_phone_mapping_conflict_across_tenants(self):
        from tenancy import PhoneMapping
        from tenancy.errors import Conflict
        with self.assertRaises(Conflict):
            self.store.add_phone_mapping(PhoneMapping(did=self.a["did"], tenant_id="ten_beta"))

    def test_usage_is_tenant_scoped(self):
        meter = UsageMeter(self.store)
        meter.record_call("ten_alpha", 600, call_id="call_a1", period="202611")
        summary_a = meter.summary("ten_alpha", "202611")
        summary_b = meter.summary("ten_beta", "202611")
        self.assertEqual(summary_a["used_minutes"], 10.0)
        self.assertEqual(summary_b["used_minutes"], 0.0)
        self.assertEqual(summary_b["call_count"], 0)

    def test_router_resolves_each_tenant_by_its_own_did(self):
        router = TenantRouter(self.store)
        self.assertEqual(router.resolve(self.a["did"]).id, "ten_alpha")
        self.assertEqual(router.resolve(self.b["did"]).id, "ten_beta")
        self.assertEqual(router.resolve("519-555-0101").id, "ten_alpha")

    def test_router_rejects_unknown_numbers(self):
        router = TenantRouter(self.store)
        with self.assertRaises(UnknownNumber):
            router.resolve("+15195559999")


class TestIsolationInMemory(IsolationMixin, unittest.TestCase):
    store_kind = "memory"


class TestIsolationSQLite(IsolationMixin, unittest.TestCase):
    store_kind = "sqlite"


if __name__ == "__main__":
    unittest.main()
