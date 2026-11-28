"""End to end integration journey across the Phase 3 packages.

This suite wires the isolated tenancy, voice, and billing packages together
the way the integrated backend will, and walks one complete commercial
journey:

- A platform operator creates two tenants from onboarding style
  BusinessConfig documents, each with an owner account and a phone number.
- Each owner logs in and the tenant configuration round trips through the
  tenancy api_models shaping layer unchanged.
- DID routing resolves each tenant's number and rejects unknown numbers.
- Call admission succeeds for an active tenant while a suspended tenant is
  refused at routing, and a tenant that exhausts its plan minutes is hard
  stopped at admission.
- Usage metering accumulates per tenant and never mixes tenants.
- The billing state machine consumes signature verified webhook events
  (signed in test with a fake test secret using the billing package's own
  scheme) and moves a tenant from checkout to active, to past due on a
  failed invoice, through grace expiry to unpaid with a suspension
  recommendation, and back to active on payment. Duplicate deliveries are
  no-ops and a tampered signature is rejected.
- Billing reconciliation compares locally metered minutes against the
  billing usage summary; the two accounting paths agree exactly.
- Voice selection gives one tenant the premium tier and the other the
  standard tier with valid fallback chains, and the phrase cache serves
  the first tenant's greeting while refusing caller specific text.

Everything here is a package level simulation. No HTTP server is involved:
the route adapter behaviour is exercised separately in
test_integration_contract_alignment.py, and only the integrated staging
fixture can prove real HTTP behaviour. Nothing in this file makes a
network call or touches a live provider.
"""

import hashlib
import hmac
import json
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PHASE3_ROOT = Path(__file__).resolve().parent
if str(PHASE3_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE3_ROOT))

from tenancy import (  # noqa: E402
    AuthService, CallAdmission, InMemoryStore, PlanLimitReached,
    PlatformOperator, SQLiteStore, TenantConfig, TenantLifecycle,
    TenantNotActive, TenantPrincipal, TenantRouter, UnknownNumber,
    UsageMeter, api_models, require,
)
from tenancy_fixtures import valid_config  # noqa: E402

from billing import (  # noqa: E402
    CallUsage, SubscriptionRecord, SubscriptionState, evaluate_grace,
    handle_event, meter_report_payload, reconcile_usage, summarize_usage,
    verify_and_parse,
)
from billing.webhooks import WebhookVerificationError  # noqa: E402

from voice import (  # noqa: E402
    PROVIDERS, PhraseCache, TenantVoiceConfig, VoiceConfigStore,
    build_standard_phrases, fallback_chain, next_provider,
)

OPERATOR = PlatformOperator(operator_id="ops-journey")
WEBHOOK_SECRET = "whsec_test_placeholder_journey"
DID_A = "+15195550101"
DID_B = "+15195550102"
DID_C = "+15195550103"
PASSWORD_A = "journey-password-a"
PASSWORD_B = "journey-password-b"


class FakeRedis:
    """Minimal redis-like client for CallAdmission: set, get, delete."""

    def __init__(self):
        self.data = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        return self.data.pop(key, None) is not None


