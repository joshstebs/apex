"""Phrase synthesis cache for ApexVoice.

A receptionist repeats itself constantly: the greeting, the AI
disclosure, hold and transfer lines, the closing, and a handful of
common answers. Re-synthesising those on every call is paying full price
for identical audio. This cache stores the rendered audio for those
phrases, per tenant, so a repeat costs a lookup instead of a synthesis.

Hard rule: caller-specific or sensitive text is never cached. Names,
callback numbers, addresses, appointment details and anything that came
from a caller or a transcript are refused at put time, by kind and by
content heuristics. A cache that remembered one caller's details and
played them to the next caller would be a cross-caller privacy failure,
so refusal is the default for anything not clearly a standard phrase.

Cached audio only saves money when it is played back (a Play of stored
audio, which is how ApexVoice already serves ElevenLabs clips). A pure
carrier <Say> rendering cannot reuse it. The cache therefore pairs with
hosted and self-hosted providers, and with pre-rendered standard phrases.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Callable, Dict, List, Optional

# Phrase kinds that are safe to cache: static, tenant-authored, identical
# for every caller of that tenant.
CACHEABLE_KINDS = frozenset(
    {"greeting", "disclosure", "hold", "transfer", "closing", "after_hours", "faq", "common"}
)

# Phrase kinds that must never be cached, whatever the text says.
NEVER_CACHE_KINDS = frozenset(
    {
        "caller_specific",
        "transcript",
        "message",
        "appointment",
        "callback_number",
        "personal",
        "sensitive",
    }
)

_PHONE_LIKE = re.compile(r"(\+?\d[\s().-]?){7,}\d")
_EMAIL_LIKE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_POSTAL_LIKE = re.compile(r"\b[A-Za-z]\d[A-Za-z][ -]?\d[A-Za-z]\d\b")
_STREET_ADDRESS_LIKE = re.compile(
    r"\b\d{1,6}\s+(?:[A-Z][a-z]+\s+){0,3}"
    r"(?:Road|Street|Avenue|Ave|Drive|Lane|Boulevard|Blvd|Court|Way|Highway|Hwy)\b"
)


def looks_sensitive(text: str) -> bool:
    """True when text carries identifiers that must not be replayed."""
    if _PHONE_LIKE.search(text):
        return True
    if _EMAIL_LIKE.search(text):
        return True
    if _POSTAL_LIKE.search(text):
        return True
    if _STREET_ADDRESS_LIKE.search(text):
        return True
    return False


def is_cacheable(text: str, kind: str) -> bool:
    if kind in NEVER_CACHE_KINDS:
        return False
    if kind not in CACHEABLE_KINDS:
        return False
    if not text or not text.strip():
        return False
    return not looks_sensitive(text)


def cache_key(
    tenant_id: str, provider: str, voice_id: str, text: str, model: str = ""
) -> str:
    """Stable key. tenant_id is in the key, so identical text spoken for
    two businesses is two entries that can never be served across tenants."""
    payload = json.dumps(
        [tenant_id, provider, voice_id, model, " ".join(text.split())],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PhraseCache:
    """Bounded TTL cache from phrase key to rendered audio bytes."""

    def __init__(
        self,
        ttl_seconds: float = 7 * 24 * 3600,
        max_entries: int = 512,
        max_total_chars: int = 200_000,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.max_total_chars = max_total_chars
        self._clock = clock
        self._entries: Dict[str, dict] = {}
        self._total_chars = 0
        self.hits = 0
        self.misses = 0
        self.refusals = 0
        self.evictions = 0

    def _expired(self, entry: dict) -> bool:
        return self._clock() - entry["stored_at"] > self.ttl_seconds

    def _drop(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._total_chars -= entry["chars"]

    def _evict_until_fits(self, incoming_chars: int) -> None:
        while self._entries and (
            len(self._entries) >= self.max_entries
            or self._total_chars + incoming_chars > self.max_total_chars
        ):
            oldest = min(self._entries, key=lambda k: self._entries[k]["stored_at"])
            self._drop(oldest)
            self.evictions += 1

    def put(
        self,
        tenant_id: str,
        provider: str,
        voice_id: str,
        text: str,
        audio: bytes,
        kind: str = "common",
        model: str = "",
    ) -> bool:
        """Store audio for a standard phrase. Returns False when refused."""
        if not is_cacheable(text, kind):
            self.refusals += 1
            return False
        if not isinstance(audio, (bytes, bytearray)) or not audio:
            raise ValueError("audio must be non-empty bytes")
        key = cache_key(tenant_id, provider, voice_id, text, model)
        if key in self._entries:
            self._drop(key)
        self._evict_until_fits(len(text))
        self._entries[key] = {
            "audio": bytes(audio),
            "tenant_id": tenant_id,
            "chars": len(text),
            "stored_at": self._clock(),
        }
        self._total_chars += len(text)
        return True

    def get(
        self,
        tenant_id: str,
        provider: str,
        voice_id: str,
        text: str,
        model: str = "",
    ) -> Optional[bytes]:
        key = cache_key(tenant_id, provider, voice_id, text, model)
        entry = self._entries.get(key)
        if entry is None or entry["tenant_id"] != tenant_id:
            self.misses += 1
            return None
        if self._expired(entry):
            self._drop(key)
            self.misses += 1
            return None
        self.hits += 1
        return entry["audio"]

    def stats(self) -> dict:
        total_lookups = self.hits + self.misses
        return {
            "entries": len(self._entries),
            "total_chars": self._total_chars,
            "hits": self.hits,
            "misses": self.misses,
            "refusals": self.refusals,
            "evictions": self.evictions,
            "hit_rate": (self.hits / total_lookups) if total_lookups else 0.0,
        }

    def clear_tenant(self, tenant_id: str) -> int:
        """Remove every entry for one tenant (suspension and deletion)."""
        keys = [k for k, e in self._entries.items() if e["tenant_id"] == tenant_id]
        for key in keys:
            self._drop(key)
        return len(keys)


STANDARD_DISCLOSURE = (
    "This call is answered by an AI receptionist for {business_name}. "
    "What you say may be transcribed so the team can follow up. "
    "You can ask for a person at any time."
)
STANDARD_HOLD = "Thank you for holding. I will be right back with you."
STANDARD_TRANSFER = "I will pass your message to the team right away."


def build_standard_phrases(tenant_config: dict) -> List[dict]:
    """The cacheable phrase set for one tenant, from its configuration.

    tenant_config is the BusinessConfig shape from the commercial
    contracts: businessName, greeting, afterHours greeting and FAQs.
    Only static tenant-authored text is included. Nothing caller-supplied
    belongs in this list.
    """
    business = str(tenant_config.get("businessName") or "the business").strip()
    phrases: List[dict] = []

    def add(kind: str, text: str) -> None:
        text = (text or "").strip()
        if text:
            phrases.append({"kind": kind, "text": text})

    add("greeting", tenant_config.get("greeting", ""))
    add("disclosure", STANDARD_DISCLOSURE.format(business_name=business))
    add("hold", STANDARD_HOLD)
    add("transfer", STANDARD_TRANSFER)
    after_hours = tenant_config.get("afterHours") or {}
    add("after_hours", after_hours.get("greeting", ""))
    for faq in tenant_config.get("faqs") or []:
        add("faq", faq.get("a", ""))
    return phrases
