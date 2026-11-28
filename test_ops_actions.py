"""Tests for the ApexVoice platform ops administrative actions.

Every action must refuse customer scoped principals, suspend and
delete must require a reason, delete must require an explicit confirm
flag, every successful action must write an audit entry, and a
platform operator must be able to run the full lifecycle.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tenancy import InMemoryStore
from tenancy.errors import NotFound, PermissionDenied, ValidationFailed
from tenancy.rbac import PlatformOperator, TenantPrincipal

from ops.actions import OpsActions

OPERATOR = PlatformOperator(operator_id="ops-lead")
CUSTOMER = TenantPrincipal(user_id="usr_owner1", tenant_id="ten_self",
                           role="owner")


class OpsActionsTest(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryStore()
        self.actions = OpsActions(self.store)

    def _create(self, **overrides):
        kwargs = {
            "legal_name": "Widget Co",
            "owner_email": "owner@widget.example",
            "owner_password": "widget-password-1",
            "plan_tier": "starter",
        }
        kwargs.update(overrides)
        return self.actions.create_tenant(OPERATOR, **kwargs)

    def _platform_audit(self, action=None):
        entries = [e for e in self.store.list_audit()
                   if e["action"].startswith("platform.")]
        if action is not None:
            entries = [e for e in entries if e["action"] == action]
        return entries

    # authorization

    def test_customer_principal_refused_for_every_action(self):
        created = self._create()
        tenant_id = created["tenant_id"]
        with self.assertRaises(PermissionDenied) as ctx:
            self.actions.create_tenant(
                CUSTOMER, legal_name="Nope Co",
                owner_email="n@example.com", owner_password="nope-password-1")
        self.assertEqual(ctx.exception.code, "forbidden")
        with self.assertRaises(PermissionDenied):
            self.actions.suspend_tenant(CUSTOMER, tenant_id, "reason")
        with self.assertRaises(PermissionDenied):
            self.actions.reactivate_tenant(CUSTOMER, tenant_id)
        with self.assertRaises(PermissionDenied):
            self.actions.delete_tenant(CUSTOMER, tenant_id, "reason",
                                       confirm=True)
        with self.assertRaises(PermissionDenied):
            self.actions.set_spending_cap(CUSTOMER, tenant_id,
                                          cap_minutes=10.0)

    def test_non_principal_refused(self):
        with self.assertRaises(PermissionDenied):
            self.actions.suspend_tenant("not-a-principal", "ten_x", "reason")

    # create

    def test_create_tenant_success_and_audit(self):
        result = self._create(reason="pilot signup")
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "create_tenant")
        tenant = self.store.get_tenant(result["tenant_id"])
        self.assertIsNotNone(tenant)
        self.assertEqual(tenant.status, "active")
        entries = self._platform_audit("platform.tenant_created")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["tenant_id"], tenant.id)
        self.assertEqual(entries[0]["actor"], "platform:ops-lead")
        self.assertEqual(entries[0]["details"]["reason"], "pilot signup")

    # suspend and reactivate

    def test_suspend_requires_reason(self):
        tenant_id = self._create()["tenant_id"]
        for bad_reason in ("", "   ", None):
            with self.assertRaises(ValidationFailed) as ctx:
                self.actions.suspend_tenant(OPERATOR, tenant_id, bad_reason)
            self.assertEqual(ctx.exception.code, "validation_failed")
        tenant = self.store.get_tenant(tenant_id)
        self.assertEqual(tenant.status, "active")

    def test_operator_suspend_and_reactivate_through_lifecycle(self):
        tenant_id = self._create()["tenant_id"]
        result = self.actions.suspend_tenant(
            OPERATOR, tenant_id, "billing review")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "suspended")
        self.assertEqual(self.store.get_tenant(tenant_id).status, "suspended")
        entries = self._platform_audit("platform.tenant_suspended")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["details"]["reason"], "billing review")

        result = self.actions.reactivate_tenant(
            OPERATOR, tenant_id, reason="review cleared")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "active")
        self.assertEqual(self.store.get_tenant(tenant_id).status, "active")
        entries = self._platform_audit("platform.tenant_reactivated")
        self.assertEqual(len(entries), 1)

    def test_suspend_unknown_tenant_is_not_found(self):
        with self.assertRaises(NotFound) as ctx:
            self.actions.suspend_tenant(OPERATOR, "ten_missing", "reason")
        self.assertEqual(ctx.exception.code, "not_found")

    # delete

    def test_delete_requires_confirm_and_reason(self):
        tenant_id = self._create()["tenant_id"]
        with self.assertRaises(ValidationFailed):
            self.actions.delete_tenant(OPERATOR, tenant_id, "winding down")
        with self.assertRaises(ValidationFailed):
            self.actions.delete_tenant(OPERATOR, tenant_id, "winding down",
                                       confirm=False)
        with self.assertRaises(ValidationFailed):
            self.actions.delete_tenant(OPERATOR, tenant_id, "", confirm=True)
        self.assertIsNotNone(self.store.get_tenant(tenant_id))

    def test_delete_purges_and_audit_survives(self):
        tenant_id = self._create()["tenant_id"]
        result = self.actions.delete_tenant(
            OPERATOR, tenant_id, "customer closed the business",
            confirm=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "deleted")
        self.assertIsNone(self.store.get_tenant(tenant_id))
        entries = self._platform_audit("platform.tenant_deleted")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["tenant_id"], tenant_id)
        self.assertEqual(entries[0]["details"]["reason"],
                         "customer closed the business")
        tenant_entries = self.store.list_audit(tenant_id)
        self.assertTrue(any(e["action"] == "platform.tenant_deleted"
                            for e in tenant_entries))

    # spending caps

    def test_set_spending_cap_and_audit(self):
        tenant_id = self._create()["tenant_id"]
        result = self.actions.set_spending_cap(
            OPERATOR, tenant_id, cap_minutes=150.0, cap_cad_cents=9000,
            reason="pilot guardrail")
        self.assertTrue(result["ok"])
        self.assertEqual(result["cap"]["cap_minutes"], 150.0)
        cap = self.actions.caps.get(tenant_id)
        self.assertEqual(cap["cap_cad_cents"], 9000)
        entries = self._platform_audit("platform.spending_cap_set")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["details"]["cap_minutes"], 150.0)

    def test_set_spending_cap_validation(self):
        tenant_id = self._create()["tenant_id"]
        with self.assertRaises(ValidationFailed):
            self.actions.set_spending_cap(OPERATOR, tenant_id)
        with self.assertRaises(ValidationFailed):
            self.actions.set_spending_cap(OPERATOR, tenant_id,
                                          cap_minutes=-5.0)
        with self.assertRaises(NotFound):
            self.actions.set_spending_cap(OPERATOR, "ten_missing",
                                          cap_minutes=10.0)

    # audit completeness

    def test_every_successful_action_writes_an_audit_entry(self):
        tenant_id = self._create()["tenant_id"]
        self.actions.set_spending_cap(OPERATOR, tenant_id, cap_minutes=200.0)
        self.actions.suspend_tenant(OPERATOR, tenant_id, "pause")
        self.actions.reactivate_tenant(OPERATOR, tenant_id)
        actions_seen = [e["action"] for e in self._platform_audit()]
        self.assertEqual(actions_seen, [
            "platform.tenant_created",
            "platform.spending_cap_set",
            "platform.tenant_suspended",
            "platform.tenant_reactivated",
        ])
        for entry in self._platform_audit():
            self.assertEqual(entry["actor"], "platform:ops-lead")
            self.assertEqual(entry["tenant_id"], tenant_id)
            self.assertTrue(entry["at"])


if __name__ == "__main__":
    unittest.main()