def signed_delivery(record, event, secret=WEBHOOK_SECRET, now=None):
    """Sign an event exactly as Stripe would and feed it through the
    billing package's verify then handle path."""
    moment = now or datetime.now(timezone.utc)
    body = json.dumps(event).encode("utf-8")
    timestamp = int(time.time())
    signature = hmac.new(
        secret.encode("utf-8"),
        str(timestamp).encode("utf-8") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    header = f"t={timestamp},v1={signature}"
    parsed = verify_and_parse(body, header, secret, now=timestamp)
    return handle_event(record, parsed, now=moment)


def stripe_event(event_id, event_type, obj):
    return {"id": event_id, "type": event_type, "created": int(time.time()),
            "data": {"object": obj}}


class JourneyBase:
    STORE_KIND = "memory"

    def setUp(self):
        if self.STORE_KIND == "sqlite":
            self.store = SQLiteStore(":memory:")
        else:
            self.store = InMemoryStore()
        self.auth = AuthService(self.store)
        self.lifecycle = TenantLifecycle(self.store, auth=self.auth)
        self.router = TenantRouter(self.store)
        self.meter = UsageMeter(self.store)
        self.config_a = valid_config("Journey Plumbing", "owner-a@journey.example", DID_A)
        self.config_b = valid_config("Journey Cuts", "owner-b@journey.example", DID_B)
        self.tenant_a, self.owner_a = self.lifecycle.create_tenant(
            OPERATOR, legal_name="Journey Plumbing Inc.",
            owner_email="owner-a@journey.example", owner_password=PASSWORD_A,
            display_name="Journey Plumbing", plan_tier="professional",
            config=self.config_a, did=DID_A)
        self.tenant_b, self.owner_b = self.lifecycle.create_tenant(
            OPERATOR, legal_name="Journey Cuts Inc.",
            owner_email="owner-b@journey.example", owner_password=PASSWORD_B,
            display_name="Journey Cuts", plan_tier="starter",
            config=self.config_b, did=DID_B)

    # -- onboarding, login, configuration --------------------------------

    def test_owner_login_and_config_round_trip_through_api_models(self):
        token, session, user = self.auth.login("owner-a@journey.example", PASSWORD_A)
        body = api_models.login_response(token, session, user, self.tenant_a)
        self.assertEqual(body["sessionToken"], token)
        self.assertEqual(body["user"]["email"], "owner-a@journey.example")
        self.assertEqual(body["user"]["role"], "owner")
        self.assertEqual(body["tenant"]["id"], self.tenant_a.id)
        self.assertIn("expiresAt", body)

        resolved_session, resolved_user = self.auth.authenticate(token)
        self.assertEqual(resolved_session.tenant_id, self.tenant_a.id)
        principal = TenantPrincipal.from_user(resolved_user)
        self.assertTrue(require(principal, "config.read", tenant_id=self.tenant_a.id))

        stored = self.store.get_config(self.tenant_a.id)
        shaped = api_models.shape_config_response(stored)
        self.assertEqual(shaped["version"], 1)
        self.assertEqual(shaped["config"], self.config_a)
        self.assertEqual(api_models.greeting_notices(self.config_a), [])

        updated = dict(self.config_a)
        updated["instructions"] = "Always confirm the callback number."
        self.store.put_config(TenantConfig(
            tenant_id=self.tenant_a.id, config=updated, version=2,
            updated_by=user.id))
        reshaped = api_models.shape_config_response(self.store.get_config(self.tenant_a.id))
        self.assertEqual(reshaped["version"], 2)
        self.assertEqual(reshaped["config"]["instructions"],
                         "Always confirm the callback number.")
        # Tenant B's configuration is untouched by tenant A's save.
        self.assertEqual(self.store.get_config(self.tenant_b.id).config, self.config_b)

    def test_second_tenant_is_fully_independent(self):
        self.assertNotEqual(self.tenant_a.id, self.tenant_b.id)
        token_b, _, user_b = self.auth.login("owner-b@journey.example", PASSWORD_B)
        self.assertEqual(user_b.tenant_id, self.tenant_b.id)
        principal_b = TenantPrincipal.from_user(user_b)
        with self.assertRaises(Exception) as caught:
            require(principal_b, "config.read", tenant_id=self.tenant_a.id)
        self.assertEqual(caught.exception.code, "forbidden")

    # -- telephony routing and admission ---------------------------------

    def test_did_routing_resolves_each_tenant_and_rejects_unknown(self):
        self.assertEqual(self.router.resolve(DID_A).id, self.tenant_a.id)
        self.assertEqual(self.router.resolve(DID_B).id, self.tenant_b.id)
        # Punctuated input normalizes to the same mapping.
        self.assertEqual(self.router.resolve("(519) 555-0101").id, self.tenant_a.id)
        with self.assertRaises(UnknownNumber) as caught:
            self.router.resolve("+15195550199")
        self.assertEqual(caught.exception.code, "number_not_in_service")

    def test_call_admission_while_other_tenant_suspended(self):
        redis = FakeRedis()
        admission = CallAdmission(redis, self.meter)
        self.lifecycle.suspend_tenant(OPERATOR, self.tenant_b.id)
        with self.assertRaises(TenantNotActive):
            self.router.resolve(DID_B)
        # Tenant A is unaffected: admitted, lock held, second call refused,
        # then admitted again after release.
        self.assertTrue(admission.try_admit(self.tenant_a.id, "call_j1"))
        self.assertFalse(admission.try_admit(self.tenant_a.id, "call_j2"))
        admission.release(self.tenant_a.id, "call_j1")
        self.assertTrue(admission.try_admit(self.tenant_a.id, "call_j2"))
        # Reactivation restores routing for tenant B.
        self.lifecycle.reactivate_tenant(OPERATOR, self.tenant_b.id)
        self.assertEqual(self.router.resolve(DID_B).id, self.tenant_b.id)

    def test_plan_limit_hard_stop_at_admission(self):
        tenant_c, _ = self.lifecycle.create_tenant(
            OPERATOR, legal_name="Journey Tiny Inc.",
            owner_email="owner-c@journey.example", owner_password="journey-password-c",
            display_name="Journey Tiny", plan_tier="starter",
            config=valid_config("Journey Tiny", "owner-c@journey.example", DID_C),
            did=DID_C)
        # Starter includes 120 minutes. One 121 minute billable call ends it.
        self.meter.record_call(tenant_c.id, duration_seconds=121 * 60)
        self.assertTrue(self.meter.is_hard_stopped(tenant_c.id))
        admission = CallAdmission(FakeRedis(), self.meter)
        with self.assertRaises(PlanLimitReached):
            admission.try_admit(tenant_c.id, "call_over_limit")
        # Tenant A still has its full professional allowance.
        self.assertFalse(self.meter.is_hard_stopped(self.tenant_a.id))

    # -- usage metering ----------------------------------------------------

    def test_usage_metering_accumulates_per_tenant(self):
        self.meter.record_call(self.tenant_a.id, duration_seconds=61,
                               tts_characters=500, stt_seconds=55)
        self.meter.record_call(self.tenant_a.id, duration_seconds=125,
                               tts_characters=300, stt_seconds=120)
        self.meter.record_call(self.tenant_b.id, duration_seconds=600)
        summary_a = self.meter.summary(self.tenant_a.id)
        summary_b = self.meter.summary(self.tenant_b.id)
        # Per call round up: 61 seconds bills 2 minutes, 125 bills 3.
        self.assertEqual(summary_a["used_minutes"], 5)
        self.assertEqual(summary_a["call_count"], 2)
        self.assertEqual(summary_a["tts_characters"], 800)
        self.assertEqual(summary_a["stt_seconds"], 175)
        self.assertEqual(summary_b["used_minutes"], 10)
        self.assertEqual(summary_b["call_count"], 1)
        shaped = api_models.shape_usage(summary_a, "professional", 350)
        self.assertEqual(shaped["tenantId"], self.tenant_a.id)
        self.assertEqual(shaped["usedMinutes"], 5)
        self.assertEqual(shaped["overageMinutes"], 0)
        self.assertEqual(shaped["estimatedCost"]["currency"], "CAD")

    # -- billing journey ---------------------------------------------------

    def test_billing_webhook_journey_full_arc(self):
        record = SubscriptionRecord(tenant_id=self.tenant_a.id)
        t0 = datetime(2026, 11, 28, 15, 0, tzinfo=timezone.utc)
        checkout = stripe_event("evt_j_checkout", "checkout.session.completed", {
            "id": "cs_test_journey", "status": "complete",
            "customer": "cus_test_journey", "subscription": "sub_test_journey",
            "metadata": {"tenant_id": self.tenant_a.id, "tier_id": "professional"},
        })
        signed_delivery(record, checkout, now=t0)
        self.assertEqual(record.state, SubscriptionState.ACTIVE)
        self.assertEqual(record.tier_id, "professional")
        self.assertEqual(record.stripe_customer_id, "cus_test_journey")
        self.assertTrue(record.service_continues)

        failed = stripe_event("evt_j_failed", "invoice.payment_failed", {
            "id": "in_test_journey", "customer": "cus_test_journey",
            "subscription": "sub_test_journey",
        })
        signed_delivery(record, failed, now=t0 + timedelta(days=1))
        self.assertEqual(record.state, SubscriptionState.PAST_DUE)
        self.assertEqual(record.failure_count, 1)
        self.assertTrue(record.service_continues)

        # Duplicate delivery of the same event id changes nothing.
        signed_delivery(record, failed, now=t0 + timedelta(days=1, hours=1))
        self.assertEqual(record.state, SubscriptionState.PAST_DUE)
        self.assertEqual(record.failure_count, 1)

        paid = stripe_event("evt_j_paid", "invoice.paid", {
            "id": "in_test_journey", "customer": "cus_test_journey",
            "subscription": "sub_test_journey",
        })
        signed_delivery(record, paid, now=t0 + timedelta(days=2))
        self.assertEqual(record.state, SubscriptionState.ACTIVE)
        self.assertEqual(record.failure_count, 0)

        # Fail again and let the grace period run out: the state machine
        # recommends suspension but takes no action itself.
        failed_again = stripe_event("evt_j_failed2", "invoice.payment_failed", {
            "id": "in_test_journey2", "customer": "cus_test_journey",
            "subscription": "sub_test_journey",
        })
        signed_delivery(record, failed_again, now=t0 + timedelta(days=3))
        self.assertEqual(record.state, SubscriptionState.PAST_DUE)
        evaluate_grace(record, now=t0 + timedelta(days=11))
        self.assertEqual(record.state, SubscriptionState.UNPAID)
        self.assertTrue(record.suspend_recommended)
        self.assertFalse(record.service_continues)
        # The tenant itself is NOT suspended by billing: that stays a
        # human or lifecycle decision.
        self.assertEqual(self.store.get_tenant(self.tenant_a.id).status, "active")

        paid_again = stripe_event("evt_j_paid2", "invoice.paid", {
            "id": "in_test_journey2", "customer": "cus_test_journey",
            "subscription": "sub_test_journey",
        })
        signed_delivery(record, paid_again, now=t0 + timedelta(days=12))
        self.assertEqual(record.state, SubscriptionState.ACTIVE)
        self.assertFalse(record.suspend_recommended)

    def test_billing_webhook_rejects_tampered_signature(self):
        body = json.dumps(stripe_event("evt_j_tamper", "invoice.paid", {
            "id": "in_x", "customer": "cus_x"})).encode("utf-8")
        timestamp = int(time.time())
        bad_header = f"t={timestamp},v1={'0' * 64}"
        with self.assertRaises(WebhookVerificationError) as caught:
            verify_and_parse(body, bad_header, WEBHOOK_SECRET, now=timestamp)
        self.assertEqual(caught.exception.code, "signature_mismatch")

    # -- reconciliation ----------------------------------------------------

    def test_reconciliation_metered_minutes_match_billing_summary(self):
        durations = [61, 125, 30]
        for seconds in durations:
            self.meter.record_call(self.tenant_a.id, duration_seconds=seconds)
        self.meter.record_call(self.tenant_b.id, duration_seconds=999)
        local = self.meter.summary(self.tenant_a.id)

        records = [CallUsage(tenant_id=self.tenant_a.id, duration_seconds=s)
                   for s in durations]
        records.append(CallUsage(tenant_id=self.tenant_b.id, duration_seconds=999))
        summary = summarize_usage(self.tenant_a.id, "professional", records)
        # Both accounting paths round up per call and ignore tenant B.
        self.assertEqual(summary.total_minutes, int(local["used_minutes"]))
        self.assertEqual(summary.total_minutes, 6)
        self.assertEqual(summary.call_count, 3)
        self.assertEqual(summary.overage_minutes, 0)

        result = reconcile_usage(self.tenant_a.id, summary.total_minutes,
                                 int(local["used_minutes"]))
        self.assertEqual(result.drift_minutes, 0)
        self.assertFalse(result.drift_exceeded)
        drifted = reconcile_usage(self.tenant_a.id, summary.total_minutes,
                                  summary.total_minutes + 6)
        self.assertTrue(drifted.drift_exceeded)

        payload = meter_report_payload(summary, timestamp=1795800000,
                                       stripe_customer_id="cus_test_journey")
        self.assertEqual(payload["payload"]["tenant_id"], self.tenant_a.id)
        self.assertEqual(payload["value"], "0")

    # -- voice -------------------------------------------------------------

    def test_voice_selection_premium_and_standard_with_valid_chains(self):
        store = VoiceConfigStore()
        config_a = store.set(TenantVoiceConfig(
            tenant_id=self.tenant_a.id, tier="premium", voice_id="21m00Tcm4TlvDq8ikWAM"))
        config_b = store.set(TenantVoiceConfig(tenant_id=self.tenant_b.id, tier="standard"))
        self.assertEqual(config_a.provider, "elevenlabs_turbo")
        self.assertEqual(config_b.provider, "signalwire_say")
        for config in (config_a, config_b):
            chain = fallback_chain(config)
            self.assertTrue(all(name in PROVIDERS for name in chain))
            self.assertEqual(chain.count("signalwire_say"), 1)
            self.assertEqual(next_provider(config, chain[0]), chain[1])
        self.assertEqual(fallback_chain(config_a)[-1], "signalwire_say")
        self.assertEqual(fallback_chain(config_b)[0], "signalwire_say")
        # Returned configs are copies: mutating one cannot leak across.
        leaked = store.get(self.tenant_a.id)
        leaked.tier = "standard"
        self.assertEqual(store.get(self.tenant_a.id).tier, "premium")
        self.assertEqual(store.get(self.tenant_b.id).tier, "standard")

    def test_phrase_cache_serves_greeting_and_refuses_caller_text(self):
        cache = PhraseCache()
        phrases = build_standard_phrases(self.config_a)
        greeting = next(p for p in phrases if p["kind"] == "greeting")
        provider = "elevenlabs_turbo"
        voice_id = self.config_a["voice"]["voiceId"]
        self.assertTrue(cache.put(self.tenant_a.id, provider, voice_id,
                                  greeting["text"], b"audio-a", kind="greeting"))
        self.assertEqual(cache.get(self.tenant_a.id, provider, voice_id,
                                   greeting["text"]), b"audio-a")
        # The same text under tenant B is a different entry and a miss.
        self.assertIsNone(cache.get(self.tenant_b.id, provider, voice_id,
                                    greeting["text"]))
        # Caller specific kinds are refused outright.
        self.assertFalse(cache.put(
            self.tenant_a.id, provider, voice_id,
            "Please tell Jordan the part arrives Thursday.",
            b"audio-x", kind="message"))
        self.assertFalse(cache.put(
            self.tenant_a.id, provider, voice_id,
            "Your callback number is confirmed.", b"audio-x",
            kind="caller_specific"))
        # Content heuristics refuse identifier bearing text even under a
        # normally cacheable kind.
        self.assertFalse(cache.put(
            self.tenant_a.id, provider, voice_id,
            "Call us at 519 555 0177 for details.", b"audio-x", kind="faq"))
        self.assertGreaterEqual(cache.stats()["refusals"], 3)


class TestJourneyInMemory(JourneyBase, unittest.TestCase):
    STORE_KIND = "memory"


class TestJourneySQLite(JourneyBase, unittest.TestCase):
    STORE_KIND = "sqlite"


if __name__ == "__main__":
    unittest.main()
