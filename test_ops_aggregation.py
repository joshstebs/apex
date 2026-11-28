"""Tests for the ApexVoice platform ops aggregation layer.

Imports the Phase 3 packages from ~/workspace/apex-phase3/full via
sys.path, exactly as the backend integration will.

Hand computed cost figures used below, from voice/cost_model.json:

- Standard tier provider signalwire_say: 425 chars per minute times
  0.032 USD per 1000 chars times FX 1.36 = 0.018496 CAD synthesis.
  Other lines: transport 0.008976 + LLM 0.0068 + STT allowance 0.0152
  = 0.030976 CAD. Full cost 0.049472 CAD per minute.
- Premium tier provider elevenlabs_turbo: 425 times 0.18 USD per 1000
  chars times 1.36 = 0.10404 CAD synthesis. Full cost 0.135016 CAD
  per minute.
- Fixed allowance: 7.00 CAD = 700 cents per tenant per period.

Tenant A, standard, 100 minutes: 100 x 0.049472 = 4.9472 CAD, rounds
to 495 cents, plus 700 fixed = 1195 cents. Starter revenue 4900
cents. Contribution 4900 - 1195 = 3705 cents.
Tenant B, premium, 50 minutes: 50 x 0.135016 = 6.7508 CAD, rounds to
675 cents, plus 700 fixed = 1375 cents. Professional revenue 9900
cents. Contribution 9900 - 1375 = 8525 cents.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from billing.state import SubscriptionRecord, SubscriptionState
from tenancy import InMemoryStore, Tenant, UsageMeter
from tenancy_fixtures import build_two_tenants
from voice.selection import TenantVoiceConfig, VoiceConfigStore

from ops.aggregation import build_platform_overview, build_tenant_row
from ops.health import HealthRegistry

PERIOD = "202612"


def make_tenant(store, tenant_id, name, plan, status="active"):
    tenant = Tenant(id=tenant_id, legal_name=name, display_name=name,
                    status=status, plan_tier=plan)
    store.create_tenant(tenant)
    return tenant


def two_tenant_world():
    store = InMemoryStore()
    make_tenant(store, "ten_a", "Alpha Plumbing", "starter")
    make_tenant(store, "ten_b", "Beta Dental", "professional")
    meter = UsageMeter(store)
    meter.record("ten_a", minutes=100.0, calls=4, period=PERIOD, billable=False)
    meter.record("ten_b", minutes=50.0, calls=2, period=PERIOD, billable=False)
    voices = VoiceConfigStore()
    voices.set(TenantVoiceConfig(tenant_id="ten_b", tier="premium"))
    billing = {
        "ten_a": SubscriptionRecord(tenant_id="ten_a",
                                    state=SubscriptionState.ACTIVE,
                                    tier_id="starter"),
        "ten_b": SubscriptionRecord(tenant_id="ten_b",
                                    state=SubscriptionState.ACTIVE,
                                    tier_id="professional"),
    }
    return store, voices, billing


class AggregationFiguresTest(unittest.TestCase):
    def setUp(self):
        self.store, self.voices, self.billing = two_tenant_world()
        self.overview = build_platform_overview(
            self.store, period=PERIOD, billing_records=self.billing,
            voice_configs=self.voices)
        self.rows = {r["tenant_id"]: r for r in self.overview["tenants"]}

    def test_tenant_a_cost_revenue_contribution(self):
        row = self.rows["ten_a"]
        self.assertEqual(row["voice"]["provider"], "signalwire_say")
        self.assertEqual(row["estimated_cost_cents"], 1195)
        self.assertEqual(row["revenue_cents"], 4900)
        self.assertEqual(row["contribution_cents"], 3705)
        self.assertEqual(row["subscription"]["state"], "active")

    def test_tenant_b_cost_revenue_contribution(self):
        row = self.rows["ten_b"]
        self.assertEqual(row["voice"]["tier"], "premium")
        self.assertEqual(row["voice"]["provider"], "elevenlabs_turbo")
        self.assertEqual(row["estimated_cost_cents"], 1375)
        self.assertEqual(row["revenue_cents"], 9900)
        self.assertEqual(row["contribution_cents"], 8525)

    def test_totals(self):
        totals = self.overview["totals"]
        self.assertEqual(totals["tenant_count"], 2)
        self.assertEqual(totals["tenants_by_status"]["active"], 2)
        current = totals["current_period"]
        self.assertEqual(current["used_minutes"], 150.0)
        self.assertEqual(current["call_count"], 6)
        self.assertEqual(current["estimated_cost_cents"], 1195 + 1375)
        self.assertEqual(current["revenue_cents"], 4900 + 9900)
        self.assertEqual(current["contribution_cents"], 3705 + 8525)

    def test_spending_against_plan_limit(self):
        row_a = self.rows["ten_a"]
        self.assertEqual(row_a["spending"]["plan_limit_minutes"], 120)
        self.assertEqual(row_a["spending"]["remaining_minutes"], 20.0)
        self.assertEqual(row_a["spending"]["percent_used"], 83.3)
        self.assertEqual(row_a["spending"]["status"], "near_limit")
        row_b = self.rows["ten_b"]
        self.assertEqual(row_b["spending"]["plan_limit_minutes"], 350)
        self.assertEqual(row_b["spending"]["status"], "within_limit")

    def test_spending_cap_exceeded(self):
        overview = build_platform_overview(
            self.store, period=PERIOD, billing_records=self.billing,
            voice_configs=self.voices,
            spending_caps={"ten_a": {"cap_minutes": 90.0,
                                     "cap_cad_cents": None}})
        row = {r["tenant_id"]: r for r in overview["tenants"]}["ten_a"]
        self.assertEqual(row["spending"]["status"], "cap_exceeded")
        self.assertEqual(row["spending"]["cap"]["cap_minutes"], 90.0)

    def test_usage_history_present(self):
        row = self.rows["ten_a"]
        history = {h["period"]: h for h in row["usage_history"]}
        self.assertIn(PERIOD, history)
        self.assertEqual(history[PERIOD]["used_minutes"], 100.0)
        self.assertEqual(history[PERIOD]["estimated_cost_cents"], 1195)

    def test_missing_billing_record_is_unknown_not_zero(self):
        overview = build_platform_overview(
            self.store, period=PERIOD, voice_configs=self.voices)
        row = {r["tenant_id"]: r for r in overview["tenants"]}["ten_a"]
        self.assertEqual(row["subscription"]["state"], "unknown")
        self.assertEqual(row["subscription"]["status"], "no_record")
        self.assertIsNone(row["revenue_cents"])
        self.assertIsNone(row["contribution_cents"])
        self.assertEqual(overview["totals"]["tenants_without_billing_record"], 2)


class StatusRepresentationTest(unittest.TestCase):
    def test_suspended_and_deleted_tenants(self):
        store = InMemoryStore()
        make_tenant(store, "ten_live", "Live Biz", "starter")
        make_tenant(store, "ten_susp", "Paused Biz", "starter", status="suspended")
        make_tenant(store, "ten_gone", "Gone Biz", "starter", status="deleted")
        overview = build_platform_overview(store, period=PERIOD)
        by_status = overview["totals"]["tenants_by_status"]
        self.assertEqual(by_status["active"], 1)
        self.assertEqual(by_status["suspended"], 1)
        self.assertEqual(by_status["deleted"], 1)
        rows = {r["tenant_id"]: r for r in overview["tenants"]}
        self.assertEqual(rows["ten_susp"]["status"], "suspended")
        gone = rows["ten_gone"]
        self.assertEqual(gone["status"], "deleted")
        self.assertEqual(gone["estimated_cost_cents"], 0)
        self.assertEqual(gone["revenue_cents"], 0)
        self.assertEqual(gone["spending"]["status"], "closed")


class HealthDefaultsTest(unittest.TestCase):
    def test_registry_defaults_unknown(self):
        registry = HealthRegistry()
        entries = registry.to_dicts()
        self.assertEqual(
            [e["provider"] for e in entries],
            ["signalwire", "elevenlabs", "llm", "redis", "stripe"])
        for entry in entries:
            self.assertEqual(entry["status"], "unknown")
            self.assertIsNone(entry["checked_at"])
            self.assertEqual(entry["source"], "")

    def test_recorded_health_surfaces_as_is(self):
        registry = HealthRegistry()
        registry.record("signalwire", "up", "2026-11-28T08:00:00Z",
                        source="backend probe")
        overview = build_platform_overview(
            InMemoryStore(), period=PERIOD, health_registry=registry)
        health = {h["provider"]: h for h in overview["provider_health"]}
        self.assertEqual(health["signalwire"]["status"], "up")
        self.assertEqual(health["signalwire"]["checked_at"], "2026-11-28T08:00:00Z")
        self.assertEqual(health["stripe"]["status"], "unknown")
        self.assertIsNone(health["stripe"]["checked_at"])

    def test_overview_without_registry_still_unknown(self):
        overview = build_platform_overview(InMemoryStore(), period=PERIOD)
        for entry in overview["provider_health"]:
            self.assertEqual(entry["status"], "unknown")


class CallMetricsTest(unittest.TestCase):
    def setUp(self):
        self.store, self.voices, self.billing = two_tenant_world()

    def test_no_records_is_explicit_no_data(self):
        overview = build_platform_overview(self.store, period=PERIOD)
        for row in overview["tenants"]:
            self.assertEqual(row["calls"]["status"], "no_data")
            self.assertIsNone(row["calls"]["failed"])
            self.assertIsNone(row["calls"]["error_rate"])
        self.assertEqual(overview["call_metrics"]["status"], "no_data")
        self.assertIsNone(overview["call_metrics"]["total"])

    def test_metrics_come_only_from_supplied_records(self):
        records = {
            "ten_a": [
                {"status": "answered"}, {"status": "answered"},
                {"status": "failed"}, {"status": "busy"},
            ],
        }
        overview = build_platform_overview(
            self.store, period=PERIOD, call_records=records)
        rows = {r["tenant_id"]: r for r in overview["tenants"]}
        calls_a = rows["ten_a"]["calls"]
        self.assertEqual(calls_a["status"], "available")
        self.assertEqual(calls_a["total"], 4)
        self.assertEqual(calls_a["failed"], 2)
        self.assertEqual(calls_a["error_rate"], 0.5)
        self.assertEqual(rows["ten_b"]["calls"]["status"], "no_data")
        platform = overview["call_metrics"]
        self.assertEqual(platform["status"], "partial")
        self.assertEqual(platform["total"], 4)
        self.assertEqual(platform["failed"], 2)
        self.assertEqual(platform["error_rate"], 0.5)

    def test_empty_record_list_is_data_with_no_calls(self):
        overview = build_platform_overview(
            self.store, period=PERIOD, call_records={"ten_a": [], "ten_b": []})
        row = {r["tenant_id"]: r for r in overview["tenants"]}["ten_a"]
        self.assertEqual(row["calls"]["status"], "available")
        self.assertEqual(row["calls"]["total"], 0)
        self.assertEqual(row["calls"]["failed"], 0)
        self.assertIsNone(row["calls"]["error_rate"])


class ActiveCallsTest(unittest.TestCase):
    def test_no_provider_is_unknown_not_zero(self):
        overview = build_platform_overview(InMemoryStore(), period=PERIOD)
        self.assertEqual(overview["active_calls"]["status"], "unknown")
        self.assertIsNone(overview["active_calls"]["count"])
        self.assertIsNone(overview["active_calls"]["calls"])

    def test_injected_provider_reports_metadata(self):
        overview = build_platform_overview(
            InMemoryStore(), period=PERIOD,
            active_calls=lambda: [
                {"id": "call_live1", "tenant_id": "ten_a",
                 "created_at": "2026-12-01T15:00:00Z",
                 "direction": "inbound", "status": "in_progress"},
            ])
        active = overview["active_calls"]
        self.assertEqual(active["status"], "available")
        self.assertEqual(active["count"], 1)
        self.assertEqual(active["by_tenant"], {"ten_a": 1})
        self.assertEqual(active["calls"][0]["call_id"], "call_live1")


class OnboardingTest(unittest.TestCase):
    def test_fixture_config_sections(self):
        store = InMemoryStore()
        world = build_two_tenants(store)
        row = build_tenant_row(store, world["a"]["tenant"], period=PERIOD)
        onboarding = row["onboarding"]
        self.assertEqual(onboarding["status"], "partial")
        self.assertIn("instructions", onboarding["missing"])
        self.assertIn("greeting", onboarding["present"])
        self.assertEqual(onboarding["percent"], 93)
        self.assertEqual(row["phone_numbers"], ["+15195550101"])

    def test_no_config_is_not_started(self):
        store = InMemoryStore()
        tenant = make_tenant(store, "ten_new", "New Biz", "starter")
        row = build_tenant_row(store, tenant, period=PERIOD)
        self.assertEqual(row["onboarding"]["status"], "not_started")
        self.assertEqual(row["onboarding"]["percent"], 0)
        self.assertEqual(row["phone_numbers"], [])


class DataMinimizationTest(unittest.TestCase):
    def test_overview_contains_no_call_or_customer_content(self):
        store = InMemoryStore()
        world = build_two_tenants(store)
        call_records = {
            tid: store.list_records(tid, "calls")
            for tid in ("ten_alpha", "ten_beta")
        }
        overview = build_platform_overview(
            store, period=PERIOD, call_records=call_records)
        blob = json.dumps(overview)
        planted = [
            "Secret words from tenant a", "Secret words from tenant b",
            "Summary for a", "Summary for b",
            "Reason a", "Reason b",
            "Caller A", "Caller B",
        ]
        for text in planted:
            self.assertNotIn(text, blob)
        for forbidden_key in ("transcript", "summary", "caller_name",
                              "callback_number", "reason_text", "notes"):
            self.assertNotIn(f'"{forbidden_key}"', blob)


if __name__ == "__main__":
    unittest.main()
