"""Contract alignment between PR #12's HTTP tenant contract and the
Phase 3 packages, proven at the package level.

PR #12 (feature/apex-security-qa, Command Code) ships qa/test_tenant_contract.py,
an HTTP contract test that currently skips because no integrated fixture
serves the routes yet. Its expectations:

- Routes /api/tenants/{tenant_id} with subresources /config, /usage,
  /calls, /messages, /appointments, /subscription.
- Bearer session authentication.
- 401 unauthenticated with no or an invalid session.
- 403 forbidden when a valid session for another tenant is used against
  a path tenant, or when the role lacks the permission.
- 404 with an IDENTICAL error code for a record that does not exist and
  a record that belongs to another tenant.

This suite proves what the Phase 3 packages can already produce for that
contract, using a small simulated adapter that follows the route rules in
docs/commercial/BACKEND_INTEGRATION_PATCH_SPEC.md step 5 exactly: session
first, path tenant must equal session tenant (else 403), every lookup is
scoped to the session tenant (a miss is 404, including another tenant's
record id). It does NOT prove HTTP behaviour. Status codes on a real
socket, JSON serialisation by the web framework, header handling, and
the actual route registration can only be proven by PR #12's own fixture
once the backend integration lands.

Mapping table. Level key: PKG means this suite proves it at the package
level; HTTP means only the integrated fixture can prove it; GAP means
the package cannot yet produce what the contract requires.

Route or behaviour            Package evidence                              Level
----------------------------  --------------------------------------------  -----
POST /api/auth/login          auth.AuthService.login,                     PKG
                              api_models.login_response
GET /api/tenants/{id}         api_models.shape_tenant                     PKG
GET .../config                api_models.shape_config_response            PKG
GET .../config not started    contract code config_not_started            GAP
GET .../usage                 api_models.shape_usage                      PKG*
GET .../calls (list)          api_models.list_response + shape_call       PKG*
GET .../calls/{id} detail     transcript and recording shaping            GAP
GET .../messages (list)       api_models.shape_message                    PKG*
PATCH .../messages/{id}       store.update_record under tenant scope      PKG
GET .../appointments          api_models.shape_appointment                PKG
GET .../subscription          no shaping function exists                  GAP
401 unauthenticated           errors.AuthenticationFailed,                PKG
                              api_models.error_body
403 cross tenant path         tenancy.rbac.require tenant binding         PKG
403 role lacks permission     tenancy.rbac.require role matrix            PKG
404 identical code rule       store.get_record tenant scoped miss plus    PKG
                              errors.NotFound through the adapter
409 version_conflict          contract code has no package error class    GAP
Error catalogue completeness  contract codes vs tenancy.errors codes      GAP
Tenant id prefix              contract says tenant_, packages use ten_    GAP
Real HTTP status and JSON     integrated app only                         HTTP

PKG* rows carry field level gaps documented in the gap tests below:
usage is missing periodEnd and reports minutes as floats, the call list
item is missing endedAt, and the message shape is missing the delivery
array. Gap tests are named test_known_gap_* and assert the CURRENT state
on purpose: when a gap is closed, its test fails and must be updated in
the same change, so the gap list can never silently go stale.
"""

import sys
import unittest
from pathlib import Path

PHASE3_ROOT = Path(__file__).resolve().parent
if str(PHASE3_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE3_ROOT))

import tenancy.errors as errors_module  # noqa: E402
from tenancy import (  # noqa: E402
    AuthenticationFailed, AuthService, InMemoryStore, NotFound,
    PermissionDenied, TenantPrincipal, api_models, require,
)
from tenancy_fixtures import PASSWORD_A, PASSWORD_B, build_two_tenants  # noqa: E402

import billing  # noqa: E402


# -- simulated route adapter (patch spec step 5 rules) --------------------

def adapter_get_record(store, principal, path_tenant_id, kind, record_id, shape):
    """One contract GET for a single tenant owned record.

    Order matters and mirrors the contract: no principal is 401, a path
    tenant that disagrees with the session tenant is 403, and any lookup
    miss inside the session tenant is 404, whether the record never
    existed or belongs to someone else.
    """
    if principal is None:
        raise AuthenticationFailed("no session token supplied")
    if path_tenant_id != principal.tenant_id:
        raise PermissionDenied("path tenant does not match the session tenant")
    record = store.get_record(principal.tenant_id, kind, record_id)
    if record is None:
        raise NotFound("record not found")
    return shape(record)


def package_error_codes():
    codes = set()
    for name in dir(errors_module):
        obj = getattr(errors_module, name)
        if isinstance(obj, type) and hasattr(obj, "code") and hasattr(obj, "http_status"):
            codes.add(obj.code)
    return codes


