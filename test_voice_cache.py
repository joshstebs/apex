"""Phrase cache tests for ApexVoice.

Run: python test_voice_cache.py
The privacy tests matter most here: caller-specific text must never be
cached, and one tenant's cached phrases must never serve another tenant.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from voice.cache import (
    PhraseCache,
    build_standard_phrases,
    cache_key,
    is_cacheable,
)

AUDIO = b"fake-audio-bytes"
GREETING = "Thank you for calling Harbour Plumbing. This is Alex, the AI receptionist. How can I help you today?"


def make_cache(**kwargs):
    return PhraseCache(**kwargs)


class TestCacheHits(unittest.TestCase):
    def test_repeated_greeting_hits(self):
        cache = make_cache()
        self.assertTrue(
            cache.put("tenant-a", "azure_speech", "en-CA-Neural", GREETING, AUDIO, kind="greeting")
        )
        self.assertIsNone(cache.get("tenant-a", "azure_speech", "en-CA-Neural", "never stored"))
        self.assertEqual(cache.get("tenant-a", "azure_speech", "en-CA-Neural", GREETING), AUDIO)
        self.assertEqual(cache.get("tenant-a", "azure_speech", "en-CA-Neural", GREETING), AUDIO)
        stats = cache.stats()
        self.assertEqual(stats["hits"], 2)
        self.assertEqual(stats["misses"], 1)

    def test_voice_and_provider_change_the_entry(self):
        cache = make_cache()
        cache.put("tenant-a", "azure_speech", "voice-1", GREETING, AUDIO, kind="greeting")
        self.assertIsNone(cache.get("tenant-a", "azure_speech", "voice-2", GREETING))
        self.assertIsNone(cache.get("tenant-a", "google_tts", "voice-1", GREETING))
        self.assertIsNone(cache.get("tenant-a", "azure_speech", "voice-1", GREETING, model="other"))

    def test_ttl_expiry(self):
        now = [1000.0]
        cache = make_cache(ttl_seconds=60, clock=lambda: now[0])
        cache.put("tenant-a", "azure_speech", "v", GREETING, AUDIO, kind="greeting")
        now[0] += 61
        self.assertIsNone(cache.get("tenant-a", "azure_speech", "v", GREETING))

    def test_size_cap_evicts_oldest(self):
        now = [0.0]
        cache = make_cache(max_entries=2, clock=lambda: now[0])
        for index in range(3):
            now[0] += 1
            text = f"Standard hold message number {index} for callers."
            self.assertTrue(cache.put("tenant-a", "azure_speech", "v", text, AUDIO, kind="hold"))
        stats = cache.stats()
        self.assertEqual(stats["entries"], 2)
        self.assertGreaterEqual(stats["evictions"], 1)
        self.assertIsNone(
            cache.get("tenant-a", "azure_speech", "v", "Standard hold message number 0 for callers.")
        )


class TestCacheRefusals(unittest.TestCase):
    def test_caller_specific_kinds_refused(self):
        cache = make_cache()
        for kind in ("caller_specific", "transcript", "message", "appointment", "sensitive"):
            self.assertFalse(cache.put("tenant-a", "azure_speech", "v", GREETING, AUDIO, kind=kind))
        self.assertEqual(cache.stats()["refusals"], 5)
        self.assertEqual(cache.stats()["entries"], 0)

    def test_unknown_kinds_refused_by_default(self):
        self.assertFalse(is_cacheable(GREETING, "something_new"))

    def test_identifiers_in_text_refused(self):
        cache = make_cache()
        samples = [
            "Hello John Smith, we will call you back shortly.",
            "Your callback number is 519 555 0142, thank you.",
            "We have your appointment at 142 Tecumseh Road East.",
            "A message from caller@example.com about the invoice.",
            "Your postal code K1A 0B1 has been noted.",
        ]
        # The name-only sample has no machine-detectable identifier, so it
        # is refused by kind in production. The rest must be refused on
        # content alone even under a cacheable kind.
        for text in samples[1:]:
            self.assertFalse(is_cacheable(text, "common"), text)
            self.assertFalse(cache.put("tenant-a", "azure_speech", "v", text, AUDIO, kind="common"))
        self.assertFalse(cache.put("tenant-a", "azure_speech", "v", samples[0], AUDIO, kind="caller_specific"))


class TestTenantIsolation(unittest.TestCase):
    def test_same_text_two_tenants_two_entries(self):
        cache = make_cache()
        key_a = cache_key("tenant-a", "azure_speech", "v", GREETING)
        key_b = cache_key("tenant-b", "azure_speech", "v", GREETING)
        self.assertNotEqual(key_a, key_b)
        cache.put("tenant-a", "azure_speech", "v", GREETING, b"audio-a", kind="greeting")
        # Tenant B cannot be served tenant A's audio for identical text.
        self.assertIsNone(cache.get("tenant-b", "azure_speech", "v", GREETING))
        cache.put("tenant-b", "azure_speech", "v", GREETING, b"audio-b", kind="greeting")
        self.assertEqual(cache.get("tenant-a", "azure_speech", "v", GREETING), b"audio-a")
        self.assertEqual(cache.get("tenant-b", "azure_speech", "v", GREETING), b"audio-b")
        self.assertEqual(cache.stats()["entries"], 2)

    def test_clear_tenant_only_removes_that_tenant(self):
        cache = make_cache()
        cache.put("tenant-a", "azure_speech", "v", GREETING, AUDIO, kind="greeting")
        cache.put("tenant-b", "azure_speech", "v", GREETING, AUDIO, kind="greeting")
        self.assertEqual(cache.clear_tenant("tenant-a"), 1)
        self.assertIsNone(cache.get("tenant-a", "azure_speech", "v", GREETING))
        self.assertEqual(cache.get("tenant-b", "azure_speech", "v", GREETING), AUDIO)


class TestStandardPhrases(unittest.TestCase):
    def test_phrases_built_from_tenant_config(self):
        config = {
            "businessName": "Harbour Plumbing",
            "greeting": GREETING,
            "afterHours": {"greeting": "We are closed. Please leave a message and we will call back."},
            "faqs": [{"q": "Do you offer emergency service?", "a": "Yes, emergency call-outs are available."}],
        }
        phrases = build_standard_phrases(config)
        kinds = [p["kind"] for p in phrases]
        for expected in ("greeting", "disclosure", "hold", "transfer", "after_hours", "faq"):
            self.assertIn(expected, kinds)
        disclosure = next(p["text"] for p in phrases if p["kind"] == "disclosure")
        self.assertIn("Harbour Plumbing", disclosure)
        self.assertIn("AI receptionist", disclosure)
        # Every built phrase must pass the cacheability gate.
        for phrase in phrases:
            self.assertTrue(is_cacheable(phrase["text"], phrase["kind"]), phrase)

    def test_empty_config_still_yields_core_phrases(self):
        phrases = build_standard_phrases({})
        kinds = {p["kind"] for p in phrases}
        self.assertEqual(kinds, {"disclosure", "hold", "transfer"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
