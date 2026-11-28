"""Tests for the Harbour & Main pilot configuration.

The pilot config must validate against the BusinessConfig rules the
tenancy package enforces, carry the AI disclosure and the 911 emergency
direction, use request-only booking, aim transfers at the verified
business number, and must not present invented business facts as real:
unverified items live in the toConfirm list, and the structured hours
are the flagged legacy placeholder, not a claim.

Run from this directory:
    python3 -m unittest test_pilot_config
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

from tenancy.models import TenantConfig, validate_business_config

PILOT_PATH = os.path.join(_HERE, "pilots", "harbour_main_pilot.json")
VERIFIED_PHONE_E164 = "+15485610651"
VERIFIED_EMAIL = "josh@harbourandmain.com"


def load_pilot():
    with open(PILOT_PATH, encoding="utf-8") as handle:
        return json.load(handle)


class PilotConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = load_pilot()
        cls.config = cls.doc["config"]

    def test_config_validates_against_tenancy_rules(self):
        problems = validate_business_config(self.config)
        self.assertEqual(problems, {})

    def test_config_constructs_as_tenant_config(self):
        tenant_config = TenantConfig(
            tenant_id="ten_harbour_main", config=self.config)
        self.assertEqual(tenant_config.business_name, "Harbour & Main")

    def test_verified_contact_facts(self):
        self.assertEqual(self.config["businessName"], "Harbour & Main")
        self.assertEqual(self.config["contact"]["email"], VERIFIED_EMAIL)
        self.assertEqual(self.config["contact"]["phone"], VERIFIED_PHONE_E164)
        self.assertEqual(self.doc["pilot"]["tenantId"], "ten_harbour_main")

    def test_ai_disclosure_present(self):
        greeting = self.config["greeting"]
        self.assertIn("Harbour & Main", greeting)
        self.assertIn("AI receptionist", greeting)
        self.assertIn("transcribed", greeting)
        self.assertIn("AI receptionist", self.config["afterHours"]["greeting"])
        instructions = self.config["instructions"]
        self.assertIn("not a person", instructions)
        self.assertIn("are human", instructions)

    def test_emergency_direction_to_911(self):
        instructions = self.config["instructions"]
        self.assertIn("911", instructions)
        self.assertIn("hang up and call 911", instructions)

    def test_booking_is_request_only(self):
        self.assertEqual(self.config["bookingPrefs"]["mode"], "request_only")
        self.assertIn("request only",
                      self.config["bookingPrefs"]["notes"].lower())
        self.assertIn("will call back to confirm",
                      self.config["instructions"])

    def test_transfer_target_is_verified_business_number(self):
        numbers = self.config["transferRules"]["numbers"]
        self.assertEqual(len(numbers), 1)
        self.assertEqual(numbers[0]["phone"], VERIFIED_PHONE_E164)
        self.assertEqual(self.config["transferRules"]["fallback"], "take_message")

    def test_message_taking_fields_in_instructions(self):
        instructions = self.config["instructions"]
        for phrase in ("name", "callback number", "reason for the call",
                       "preferred contact time"):
            self.assertIn(phrase, instructions)
        self.assertIn("Read the callback number back", instructions)

    def test_fallback_behaviour_is_take_a_message_not_a_guess(self):
        instructions = self.config["instructions"]
        self.assertIn("take a message instead of guessing", instructions)
        self.assertIn("A complete message is always a successful outcome",
                      instructions)

    def test_no_invented_prices(self):
        for service in self.config["services"]:
            self.assertEqual(service["price"], "")
        blob = json.dumps(self.config)
        for figure in ("1450", "2850", "4800", "$1,450", "$2,850", "$4,800"):
            self.assertNotIn(figure, blob)

    def test_services_are_the_two_verified_lines(self):
        names = [s["name"] for s in self.config["services"]]
        self.assertEqual(len(names), 2)
        self.assertTrue(any("Website design" in n for n in names))
        self.assertTrue(any("AI receptionist" in n for n in names))

    def test_message_delivery_goes_to_verified_email(self):
        delivery = self.config["messageDelivery"]
        self.assertEqual(delivery["emailTo"], [VERIFIED_EMAIL])
        self.assertNotIn("sms", delivery["methods"])

    def test_pilot_limits_are_strict(self):
        limits = self.doc["limits"]
        self.assertEqual(limits["maxCallDurationMinutes"], 5)
        self.assertEqual(limits["maxCallDurationSeconds"], 300)
        self.assertEqual(limits["spendingCapCad"], 5.0)
        self.assertTrue(limits["testCallersOnly"])
        self.assertFalse(limits["receptionistEnabledPublic"])
        self.assertFalse(limits["recordingEnabled"])
        self.assertTrue(limits["transcriptionEnabled"])

    def test_live_calling_disabled_in_document(self):
        self.assertIn("Disabled", self.doc["pilot"]["liveCalling"])
        self.assertIn("NOT ENABLED", self.doc["pilot"]["documentStatus"])

    def test_to_confirm_covers_unverified_items(self):
        fields = {entry["field"] for entry in self.doc["toConfirm"]}
        for required in ("hours", "afterHours.behaviour specifics",
                         "transferRules availability",
                         "pilot window and named test callers",
                         "pilot telephone number", "recording"):
            self.assertIn(required, fields)
        for entry in self.doc["toConfirm"]:
            self.assertTrue(entry["question"])
            self.assertTrue(entry["why"])

    def test_hours_are_flagged_as_placeholder_not_presented_as_real(self):
        self.assertIn("hoursStatus", self.config)
        self.assertIn("PLACEHOLDER", self.config["hoursStatus"])
        self.assertIn("NOT VERIFIED", self.config["hoursStatus"])
        hours_entry = [e for e in self.doc["toConfirm"]
                       if e["field"] == "hours"][0]
        self.assertIn("not on record", hours_entry["why"])
        # The hours FAQ must not state hours as fact.
        hours_faq = [f for f in self.config["faqs"]
                     if f["q"] == "What are your hours?"][0]
        self.assertIn("confirm our current hours", hours_faq["a"])
        for day in ("monday", "tuesday", "wednesday", "thursday", "friday"):
            self.assertNotIn(self.config["hours"][day]["open"],
                             hours_faq["a"])


if __name__ == "__main__":
    unittest.main()
