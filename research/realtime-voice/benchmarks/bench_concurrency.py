#!/usr/bin/env python3
"""Concurrent-session capacity benchmark for local Piper on arm-free-1.

Answers the operational question: how many simultaneous calls can one 2 vCPU
Oracle Free Tier instance carry before audio starts arriving late?

Measures real-time factor (RTF) per session. RTF < 1.0 means synthesis is faster
than playback, which is the condition for smooth conversation. Above 1.0 the
caller hears gaps.
"""
import asyncio
import json
import os
import resource
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex_voice.audio import piper_wav_to_ulaw_8k
from apex_voice.piper_tts import PiperTTS, PiperVoice

VOICES = Path(os.environ.get("APEX_VOICE_DIR", "voices"))

SENTENCES = [
    "Hello, thank you for calling. How can I help you today?",
    "We are open Monday to Friday, nine until five.",
    "I can book you in for Tuesday at two thirty. Does that suit you?",
    "Let me check that for you, one moment please.",
    "I have taken your message and the team will call you back within the hour.",
]


def build_pool(concurrency: int) -> PiperTTS:
    return PiperTTS(
        voices={
            "en": PiperVoice(
                name="en",
                model_path=VOICES / "en_US-ljspeech-medium.onnx",
                config_path=VOICES / "en_US-ljspeech-medium.onnx.json",
                language="en_US",
                licence="public-domain",
            ),
        },
        max_concurrency=concurrency,
    )


async def one_session(tts: PiperTTS, session_id: int, turns: int = 5) -> dict:
    """Simulate one caller: N spoken replies, timed end to end."""
    latencies = []
    audio_seconds = 0.0
    total_synth = 0.0
    for i in range(turns):
        text = SENTENCES[i % len(SENTENCES)]
        t0 = time.perf_counter()
        pcm = await tts.synthesize(text, "en", f"bench_{session_id}")
        elapsed = time.perf_counter() - t0
        ulaw = piper_wav_to_ulaw_8k(pcm)
        duration = len(pcm) / 2 / 22050
        latencies.append(elapsed)
        audio_seconds += duration
        total_synth += elapsed
    return {
        "session": session_id,
        "turns": turns,
        "audio_seconds": round(audio_seconds, 2),
        "synthesis_seconds": round(total_synth, 2),
        "rtf": round(total_synth / audio_seconds, 3) if audio_seconds else None,
        "median_latency_ms": round(statistics.median(latencies) * 1000, 1),
        "p95_latency_ms": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)] * 1000, 1),
        "first_audio_ms": round(latencies[0] * 1000, 1),
    }


async def run_level(concurrency: int) -> dict:
    tts = build_pool(concurrency)
    cold_start = time.perf_counter()
    tts.warm(["en"])
    cold_ms = (time.perf_counter() - cold_start) * 1000

    wall_start = time.perf_counter()
    sessions = await asyncio.gather(*[
        one_session(tts, i) for i in range(concurrency)
    ])
    wall = time.perf_counter() - wall_start

    audio_total = sum(s["audio_seconds"] for s in sessions)
    synth_total = sum(s["synthesis_seconds"] for s in sessions)
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

    return {
        "concurrency": concurrency,
        "cold_start_ms": round(cold_ms, 1),
        "wall_seconds": round(wall, 2),
        "aggregate_audio_seconds": round(audio_total, 2),
        "aggregate_rtf": round(synth_total / audio_total, 3) if audio_total else None,
        "peak_rss_mb": round(peak_rss, 1),
        "sessions": sessions,
        "realtime_feasible": all(s["rtf"] < 1.0 for s in sessions),
    }


async def main() -> int:
    cpus = os.cpu_count() or 1
    results = {"cpus": cpus, "levels": []}
    for level in (1, 2, 4):
        results["levels"].append(await run_level(level))
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