class AlignmentBase:
    def setUp(self):
        self.store = InMemoryStore()
        self.world = build_two_tenants(self.store)
        self.a = self.world["a"]
        self.b = self.world["b"]
        self.auth = AuthService(self.store)


class TestAuthContract(AlignmentBase, unittest.TestCase):
    def test_login_response_matches_contract_shape(self):
        token, session, user = self.auth.login(self.a["email"], PASSWORD_A)
        body = api_models.login_response(token, session, user, self.a["tenant"])
        self.assertEqual(set(body), {"sessionToken", "expiresAt", "user", "tenant"})
        self.assertEqual(set(body["user"]), {"id", "email", "role"})
        self.assertEqual(set(body["tenant"]), {"id", "displayName", "status"})
        session_body = api_models.session_response(session, user, self.a["tenant"])
        self.assertEqual(session_body["user"]["id"], user.id)
        self.assertEqual(session_body["role"], "owner")

    def test_wrong_password_and_unknown_email_are_identical_401(self):
        failures = []
        for email, password in ((self.a["email"], "wrong-password-1"),
                                ("nobody@example.com", PASSWORD_A)):
            with self.assertRaises(AuthenticationFailed) as caught:
                self.auth.login(email, password)
            failures.append(caught.exception)
        self.assertEqual(failures[0].code, "unauthenticated")
        self.assertEqual(failures[0].code, failures[1].code)
        self.assertEqual(failures[0].message, failures[1].message)
        body = api_models.error_body_from_exception(failures[0])
        self.assertEqual(body, {"error": {"code": "unauthenticated",
                                          "message": failures[0].message}})

    def test_missing_and_invalid_tokens_are_401(self):
        for token in (None, "", "sess_not_a_real_token"):
            with self.assertRaises(AuthenticationFailed) as caught:
                self.auth.authenticate(token)
            self.assertEqual(caught.exception.code, "unauthenticated")
            self.assertEqual(caught.exception.http_status, 401)

    def test_expired_and_revoked_sessions_are_401(self):
        clock = [1_000_000.0]
        timed_auth = AuthService(self.store, clock=lambda: clock[0])
        token, _, _ = timed_auth.login(self.a["email"], PASSWORD_A)
        timed_auth.authenticate(token)
        clock[0] += 12 * 3600 + 1
        with self.assertRaises(AuthenticationFailed):
            timed_auth.authenticate(token)
        token2, _, _ = self.auth.login(self.a["email"], PASSWORD_A)
        self.assertTrue(self.auth.logout(token2))
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(token2)


class TestTenantAndConfigShapes(AlignmentBase, unittest.TestCase):
    def test_shape_tenant_matches_contract_fields(self):
        mappings = self.store.list_phone_mappings(self.a["tenant"].id)
        body = api_models.shape_tenant(self.a["tenant"], mappings)
        for key in ("id", "displayName", "legalName", "status", "timezone",
                    "planId", "createdAt", "phoneNumbers"):
            self.assertIn(key, body)
        self.assertEqual(body["id"], self.a["tenant"].id)
        self.assertEqual(body["phoneNumbers"][0]["phoneNumber"], self.a["did"])

    def test_gap_closed_phone_number_id_is_distinct(self):
        # Closed in Phase 4: shape_tenant emits a num_ identifier
        # distinct from the phone number itself.
        mappings = self.store.list_phone_mappings(self.a["tenant"].id)
        body = api_models.shape_tenant(self.a["tenant"], mappings)
        self.assertTrue(body["phoneNumbers"][0]["id"].startswith("num_"))
        self.assertNotEqual(body["phoneNumbers"][0]["id"],
                            body["phoneNumbers"][0]["phoneNumber"])

    def test_config_response_round_trips_the_frozen_schema(self):
        stored = self.store.get_config(self.a["tenant"].id)
        body = api_models.shape_config_response(stored)
        self.assertEqual(set(body) >= {"version", "updatedAt", "updatedBy", "config"}, True)
        self.assertEqual(body["config"], self.a["config"])

    def test_gap_closed_config_not_started_code_exists(self):
        # Closed in Phase 4: the package carries the config_not_started
        # error code for a tenant that has not started configuration.
        from tenancy import Tenant
        bare = Tenant(id="ten_bare", legal_name="Bare Inc.", status="active")
        self.store.create_tenant(bare)
        self.assertIsNone(self.store.get_config("ten_bare"))
        self.assertIn("config_not_started", package_error_codes())


