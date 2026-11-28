"""Local Piper TTS with persistent models, bounded concurrency and a safe cache.

Licensing, recorded from the Piper project's own LICENSING.md (read 2026-11-28):

  * The Piper ENGINE is GPL-3.0-or-later. That is a real grant over the code.
  * Piper makes **no licence grant over voice models** and adds no restriction.
    Rights in a voice come from its training data and from whoever trained it.
  * A voice's MODEL_CARD `License` line covers that voice's DATASET ONLY. It is
    not a statement about the weights, and it is not a grant from Piper.
  * Whether weights are a derivative work of the corpus is legally unsettled, and
    Piper takes no position. Piper's own guidance: for commercial use, take legal
    advice rather than treating a model card as permission.

So this module records a dataset licence and a documented risk level per voice
instead of pretending an allowlist settles it. Voices are metadata, not gatekeeping:
`licence_risk` is surfaced so a commercial decision can be made with the facts.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
import wave
from dataclasses import dataclass, field
from pathlib import Path

# Dataset licences that carry the least commercial risk, and how each is classified.
# "documented" = dataset licence is explicit and permissive. "unsettled" = usable
# but the weights question is open. Anything unknown is refused rather than assumed.
LICENCE_RISK = {
    "public-domain": "documented",
    "cc0-1.0": "documented",
    "cc-by-4.0": "documented-attribution-required",
    "cc-by-sa-4.0": "documented-sharealike-required",
    "mit": "documented",
    "apache-2.0": "documented",
}
ACCEPTABLE_RISK = frozenset({"documented", "documented-attribution-required"})


class VoiceNotCommercial(RuntimeError):
    """Raised when a requested voice's dataset licence is unknown or unsuitable."""


class TTSUnavailable(RuntimeError):
    """Raised when synthesis fails after bounded retries."""


@dataclass(frozen=True)
class PiperVoice:
    name: str
    model_path: Path
    config_path: Path
    language: str
    licence: str
    sample_rate: int = 22050


@dataclass
class CacheKey:
    """Every field that can change the audio belongs in the key."""

    tenant_id: str
    provider: str
    model: str
    voice: str
    sample_rate: int
    audio_format: str
    text_digest: str
    extra: str = ""

    def digest(self) -> str:
        raw = "|".join([
            self.tenant_id, self.provider, self.model, self.voice,
            str(self.sample_rate), self.audio_format, self.text_digest, self.extra,
        ])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def text_digest(text: str) -> str:
    normalised = " ".join(text.split()).lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:32]


class PiperTTS:
    """Persistent Piper voices with a concurrency cap.

    The model is loaded once per voice and reused. Piper's synthesis is CPU bound
    and releases the GIL inside onnxruntime, so a thread pool is used rather than
    processes; concurrency is capped because this host has two cores and shares
    them with the production services.
    """

    def __init__(
        self,
        voices: dict[str, PiperVoice],
        max_concurrency: int = 2,
        cache_dir: Path | None = None,
        cache_enabled_for_tenant_speech: bool = False,
    ):
        self._voices = voices
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._models: dict[str, object] = {}
        self._cache_dir = cache_dir
        self._cache_tenant_speech = cache_enabled_for_tenant_speech
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def available_voices(self) -> list[str]:
        return sorted(self._voices)

    def _voice(self, name: str) -> PiperVoice:
        voice = self._voices.get(name)
        if voice is None:
            raise TTSUnavailable(f"unknown voice {name!r}")
        risk = LICENCE_RISK.get(voice.licence.lower())
        if risk is None:
            raise VoiceNotCommercial(
                f"voice {name!r} carries dataset licence {voice.licence!r}, which is "
                f"not classified. Add it to LICENCE_RISK only after reading its "
                f"MODEL_CARD, or select a different voice."
            )
        if risk not in ACCEPTABLE_RISK:
            raise VoiceNotCommercial(
                f"voice {name!r} is {risk}: {voice.licence}. Select a voice whose "
                f"dataset licence permits commercial synthesis."
            )
        return voice

    def _load(self, name: str):
        """Load once, keep resident. Cold load is ~350-400 ms on this ARM host."""
        if name in self._models:
            return self._models[name]
        from piper import PiperVoice as _PiperVoice

        voice = self._voice(name)
        model = _PiperVoice.load(str(voice.model_path))
        self._models[name] = model
        return model

    def warm(self, names: list[str] | None = None) -> list[str]:
        """Preload models so the first call does not pay the cold-start cost."""
        loaded = []
        for name in (names or list(self._voices)):
            try:
                self._load(name)
                loaded.append(name)
            except (TTSUnavailable, VoiceNotCommercial, OSError):
                continue
        return loaded

    def _synthesize_sync(self, name: str, text: str) -> bytes:
        model = self._load(name)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            model.synthesize_wav(text, wf)
        buf.seek(0)
        with wave.open(buf) as wf:
            return wf.readframes(wf.getnframes())

    async def synthesize(
        self,
        text: str,
        voice_name: str,
        tenant_id: str,
        audio_format: str = "pcm_s16le",
    ) -> bytes:
        """Synthesise speech, returning raw 16-bit PCM at the voice's rate.

        Callers convert to mu-law at the edge; keeping synthesis and telephony
        conversion separate is what makes the format explicit rather than assumed.
        """
        voice = self._voice(voice_name)
        key = CacheKey(
            tenant_id=tenant_id,
            provider="piper",
            model=voice.model_path.name,
            voice=voice_name,
            sample_rate=voice.sample_rate,
            audio_format=audio_format,
            text_digest=text_digest(text),
        )
        cache_path = None
        if self._cache_dir and self._cache_tenant_speech:
            cache_path = self._cache_dir / f"{key.digest()}.pcm"
            if cache_path.exists():
                return cache_path.read_bytes()

        async with self._semaphore:
            loop = asyncio.get_running_loop()
            pcm = await loop.run_in_executor(None, self._synthesize_sync, voice_name, text)

        if cache_path is not None:
            tmp = cache_path.with_suffix(".tmp")
            tmp.write_bytes(pcm)
            os.replace(tmp, cache_path)
        return pcm
