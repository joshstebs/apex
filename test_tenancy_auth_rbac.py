"""Authentication, session binding, and RBAC tests.

Proves: passwords are never stored in plaintext and verify correctly, a
user from tenant B cannot authenticate into tenant A scope, sessions are
tenant-bound, expired and revoked sessions fail, and the role matrix is
enforced including platform-only lifecycle actions.
"""

import time
import unittest

from tenancy import (
    AuthService, PermissionDenied, PlatformOperator, TenantPrincipal,
    TenantRouter, require, require_platform, role_has,
)
from tenancy.errors import AuthenticationFailed
from tenancy_fixtures import OPERATOR, STORE_KINDS, build_two_tenants, make_store


class AuthMixin:
    store_kind = None

    def setUp(self):
        self.store = make_store(self.store_kind)
        self.world = build_two_tenants(self.store)
        self.auth = self.world["auth"]
        self.a = self.world["a"]
        self.b = self.world["b"]

    def test_password_is_hashed_with_salt_never_plaintext(self):
        owner = self.a["owner"]
        self.assertNotIn(self.a["password"], owner.password_hash)
        self.assertNotIn(self.a["password"], owner.password_salt)
        self.assertGreaterEqual(owner.password_iterations, 100_000)
        self.assertNotEqual(owner.password_salt, self.b["owner"].password_salt)

    def test_login_success_returns_session_bound_to_own_tenant(self):
        token, session, user = self.auth.login(self.a["email"], self.a["password"])
        self.assertEqual(session.tenant_id, "ten_alpha")
        self.assertEqual(user.tenant_id, "ten_alpha")
        resolved_session, resolved_user = self.auth.authenticate(token)
        self.assertEqual(resolved_session.tenant_id, "ten_alpha")
        self.assertEqual(resolved_user.id, user.id)

    def test_login_wrong_password_and_unknown_email_fail_identically(self):
        with self.assertRaises(AuthenticationFailed) as wrong_pw:
            self.auth.login(self.a["email"], "not-the-password-1")
        with self.assertRaises(AuthenticationFailed) as unknown:
            self.auth.login("nobody@example.com", self.a["password"])
        self.assertEqual(str(wrong_pw.exception), str(unknown.exception))

    def test_tenant_b_user_cannot_act_in_tenant_a_scope(self):
        token_b, session_b, user_b = self.auth.login(self.b["email"], self.b["password"])
        principal_b = TenantPrincipal.from_user(user_b)
        self.assertEqual(principal_b.tenant_id, "ten_beta")
        with self.assertRaises(PermissionDenied):
            require(principal_b, "config.read", tenant_id="ten_alpha")
        with self.assertRaises(PermissionDenied):
            require(principal_b, "calls.read", tenant_id="ten_alpha")
        with self.assertRaises(PermissionDenied):
            require(principal_b, "tenant.delete", tenant_id="ten_alpha")
        # And the session itself carries only tenant B scope.
        session, user = self.auth.authenticate(token_b)
        self.assertEqual(session.tenant_id, "ten_beta")
        self.assertNotEqual(session.tenant_id, "ten_alpha")

    def test_tenant_b_credentials_do_not_unlock_tenant_a_user_record(self):
        # Logging in with B's email always resolves to B's user and tenant,
        # even though both tenants exist in the same store.
        _, session, user = self.auth.login(self.b["email"], self.b["password"])
        self.assertEqual(user.id, self.b["owner"].id)
        self.assertEqual(session.tenant_id, "ten_beta")
        with self.assertRaises(AuthenticationFailed):
            self.auth.login(self.b["email"], self.a["password"])

    def test_revoked_session_fails_after_logout(self):
        token, _, _ = self.auth.login(self.a["email"], self.a["password"])
        self.assertTrue(self.auth.logout(token))
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(token)

    def test_expired_session_fails(self):
        now = [1_700_000_000.0]
        auth = AuthService(self.store, clock=lambda: now[0], session_ttl=3600)
        token, session, _ = auth.login(self.a["email"], self.a["password"])
        auth.authenticate(token)
        now[0] += 3601
        with self.assertRaises(AuthenticationFailed):
            auth.authenticate(token)

    def test_unknown_token_fails(self):
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate("sess_doesnotexist")
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate("")

    def test_password_change_revokes_existing_sessions(self):
        token, _, user = self.auth.login(self.a["email"], self.a["password"])
        self.auth.change_password("ten_alpha", user.id, self.a["password"],
                                  "a-brand-new-password-1")
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(token)
        with self.assertRaises(AuthenticationFailed):
            self.auth.login(self.a["email"], self.a["password"])
        token2, session2, _ = self.auth.login(self.a["email"], "a-brand-new-password-1")
        self.assertEqual(session2.tenant_id, "ten_alpha")

    def test_password_change_in_wrong_tenant_scope_fails(self):
        with self.assertRaises(AuthenticationFailed):
            self.auth.change_password("ten_beta", self.a["owner"].id,
                                      self.a["password"], "another-new-password-1")


