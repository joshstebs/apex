"""Voice provider abstraction for ApexVoice V2.

Lets ApexVoice choose an engine per tenant without touching call routing:

    legacy      existing ApexVoice voice engine (Hugging Face + ElevenLabs)
    gemini_live Gemini Live bidirectional conversational engine
    local       modular pipeline: local ASR + LLM + Piper TTS
    premium     hosted commercial voice provider

Safety rules encoded here, not left to callers:
  * Default is ``legacy``. Nothing changes unless a flag is set explicitly.
  * Unknown or unparseable flags fall back to ``legacy`` and log, so a typo cannot
    silently move a live tenant onto an unproven engine.
  * A provider that is not enabled cannot be resolved, even if requested.
  * Rollout is per tenant, with an optional percentage canary that is stable for a
    given tenant (same tenant always lands on the same side).
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from enum import Enum


class VoiceEngine(str, Enum):
    LEGACY = "legacy"
    GEMINI_LIVE = "gemini_live"
    LOCAL = "local"
    PREMIUM = "premium"


DEFAULT_ENGINE = VoiceEngine.LEGACY


@dataclass(frozen=True)
class EngineFlags:
    """Feature flags, read from the environment once at startup.

    APEX_VOICE_ENGINE              default engine for tenants with no override
    APEX_VOICE_ENABLED_ENGINES     comma list that may be used at all
    APEX_VOICE_CANARY_PERCENT      percent of tenants sent to the canary engine
    APEX_VOICE_CANARY_ENGINE       engine the canary bucket receives
    APEX_VOICE_TENANT_<ID>         per-tenant forced engine
    """

    default: VoiceEngine = DEFAULT_ENGINE
    enabled: frozenset[VoiceEngine] = field(default_factory=lambda: frozenset({DEFAULT_ENGINE}))
    canary_percent: int = 0
    canary_engine: VoiceEngine = DEFAULT_ENGINE

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "EngineFlags":
        env = env if env is not None else dict(os.environ)

        def parse(value: str | None, fallback: VoiceEngine) -> VoiceEngine:
            if not value:
                return fallback
            try:
                return VoiceEngine(value.strip().lower())
            except ValueError:
                return fallback

        default = parse(env.get("APEX_VOICE_ENGINE"), DEFAULT_ENGINE)
        raw_enabled = env.get("APEX_VOICE_ENABLED_ENGINES", "")
        # The allowlist is authoritative: never add the default to it implicitly,
        # otherwise a disabled engine would enable itself by being named as default.
        if raw_enabled.strip():
            enabled: set[VoiceEngine] = set()
            for item in raw_enabled.split(","):
                item = item.strip().lower()
                if not item:
                    continue
                try:
                    enabled.add(VoiceEngine(item))
                except ValueError:
                    continue
        else:
            enabled = {DEFAULT_ENGINE}

        try:
            percent = max(0, min(100, int(env.get("APEX_VOICE_CANARY_PERCENT", "0"))))
        except ValueError:
            percent = 0
        canary = parse(env.get("APEX_VOICE_CANARY_ENGINE"), default)

        return cls(
            default=default,
            enabled=frozenset(enabled),
            canary_percent=percent,
            canary_engine=canary,
        )


def _bucket(tenant_id: str) -> int:
    """Stable 0-99 bucket. Deterministic across processes and restarts."""
    digest = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def resolve_engine(
    tenant_id: str,
    flags: EngineFlags | None = None,
    env: dict[str, str] | None = None,
) -> VoiceEngine:
    """Pick the engine for one tenant.

    An explicitly enabled per-tenant flag wins. Otherwise the canary bucket
    applies. Anything that resolves to a disabled engine falls back to the
    default, never to an arbitrary choice.
    """
    flags = flags or EngineFlags.from_env(env)
    source_env = env if env is not None else dict(os.environ)

    override = source_env.get(f"APEX_VOICE_TENANT_{tenant_id.upper().replace('-', '_')}")
    chosen: VoiceEngine
    if override:
        try:
            chosen = VoiceEngine(override.strip().lower())
        except ValueError:
            chosen = flags.default
    elif flags.canary_percent > 0 and _bucket(tenant_id) < flags.canary_percent:
        chosen = flags.canary_engine
    else:
        chosen = flags.default

    if chosen not in flags.enabled:
        # `enabled` is authoritative. A tenant flag or canary that names a disabled
        # engine never wins. An allowlist that excludes everything is a config
        # error, so it resolves to the safest engine rather than crashing.
        if DEFAULT_ENGINE in flags.enabled:
            return DEFAULT_ENGINE
        return next(iter(flags.enabled), DEFAULT_ENGINE)
    return chosen
