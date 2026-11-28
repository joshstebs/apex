"""Tests for the ApexVoice support and operations readiness package.

Covers ticket tenant scoping and escalation audit entries, notification
payload construction and suppression, monthly summary totals against
hand-computed figures, and export safety (no credential or session
material, config backup revalidates).

Run from this directory with the Phase 3 tree importable:
    python3 -m unittest test_support_workflows
"""

import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PHASE3 = os.path.dirname(os.path.abspath(__file__))
for _path in (_HERE, _PHASE3):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tenancy import (
    CallRecord, InMemoryStore, MessageRecord, PlatformOperator, Session,
    TenantLifecycle, UsageRecord,
)
from tenancy_fixtures import valid_config

from support import exports as exports_mod
from support import notifications as notif
from support import summaries
from support.tickets import (
    InvalidTicketChange, PlatformViewer, SupportStore, TenantViewer,
    TicketNotVisible,
)

TENANT_A = "ten_alpha"
TENANT_B = "ten_beta"
OPERATOR = PlatformOperator(operator_id="ops-test")
PERIOD = "202611"


def build_world():
    """Two tenants with owners, configs, DIDs, and records."""
    store = InMemoryStore()
    lifecycle = TenantLifecycle(store)
    tenant_a, owner_a = lifecycle.create_tenant(
        OPERATOR, "Alpha Plumbing", "owner-a@example.com", "alpha-password-1",
        config=valid_config("Alpha Plumbing", "owner-a@example.com", "+15195550101"),
        did="+15195550101", tenant_id=TENANT_A)
    tenant_b, owner_b = lifecycle.create_tenant(
        OPERATOR, "Beta Salon", "owner-b@example.com", "beta-password-2",
        plan_tier="professional",
        config=valid_config("Beta Salon", "owner-b@example.com", "+15195550102"),
        did="+15195550102", tenant_id=TENANT_B)
    store.put_record("calls", CallRecord(
        id="call_a1", tenant_id=TENANT_A, from_number="+15195559999",
        to_number="+15195550101", status="answered", duration_seconds=180,
        contact_name="Caller One"))
    store.put_record("messages", MessageRecord(
        id="msg_a1", tenant_id=TENANT_A, call_id="call_a1",
        caller_name="Caller One", callback_number="+15195559999",
        reason="Quote request", preferred_time="mornings"))
    store.put_record("usage", UsageRecord(
        id="use_a1", tenant_id=TENANT_A, call_id="call_a1", period=PERIOD,
        minutes=3.0, calls=1, tts_characters=1200, stt_seconds=150.0))
    return store, owner_a, owner_b


