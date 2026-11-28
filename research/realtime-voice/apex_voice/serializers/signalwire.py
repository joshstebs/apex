"""SignalWire Media Streams serializer for Pipecat.

Pipecat 1.17 ships serializers for Twilio, Telnyx, Plivo, Vonage, Genesys, Exotel
and Jambonz, but NOT SignalWire. The Media Streams wire protocol SignalWire uses is
the same JSON envelope Twilio uses, so this is modelled on TwilioFrameSerializer
with two deliberate differences:

  1. Hang-up goes through SignalWire's LaML REST API (``/api/laml/2010-04-01``),
     not Twilio's ``/2010-04-01``. Sending a Twilio-shaped hang-up to SignalWire
     would fail silently and leave the caller connected.
  2. Frames are 8 kHz G.711 mu-law, mono, base64, 20 ms each. The rate is declared
     explicitly so the serializer resamples rather than assuming.
"""
from __future__ import annotations

import base64
import json
from typing import Any

import aiohttp
from loguru import logger

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InputDTMFFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
    StartFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.audio.dtmf.types import KeypadEntry

try:  # Pipecat 1.17 exposes g711 here.
    from pipecat.audio import g711
except ImportError:  # pragma: no cover
    g711 = None

if g711 is None:  # pragma: no cover
    import audioop as _audioop

    class _G711:
        @staticmethod
        def pcm_to_ulaw(data: bytes) -> bytes:
            return _audioop.lin2ulaw(data, 2)

        @staticmethod
        def ulaw_to_pcm(data: bytes) -> bytes:
            return _audioop.ulaw2lin(data, 2)

    g711 = _G711()

SIGNALWIRE_LAML = "/api/laml/2010-04-01"


class SignalWireFrameSerializer(FrameSerializer):
    """Serialize Pipecat frames to SignalWire Media Streams JSON."""

    class InputParams(FrameSerializer.InputParams):
        """SignalWire wire format.

        Parameters:
            audio_in_sample_rate: Rate SignalWire sends, fixed at 8000 Hz.
            audio_out_sample_rate: Rate SignalWire expects, fixed at 8000 Hz.
            auto_hang_up: Terminate the call on EndFrame/CancelFrame.
        """

        audio_in_sample_rate: int = 8000
        audio_out_sample_rate: int = 8000
        auto_hang_up: bool = True

    def __init__(
        self,
        stream_sid: str,
        call_sid: str | None = None,
        space_url: str | None = None,
        project_id: str | None = None,
        api_token: str | None = None,
        params: InputParams | None = None,
    ):
        super().__init__(params=params or self.InputParams())
        self._stream_sid = stream_sid
        self._call_sid = call_sid
        self._space_url = (space_url or "").rstrip("/")
        self._project_id = project_id
        self._api_token = api_token
        self._sample_rate = self.audio_out_sample_rate

    async def setup(self, frame: StartFrame) -> None:
        """No handshake needed; SignalWire starts the stream itself."""
        self._sample_rate = self.audio_out_sample_rate

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, (EndFrame, CancelFrame)):
            if self._params.auto_hang_up:
                await self._hang_up_call()
            return None

        if isinstance(frame, OutputTransportMessageFrame):
            if self.should_ignore_frame(frame):
                return None
            return json.dumps(frame.message)

        if isinstance(frame, OutputTransportMessageUrgentFrame):
            if self.should_ignore_frame(frame):
                return None
            return json.dumps(frame.message)

        # Audio is handled by the transport path in newer Pipecat; anything else
        # (control frames) is not part of the Media Streams protocol we speak.
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        try:
            message = json.loads(data)
        except json.JSONDecodeError:
            logger.warning("SignalWire payload was not JSON; dropping")
            return None

        event = message.get("event")

        if event == "media":
            payload = (message.get("media") or {}).get("payload")
            if not payload:
                return None
            try:
                raw = base64.b64decode(payload)
            except (ValueError, TypeError):
                logger.warning("SignalWire media payload was not base64")
                return None
            audio = await self._resample_audio_in(g711.ulaw_to_pcm(raw))
            if not audio:
                return None
            return InputAudioRawFrame(
                audio=audio, num_channels=1, sample_rate=self.audio_in_sample_rate
            )

        if event == "dtmf":
            digit = (message.get("dtmf") or {}).get("digit")
            try:
                return InputDTMFFrame(KeypadEntry(digit))
            except ValueError:
                return None

        # connected / start / mark / stop carry no audio we act on here.
        return None

    async def _hang_up_call(self) -> None:
        """End the call through SignalWire's LaML API."""
        if not (self._space_url and self._project_id and self._api_token and self._call_sid):
            logger.debug("SignalWire hang-up skipped: credentials or call_sid missing")
            return
        url = (
            f"{self._space_url}{SIGNALWIRE_LAML}/Accounts/"
            f"{self._project_id}/Calls/{self._call_sid}.json"
        )
        auth = aiohttp.BasicAuth(self._project_id, self._api_token)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data={"Status": "completed"}, auth=auth) as resp:
                    if resp.status >= 400:
                        logger.warning(
                            f"SignalWire hang-up returned {resp.status}: "
                            f"{(await resp.text())[:200]}"
                        )
        except (aiohttp.ClientError, OSError) as exc:
            logger.warning(f"SignalWire hang-up failed: {exc}")
