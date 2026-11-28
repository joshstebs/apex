"""Per-tenant voice selection for ApexVoice.

Every tenant carries its own voice configuration, so one business can pay
for the premium ElevenLabs tier while the business next door stays on the
standard tier, and neither choice leaks into the other tenant's calls.

The fallback chain always ends at carrier speech. ApexVoice already has
that path for degraded mode, and it depends on nothing outside the call
itself, which makes it the safe last resort when every synthesis
provider is down.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional

from .providers import PROVIDERS, VoiceProvider, get_provider

TIER_STANDARD = "standard"
TIER_PREMIUM = "premium"
TIERS = (TIER_STANDARD, TIER_PREMIUM)

# Default policy. Standard is the cheapest option that keeps a natural
# neural voice: carrier-rendered Economy+ speech through SignalWire,
# which needs no new vendor and no audio hosting. Premium keeps the
# current ElevenLabs experience.
TIER_DEFAULT_PROVIDER = {
    TIER_STANDARD: "signalwire_say",
    TIER_PREMIUM: "elevenlabs_turbo",
}

# Ordered fallbacks per tier, tried after the tenant's own fallback.
# Carrier speech is appended by fallback_chain, never listed here.
TIER_FALLBACKS = {
    TIER_STANDARD: ["azure_speech", "google_tts", "amazon_polly", "kokoro_selfhost"],
    TIER_PREMIUM: ["elevenlabs_flash", "azure_speech", "google_tts"],
}

LAST_RESORT_PROVIDER = "signalwire_say"


@dataclass
class TenantVoiceConfig:
    """Voice settings for exactly one tenant."""

    tenant_id: str
    tier: str = TIER_STANDARD
    provider: str = ""
    voice_id: str = ""
    fallback_provider: str = ""
    model: str = ""

    def __post_init__(self) -> None:
        if not self.tenant_id or not str(self.tenant_id).strip():
            raise ValueError("tenant_id is required")
        if self.tier not in TIERS:
            raise ValueError(f"unknown voice tier: {self.tier}")
        if not self.provider:
            self.provider = TIER_DEFAULT_PROVIDER[self.tier]
        get_provider(self.provider)
        if self.fallback_provider:
            get_provider(self.fallback_provider)
            if self.fallback_provider == self.provider:
                raise ValueError("fallback_provider must differ from provider")

    @property
    def voice_provider(self) -> VoiceProvider:
        return get_provider(self.provider)

    def with_tier(self, tier: str) -> "TenantVoiceConfig":
        """Return a copy on another tier, resetting provider to its default."""
        if tier not in TIERS:
            raise ValueError(f"unknown voice tier: {tier}")
        return replace(
            self, tier=tier, provider=TIER_DEFAULT_PROVIDER[tier], fallback_provider=""
        )


def default_config(tenant_id: str, tier: str = TIER_STANDARD) -> TenantVoiceConfig:
    return TenantVoiceConfig(tenant_id=tenant_id, tier=tier)


def fallback_chain(config: TenantVoiceConfig) -> List[str]:
    """Provider names to try, in order, for one tenant's call.

    Order: the tenant's provider, the tenant's chosen fallback, the tier
    fallback list, then carrier speech as the last resort. Duplicates are
    removed and every name is a registered provider. Carrier speech
    appears exactly once: last for any non-carrier primary, and first
    when it is itself the primary, with hosted providers behind it.
    """
    chain: List[str] = [config.provider]
    if config.fallback_provider:
        chain.append(config.fallback_provider)
    chain.extend(TIER_FALLBACKS[config.tier])
    chain.append(LAST_RESORT_PROVIDER)
    seen: List[str] = []
    for name in chain:
        if name not in seen:
            get_provider(name)
            seen.append(name)
    return seen


def next_provider(config: TenantVoiceConfig, failed: str) -> Optional[str]:
    """The provider to try after one fails, or None when the chain ends."""
    chain = fallback_chain(config)
    if failed not in chain:
        raise ValueError(f"provider not in this tenant's fallback chain: {failed}")
    index = chain.index(failed)
    return chain[index + 1] if index + 1 < len(chain) else None


class VoiceConfigStore:
    """In-memory tenant voice configuration store.

    The production store is a backend concern (tenant-scoped rows plus
    Redis namespacing are specified in the Phase 3 integration notes).
    This store exists so selection behaviour is testable in isolation and
    so the isolation rule is executable: reads and writes are keyed by
    tenant_id and there is no shared mutable default.
    """

    def __init__(self) -> None:
        self._configs: Dict[str, TenantVoiceConfig] = {}

    def set(self, config: TenantVoiceConfig) -> TenantVoiceConfig:
        self._configs[config.tenant_id] = replace(config)
        return replace(config)

    def get(self, tenant_id: str) -> TenantVoiceConfig:
        """The tenant's config, or a fresh standard default for that tenant."""
        stored = self._configs.get(tenant_id)
        if stored is None:
            return default_config(tenant_id)
        return replace(stored)

    def delete(self, tenant_id: str) -> bool:
        return self._configs.pop(tenant_id, None) is not None

    def tenant_ids(self) -> List[str]:
        return sorted(self._configs)
