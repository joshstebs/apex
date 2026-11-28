"""Subscription state machine tests, including failure, grace, and recovery."""

import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from billing.state import (
    InvalidTransitionError,
    SubscriptionRecord,
    SubscriptionState,
    evaluate_grace,
    handle_event,
    transition,
)
from billing.webhooks import parse_event

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_counter = [0]


def event(event_type, status=None, tenant_id="ten_abc123"):
    _counter[0] += 1
    obj = {"id": "obj_test_001", "customer": "cus_test_001", "metadata": {"tenant_id": tenant_id}}
    if event_type.startswith("customer.subscription."):
        obj["id"] = "sub_test_001"
    if event_type.startswith("checkout."):
        obj["subscription"] = "sub_test_001"
    if status is not None:
        obj["status"] = status
    body = json.dumps(
        {"id": f"evt_test_{_counter[0]:03d}", "type": event_type, "data": {"object": obj}}
    ).encode("utf-8")
    return parse_event(body)


def active_record():
    record = SubscriptionRecord(tenant_id="ten_abc123", tier_id="starter", grace_days=7)
    handle_event(record, event("checkout.session.completed"), now=T0)
    assert record.state == SubscriptionState.ACTIVE
    return record


class TestHappyPaths(unittest.TestCase):
    def test_checkout_completed_activates(self):
        record = SubscriptionRecord(tenant_id="ten_abc123")
        handle_event(record, event("checkout.session.completed"), now=T0)
        self.assertEqual(record.state, SubscriptionState.ACTIVE)
        self.assertEqual(record.stripe_subscription_id, "sub_test_001")
        self.assertTrue(record.service_continues)

    def test_subscription_created_trialing_then_paid_activates(self):
        record = SubscriptionRecord(tenant_id="ten_abc123")
        handle_event(record, event("customer.subscription.created", status="trialing"), now=T0)
        self.assertEqual(record.state, SubscriptionState.TRIALING)
        handle_event(record, event("invoice.paid"), now=T0 + timedelta(days=14))
        self.assertEqual(record.state, SubscriptionState.ACTIVE)

    def test_subscription_deleted_cancels(self):
        record = active_record()
        handle_event(record, event("customer.subscription.deleted"), now=T0 + timedelta(days=30))
        self.assertEqual(record.state, SubscriptionState.CANCELED)
        self.assertFalse(record.service_continues)

    def test_invoice_finalized_is_informational(self):
        record = active_record()
        handle_event(record, event("invoice.finalized"), now=T0 + timedelta(days=30))
        self.assertEqual(record.state, SubscriptionState.ACTIVE)
        self.assertEqual(record.last_finalized_invoice_id, "obj_test_001")

    def test_canceled_tenant_can_resubscribe_via_checkout(self):
        record = active_record()
        handle_event(record, event("customer.subscription.deleted"), now=T0 + timedelta(days=30))
        handle_event(record, event("checkout.session.completed"), now=T0 + timedelta(days=31))
        self.assertEqual(record.state, SubscriptionState.ACTIVE)


class TestFailureAndGrace(unittest.TestCase):
    def test_first_failure_goes_past_due_and_service_continues(self):
        record = active_record()
        handle_event(record, event("invoice.payment_failed"), now=T0 + timedelta(days=30))
        self.assertEqual(record.state, SubscriptionState.PAST_DUE)
        self.assertEqual(record.failure_count, 1)
        self.assertTrue(record.service_continues)
        self.assertFalse(record.suspend_recommended)
        self.assertEqual(record.grace_expires_at, T0 + timedelta(days=37))

    def test_grace_holds_before_expiry(self):
        record = active_record()
        failed_at = T0 + timedelta(days=30)
        handle_event(record, event("invoice.payment_failed"), now=failed_at)
        evaluate_grace(record, now=failed_at + timedelta(days=6, hours=23))
        self.assertEqual(record.state, SubscriptionState.PAST_DUE)
        self.assertFalse(record.suspend_recommended)

    def test_grace_expiry_goes_unpaid_and_recommends_suspension(self):
        record = active_record()
        failed_at = T0 + timedelta(days=30)
        handle_event(record, event("invoice.payment_failed"), now=failed_at)
        evaluate_grace(record, now=failed_at + timedelta(days=7))
        self.assertEqual(record.state, SubscriptionState.UNPAID)
        self.assertTrue(record.suspend_recommended)
        self.assertFalse(record.service_continues)

    def test_recovery_on_invoice_paid_during_grace(self):
        record = active_record()
        failed_at = T0 + timedelta(days=30)
        handle_event(record, event("invoice.payment_failed"), now=failed_at)
        handle_event(record, event("invoice.paid"), now=failed_at + timedelta(days=3))
        self.assertEqual(record.state, SubscriptionState.ACTIVE)
        self.assertEqual(record.failure_count, 0)
        self.assertIsNone(record.past_due_since)
        self.assertFalse(record.suspend_recommended)
        self.assertTrue(record.service_continues)

    def test_recovery_on_invoice_paid_after_grace_expiry(self):
        record = active_record()
        failed_at = T0 + timedelta(days=30)
        handle_event(record, event("invoice.payment_failed"), now=failed_at)
        evaluate_grace(record, now=failed_at + timedelta(days=8))
        self.assertEqual(record.state, SubscriptionState.UNPAID)
        handle_event(record, event("invoice.paid"), now=failed_at + timedelta(days=9))
        self.assertEqual(record.state, SubscriptionState.ACTIVE)
        self.assertFalse(record.suspend_recommended)

    def test_repeated_failures_increment_count_without_resetting_grace(self):
        record = active_record()
        failed_at = T0 + timedelta(days=30)
        handle_event(record, event("invoice.payment_failed"), now=failed_at)
        handle_event(record, event("invoice.payment_failed"), now=failed_at + timedelta(days=2))
        self.assertEqual(record.state, SubscriptionState.PAST_DUE)
        self.assertEqual(record.failure_count, 2)
        self.assertEqual(record.past_due_since, failed_at)


class TestTransitionGuards(unittest.TestCase):
    def test_invalid_transition_raises(self):
        record = SubscriptionRecord(tenant_id="ten_abc123")
        with self.assertRaises(InvalidTransitionError):
            transition(record, SubscriptionState.PAST_DUE, now=T0)

    def test_tenant_id_must_be_tenant_scoped(self):
        with self.assertRaises(ValueError):
            SubscriptionRecord(tenant_id="acme-plumbing")

    def test_unknown_event_is_noted_not_fatal(self):
        record = active_record()
        handle_event(record, event("payment_intent.created"), now=T0)
        self.assertEqual(record.state, SubscriptionState.ACTIVE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
