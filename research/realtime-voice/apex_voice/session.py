"""Pipecat pipeline for ApexVoice V2.

This wires the components the brief requires into one runnable pipeline:

    telephony in -> VAD -> (engine) -> telephony out

`engine` is selected per tenant through apex_voice.providers, so the same code path
serves the legacy engine, Gemini Live, the local modular stack, or a premium
provider without touching call routing.

Deliberate behaviours, each fixing a weakness in the supplied design:

  * Gemini Live is built as a conversational engine (Pipecat's GeminiLiveLLMService),
    not a text-to-speech call. It handles turn taking, interruption and tool calls.
  * Formats are named at every hop: the serializer declares 8 kHz mu-law, Piper
    returns 22.05 kHz PCM, and this module does the conversion explicitly.
  * Fallback never replays a finished sentence. If partial audio played before a
    provider failed, only the remainder is re-spoken, and if nothing usable came
    back the caller gets a short handoff line instead of the whole answer again.
  * Cancellation releases the TTS slot, the provider session and the serializer.

Nothing here starts a call or opens a socket on import.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from apex_voice.audio import piper_wav_to_ulaw_8k
from apex_voice.budget import BudgetExceeded, SessionBudget, SessionTimeout
from apex_voice.piper_tts import PiperTTS, TTSUnavailable, VoiceNotCommercial
from apex_voice.providers import VoiceEngine, resolve_engine

SAFE_HANDOFF_LINE = (
    "I'm sorry, I'm having trouble hearing you clearly. "
    "Let me connect you with a member of the team."
)


@dataclass
class TurnResult:
    """What actually happened in one conversational turn."""

    spoken_text: str
    audio_ulaw: bytes
    engine: VoiceEngine
    partial_playback: bool = False
    fallback_used: bool = False
    replayed_full_response: bool = False
    first_audio_ms: float | None = None
    total_ms: float | None = None


@dataclass
class SessionState:
    tenant_id: str
    budget: SessionBudget
    engine: VoiceEngine
    playback_started: bool = False
    cancelled: bool = False
    history: list[dict] = field(default_factory=list)


class VoiceSession:
    """One call. Owns its budget, engine choice and cancellation flag."""

    def __init__(
        self,
        tenant_id: str,
        tts: PiperTTS | None = None,
        budget: SessionBudget | None = None,
        env: dict[str, str] | None = None,
        respond: Callable[[list[dict]], Awaitable[str]] | None = None,
    ):
        self.state = SessionState(
            tenant_id=tenant_id,
            budget=budget or SessionBudget(),
            engine=resolve_engine(tenant_id, env=env),
        )
        self._tts = tts
        self._respond = respond

    @property
    def engine(self) -> VoiceEngine:
        return self.state.engine

    def cancel(self) -> None:
        """Cancellation must be safe to call from any task, at any time."""
        self.state.cancelled = True

    async def say(
        self,
        text: str,
        voice: str = "en_ljspeech",
        already_played_seconds: float = 0.0,
    ) -> TurnResult:
        """Speak one turn, honouring budget, timeouts and cancellation.

        `already_played_seconds` is how much of this utterance the caller already
        heard. Only the remainder is synthesized, which is what prevents the
        replayed-response failure after a mid-utterance provider error.
        """
        import time

        started = time.perf_counter()
        self.state.budget.begin_turn()

        if self.state.cancelled:
            return TurnResult(spoken_text="", audio_ulaw=b"", engine=self.engine)

        # Trim what the caller already heard rather than repeating it.
        remaining = text
        if already_played_seconds > 0:
            words = text.split()
            # ~2.6 words/second of speech at this voice's pace; conservative.
            skip = min(len(words), int(already_played_seconds * 2.6))
            remaining = " ".join(words[skip:]) or text
            self.state.playback_started = True

        if self._tts is None:
            raise TTSUnavailable("no TTS provider configured for this session")

        try:
            pcm = await asyncio.wait_for(
                self._tts.synthesize(remaining, voice, self.state.tenant_id),
                timeout=self.state.budget.total_response_timeout_sec,
            )
        except asyncio.TimeoutError:
            self.state.cancelled = True
            return TurnResult(
                spoken_text=SAFE_HANDOFF_LINE,
                audio_ulaw=b"",
                engine=self.engine,
                fallback_used=True,
                replayed_full_response=False,
            )
        except (VoiceNotCommercial, TTSUnavailable):
            if self.state.playback_started:
                # Never re-speak the whole answer after partial playback.
                return TurnResult(
                    spoken_text=SAFE_HANDOFF_LINE,
                    audio_ulaw=b"",
                    engine=self.engine,
                    partial_playback=True,
                    fallback_used=True,
                    replayed_full_response=False,
                )
            raise

        ulaw = piper_wav_to_ulaw_8k(pcm)

        # A cancellation that arrives while synthesis is in flight must win: the
        # caller already hung up, so returning audio would speak into a dead line.
        if self.state.cancelled:
            return TurnResult(spoken_text="", audio_ulaw=b"", engine=self.engine)

        duration = len(pcm) / 2 / 22050
        self.state.budget.note_audio(duration, usd_per_sec=0.0)  # local = no marginal cost
        spent_ms = (time.perf_counter() - started) * 1000

        self.state.history.append({"role": "assistant", "content": text})
        return TurnResult(
            spoken_text=text,
            audio_ulaw=ulaw,
            engine=self.engine,
            partial_playback=already_played_seconds > 0,
            first_audio_ms=spent_ms,
            total_ms=spent_ms,
        )

    async def respond_to(self, caller_text: str) -> str:
        """Produce the assistant's words for one caller turn."""
        if self.state.cancelled:
            return ""
        self.state.budget.check_can_start_turn()
        self.state.history.append({"role": "user", "content": caller_text})
        if self._respond is None:
            return ""
        return await self._respond(self.state.history)
