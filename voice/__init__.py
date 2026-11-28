"""Configurable voice provider system for ApexVoice.

Public surface:
- providers: the registry, per-minute cost maths and monthly margins
- selection: per-tenant standard and premium voice configuration
- cache: the standard phrase synthesis cache
"""
from .providers import (
    COST_MODEL,
    DEFAULT_OTHER_LINES_CAD,
    FIXED_PER_TENANT_CAD_PER_MONTH,
    PROVIDERS,
    VoiceProvider,
    cost_per_call_minute,
    get_provider,
    gross_margin,
    monthly_cost_cad,
    total_cost_per_minute,
)
from .selection import (
    TIER_PREMIUM,
    TIER_STANDARD,
    TenantVoiceConfig,
    VoiceConfigStore,
    default_config,
    fallback_chain,
    next_provider,
)
from .cache import PhraseCache, build_standard_phrases, cache_key, is_cacheable

__all__ = [
    "COST_MODEL",
    "DEFAULT_OTHER_LINES_CAD",
    "FIXED_PER_TENANT_CAD_PER_MONTH",
    "PROVIDERS",
    "VoiceProvider",
    "cost_per_call_minute",
    "get_provider",
    "gross_margin",
    "monthly_cost_cad",
    "total_cost_per_minute",
    "TIER_PREMIUM",
    "TIER_STANDARD",
    "TenantVoiceConfig",
    "VoiceConfigStore",
    "default_config",
    "fallback_chain",
    "next_provider",
    "PhraseCache",
    "build_standard_phrases",
    "cache_key",
    "is_cacheable",
]
