#!/usr/bin/env python3
"""Conversation benchmarks: latency, interruption, outage recovery, French.

Synthetic audio only. No telephone calls are placed and no billed provider is
called, so nothing here costs money or touches a live number.
"""
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex_voice.audio import piper_wav_to_ulaw_8k
from apex_voice.budget import BudgetExceeded, SessionBudget, SessionTimeout
from apex_voice.piper_tts import PiperTTS, PiperVoice, TTSUnavailable
from apex_voice.providers import VoiceEngine, resolve_engine
from apex_voice.session import SAFE_HANDOFF_LINE, VoiceSession

VOICES = Path(os.environ.get("APEX_VOICE_DIR", "voices"))
CC_BY = "cc-by-4.0"


def pool(concurrency: int = 2) -> PiperTTS:
    return PiperTTS(
        voices={
            "en_ljspeech": PiperVoice("en_ljspeech",
                VOICES / "en_US-ljspeech-medium.onnx",
                VOICES / "en_US-ljspeech-medium.onnx.json", "en_US", "public-domain"),
            "fr_siwis": PiperVoice("fr_siwis",
                VOICES / "fr_FR-siwis-medium.onnx",
                VOICES / "fr_FR-siwis-medium.onnx.json", "fr_FR", CC_BY),
        },
        max_concurrency=concurrency,
    )


CASES = {
    "greeting": ("Hello, thank you for calling Harbour and Main. How can I help?", "en_ljspeech"),
    "business_question": ("We are open Monday to Friday from nine until five, and Saturday by appointment.", "en_ljspeech"),
    "appointment": ("I have Tuesday at two thirty available. Shall I book that for you?", "en_ljspeech"),
    "message_taking": ("I have noted your message and passed it to the team. They will call you back today.", "en_ljspeech"),
    "long_pause": ("Take your time. I am still here whenever you are ready.", "en_ljspeech"),
    "french": ("Bonjour, merci d'avoir appelé. Nous sommes ouverts du lundi au vendredi.", "fr_siwis"),
}


