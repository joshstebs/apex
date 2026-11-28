"""Usage, overage, reconciliation, mode guard, and payload builder tests."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from billing.config import BillingConfig, BillingModeError
from billing.payloads import (
    build_billing_portal_payload,
    build_checkout_session_payload,
    build_subscription_update_payload,
)
from billing.usage import (
    CallUsage,
    meter_report_payload,
    reconcile_usage,
    summarize_usage,
)

TENANT = "ten_abc123"
OTHER = "ten_other999"


def calls(tenant, seconds_list):
    return [CallUsage(tenant_id=tenant, duration_seconds=s) for s in seconds_list]


def minutes_calls(tenant, total_minutes):
    # One synthetic call per minute keeps per call rounding neutral.
    return calls(tenant, [60] * total_minutes)


class TestRounding(unittest.TestCase):
    def test_minutes_round_up_per_call(self):
        self.assertEqual(CallUsage(tenant_id=TENANT, duration_seconds=61).billable_minutes(), 2)
        self.assertEqual(CallUsage(tenant_id=TENANT, duration_seconds=60).billable_minutes(), 1)
        self.assertEqual(CallUsage(tenant_id=TENANT, duration_seconds=1).billable_minutes(), 1)
        self.assertEqual(CallUsage(tenant_id=TENANT, duration_seconds=0).billable_minutes(), 0)

    def test_rounding_is_per_call_not_per_period(self):
        summary = summarize_usage(TENANT, "starter", calls(TENANT, [61, 61]))
        # 2 plus 2 per call rounding, not 3 from rounding the 122 second total.
        self.assertEqual(summary.total_minutes, 4)


class TestOverageMath(unittest.TestCase):
    def check_tier(self, tier_id, included, overage_cents):
        at_limit = summarize_usage(TENANT, tier_id, minutes_calls(TENANT, included))
        self.assertEqual(at_limit.total_minutes, included)
        self.assertEqual(at_limit.included_consumed, included)
        self.assertEqual(at_limit.overage_minutes, 0)
        self.assertEqual(at_limit.overage_amount_cad_cents, 0)

        one_over = summarize_usage(TENANT, tier_id, minutes_calls(TENANT, included + 1))
        self.assertEqual(one_over.overage_minutes, 1)
        self.assertEqual(one_over.overage_amount_cad_cents, overage_cents)

        under = summarize_usage(TENANT, tier_id, minutes_calls(TENANT, included - 10))
        self.assertEqual(under.included_consumed, included - 10)
        self.assertEqual(under.overage_minutes, 0)

    def test_starter_overage(self):
        self.check_tier("starter", 120, 40)

    def test_professional_overage(self):
        self.check_tier("professional", 350, 35)

    def test_business_overage(self):
        self.check_tier("business", 800, 30)

    def test_larger_overage_scales_linearly(self):
        summary = summarize_usage(TENANT, "professional", minutes_calls(TENANT, 450))
        self.assertEqual(summary.overage_minutes, 100)
        self.assertEqual(summary.overage_amount_cad_cents, 3500)

    def test_other_tenants_records_are_ignored(self):
        records = minutes_calls(TENANT, 10) + minutes_calls(OTHER, 5000)
        summary = summarize_usage(TENANT, "starter", records)
        self.assertEqual(summary.total_minutes, 10)
        self.assertEqual(summary.call_count, 10)

    def test_dict_records_accepted(self):
        summary = summarize_usage(
            TENANT, "starter", [{"tenant_id": TENANT, "duration_seconds": 90}]
        )
        self.assertEqual(summary.total_minutes, 2)

    def test_enterprise_overage_is_not_guessed(self):
        summary = summarize_usage(TENANT, "enterprise", minutes_calls(TENANT, 10))
        self.assertIsNone(summary.overage_minutes)
        self.assertIsNone(summary.overage_amount_cad_cents)


class TestMeterReport(unittest.TestCase):
    def test_payload_shape_and_summarize_action(self):
        summary = summarize_usage(TENANT, "starter", minutes_calls(TENANT, 150))
        payload = meter_report_payload(summary, timestamp=1_700_000_000)
        self.assertEqual(payload["event_name"], "apexvoice_overage_minutes")
        self.assertEqual(payload["action"], "summarize")
        self.assertEqual(payload["value"], "30")
        self.assertEqual(payload["payload"]["tenant_id"], TENANT)
        self.assertEqual(payload["payload"]["total_minutes"], "150")

    def test_enterprise_meter_report_refused(self):
        summary = summarize_usage(TENANT, "enterprise", minutes_calls(TENANT, 10))
        with self.assertRaises(ValueError):
            meter_report_payload(summary, timestamp=1_700_000_000)


class TestReconciliation(unittest.TestCase):
    def test_no_drift(self):
        result = reconcile_usage(TENANT, 100, 100)
        self.assertEqual(result.drift_minutes, 0)
        self.assertFalse(result.drift_exceeded)

    def test_drift_at_threshold_not_flagged(self):
        result = reconcile_usage(TENANT, 105, 100, threshold_minutes=5)
        self.assertEqual(result.drift_minutes, 5)
        self.assertFalse(result.drift_exceeded)

    def test_drift_beyond_threshold_flagged(self):
        result = reconcile_usage(TENANT, 106, 100, threshold_minutes=5)
        self.assertEqual(result.drift_minutes, 6)
        self.assertTrue(result.drift_exceeded)

    def test_underreporting_also_flagged(self):
        result = reconcile_usage(TENANT, 90, 100, threshold_minutes=5)
        self.assertEqual(result.drift_minutes, 10)
        self.assertTrue(result.drift_exceeded)


class TestLiveModeGuard(unittest.TestCase):
    def test_unset_mode_defaults_to_test(self):
        config = BillingConfig.from_env({})
        self.assertEqual(config.mode, "test")

    def test_explicit_test_mode_accepted(self):
        config = BillingConfig.from_env({"APEX_BILLING_MODE": "test"})
        self.assertEqual(config.mode, "test")

    def test_live_mode_raises(self):
        with self.assertRaises(BillingModeError):
            BillingConfig.from_env({"APEX_BILLING_MODE": "live"})

    def test_any_non_test_mode_raises(self):
        with self.assertRaises(BillingModeError):
            BillingConfig.from_env({"APEX_BILLING_MODE": "production"})

    def test_live_key_raises_even_in_test_mode(self):
        with self.assertRaises(BillingModeError):
            BillingConfig.from_env({"STRIPE_SECRET_KEY": "sk_live_placeholder_not_real"})

    def test_repr_never_shows_secret_values(self):
        marker = "whsec_test_placeholder_value"
        config = BillingConfig.from_env({"STRIPE_WEBHOOK_SECRET": marker})
        self.assertNotIn(marker, repr(config))
        self.assertNotIn(marker, str(config))
        self.assertIn("webhook_secret_set=True", repr(config))


class TestPayloadBuilders(unittest.TestCase):
    def test_checkout_carries_tenant_metadata(self):
        payload = build_checkout_session_payload(
            TENANT,
            "professional",
            success_url="https://example.test/billing/success",
            cancel_url="https://example.test/billing/cancel",
        )
        self.assertEqual(payload["mode"], "subscription")
        self.assertEqual(payload["client_reference_id"], TENANT)
        self.assertEqual(payload["metadata"]["tenant_id"], TENANT)
        self.assertEqual(payload["subscription_data"]["metadata"]["tenant_id"], TENANT)
        self.assertEqual(payload["subscription_data"]["metadata"]["tier_id"], "professional")

    def test_portal_payload(self):
        payload = build_billing_portal_payload(
            TENANT, "cus_test_001", return_url="https://example.test/dashboard"
        )
        self.assertEqual(payload["customer"], "cus_test_001")
        self.assertEqual(payload["return_url"], "https://example.test/dashboard")

    def test_subscription_update_proration_flag(self):
        payload = build_subscription_update_payload(TENANT, "si_test_001", "business")
        self.assertEqual(payload["proration_behavior"], "create_prorations")
        self.assertEqual(payload["metadata"]["tenant_id"], TENANT)
        downgrade = build_subscription_update_payload(
            TENANT, "si_test_001", "starter", proration_behavior="none"
        )
        self.assertEqual(downgrade["proration_behavior"], "none")
        with self.assertRaises(ValueError):
            build_subscription_update_payload(
                TENANT, "si_test_001", "starter", proration_behavior="whenever"
            )

    def test_enterprise_has_no_self_serve_checkout(self):
        with self.assertRaises(ValueError):
            build_checkout_session_payload(
                TENANT,
                "enterprise",
                success_url="https://example.test/ok",
                cancel_url="https://example.test/no",
            )

    def test_tenant_id_validated(self):
        with self.assertRaises(ValueError):
            build_checkout_session_payload(
                "acme-plumbing",
                "starter",
                success_url="https://example.test/ok",
                cancel_url="https://example.test/no",
            )

    def test_no_secret_material_in_any_payload(self):
        payloads = [
            build_checkout_session_payload(
                TENANT,
                "starter",
                success_url="https://example.test/ok",
                cancel_url="https://example.test/no",
            ),
            build_billing_portal_payload(
                TENANT, "cus_test_001", return_url="https://example.test/dashboard"
            ),
            build_subscription_update_payload(TENANT, "si_test_001", "business"),
            meter_report_payload(
                summarize_usage(TENANT, "starter", minutes_calls(TENANT, 130)),
                timestamp=1_700_000_000,
            ),
        ]
        for payload in payloads:
            blob = json.dumps(payload)
            self.assertNotIn("sk_test", blob)
            self.assertNotIn("sk_live", blob)
            self.assertNotIn("whsec", blob)


if __name__ == "__main__":
    unittest.main(verbosity=2)
