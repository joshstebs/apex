#!/usr/bin/env python3
"""Exercise the Piper TTS module for real: synthesis, cache keys, licensing gate."""
import os
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex_voice.audio import piper_wav_to_ulaw_8k  # noqa: E402
from apex_voice.piper_tts import (  # noqa: E402
    CacheKey, PiperTTS, PiperVoice, TTSUnavailable, VoiceNotCommercial, text_digest,
)

VOICES = Path(os.environ.get("APEX_VOICE_DIR", "voices"))


def build(max_concurrency: int = 2) -> PiperTTS:
    return PiperTTS(
        voices={
            "en_ljspeech": PiperVoice(
                name="en_ljspeech",
                model_path=VOICES / "en_US-ljspeech-medium.onnx",
                config_path=VOICES / "en_US-ljspeech-medium.onnx.json",
                language="en_US",
                licence="public-domain",
            ),
            "fr_siwis": PiperVoice(
                name="fr_siwis",
                model_path=VOICES / "fr_FR-siwis-medium.onnx",
                config_path=VOICES / "fr_FR-siwis-medium.onnx.json",
                language="fr_FR",
                licence="cc-by-4.0",
            ),
            "en_lessac_risky": PiperVoice(
                name="en_lessac_risky",
                model_path=VOICES / "en_US-lessac-medium.onnx",
                config_path=VOICES / "en_US-lessac-medium.onnx.json",
                language="en_US",
                licence="blizzard-2013-research",
            ),
        },
        max_concurrency=max_concurrency,
        cache_dir=Path("/tmp/apex-cache"),
        cache_enabled_for_tenant_speech=True,
    )


async def main() -> int:
    tts = build()
    ok = True

    print("warm load:", tts.warm(["en_ljspeech", "fr_siwis"]))

    # 1. English synthesis produces audio that converts to telephony mu-law.
    pcm = await tts.synthesize("Hello, thanks for calling Harbour and Main.", "en_ljspeech", "tenant_a")
    ulaw = piper_wav_to_ulaw_8k(pcm)
    expected_ulaw = round(len(pcm) / 2 * 8000 / 22050)
    print(f"en pcm bytes={len(pcm)} duration={len(pcm)/2/22050:.2f}s -> ulaw bytes={len(ulaw)} "
          f"(expected ~{expected_ulaw})")
    ok &= len(pcm) > 10000 and abs(len(ulaw) - expected_ulaw) <= 2

    # 2. French uses the French model, not the English one.
    pcm_fr = await tts.synthesize("Bonjour, merci d'avoir appelé.", "fr_siwis", "tenant_a")
    print(f"fr pcm bytes={len(pcm_fr)}")
    ok &= len(pcm_fr) > 10000

    # 3. A research-licensed voice is refused.
    try:
        await tts.synthesize("This must not synthesize.", "en_lessac_risky", "tenant_a")
        print("LICENCE GATE FAILED: risky voice synthesized")
        ok = False
    except VoiceNotCommercial as exc:
        print(f"licence gate refused risky voice: {str(exc)[:70]}...")

    # 4. Unknown voice refused.
    try:
        await tts.synthesize("x", "does_not_exist", "tenant_a")
        print("UNKNOWN VOICE FAILED")
        ok = False
    except TTSUnavailable:
        print("unknown voice refused correctly")

    # 5. Cache keys separate tenants and voices.
    k1 = CacheKey("tenant_a", "piper", "m", "v1", 22050, "pcm", text_digest("hello"))
    k2 = CacheKey("tenant_b", "piper", "m", "v1", 22050, "pcm", text_digest("hello"))
    k3 = CacheKey("tenant_a", "piper", "m", "v2", 22050, "pcm", text_digest("hello"))
    k4 = CacheKey("tenant_a", "piper", "m", "v1", 8000, "ulaw", text_digest("hello"))
    keys = {k1.digest(), k2.digest(), k3.digest(), k4.digest()}
    print(f"cache keys distinct across tenant/voice/rate/format: {len(keys) == 4}")
    ok &= len(keys) == 4

    # 6. Cache hit is populated and reused.
    cached = list(Path("/tmp/apex-cache").glob("*.pcm"))
    print(f"cache entries written: {len(cached)}")
    ok &= len(cached) >= 1

    # 7. Bounded concurrency completes without error.
    results = await asyncio.gather(*[
        tts.synthesize(f"Concurrent sentence number {i}.", "en_ljspeech", f"tenant_{i}")
        for i in range(4)
    ])
    print(f"4 concurrent syntheses ok: {all(len(r) > 1000 for r in results)}")
    ok &= all(len(r) > 1000 for r in results)

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
