"""Webhook signature verification tests. Standard library only, no network.

The signing secret used here is a clearly fake placeholder for tests only.
"""

import hashlib
import hmac
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from billing.webhooks import (
    ERR_MALFORMED_EVENT,
    ERR_MISSING_HEADER,
    ERR_MISSING_SIGNATURE,
    ERR_SIGNATURE_MISMATCH,
    ERR_TIMESTAMP_OUT_OF_TOLERANCE,
    WebhookVerificationError,
    parse_event,
    verify_and_parse,
    verify_signature,
)

SECRET = "whsec_test_placeholder"
WRONG_SECRET = "whsec_test_wrong_placeholder"
NOW = 1_700_000_000


def make_body(event_type="invoice.paid", tenant_id="ten_abc123"):
    return json.dumps(
        {
            "id": "evt_test_001",
            "type": event_type,
            "created": NOW,
            "data": {
                "object": {
                    "id": "in_test_001",
                    "customer": "cus_test_001",
                    "metadata": {"tenant_id": tenant_id},
                }
            },
        }
    ).encode("utf-8")


def sign(body, secret, timestamp):
    payload = str(timestamp).encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def header_for(body, secret=SECRET, timestamp=NOW, extra_signatures=()):
    sig = sign(body, secret, timestamp)
    parts = [f"t={timestamp}"]
    for extra in extra_signatures:
        parts.append(f"v1={extra}")
    parts.append(f"v1={sig}")
    return ",".join(parts)


class TestValidSignatures(unittest.TestCase):
    def test_valid_signature_accepted(self):
        body = make_body()
        self.assertTrue(verify_signature(body, header_for(body), SECRET, now=NOW))

    def test_verify_and_parse_returns_typed_event(self):
        body = make_body()
        event = verify_and_parse(body, header_for(body), SECRET, now=NOW)
        self.assertEqual(event.id, "evt_test_001")
        self.assertEqual(event.type, "invoice.paid")
        self.assertEqual(event.tenant_id, "ten_abc123")
        self.assertEqual(event.object["customer"], "cus_test_001")

    def test_rotation_two_v1_values_either_position_accepted(self):
        body = make_body()
        bogus = "0" * 64
        header = header_for(body, extra_signatures=(bogus,))
        self.assertTrue(verify_signature(body, header, SECRET, now=NOW))
        good = sign(body, SECRET, NOW)
        header_reversed = f"t={NOW},v1={good},v1={bogus}"
        self.assertTrue(verify_signature(body, header_reversed, SECRET, now=NOW))

    def test_timestamp_at_tolerance_edge_accepted(self):
        body = make_body()
        header = header_for(body, timestamp=NOW - 300)
        self.assertTrue(verify_signature(body, header, SECRET, now=NOW))


class TestRejectedSignatures(unittest.TestCase):
    def test_tampered_body_rejected(self):
        body = make_body()
        header = header_for(body)
        tampered = make_body(event_type="invoice.payment_failed")
        with self.assertRaises(WebhookVerificationError) as ctx:
            verify_signature(tampered, header, SECRET, now=NOW)
        self.assertEqual(ctx.exception.code, ERR_SIGNATURE_MISMATCH)

    def test_wrong_secret_rejected(self):
        body = make_body()
        header = header_for(body, secret=WRONG_SECRET)
        with self.assertRaises(WebhookVerificationError) as ctx:
            verify_signature(body, header, SECRET, now=NOW)
        self.assertEqual(ctx.exception.code, ERR_SIGNATURE_MISMATCH)

    def test_stale_timestamp_rejected(self):
        body = make_body()
        header = header_for(body, timestamp=NOW - 301)
        with self.assertRaises(WebhookVerificationError) as ctx:
            verify_signature(body, header, SECRET, now=NOW)
        self.assertEqual(ctx.exception.code, ERR_TIMESTAMP_OUT_OF_TOLERANCE)

    def test_future_timestamp_beyond_tolerance_rejected(self):
        body = make_body()
        header = header_for(body, timestamp=NOW + 3600)
        with self.assertRaises(WebhookVerificationError) as ctx:
            verify_signature(body, header, SECRET, now=NOW)
        self.assertEqual(ctx.exception.code, ERR_TIMESTAMP_OUT_OF_TOLERANCE)

    def test_missing_header_rejected(self):
        with self.assertRaises(WebhookVerificationError) as ctx:
            verify_signature(make_body(), None, SECRET, now=NOW)
        self.assertEqual(ctx.exception.code, ERR_MISSING_HEADER)
        with self.assertRaises(WebhookVerificationError) as ctx:
            verify_signature(make_body(), "", SECRET, now=NOW)
        self.assertEqual(ctx.exception.code, ERR_MISSING_HEADER)

    def test_header_without_signature_rejected(self):
        with self.assertRaises(WebhookVerificationError) as ctx:
            verify_signature(make_body(), f"t={NOW}", SECRET, now=NOW)
        self.assertEqual(ctx.exception.code, ERR_MISSING_SIGNATURE)

    def test_malformed_header_segment_rejected(self):
        with self.assertRaises(WebhookVerificationError) as ctx:
            verify_signature(make_body(), "not-a-header", SECRET, now=NOW)
        self.assertIn(ctx.exception.code, ("malformed_signature_header", "missing_timestamp"))

    def test_missing_secret_rejected(self):
        body = make_body()
        with self.assertRaises(WebhookVerificationError) as ctx:
            verify_signature(body, header_for(body), "", now=NOW)
        self.assertEqual(ctx.exception.code, "missing_webhook_secret")


class TestEventParsing(unittest.TestCase):
    def test_malformed_json_rejected(self):
        with self.assertRaises(WebhookVerificationError) as ctx:
            parse_event(b"{not json")
        self.assertEqual(ctx.exception.code, ERR_MALFORMED_EVENT)

    def test_event_without_type_rejected(self):
        with self.assertRaises(WebhookVerificationError) as ctx:
            parse_event(json.dumps({"id": "evt_x"}).encode("utf-8"))
        self.assertEqual(ctx.exception.code, ERR_MALFORMED_EVENT)

    def test_tenant_from_client_reference_id(self):
        body = json.dumps(
            {
                "id": "evt_test_002",
                "type": "checkout.session.completed",
                "data": {"object": {"id": "cs_test_001", "client_reference_id": "ten_ref456"}},
            }
        ).encode("utf-8")
        event = parse_event(body)
        self.assertEqual(event.tenant_id, "ten_ref456")


if __name__ == "__main__":
    unittest.main(verbosity=2)