class TestAuthInMemory(AuthMixin, unittest.TestCase):
    store_kind = "memory"


class TestAuthSQLite(AuthMixin, unittest.TestCase):
    store_kind = "sqlite"


class TestRBAC(unittest.TestCase):
    def principal(self, role, tenant_id="ten_alpha"):
        return TenantPrincipal(user_id=f"user_{role}", tenant_id=tenant_id, role=role)

    def test_viewer_is_read_only(self):
        viewer = self.principal("viewer")
        for permission in ("calls.read", "messages.read", "appointments.read",
                           "customers.read", "config.read"):
            self.assertTrue(require(viewer, permission))
        for permission in ("config.write", "appointments.write", "messages.write",
                           "users.manage", "billing.read", "usage.read",
                           "tenant.suspend", "tenant.delete"):
            with self.assertRaises(PermissionDenied, msg=permission):
                require(viewer, permission)

    def test_staff_cannot_manage_users_billing_or_usage(self):
        staff = self.principal("staff")
        self.assertTrue(require(staff, "appointments.write"))
        self.assertTrue(require(staff, "messages.write"))
        for permission in ("users.manage", "billing.read", "usage.read",
                           "config.write", "tenant.suspend", "tenant.delete"):
            with self.assertRaises(PermissionDenied, msg=permission):
                require(staff, permission)

    def test_admin_cannot_touch_billing_users_or_lifecycle(self):
        admin = self.principal("admin")
        self.assertTrue(require(admin, "config.write"))
        self.assertTrue(require(admin, "usage.read"))
        for permission in ("billing.read", "users.manage",
                           "tenant.suspend", "tenant.delete"):
            with self.assertRaises(PermissionDenied, msg=permission):
                require(admin, permission)

    def test_only_owner_can_suspend_or_delete_own_tenant(self):
        owner = self.principal("owner")
        self.assertTrue(require(owner, "tenant.suspend", tenant_id="ten_alpha"))
        self.assertTrue(require(owner, "tenant.delete", tenant_id="ten_alpha"))
        self.assertTrue(require(owner, "billing.read"))
        self.assertTrue(require(owner, "users.manage"))

    def test_no_tenant_role_can_act_on_another_tenant(self):
        for role in ("owner", "admin", "staff", "viewer"):
            principal = self.principal(role, tenant_id="ten_beta")
            for permission in ("config.read", "config.write", "calls.read",
                               "tenant.suspend", "tenant.delete", "users.manage"):
                with self.assertRaises(PermissionDenied, msg=f"{role} {permission}"):
                    require(principal, permission, tenant_id="ten_alpha")

    def test_platform_actions_are_operator_only(self):
        for role in ("owner", "admin", "staff", "viewer"):
            principal = self.principal(role)
            with self.assertRaises(PermissionDenied, msg=role):
                require_platform(principal, "tenant.create")
            with self.assertRaises(PermissionDenied, msg=role):
                require(principal, "tenant.create", tenant_id="ten_alpha")
        self.assertTrue(require_platform(OPERATOR, "tenant.create"))
        self.assertTrue(require(OPERATOR, "tenant.delete", tenant_id="ten_alpha"))
        self.assertTrue(require(OPERATOR, "tenant.delete", tenant_id="ten_beta"))

    def test_role_matrix_shape(self):
        self.assertTrue(role_has("owner", "billing.read"))
        self.assertFalse(role_has("staff", "billing.read"))
        self.assertFalse(role_has("viewer", "config.write"))
        self.assertFalse(role_has("nonexistent-role", "calls.read"))


if __name__ == "__main__":
    unittest.main()
