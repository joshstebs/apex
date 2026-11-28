"""Audio format handling for telephony.

Every conversion here is explicit. Formats are named, never implied, because a
silent sample-rate assumption is the classic cause of chipmunk audio on a phone
call. SignalWire Media Streams carry 8 kHz G.711 mu-law, mono, base64 per frame.

`audioop` was removed from the standard library in Python 3.13. The maintained
`audioop-lts` package (PSF-2.0) restores it, C-accelerated, and is a hard
dependency. A pure-numpy fallback exists so the module still imports if that
package is missing, but the fallback encoder is NOT bit-exact at segment
boundaries and must not be used for production telephony.
"""
from __future__ import annotations

import base64
import struct

import numpy as np

try:  # PSF-2.0, the real G.711 implementation
    import audioop as _audioop
except ImportError:  # pragma: no cover
    _audioop = None

PCM_RATE = 22050        # Piper native output
TELEPHONY_RATE = 8000   # SignalWire / G.711
FRAME_MS = 20
ULAW_FRAME_BYTES = TELEPHONY_RATE * FRAME_MS // 1000   # 160 bytes per 20 ms frame


def codec_ready() -> bool:
    """True when the bit-exact G.711 implementation is available."""
    return _audioop is not None


def pcm16_to_pcm_rate(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Resample mono 16-bit PCM by linear interpolation. Adequate for speech."""
    if src_rate == dst_rate or not pcm:
        return pcm
    if _audioop is not None:
        converted, _ = _audioop.ratecv(pcm, 2, 1, src_rate, dst_rate, None)
        return converted
    src = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    if src.size == 0:
        return b""
    n_dst = int(round(src.size * dst_rate / src_rate))
    x_dst = np.linspace(0, src.size - 1, n_dst)
    out = np.interp(x_dst, np.arange(src.size, dtype=np.float64), src)
    return np.clip(out, -32768, 32767).astype("<i2").tobytes()


def pcm16_to_ulaw(pcm: bytes) -> bytes:
    """Encode 16-bit PCM to G.711 mu-law. Bit-exact via audioop-lts."""
    if not pcm:
        return b""
    if _audioop is None:
        raise RuntimeError(
            "audioop-lts is required for telephony encoding; the fallback is not "
            "bit-exact and would degrade call audio"
        )
    return _audioop.lin2ulaw(pcm, 2)


def ulaw_to_pcm16(ulaw: bytes) -> bytes:
    """Decode G.711 mu-law to 16-bit PCM."""
    if not ulaw:
        return b""
    if _audioop is None:
        raise RuntimeError("audioop-lts is required for telephony decoding")
    return _audioop.ulaw2lin(ulaw, 2)


def piper_wav_to_ulaw_8k(pcm22k: bytes) -> bytes:
    """The exact path phone audio takes: 22.05 kHz PCM -> 8 kHz PCM -> mu-law."""
    return pcm16_to_ulaw(pcm16_to_pcm_rate(pcm22k, PCM_RATE, TELEPHONY_RATE))


def ulaw_to_asr_input(ulaw8k: bytes, target_rate: int = 16000) -> bytes:
    """Inbound phone audio -> PCM for speech recognition models."""
    return pcm16_to_pcm_rate(ulaw_to_pcm16(ulaw8k), TELEPHONY_RATE, target_rate)


def frame_ulaw(ulaw: bytes, frame_bytes: int = ULAW_FRAME_BYTES):
    """Split mu-law into fixed 20 ms frames, padding the tail with silence (0xFF)."""
    for i in range(0, len(ulaw), frame_bytes):
        chunk = ulaw[i:i + frame_bytes]
        if len(chunk) < frame_bytes:
            chunk = chunk + b"\xff" * (frame_bytes - len(chunk))
        yield chunk


def frames_to_media_payload(ulaw: bytes, stream_sid: str) -> list[dict]:
    """SignalWire media messages, one per 20 ms frame."""
    return [
        {
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": base64.b64encode(f).decode("ascii")},
        }
        for f in frame_ulaw(ulaw)
    ]


def wav_header(pcm: bytes, rate: int, channels: int = 1) -> bytes:
    """Minimal RIFF header so a caller can write a playable wav without a library."""
    data_len = len(pcm)
    byte_rate = rate * channels * 2
    block_align = channels * 2
    return (
        b"RIFF" + struct.pack("<I", 36 + data_len) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, rate, byte_rate, block_align, 16)
        + b"data" + struct.pack("<I", data_len)
    )
