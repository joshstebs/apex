"""Configurable voice provider registry and cost model for ApexVoice.

ApexVoice today sends every spoken reply to ElevenLabs. This module makes
the voice a per-tenant choice: a standard tier built on cheap natural
voices and a premium tier that keeps ElevenLabs, with the cost of each
option computed from the rates in cost_model.json beside this file.

Rates are list prices or clearly labelled estimates. Nothing here calls a
provider. Synthesis, playback and carrier wiring stay in the backend,
which a separate change owns.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_COST_MODEL_PATH = os.path.join(_HERE, "cost_model.json")

DEFAULT_CHARS_PER_CALL_MINUTE = 425
DEFAULT_FX_USD_CAD = 1.36

KIND_HOSTED = "hosted"
KIND_SELF_HOSTED = "self_hosted"
KIND_CARRIER = "carrier"
_KINDS = (KIND_HOSTED, KIND_SELF_HOSTED, KIND_CARRIER)


@dataclass(frozen=True)
class VoiceProvider:
    """One speech synthesis option ApexVoice can route a tenant to."""

    name: str
    kind: str
    usd_per_1000_chars: float
    supports_streaming: bool
    model: str = ""
    source: str = ""
    source_url: str = ""
    rate_status: str = ""
    licence: str = ""
    notes: str = ""
    alternate_rates_usd_per_1000_chars: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"unknown provider kind: {self.kind}")
        if self.usd_per_1000_chars < 0:
            raise ValueError("rate cannot be negative")

    def cost_cad_per_call_minute(
        self, chars_per_min: float = DEFAULT_CHARS_PER_CALL_MINUTE, fx: float = DEFAULT_FX_USD_CAD
    ) -> float:
        """Synthesis cost for one call minute, in CAD.

        Only the receptionist's spoken characters are billed, so the
        character count is spoken characters per call minute, not per
        minute of finished speech.
        """
        return chars_per_min / 1000.0 * self.usd_per_1000_chars * fx


def _load_cost_model() -> dict:
    with open(_COST_MODEL_PATH, encoding="utf-8") as handle:
        return json.load(handle)


COST_MODEL = _load_cost_model()


def _build_registry() -> Dict[str, VoiceProvider]:
    registry: Dict[str, VoiceProvider] = {}
    for name, raw in COST_MODEL["providers"].items():
        registry[name] = VoiceProvider(
            name=name,
            kind=raw["kind"],
            usd_per_1000_chars=float(raw["usd_per_1000_chars"]),
            supports_streaming=bool(raw["supports_streaming"]),
            model=raw.get("model", ""),
            source=raw.get("source", ""),
            source_url=raw.get("source_url", ""),
            rate_status=raw.get("rate_status", ""),
            licence=raw.get("licence", ""),
            notes=raw.get("notes", ""),
            alternate_rates_usd_per_1000_chars={
                key: float(value)
                for key, value in raw.get("alternate_rates_usd_per_1000_chars", {}).items()
            },
        )
    return registry


PROVIDERS: Dict[str, VoiceProvider] = _build_registry()

# Non-synthesis cost lines for one call minute, in CAD, from cost_model.json.
# The speech recognition line is an allowance, not a verified invoice line.
DEFAULT_OTHER_LINES_CAD: Dict[str, float] = {
    key: float(value["cad"])
    for key, value in COST_MODEL["other_lines_cad_per_call_minute"].items()
}

FIXED_PER_TENANT_CAD_PER_MONTH: float = float(
    COST_MODEL["fixed_per_tenant_cad_per_month"]["amount"]
)


def get_provider(name: str) -> VoiceProvider:
    try:
        return PROVIDERS[name]
    except KeyError:
        raise ValueError(f"unknown voice provider: {name}") from None


def cost_per_call_minute(
    provider: VoiceProvider,
    chars_per_min: float = DEFAULT_CHARS_PER_CALL_MINUTE,
    fx: float = DEFAULT_FX_USD_CAD,
) -> float:
    """Synthesis-only cost per call minute in CAD for one provider."""
    if not isinstance(provider, VoiceProvider):
        raise TypeError("provider must be a VoiceProvider")
    if chars_per_min <= 0:
        raise ValueError("chars_per_min must be positive")
    if fx <= 0:
        raise ValueError("fx must be positive")
    return provider.cost_cad_per_call_minute(chars_per_min, fx)


def total_cost_per_minute(
    provider: VoiceProvider,
    other_lines: Optional[Dict[str, float]] = None,
    chars_per_min: float = DEFAULT_CHARS_PER_CALL_MINUTE,
    fx: float = DEFAULT_FX_USD_CAD,
    cache_hit_share: float = 0.0,
) -> Dict[str, float]:
    """Full cost per call minute in CAD: synthesis plus the other lines.

    other_lines maps line names to CAD per call minute. Defaults to the
    audited non-synthesis lines (transport, LLM, STT and platform
    allowance). cache_hit_share is the modelled share of spoken
    characters served from the phrase cache, which avoids synthesis cost
    only. It never reduces transport, LLM or STT lines, and it only
    applies when cached audio is played back instead of re-synthesised.
    """
    lines = dict(DEFAULT_OTHER_LINES_CAD if other_lines is None else other_lines)
    if not 0.0 <= cache_hit_share < 1.0:
        raise ValueError("cache_hit_share must be in [0, 1)")
    synthesis = cost_per_call_minute(provider, chars_per_min, fx) * (1.0 - cache_hit_share)
    breakdown = {"tts_synthesis": synthesis}
    breakdown.update(lines)
    breakdown["total"] = synthesis + sum(lines.values())
    return breakdown


def monthly_cost_cad(
    provider: VoiceProvider,
    included_minutes: float,
    other_lines: Optional[Dict[str, float]] = None,
    fixed_per_tenant: float = FIXED_PER_TENANT_CAD_PER_MONTH,
    cache_hit_share: float = 0.0,
) -> float:
    """Cost of one tenant using every included minute in a month, in CAD."""
    per_minute = total_cost_per_minute(
        provider, other_lines, cache_hit_share=cache_hit_share
    )["total"]
    return per_minute * included_minutes + fixed_per_tenant


def gross_margin(
    price_cad: float,
    provider: VoiceProvider,
    included_minutes: float,
    other_lines: Optional[Dict[str, float]] = None,
    fixed_per_tenant: float = FIXED_PER_TENANT_CAD_PER_MONTH,
    cache_hit_share: float = 0.0,
) -> float:
    """Gross margin fraction at full use of included minutes."""
    if price_cad <= 0:
        raise ValueError("price_cad must be positive")
    cost = monthly_cost_cad(
        provider, included_minutes, other_lines, fixed_per_tenant, cache_hit_share
    )
    return (price_cad - cost) / price_cad
