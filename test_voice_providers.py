"""Voice provider cost and selection tests for ApexVoice.

Run: python test_voice_providers.py
All figures in CAD unless a name says otherwise.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from voice.providers import (
    DEFAULT_OTHER_LINES_CAD,
    PROVIDERS,
    cost_per_call_minute,
    get_provider,
    gross_margin,
    total_cost_per_minute,
)
from voice.selection import (
    TIER_PREMIUM,
    TIER_STANDARD,
    TenantVoiceConfig,
    VoiceConfigStore,
    default_config,
    fallback_chain,
    next_provider,
)

AUDIT_TOTAL_CAD = 0.135
AUDIT_ELEVENLABS_CAD = 0.104
TARGET_STANDARD_TOTAL_CAD = 0.07


class TestRegistry(unittest.TestCase):
    def test_all_required_providers_registered(self):
        for name in (
            "signalwire_say",
            "elevenlabs_turbo",
            "elevenlabs_flash",
            "azure_speech",
            "google_tts",
            "amazon_polly",
            "kokoro_selfhost",
            "piper_selfhost",
        ):
            self.assertIn(name, PROVIDERS)
            provider = get_provider(name)
            self.assertIn(provider.kind, ("hosted", "self_hosted", "carrier"))
            self.assertGreater(provider.usd_per_1000_chars, 0)

    def test_unknown_provider_rejected(self):
        with self.assertRaises(ValueError):
            get_provider("not_a_provider")


class TestCostMath(unittest.TestCase):
    def test_premium_tier_reproduces_the_audit(self):
        turbo = get_provider("elevenlabs_turbo")
        self.assertAlmostEqual(cost_per_call_minute(turbo), AUDIT_ELEVENLABS_CAD, delta=0.002)
        total = total_cost_per_minute(turbo)["total"]
        self.assertAlmostEqual(total, AUDIT_TOTAL_CAD, delta=0.002)

    def test_standard_tier_under_target(self):
        config = default_config("tenant-a")
        self.assertEqual(config.tier, TIER_STANDARD)
        total = total_cost_per_minute(config.voice_provider)["total"]
        self.assertLess(total, TARGET_STANDARD_TOTAL_CAD, f"standard total {total:.4f} CAD")

    def test_every_natural_alternative_also_under_target(self):
        for name in ("azure_speech", "google_tts", "amazon_polly", "kokoro_selfhost", "piper_selfhost"):
            total = total_cost_per_minute(get_provider(name))["total"]
            self.assertLess(total, TARGET_STANDARD_TOTAL_CAD, name)

    def test_standard_is_a_fraction_of_premium(self):
        standard = total_cost_per_minute(get_provider("signalwire_say"))["total"]
        premium = total_cost_per_minute(get_provider("elevenlabs_turbo"))["total"]
        self.assertLess(standard, premium * 0.5)

    def test_other_lines_match_audit_residual(self):
        # Transport plus LLM plus the STT and platform allowance should
        # reconcile with the audit total once ElevenLabs is removed.
        self.assertAlmostEqual(sum(DEFAULT_OTHER_LINES_CAD.values()), 0.031, delta=0.001)

    def test_cache_share_reduces_synthesis_only(self):
        turbo = get_provider("elevenlabs_turbo")
        plain = total_cost_per_minute(turbo)
        cached = total_cost_per_minute(turbo, cache_hit_share=0.30)
        self.assertAlmostEqual(
            cached["tts_synthesis"], plain["tts_synthesis"] * 0.70, places=6
        )
        for line in DEFAULT_OTHER_LINES_CAD:
            self.assertAlmostEqual(cached[line], plain[line], places=9)

    def test_margins_improve_on_standard_tier(self):
        standard = get_provider("signalwire_say")
        premium = get_provider("elevenlabs_turbo")
        for price, minutes in ((49, 120), (99, 350), (199, 800)):
            self.assertGreater(
                gross_margin(price, standard, minutes),
                gross_margin(price, premium, minutes),
            )
        # Standard tier keeps a healthy margin even at full included use.
        self.assertGreater(gross_margin(49, standard, 120), 0.60)


class TestSelectionIsolation(unittest.TestCase):
    def test_tenant_choices_do_not_leak(self):
        store = VoiceConfigStore()
        store.set(TenantVoiceConfig(tenant_id="biz-premium", tier=TIER_PREMIUM))
        store.set(TenantVoiceConfig(tenant_id="biz-standard", tier=TIER_STANDARD))
        self.assertEqual(store.get("biz-premium").provider, "elevenlabs_turbo")
        self.assertEqual(store.get("biz-standard").provider, "signalwire_say")
        # Changing one tenant afterwards still leaves the other untouched.
        store.set(store.get("biz-premium").with_tier(TIER_STANDARD))
        self.assertEqual(store.get("biz-premium").provider, "signalwire_say")
        self.assertEqual(store.get("biz-standard").tier, TIER_STANDARD)

    def test_unconfigured_tenant_gets_its_own_default(self):
        store = VoiceConfigStore()
        store.set(TenantVoiceConfig(tenant_id="biz-premium", tier=TIER_PREMIUM))
        fresh = store.get("biz-new")
        self.assertEqual(fresh.tenant_id, "biz-new")
        self.assertEqual(fresh.tier, TIER_STANDARD)
        self.assertEqual(store.tenant_ids(), ["biz-premium"])

    def test_returned_configs_are_copies(self):
        store = VoiceConfigStore()
        store.set(TenantVoiceConfig(tenant_id="biz-a", tier=TIER_STANDARD))
        leaked = store.get("biz-a")
        leaked.tier = TIER_PREMIUM
        self.assertEqual(store.get("biz-a").tier, TIER_STANDARD)

    def test_validation(self):
        with self.assertRaises(ValueError):
            TenantVoiceConfig(tenant_id="")
        with self.assertRaises(ValueError):
            TenantVoiceConfig(tenant_id="biz-a", tier="deluxe")
        with self.assertRaises(ValueError):
            TenantVoiceConfig(tenant_id="biz-a", provider="nope")
        with self.assertRaises(ValueError):
            TenantVoiceConfig(
                tenant_id="biz-a",
                provider="azure_speech",
                fallback_provider="azure_speech",
            )


class TestFallback(unittest.TestCase):
    def test_chain_ends_at_carrier_speech(self):
        for tier in (TIER_STANDARD, TIER_PREMIUM):
            chain = fallback_chain(default_config("biz-a", tier=tier))
            self.assertEqual(chain.count("signalwire_say"), 1)
            self.assertEqual(len(chain), len(set(chain)))
            for name in chain:
                self.assertIn(name, PROVIDERS)
        # For a non-carrier primary, carrier speech is the last resort.
        premium_chain = fallback_chain(default_config("biz-a", tier=TIER_PREMIUM))
        self.assertEqual(premium_chain[-1], "signalwire_say")
        # For the standard tier the carrier is the primary itself, with
        # hosted providers behind it if carrier rendering ever fails.
        standard_chain = fallback_chain(default_config("biz-a", tier=TIER_STANDARD))
        self.assertEqual(standard_chain[0], "signalwire_say")
        self.assertGreater(len(standard_chain), 1)

    def test_next_provider_walks_the_chain(self):
        config = default_config("biz-a", tier=TIER_PREMIUM)
        chain = fallback_chain(config)
        self.assertEqual(chain[0], "elevenlabs_turbo")
        self.assertEqual(next_provider(config, chain[0]), chain[1])
        self.assertIsNone(next_provider(config, chain[-1]))
        with self.assertRaises(ValueError):
            next_provider(config, "kokoro_selfhost" if "kokoro_selfhost" not in chain else "bogus")

    def test_tenant_fallback_comes_second(self):
        config = TenantVoiceConfig(
            tenant_id="biz-a", tier=TIER_STANDARD, fallback_provider="piper_selfhost"
        )
        chain = fallback_chain(config)
        self.assertEqual(chain[0], "signalwire_say")
        self.assertEqual(chain[1], "piper_selfhost")


if __name__ == "__main__":
    unittest.main(verbosity=2)