class TicketScopingTests(unittest.TestCase):
    def setUp(self):
        self.store = SupportStore()
        self.viewer_a = TenantViewer(tenant_id=TENANT_A, user_id="usr_a")
        self.viewer_b = TenantViewer(tenant_id=TENANT_B, user_id="usr_b")
        self.platform = PlatformViewer(operator_id="ops-test")
        self.ticket_a = self.store.create_ticket(
            self.viewer_a, TENANT_A, "technical", "normal",
            "Receptionist not answering", "Calls ring out since Tuesday.")
        self.ticket_b = self.store.create_ticket(
            self.viewer_b, TENANT_B, "billing", "low",
            "Question about my invoice", "Please explain the overage line.")

    def test_tenant_lists_only_own_tickets(self):
        mine = self.store.list_tickets(self.viewer_a)
        self.assertEqual([t.id for t in mine], [self.ticket_a.id])
        theirs = self.store.list_tickets(self.viewer_b)
        self.assertEqual([t.id for t in theirs], [self.ticket_b.id])

    def test_platform_lists_all_tickets(self):
        all_tickets = self.store.list_tickets(self.platform)
        self.assertEqual(len(all_tickets), 2)

    def test_tenant_cannot_get_another_tenants_ticket(self):
        self.assertIsNone(self.store.get_ticket(self.viewer_b, self.ticket_a.id))
        self.assertIsNotNone(self.store.get_ticket(self.viewer_a, self.ticket_a.id))

    def test_tenant_cannot_create_for_another_tenant(self):
        with self.assertRaises(TicketNotVisible):
            self.store.create_ticket(
                self.viewer_a, TENANT_B, "other", "low", "Forged", "Nope.")

    def test_unknown_category_rejected(self):
        with self.assertRaises(InvalidTicketChange):
            self.store.create_ticket(
                self.viewer_a, TENANT_A, "sales", "low", "Bad", "Bad category.")

    def test_status_change_writes_audit_entry(self):
        self.store.change_status(self.platform, self.ticket_a.id, "acknowledged")
        self.store.change_status(self.platform, self.ticket_a.id, "in_progress",
                                 note="Investigating with provider logs")
        actions = [e["action"] for e in self.ticket_a.audit]
        self.assertEqual(actions.count("ticket.status_changed"), 2)
        detail = self.ticket_a.audit[-1]["detail"]
        self.assertIn("acknowledged -> in_progress", detail)
        self.assertEqual(self.ticket_a.status, "in_progress")

    def test_tenant_can_close_own_resolved_ticket(self):
        self.store.change_status(self.platform, self.ticket_a.id, "resolved")
        self.store.change_status(self.viewer_a, self.ticket_a.id, "closed")
        self.assertEqual(self.ticket_a.status, "closed")

    def test_tenant_cannot_drive_status_workflow(self):
        with self.assertRaises(InvalidTicketChange):
            self.store.change_status(self.viewer_a, self.ticket_a.id, "in_progress")

    def test_escalation_raises_priority_and_writes_audit(self):
        self.store.escalate(self.viewer_a, self.ticket_a.id,
                            "Customers are reporting missed calls")
        self.assertEqual(self.ticket_a.priority, "high")
        self.assertTrue(self.ticket_a.escalated)
        entries = [e for e in self.ticket_a.audit if e["action"] == "ticket.escalated"]
        self.assertEqual(len(entries), 1)
        self.assertIn("normal -> high", entries[0]["detail"])
        self.assertIn("missed calls", entries[0]["detail"])

    def test_escalation_requires_reason(self):
        with self.assertRaises(InvalidTicketChange):
            self.store.escalate(self.viewer_a, self.ticket_a.id, "  ")

    def test_escalation_caps_at_urgent(self):
        self.store.escalate(self.platform, self.ticket_a.id, "one")
        self.store.escalate(self.platform, self.ticket_a.id, "two")
        self.store.escalate(self.platform, self.ticket_a.id, "three")
        self.assertEqual(self.ticket_a.priority, "urgent")

    def test_cannot_escalate_another_tenants_ticket(self):
        with self.assertRaises(TicketNotVisible):
            self.store.escalate(self.viewer_b, self.ticket_a.id, "Not mine")


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.ledger = notif.NotificationLedger()
        self.recipients = ["owner-a@example.com"]

    def test_outage_notice_payload_and_suppression(self):
        incident = {"incident_id": "inc_1", "provider": "SignalWire",
                    "summary": "Inbound calls in Ontario are failing.",
                    "started_at": "2026-11-28T12:00:00Z"}
        payload = notif.provider_outage_notice(
            TENANT_A, "Alpha Plumbing", self.recipients, incident, self.ledger)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["kind"], "provider_outage")
        self.assertEqual(payload["from"], "josh@harbourandmain.com")
        self.assertEqual(payload["to"], self.recipients)
        self.assertIn("SignalWire", payload["body"])
        again = notif.provider_outage_notice(
            TENANT_A, "Alpha Plumbing", self.recipients, incident, self.ledger)
        self.assertIsNone(again)
        other = dict(incident, incident_id="inc_2")
        self.assertIsNotNone(notif.provider_outage_notice(
            TENANT_A, "Alpha Plumbing", self.recipients, other, self.ledger))

    def test_failed_call_alert_threshold_and_suppression(self):
        below = notif.failed_call_alert(
            TENANT_A, "Alpha Plumbing", self.recipients, 2, "this morning",
            "2026-11-28-am", self.ledger)
        self.assertIsNone(below)
        payload = notif.failed_call_alert(
            TENANT_A, "Alpha Plumbing", self.recipients, 3, "this morning",
            "2026-11-28-am", self.ledger)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["kind"], "failed_call_alert")
        repeat = notif.failed_call_alert(
            TENANT_A, "Alpha Plumbing", self.recipients, 5, "this morning",
            "2026-11-28-am", self.ledger)
        self.assertIsNone(repeat)
        new_window = notif.failed_call_alert(
            TENANT_A, "Alpha Plumbing", self.recipients, 4, "this afternoon",
            "2026-11-28-pm", self.ledger)
        self.assertIsNotNone(new_window)

    def test_usage_threshold_fires_once_per_threshold(self):
        below = notif.usage_threshold_warning(
            TENANT_A, "Alpha Plumbing", self.recipients, "starter",
            50, 120, PERIOD, self.ledger)
        self.assertIsNone(below)
        at80 = notif.usage_threshold_warning(
            TENANT_A, "Alpha Plumbing", self.recipients, "starter",
            96, 120, PERIOD, self.ledger)
        self.assertIsNotNone(at80)
        self.assertEqual(at80["meta"]["threshold_percent"], 80)
        repeat80 = notif.usage_threshold_warning(
            TENANT_A, "Alpha Plumbing", self.recipients, "starter",
            100, 120, PERIOD, self.ledger)
        self.assertIsNone(repeat80)
        at100 = notif.usage_threshold_warning(
            TENANT_A, "Alpha Plumbing", self.recipients, "starter",
            121, 120, PERIOD, self.ledger)
        self.assertIsNotNone(at100)
        self.assertEqual(at100["meta"]["threshold_percent"], 100)
        repeat100 = notif.usage_threshold_warning(
            TENANT_A, "Alpha Plumbing", self.recipients, "starter",
            130, 120, PERIOD, self.ledger)
        self.assertIsNone(repeat100)
        next_period = notif.usage_threshold_warning(
            TENANT_A, "Alpha Plumbing", self.recipients, "starter",
            96, 120, "202612", self.ledger)
        self.assertIsNotNone(next_period)

    def test_payment_failure_notice_references_grace_policy(self):
        payload = notif.payment_failure_notice(
            TENANT_A, "Alpha Plumbing", self.recipients,
            grace_expires_on="2026-12-05")
        self.assertEqual(payload["kind"], "payment_failure")
        self.assertIn("7 day grace period", payload["body"])
        self.assertIn("Nothing is suspended automatically", payload["body"])
        self.assertIn("2026-12-05", payload["body"])

    def test_monthly_summary_email_wraps_text(self):
        payload = notif.monthly_usage_summary_email(
            TENANT_A, "Alpha Plumbing", self.recipients,
            "Minutes used: 80", PERIOD)
        self.assertEqual(payload["kind"], "monthly_usage_summary")
        self.assertIn(PERIOD, payload["subject"])
        self.assertIn("Minutes used: 80", payload["body"])


