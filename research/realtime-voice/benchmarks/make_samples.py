#!/usr/bin/env python3
"""Generate sample audio artefacts for the PR: wav (listenable) and ulaw (wire format)."""
import os
import asyncio
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex_voice.audio import (  # noqa: E402
    TELEPHONY_RATE,
    piper_wav_to_ulaw_8k,
    ulaw_to_pcm16,
    wav_header,
)
from apex_voice.piper_tts import PiperTTS, PiperVoice  # noqa: E402

VOICES = Path(os.environ.get("APEX_VOICE_DIR", "voices"))
OUT = Path(__file__).resolve().parents[1] / "samples"

SAMPLES = [
    ("greeting_en", "Hello, thank you for calling Harbour and Main. How can I help you today?", "en_ljspeech"),
    ("appointment_en", "I have Tuesday at two thirty available. Shall I book that for you?", "en_ljspeech"),
    ("message_taking_en", "I have noted your message and passed it to the team. They will call you back today.", "en_ljspeech"),
    ("greeting_fr", "Bonjour, merci d'avoir appelé Harbour and Main. Comment puis-je vous aider ?", "fr_siwis"),
]


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tts = PiperTTS(
        voices={
            "en_ljspeech": PiperVoice("en_ljspeech",
                VOICES / "en_US-ljspeech-medium.onnx",
                VOICES / "en_US-ljspeech-medium.onnx.json", "en_US", "public-domain"),
            "fr_siwis": PiperVoice("fr_siwis",
                VOICES / "fr_FR-siwis-medium.onnx",
                VOICES / "fr_FR-siwis-medium.onnx.json", "fr_FR", "cc-by-4.0"),
        },
        max_concurrency=1,
    )
    tts.warm(["en_ljspeech", "fr_siwis"])

    for name, text, voice in SAMPLES:
        pcm = await tts.synthesize(text, voice, "sample_tenant")
        # 1. Native 22.05 kHz wav, what a human listens to
        (OUT / f"{name}_22k.wav").write_bytes(
            wav_header(pcm, 22050) + pcm
        )
        # 2. Telephony 8 kHz mu-law, exactly what goes on the wire
        ulaw = piper_wav_to_ulaw_8k(pcm)
        (OUT / f"{name}_8k.ulaw").write_bytes(ulaw)
        # 3. 8 kHz wav, so the phone audio can be audited by ear
        pcm8k = ulaw_to_pcm16(ulaw)
        (OUT / f"{name}_8k.wav").write_bytes(
            wav_header(pcm8k, TELEPHONY_RATE) + pcm8k
        )
        print(f"{name}: 22k={len(pcm)}B  ulaw={len(ulaw)}B  dur={len(pcm)/2/22050:.2f}s")

    sizes = sorted(p.name for p in OUT.iterdir())
    print(f"\nfiles written: {len(sizes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
