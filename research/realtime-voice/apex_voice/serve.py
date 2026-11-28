"""WebSocket entrypoint for the SignalWire Media Streams voice prototype.

Wire contract (SignalWire Media Streams):
  inbound  : JSON events - connected, start, media (base64 mu-law), dtmf, stop
  outbound : {"event":"media","streamSid":...,"media":{"payload":...}}

Security:
  * Bearer token required on the WebSocket handshake, compared in constant time.
  * A connection with no token, or a wrong token, is closed before any audio.
  * Per-session budget and duration caps from apex_voice.budget apply to every
    connection, so one call cannot run away.

This is a PROTOTYPE. It is not wired into production call routing, and it does
not place or answer real calls by itself.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any

try:
    import websockets
    from websockets.asyncio.server import serve
except ImportError:  # pragma: no cover
    websockets = None
    serve = None

from apex_voice.audio import frames_to_media_payload, piper_wav_to_ulaw_8k
from apex_voice.budget import BudgetExceeded, SessionBudget, SessionTimeout
from apex_voice.piper_tts import PiperTTS, PiperVoice
from apex_voice.providers import resolve_engine

HOST = os.environ.get("APEX_VOICE_BIND", "127.0.0.1")
PORT = int(os.environ.get("APEX_VOICE_PORT", "8098"))
TOKEN = os.environ.get("APEX_VOICE_WS_TOKEN", "")
VOICE_DIR = os.environ.get("APEX_VOICE_DIR", "/voices")


def load_tts() -> PiperTTS:
    """Build the voice pool from what is actually on disk.

    Missing models are skipped rather than fatal, so a partial mount still serves
    the voices it has instead of failing the whole service.
    """
    catalogue = {
        "en_ljspeech": ("en_US-ljspeech-medium", "en_US", "public-domain"),
        "fr_siwis": ("fr_FR-siwis-medium", "fr_FR", "cc-by-4.0"),
    }
    voices: dict[str, PiperVoice] = {}
    for name, (stem, lang, licence) in catalogue.items():
        model = Path(VOICE_DIR) / f"{stem}.onnx"
        config = Path(VOICE_DIR) / f"{stem}.onnx.json"
        if model.exists() and config.exists():
            voices[name] = PiperVoice(name, model, config, lang, licence)
    tts = PiperTTS(voices=voices, max_concurrency=int(os.environ.get("APEX_VOICE_CONCURRENCY", "2")))
    tts.warm(list(voices))
    return tts


async def _authorised(websocket) -> bool:
    """Constant-time bearer check on the handshake."""
    if not TOKEN:
        return False
    header = ""
    for name, value in websocket.request.headers.items():
        if name.lower() == "authorization":
            header = value
            break
    expected = f"Bearer {TOKEN}"
    return hmac.compare_digest(header, expected)


async def handle(websocket, tts: PiperTTS) -> None:
    if not await _authorised(websocket):
        await websocket.close(code=4401, reason="unauthorized")
        return

    stream_sid = "unknown"
    tenant_id = "unknown"
    budget = SessionBudget(
        max_usd=float(os.environ.get("APEX_VOICE_MAX_USD", "0.25")),
        max_duration_sec=int(os.environ.get("APEX_VOICE_MAX_SECONDS", "600")),
    )
    started = time.monotonic()

    try:
        async for raw in websocket:
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue

            kind = event.get("event")

            if kind == "start":
                info = event.get("start") or {}
                stream_sid = info.get("streamSid") or event.get("streamSid") or stream_sid
                tenant_id = (info.get("customParameters") or {}).get("tenant", "unknown")
                engine = resolve_engine(tenant_id)
                await websocket.send(json.dumps({"event": "mark", "streamSid": stream_sid,
                                                 "mark": {"name": f"engine:{engine.value}"}}))
                continue

            if kind == "stop":
                break

            if kind != "media":
                continue

            # Budget is checked before doing any work, so a capped session stops
            # synthesising rather than spending first and reporting later.
            if budget.elapsed() >= budget.max_duration_sec:
                raise SessionTimeout("call duration cap reached")
            budget.check_can_start_turn()

            payload = (event.get("media") or {}).get("payload")
            if not payload:
                continue

            # Prototype reply: a fixed acknowledgement. The conversational turn is
            # produced by the engine bound to this tenant; wiring Gemini Live or an
            # ASR+LLM here is the integration step, not something faked in a socket.
            voice = os.environ.get("APEX_VOICE_DEFAULT_VOICE", "en_ljspeech")
            if voice not in tts.available_voices():
                continue
            pcm = await tts.synthesize("One moment please.", voice, tenant_id)
            budget.note_audio(len(pcm) / 2 / 22050, 0.0)
            for message in frames_to_media_payload(piper_wav_to_ulaw_8k(pcm), stream_sid):
                await websocket.send(json.dumps(message))

    except (BudgetExceeded, SessionTimeout) as exc:
        try:
            await websocket.send(json.dumps({"event": "mark", "streamSid": stream_sid,
                                             "mark": {"name": f"halted:{exc}"}}))
        except Exception:
            pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        # Nothing survives the socket: no task, no model reference held per call.
        pass


async def main() -> None:
    if serve is None:
        raise SystemExit("websockets is required: pip install websockets")
    if not TOKEN:
        raise SystemExit("APEX_VOICE_WS_TOKEN must be set; refusing to serve without auth")
    tts = load_tts()
    print(f"apex-voice realtime on ws://{HOST}:{PORT} voices={tts.available_voices()}", flush=True)
    async with serve(lambda ws: handle(ws, tts), HOST, PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