class SummaryTests(unittest.TestCase):
    def _records(self):
        return [
            {"tenant_id": TENANT_A, "period": PERIOD, "minutes": 30.0,
             "calls": 20, "tts_characters": 10000, "stt_seconds": 600.0},
            {"tenant_id": TENANT_A, "period": PERIOD, "minutes": 50.5,
             "calls": 30, "tts_characters": 5000, "stt_seconds": 300.0},
            {"tenant_id": TENANT_B, "period": PERIOD, "minutes": 999.0,
             "calls": 999, "tts_characters": 999, "stt_seconds": 999.0},
            {"tenant_id": TENANT_A, "period": "202610", "minutes": 7.0,
             "calls": 7, "tts_characters": 7, "stt_seconds": 7.0},
        ]

    def test_totals_match_hand_computed_figures(self):
        result = summaries.monthly_summary(
            self._records(), TENANT_A, PERIOD, plan_tier="starter")
        self.assertEqual(result["calls"], 50)
        self.assertEqual(result["minutes"], 80.5)
        self.assertEqual(result["tts_characters"], 15000)
        self.assertEqual(result["stt_seconds"], 900.0)
        self.assertEqual(result["plan_limit_minutes"], 120)
        self.assertEqual(result["overage_minutes"], 0.0)
        # 80.5 min x 13.5c + 15000 chars / 1000 x 10.4c = 1086.75 + 156 = 1242.75
        self.assertEqual(result["estimated_cost_cents"], 1243)

    def test_overage_minutes(self):
        records = self._records() + [
            {"tenant_id": TENANT_A, "period": PERIOD, "minutes": 60.0,
             "calls": 10, "tts_characters": 0, "stt_seconds": 0.0},
        ]
        result = summaries.monthly_summary(
            records, TENANT_A, PERIOD, plan_tier="starter")
        self.assertEqual(result["minutes"], 140.5)
        self.assertEqual(result["overage_minutes"], 20.5)

    def test_enterprise_has_no_fixed_limit(self):
        result = summaries.monthly_summary(
            self._records(), TENANT_A, PERIOD, plan_tier="enterprise")
        self.assertIsNone(result["plan_limit_minutes"])
        self.assertEqual(result["overage_minutes"], 0.0)

    def test_summary_text_contains_figures(self):
        result = summaries.monthly_summary(
            self._records(), TENANT_A, PERIOD, plan_tier="starter")
        text = summaries.summary_to_text(result, "Alpha Plumbing")
        self.assertIn("Alpha Plumbing", text)
        self.assertIn("Calls: 50", text)
        self.assertIn("Minutes used: 80.5", text)
        self.assertIn("$12.43 CAD", text)
        self.assertIn("not an invoice", text)

    def test_summary_from_tenancy_records(self):
        store, _a, _b = build_world()
        records = store.list_records(TENANT_A, "usage")
        result = summaries.monthly_summary(
            records, TENANT_A, PERIOD, plan_tier="starter")
        self.assertEqual(result["calls"], 1)
        self.assertEqual(result["minutes"], 3.0)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.store, self.owner_a, self.owner_b = build_world()
        # Plant a session with a marker token hash in the store.
        self.store.put_session(Session(
            id="ses_marker", tenant_id=TENANT_A, user_id=self.owner_a.id,
            token_hash="SESSION_MARKER_9f3d2c", created_at_epoch=1.0,
            expires_at_epoch=2.0))
        self.export = exports_mod.export_tenant_data(
            self.store, TENANT_A, exported_at="2026-11-28T00:00:00Z")
        self.blob = json.dumps(self.export)

    def test_export_shape(self):
        self.assertEqual(self.export["tenant"]["id"], TENANT_A)
        self.assertEqual(self.export["tenant"]["plan_tier"], "starter")
        self.assertEqual(self.export["phone_numbers"][0]["did"], "+15195550101")
        self.assertEqual(len(self.export["records"]["calls"]), 1)
        self.assertEqual(len(self.export["records"]["messages"]), 1)
        self.assertEqual(len(self.export["records"]["usage"]), 1)
        json.dumps(self.export)  # must stay JSON serializable

    def test_no_password_material_in_export(self):
        owner_record = self.store.get_user_by_email(TENANT_A, "owner-a@example.com")
        self.assertTrue(owner_record.password_hash)
        self.assertNotIn(owner_record.password_hash, self.blob)
        self.assertNotIn(owner_record.password_salt, self.blob)
        self.assertNotIn("alpha-password-1", self.blob)
        user_entry = self.export["users"][0]
        self.assertEqual(
            set(user_entry.keys()),
            {"id", "tenant_id", "email", "role", "status"})

    def test_no_session_material_in_export(self):
        self.assertNotIn("SESSION_MARKER_9f3d2c", self.blob)
        self.assertNotIn("sessions", self.export)

    def test_safety_scan_is_clean(self):
        self.assertEqual(exports_mod.validate_export_safety(self.export), [])

    def test_safety_scan_catches_planted_secret_key(self):
        tampered = json.loads(self.blob)
        tampered["records"]["calls"][0]["api_key"] = "planted"
        findings = exports_mod.validate_export_safety(tampered)
        self.assertTrue(any("api_key" in f for f in findings))

    def test_config_backup_matches_and_revalidates(self):
        backup = exports_mod.config_backup(self.export)
        self.assertEqual(backup["businessName"], "Alpha Plumbing")
        check = exports_mod.restore_readiness_check(self.export)
        self.assertTrue(check["ok"], check)

    def test_restore_check_fails_on_broken_config(self):
        tampered = json.loads(self.blob)
        del tampered["config"]["businessName"]
        check = exports_mod.restore_readiness_check(tampered)
        self.assertFalse(check["ok"])
        self.assertIn("businessName", check["problems"])

    def test_export_excludes_other_tenant(self):
        self.assertNotIn("Beta Salon", self.blob)
        self.assertNotIn("+15195550102", self.blob)

    def test_retention_defaults_documented(self):
        defaults = exports_mod.RETENTION_DEFAULTS
        self.assertEqual(defaults["transcripts_days_by_plan"]["starter"], 90)
        self.assertIn("pending legal review", defaults["status"])


if __name__ == "__main__":
    unittest.main()
