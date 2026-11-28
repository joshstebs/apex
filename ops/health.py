"""Provider health records for the ApexVoice platform.

Provider health in this package is an INPUT, not a measurement. Nothing
here probes SignalWire, ElevenLabs, the language model host, Redis, or
Stripe, and nothing here infers a status from traffic. A health value
exists only because some real probe, run by the backend or by an
external monitor, recorded one through HealthRegistry.record.

Until a probe result is recorded for a provider, that provider's status
is "unknown" and its checked_at is None. The platform overview surfaces
these records exactly as they are, so the operator dashboard shows
"unknown" rather than a reassuring guess.
"""

from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

PROVIDERS = ("signalwire", "elevenlabs", "llm", "redis", "stripe")
HEALTH_STATUSES = ("unknown", "up", "degraded", "down")


@dataclass
class ProviderHealth:
    """One provider's last recorded health state.

    checked_at is an ISO 8601 timestamp string supplied by whoever ran
    the probe. source names where the result came from, for example
    "backend probe", "status page", or "manual check". Both stay empty
    (None and "") until a real result is recorded.
    """

    provider: str
    status: str = "unknown"
    checked_at: Optional[str] = None
    source: str = ""

    def __post_init__(self):
        if not self.provider or not str(self.provider).strip():
            raise ValueError("provider name is required")
        if self.status not in HEALTH_STATUSES:
            raise ValueError(f"unknown health status: {self.status}")

    def to_dict(self):
        return asdict(self)


class HealthRegistry:
    """Last recorded health per provider, defaulting to unknown.

    The five providers ApexVoice depends on are pre-registered with
    status "unknown", no timestamp, and no source. Recording a result
    for any other provider name adds it after the defaults.
    """

    def __init__(self, providers=PROVIDERS):
        self._records: Dict[str, ProviderHealth] = {
            name: ProviderHealth(provider=name) for name in providers
        }

    def record(self, provider, status, checked_at, source=""):
        """Store one real probe result and return the stored record."""
        entry = ProviderHealth(
            provider=provider, status=status,
            checked_at=checked_at, source=source)
        self._records[provider] = entry
        return entry

    def get(self, provider):
        found = self._records.get(provider)
        if found is None:
            return ProviderHealth(provider=provider)
        return found

    def all(self) -> List[ProviderHealth]:
        return list(self._records.values())

    def to_dicts(self):
        return [entry.to_dict() for entry in self.all()]
