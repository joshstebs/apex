"""Commercial readiness checks for ApexVoice.

Covers only the new commercial layer (static/commercial, prompts/templates,
docs/commercial, docs/legal-drafts). It does not exercise the telephony
backend, which is owned by a separate change.

Run: python test_commercial_readiness.py
"""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
COMMERCIAL = os.path.join(ROOT, "static", "commercial")
PROMPT_TEMPLATES = os.path.join(ROOT, "prompts", "templates")
LEGAL = os.path.join(ROOT, "docs", "legal-drafts")
COMMERCIAL_DOCS = os.path.join(ROOT, "docs", "commercial")

EXPECTED_PROMPT_IDS = {
    "tpl_plumbing_hvac",
    "tpl_auto_repair",
    "tpl_dental_medical",
    "tpl_real_estate",
    "tpl_salon_barbershop",
    "tpl_restaurant",
    "tpl_professional_services",
    "tpl_general_small_business",
}
PROMPT_SCHEMA_KEYS = {
    "id", "name", "category", "description", "first_message",
    "dynamic_variables", "system_prompt", "temperature",
    "voice_provider", "voice_id", "tools",
}
BUSINESS_CONFIG_FIELDS = [
    "businessName", "contact", "hours", "holidays", "receptionistName",
    "greeting", "services", "faqs", "bookingPrefs", "transferRules",
    "afterHours", "messageDelivery", "voice", "instructions",
    "industry", "timezone",
]
FORBIDDEN_PHRASES = [
    "customers love", "trusted by", "five-star",
    "5-star", "rated 4.", "join thousands",
]


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class TestPromptTemplates(unittest.TestCase):
    def test_eight_templates_with_exact_schema(self):
        files = [f for f in os.listdir(PROMPT_TEMPLATES) if f.endswith(".json")]
        self.assertEqual(len(files), 8)
        seen = set()
        for name in files:
            data = json.loads(read(os.path.join(PROMPT_TEMPLATES, name)))
            self.assertTrue(PROMPT_SCHEMA_KEYS.issubset(set(data)), name)
            seen.add(data["id"])
            self.assertEqual(data["voice_provider"], "elevenlabs")
            self.assertTrue(0.2 <= data["temperature"] <= 0.3, name)
            self.assertIn("{{business_name}}", data["first_message"])
            self.assertIn("AI", data["first_message"])
            prompt = data["system_prompt"].lower()
            self.assertIn("911", prompt, name)
            self.assertIn("never invent", prompt, name)
            tool_names = {t["name"] for t in data["tools"]}
            self.assertIn("save_receptionist_message", tool_names)
        self.assertEqual(seen, EXPECTED_PROMPT_IDS)

    def test_regulated_templates_refuse_advice(self):
        dental = json.loads(read(os.path.join(PROMPT_TEMPLATES, "tpl_dental_medical.json")))
        self.assertIn("never provide medical or dental advice", dental["system_prompt"].lower())
        self.assertIn("never diagnose", dental["system_prompt"].lower())
        self.assertIn("ohip", dental["system_prompt"].lower())
        prof = json.loads(read(os.path.join(PROMPT_TEMPLATES, "tpl_professional_services.json")))
        self.assertIn("never provide legal, tax, accounting, or financial advice", prof["system_prompt"].lower())
        self.assertIn("conflict check", prof["system_prompt"].lower())
        restaurant = json.loads(read(os.path.join(PROMPT_TEMPLATES, "tpl_restaurant.json")))
        self.assertIn("card", restaurant["system_prompt"].lower())


class TestFrontendTemplates(unittest.TestCase):
    def test_picker_templates_align_with_prompts(self):
        data = json.loads(read(os.path.join(COMMERCIAL, "templates.json")))
        templates = data["templates"]
        self.assertEqual(len(templates), 8)
        self.assertEqual({t["promptTemplateId"] for t in templates}, EXPECTED_PROMPT_IDS)
        for entry in templates:
            for field in ("id", "label", "greeting", "services", "faqs",
                          "escalationRules", "messageWorkflow", "guardrails"):
                self.assertIn(field, entry, entry.get("id"))


class TestPages(unittest.TestCase):
    def _page(self, name):
        return read(os.path.join(COMMERCIAL, name))

    def test_no_external_assets_no_em_dash_no_fabrication(self):
        for name in ("onboarding.html", "dashboard.html", "demo.html"):
            html = self._page(name)
            self.assertNotIn("\u2014", html, name)
            self.assertNotIn("\u2013", html, name)
            self.assertIsNone(re.search(r'<(?:script|link|img)[^>]+(?:src|href)="https?://', html), name)
            lowered = html.lower()
            for phrase in FORBIDDEN_PHRASES:
                self.assertNotIn(phrase, lowered, f"{name}: {phrase}")

    def test_onboarding_covers_business_config_schema(self):
        html = self._page("onboarding.html")
        for field in BUSINESS_CONFIG_FIELDS:
            self.assertIn(field, html, field)
        self.assertIn("apex_business_config", html)
        self.assertIn("templates.json", html)
        self.assertIn("not yet live", html)

    def test_dashboard_uses_real_endpoints_and_honest_states(self):
        html = self._page("dashboard.html")
        self.assertIn("/api/dashboard", html)
        self.assertIn("/api/health", html)
        self.assertIn("/api/receptionist/messages", html)
        self.assertIn("No calls yet", html)
        self.assertIn("not a carrier invoice", html)
        # The admin token must never be persisted: the dashboard may read the
        # onboarding config from localStorage but must never write to it.
        self.assertNotIn("localStorage.setItem", html)
        self.assertIn("localStorage.getItem('apex_business_config')", html)

    def test_demo_is_labelled_simulated_and_functional(self):
        html = self._page("demo.html")
        self.assertIn("SIMULATED", html)
        self.assertIn("No real phone call is placed", html)
        self.assertIn("speechSynthesis", html)
        self.assertIn("Browser voice preview", html)
        self.assertIn("BEGIN:VCALENDAR", html)
        self.assertIn("What is simulated vs live", html)
        self.assertIn("911", html)


class TestDocs(unittest.TestCase):
    def test_legal_drafts_carry_review_header(self):
        files = [f for f in os.listdir(LEGAL) if f.endswith(".md")]
        self.assertEqual(len(files), 7)
        for name in files:
            text = read(os.path.join(LEGAL, name))
            self.assertIn("DRAFT, NOT LEGAL ADVICE, REQUIRES PROFESSIONAL LEGAL REVIEW BEFORE USE", text, name)
            self.assertNotIn("\u2014", text, name)

    def test_pricing_recommendations_present(self):
        text = read(os.path.join(COMMERCIAL_DOCS, "PRICING_AND_PROFITABILITY.md"))
        for needle in ("$49", "$99", "$199", "120", "350", "800", "not approved"):
            self.assertIn(needle, text, needle)
        self.assertNotIn("\u2014", text)

    def test_contracts_freeze_business_config(self):
        text = read(os.path.join(COMMERCIAL_DOCS, "BACKEND_CONTRACTS.md"))
        for field in BUSINESS_CONFIG_FIELDS:
            self.assertIn(field, text, field)

    def test_architecture_ratings_present(self):
        text = read(os.path.join(COMMERCIAL_DOCS, "MULTI_TENANT_ARCHITECTURE.md"))
        for needle in ("tenant_id", "apex:t:{tenant_id}:", "Missing", "Partial"):
            self.assertIn(needle, text, needle)


if __name__ == "__main__":
    unittest.main(verbosity=2)
