"""Session-level spending control and timeout enforcement.

The supplied prototype's known weaknesses were: no per-session budget, no explicit
timeouts, and fallback that replayed an entire response after partial playback.
This module owns the first two; the third is handled by the pipeline's
`playback_started` guard.

Design notes:
  * Budget is checked before a provider call, not after, so an expensive turn
    cannot start once the cap is reached.
  * Cost is accumulated from measured audio seconds and token counts, not from
    wall-clock estimates, so the number matches what a provider will bill.
  * Every limit is settable per session and has a conservative default.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


class BudgetExceeded(RuntimeError):
    """Raised when a session would exceed its spending cap."""


class SessionTimeout(RuntimeError):
    """Raised when a phase of the conversation takes too long."""


@dataclass
class SessionBudget:
    """Hard caps for one call.

    max_usd:               total spend allowed for the session
    max_duration_sec:      wall-clock cap for the call
    max_turns:             conversational turns allowed
    first_audio_timeout_sec: time allowed before the first audio frame
    inter_chunk_timeout_sec: gap allowed between audio chunks mid-utterance
    total_response_timeout_sec: cap for one complete spoken response
    """

    max_usd: float = 0.25
    max_duration_sec: int = 600
    max_turns: int = 60
    first_audio_timeout_sec: float = 3.0
    inter_chunk_timeout_sec: float = 2.0
    total_response_timeout_sec: float = 25.0

    spent_usd: float = 0.0
    turns: int = 0
    started_at: float = field(default_factory=time.monotonic)
    _first_audio_at: float | None = None
    _last_chunk_at: float | None = None

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def remaining_usd(self) -> float:
        return max(0.0, self.max_usd - self.spent_usd)

    def note_audio(self, seconds: float, usd_per_sec: float) -> None:
        """Charge for audio actually produced or consumed."""
        self.spent_usd += max(0.0, seconds) * max(0.0, usd_per_sec)

    def note_tokens(self, tokens: int, usd_per_million: float) -> None:
        self.spent_usd += max(0, tokens) / 1_000_000 * max(0.0, usd_per_million)

    def check_can_start_turn(self) -> None:
        """Call before contacting a provider."""
        if self.elapsed() >= self.max_duration_sec:
            raise SessionTimeout(f"call duration cap {self.max_duration_sec}s reached")
        if self.turns >= self.max_turns:
            raise BudgetExceeded(f"turn cap {self.max_turns} reached")
        if self.spent_usd >= self.max_usd:
            raise BudgetExceeded(
                f"session budget exhausted: spent ${self.spent_usd:.4f} of ${self.max_usd:.2f}"
            )

    def begin_turn(self) -> None:
        self.check_can_start_turn()
        self.turns += 1
        self._first_audio_at = None
        self._last_chunk_at = None

    def note_first_audio(self) -> None:
        self._first_audio_at = time.monotonic()
        self._last_chunk_at = self._first_audio_at

    def check_audio_timeouts(self, response_started_at: float) -> None:
        """Enforce first-audio and mid-stream gaps while audio is streaming."""
        now = time.monotonic()
        if self._first_audio_at is None:
            if now - response_started_at > self.first_audio_timeout_sec:
                raise SessionTimeout(
                    f"no first audio within {self.first_audio_timeout_sec}s"
                )
            return
        if self._last_chunk_at is not None:
            gap = now - self._last_chunk_at
            if gap > self.inter_chunk_timeout_sec:
                raise SessionTimeout(f"audio gap of {gap:.1f}s mid-response")
            self._last_chunk_at = now
        if now - response_started_at > self.total_response_timeout_sec:
            raise SessionTimeout(
                f"response exceeded {self.total_response_timeout_sec}s"
            )

    def summary(self) -> dict:
        return {
            "turns": self.turns,
            "elapsed_sec": round(self.elapsed(), 2),
            "spent_usd": round(self.spent_usd, 5),
            "remaining_usd": round(self.remaining_usd(), 5),
        }