class TestRecordRoutes(AlignmentBase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        _, _, user_a = self.auth.login(self.a["email"], PASSWORD_A)
        _, _, user_b = self.auth.login(self.b["email"], PASSWORD_B)
        self.principal_a = TenantPrincipal.from_user(user_a)
        self.principal_b = TenantPrincipal.from_user(user_b)

    def test_calls_list_shape_and_pagination(self):
        calls = self.store.list_records(self.a["tenant"].id, "calls")
        body = api_models.list_response(calls, shape=api_models.shape_call)
        self.assertEqual(set(body), {"items", "page"})
        self.assertEqual(set(body["page"]), {"limit", "nextCursor", "total"})
        item = body["items"][0]
        for key in ("id", "startedAt", "direction", "fromNumber", "toNumber",
                    "status", "durationSeconds", "contactName", "summary",
                    "appointmentId", "messageId", "recordingUrl"):
            self.assertIn(key, item)
        many = list(range(30))
        page1 = api_models.list_response(many, limit=25)
        self.assertEqual(len(page1["items"]), 25)
        self.assertIsNotNone(page1["page"]["nextCursor"])
        page2 = api_models.list_response(many, limit=25,
                                         cursor=page1["page"]["nextCursor"])
        self.assertEqual(len(page2["items"]), 5)
        self.assertIsNone(page2["page"]["nextCursor"])

    def test_gap_closed_call_shape_has_ended_at(self):
        # Closed in Phase 4: CallRecord carries ended_at (populated by
        # the backend at call end) and shape_call emits endedAt.
        call = self.store.list_records(self.a["tenant"].id, "calls")[0]
        self.assertIn("endedAt", api_models.shape_call(call))
        self.assertTrue(hasattr(call, "ended_at"))

    def test_gap_closed_call_detail_shaping_exists(self):
        # Closed in Phase 4: shape_call_detail combines the call with
        # its transcript turns and an explicit recording object.
        self.assertTrue(hasattr(api_models, "shape_call_detail"))
        call = self.store.list_records(self.a["tenant"].id, "calls")[0]
        transcripts = self.store.list_records(self.a["tenant"].id, "transcripts")
        detail = api_models.shape_call_detail(call, transcripts)
        self.assertEqual(len(detail["transcript"]), 1)
        self.assertEqual(detail["recording"]["status"], "unavailable")

    def test_messages_shape_and_known_gap_delivery(self):
        message = self.store.list_records(self.a["tenant"].id, "messages")[0]
        body = api_models.shape_message(message)
        for key in ("id", "callId", "receivedAt", "callerName", "callbackNumber",
                    "reason", "preferredTime", "urgent", "handled"):
            self.assertIn(key, body)
        # Closed in Phase 4: the message shape carries the delivery
        # array (empty until the backend records delivery channels on
        # the MessageRecord.delivery field).
        self.assertIn("delivery", body)
        self.assertEqual(body["delivery"], [])

    def test_message_handled_patch_stays_inside_tenant_scope(self):
        message = self.store.list_records(self.a["tenant"].id, "messages")[0]
        message.handled = True
        self.assertTrue(self.store.update_record(self.a["tenant"].id, "messages", message))
        self.assertTrue(self.store.get_record(
            self.a["tenant"].id, "messages", message.id).handled)
        # The same record presented under tenant B's scope cannot update.
        forged = self.store.list_records(self.a["tenant"].id, "messages")[0]
        self.assertFalse(self.store.update_record(self.b["tenant"].id, "messages", forged))

    def test_appointments_shape_matches_contract_exactly(self):
        appt = self.store.list_records(self.a["tenant"].id, "appointments")[0]
        body = api_models.shape_appointment(appt)
        self.assertEqual(set(body), {
            "id", "callId", "createdAt", "contactName", "contactPhone",
            "serviceName", "requestedStart", "requestedEnd", "status", "notes"})

    def test_usage_shape_and_known_gaps(self):
        from tenancy import UsageMeter
        meter = UsageMeter(self.store)
        meter.record_call(self.a["tenant"].id, duration_seconds=61)
        summary = meter.summary(self.a["tenant"].id)
        body = api_models.shape_usage(summary, self.a["tenant"].plan_tier, 120)
        for key in ("tenantId", "periodStart", "planId", "includedMinutes",
                    "usedMinutes", "overageMinutes", "callCount",
                    "estimatedCost", "overageRate"):
            self.assertIn(key, body)
        self.assertEqual(set(body["estimatedCost"]),
                         {"amount_cents", "currency", "basis"})
        # Closed in Phase 4: shape_usage emits periodEnd and whole
        # minute integers.
        self.assertIn("periodEnd", body)
        self.assertIsInstance(body["usedMinutes"], int)


class TestAuthorizationRules(AlignmentBase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        _, _, user_a = self.auth.login(self.a["email"], PASSWORD_A)
        _, _, user_b = self.auth.login(self.b["email"], PASSWORD_B)
        self.principal_a = TenantPrincipal.from_user(user_a)
        self.principal_b = TenantPrincipal.from_user(user_b)

    def test_unauthenticated_adapter_call_is_401(self):
        with self.assertRaises(AuthenticationFailed) as caught:
            adapter_get_record(self.store, None, self.a["tenant"].id,
                               "calls", "call_a1", api_models.shape_call)
        self.assertEqual(caught.exception.http_status, 401)
        body = api_models.error_body_from_exception(caught.exception)
        self.assertEqual(body["error"]["code"], "unauthenticated")

    def test_cross_tenant_path_is_403_even_for_own_record(self):
        with self.assertRaises(PermissionDenied) as caught:
            adapter_get_record(self.store, self.principal_a, self.b["tenant"].id,
                               "calls", "call_a1", api_models.shape_call)
        self.assertEqual(caught.exception.http_status, 403)
        self.assertEqual(caught.exception.code, "forbidden")

    def test_identical_404_for_missing_and_other_tenants_record(self):
        bodies = []
        for record_id in ("call_does_not_exist", "call_a1"):
            with self.assertRaises(NotFound) as caught:
                adapter_get_record(self.store, self.principal_b,
                                   self.b["tenant"].id, "calls", record_id,
                                   api_models.shape_call)
            self.assertEqual(caught.exception.http_status, 404)
            bodies.append(api_models.error_body_from_exception(caught.exception))
        # The whole error body is identical, not just the code, so record
        # existence inside another tenant cannot be probed.
        self.assertEqual(bodies[0], bodies[1])
        self.assertEqual(bodies[0]["error"]["code"], "not_found")
        # Sanity: the same id under its owner's scope resolves fine.
        found = adapter_get_record(self.store, self.principal_a,
                                   self.a["tenant"].id, "calls", "call_a1",
                                   api_models.shape_call)
        self.assertEqual(found["id"], "call_a1")

    def test_role_matrix_denials_are_403(self):
        from tenancy import TenantPrincipal as TP
        staff = TP(user_id="user_staff", tenant_id=self.a["tenant"].id, role="staff")
        viewer = TP(user_id="user_viewer", tenant_id=self.a["tenant"].id, role="viewer")
        for principal, permission in ((staff, "billing.read"),
                                      (staff, "usage.read"),
                                      (viewer, "config.write"),
                                      (viewer, "messages.write")):
            with self.assertRaises(PermissionDenied) as caught:
                require(principal, permission, tenant_id=self.a["tenant"].id)
            self.assertEqual(caught.exception.code, "forbidden")
        self.assertTrue(require(viewer, "calls.read", tenant_id=self.a["tenant"].id))
        self.assertTrue(require(staff, "messages.write", tenant_id=self.a["tenant"].id))


class TestKnownGaps(AlignmentBase, unittest.TestCase):
    def test_gap_closed_subscription_shaping_exists(self):
        # Closed in Phase 4: api_models.shape_subscription produces the
        # contract body from a billing SubscriptionRecord, and status
        # none for a tenant without one. Billing period bounds stay
        # honest nulls until the billing package stores them.
        self.assertTrue(hasattr(api_models, "shape_subscription"))
        self.assertEqual(api_models.shape_subscription(None)["status"], "none")

    def test_known_gap_contract_error_codes_missing_from_package(self):
        contract_codes = {
            "validation_failed", "malformed_json", "unauthenticated",
            "forbidden", "not_found", "conflict", "version_conflict",
            "rate_limited", "plan_limit_reached", "provider_error",
            "service_unavailable", "config_not_started",
        }
        missing = contract_codes - package_error_codes()
        # Closed in Phase 4: version_conflict and config_not_started are
        # package domain errors now. The remaining four are transport
        # level codes (request parsing, rate limiting, provider and
        # availability failures) owned by the HTTP adapter, not the
        # domain package.
        self.assertEqual(missing, {
            "malformed_json", "rate_limited",
            "provider_error", "service_unavailable",
        })

    def test_known_gap_tenant_id_prefix_differs_from_contract(self):
        # BACKEND_CONTRACTS.md conventions name the tenant prefix tenant_,
        # while the tenancy package generates ten_ ids and the billing
        # package refuses anything else. The implemented prefix is ten_.
        from tenancy import generate_tenant_id
        tenant_id = generate_tenant_id(self.store)
        self.assertTrue(tenant_id.startswith("ten_"))
        self.assertFalse(tenant_id.startswith("tenant_"))

    def test_known_gap_created_tenant_starts_active_not_trial(self):
        # The contract creates tenants in trial status. TenantLifecycle
        # creates them active; trial exists as a status value only.
        from tenancy import PlatformOperator, TenantLifecycle
        lifecycle = TenantLifecycle(self.store)
        tenant, _ = lifecycle.create_tenant(
            PlatformOperator(operator_id="ops-gap"), legal_name="Gap Inc.",
            owner_email="gap@example.com", owner_password="gap-password-123",
            plan_tier="starter")
        self.assertEqual(tenant.status, "active")


if __name__ == "__main__":
    unittest.main()