class FlakyTTS(PiperTTS):
    """Fails on demand so provider-outage recovery can be measured."""

    def __init__(self, *args, fail_after: int = 0, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_after = fail_after
        self.calls = 0

    async def synthesize(self, text, voice_name, tenant_id, audio_format="pcm_s16le"):
        self.calls += 1
        if self.fail_after and self.calls > self.fail_after:
            raise TTSUnavailable("simulated provider outage")
        return await super().synthesize(text, voice_name, tenant_id, audio_format)


async def bench_cases(tts: PiperTTS) -> dict:
    out = {}
    for name, (text, voice) in CASES.items():
        runs = []
        for _ in range(5):
            t0 = time.perf_counter()
            pcm = await tts.synthesize(text, voice, "bench")
            wall = (time.perf_counter() - t0) * 1000
            ulaw = piper_wav_to_ulaw_8k(pcm)
            audio_s = len(pcm) / 2 / 22050
            runs.append({
                "first_audio_ms": wall,
                "rtf": wall / 1000 / audio_s if audio_s else None,
                "audio_s": round(audio_s, 2),
                "ulaw_bytes": len(ulaw),
            })
        walls = [r["first_audio_ms"] for r in runs]
        out[name] = {
            "runs": len(runs),
            "median_first_audio_ms": round(statistics.median(walls), 1),
            "p95_first_audio_ms": round(sorted(walls)[-2], 1),
            "median_rtf": round(statistics.median(r["rtf"] for r in runs), 3),
            "median_audio_s": round(statistics.median(r["audio_s"] for r in runs), 2),
        }
    return out


async def bench_interruption(tts: PiperTTS) -> dict:
    """Caller interrupts mid-utterance; only the remainder should be spoken."""
    session = VoiceSession("tenant_int", tts=tts, env={"APEX_VOICE_ENGINE": "legacy"})
    full = await session.say("I can book you in for Tuesday at two thirty in the afternoon.", "en_ljspeech")
    remainder = await session.say(
        "I can book you in for Tuesday at two thirty in the afternoon.",
        "en_ljspeech",
        already_played_seconds=1.5,
    )
    return {
        "full_audio_bytes": len(full.audio_ulaw),
        "remainder_audio_bytes": len(remainder.audio_ulaw),
        "shorter_than_full": len(remainder.audio_ulaw) < len(full.audio_ulaw),
        "replayed_full_response": remainder.replayed_full_response,
    }


async def bench_cancellation(tts: PiperTTS) -> dict:
    session = VoiceSession("tenant_cancel", tts=tts, env={"APEX_VOICE_ENGINE": "legacy"})
    task = asyncio.create_task(session.say("This is a long sentence that will be cancelled part way through.", "en_ljspeech"))
    await asyncio.sleep(0.02)
    session.cancel()
    result = await task
    return {
        "audio_returned_bytes": len(result.audio_ulaw),
        "cancelled_cleanly": session.state.cancelled,
    }


async def bench_outage(tts: PiperTTS) -> dict:
    """Provider dies after audio already played: the whole answer must NOT replay."""
    flaky = FlakyTTS(voices=tts._voices, max_concurrency=2, fail_after=1)
    session = VoiceSession("tenant_out", tts=flaky, env={"APEX_VOICE_ENGINE": "legacy"})

    first = await session.say("Hello, how can I help today?", "en_ljspeech")
    # Mark that the caller already heard part of the next answer.
    session.state.playback_started = True

    recovery_start = time.perf_counter()
    second = await session.say(
        "Let me check that for you. I am looking at the diary now.",
        "en_ljspeech",
        already_played_seconds=1.0,
    )
    recovery_ms = (time.perf_counter() - recovery_start) * 1000

    return {
        "first_turn_ok": len(first.audio_ulaw) > 0,
        "outage_handled": second.fallback_used,
        "partial_playback_flagged": second.partial_playback,
        "replayed_full_response": second.replayed_full_response,
        "handoff_line_used": second.spoken_text == SAFE_HANDOFF_LINE,
        "recovery_ms": round(recovery_ms, 1),
    }


async def bench_budget(tts: PiperTTS) -> dict:
    budget = SessionBudget(max_usd=0.0001, max_turns=2, max_duration_sec=600)
    session = VoiceSession("tenant_budget", tts=tts, budget=budget,
                           env={"APEX_VOICE_ENGINE": "legacy"})
    hits = []
    for _ in range(4):
        try:
            budget.spent_usd += 0.00004
            await session.say("Short reply.", "en_ljspeech")
            hits.append("ok")
        except BudgetExceeded:
            hits.append("blocked")
    return {"sequence": hits, "final_spent_usd": round(budget.spent_usd, 6)}


def bench_engine_flags() -> dict:
    cases = {}
    cases["default"] = resolve_engine("t1", env={}).value
    cases["explicit_local"] = resolve_engine("t1", env={
        "APEX_VOICE_ENGINE": "local", "APEX_VOICE_ENABLED_ENGINES": "legacy,local"}).value
    cases["typo_falls_back"] = resolve_engine("t1", env={
        "APEX_VOICE_ENGINE": "gemini_liv", "APEX_VOICE_ENABLED_ENGINES": "legacy"}).value
    cases["disabled_engine_refused"] = resolve_engine("t1", env={
        "APEX_VOICE_ENGINE": "gemini_live", "APEX_VOICE_ENABLED_ENGINES": "legacy"}).value
    cases["per_tenant_override"] = resolve_engine("acme", env={
        "APEX_VOICE_ENGINE": "legacy", "APEX_VOICE_ENABLED_ENGINES": "legacy,local",
        "APEX_VOICE_TENANT_ACME": "local"}).value
    # Canary must be stable for the same tenant.
    env = {"APEX_VOICE_ENGINE": "legacy", "APEX_VOICE_ENABLED_ENGINES": "legacy,local",
           "APEX_VOICE_CANARY_PERCENT": "50", "APEX_VOICE_CANARY_ENGINE": "local"}
    picks = [resolve_engine("tenant_stable", env=env).value for _ in range(5)]
    cases["canary_stable"] = len(set(picks)) == 1
    return cases


async def main() -> int:
    tts = pool()
    tts.warm(["en_ljspeech", "fr_siwis"])

    results = {
        "cases": await bench_cases(tts),
        "interruption": await bench_interruption(tts),
        "cancellation": await bench_cancellation(tts),
        "outage": await bench_outage(tts),
        "budget_control": await bench_budget(tts),
        "engine_flags": bench_engine_flags(),
    }
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
