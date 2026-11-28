"""Automated tests for the ApexVoice V2 realtime research branch.

Run: python -m pytest tests/ -q
Tests that need voice models are skipped when the model files are absent, so the
suite still runs in CI without downloading 120 MB of models.
"""
import asyncio
import base64
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex_voice.audio import (  # noqa: E402
    FRAME_MS,
    TELEPHONY_RATE,
    ULAW_FRAME_BYTES,
    frame_ulaw,
    frames_to_media_payload,
    pcm16_to_pcm_rate,
    pcm16_to_ulaw,
    piper_wav_to_ulaw_8k,
    ulaw_to_pcm16,
    wav_header,
)
from apex_voice.budget import BudgetExceeded, SessionBudget, SessionTimeout  # noqa: E402
from apex_voice.providers import (  # noqa: E402
    DEFAULT_ENGINE,
    EngineFlags,
    VoiceEngine,
    resolve_engine,
)

VOICES = Path(os.environ.get("APEX_VOICE_DIR", "voices"))
HAVE_EN = (VOICES / "en_US-ljspeech-medium.onnx").exists()
HAVE_FR = (VOICES / "fr_FR-siwis-medium.onnx").exists()


class TestAudio:
    def test_ulaw_roundtrip_is_faithful(self):
        import numpy as np
        rng = np.random.default_rng(3)
        pcm = rng.integers(-20000, 20000, 4000, dtype=np.int16).astype("<i2").tobytes()
        decoded = ulaw_to_pcm16(pcm16_to_ulaw(pcm))
        assert len(decoded) == len(pcm)
        a = np.frombuffer(pcm, dtype="<i2").astype(int)
        b = np.frombuffer(decoded, dtype="<i2").astype(int)
        # Correlation near 1 proves the codec preserves the waveform.
        assert float(np.corrcoef(a, b)[0, 1]) > 0.99

    def test_silence_encodes_to_ulaw_silence(self):
        pcm = b"\x00\x00" * 100
        assert set(pcm16_to_ulaw(pcm)) == {0xFF}

    def test_resample_preserves_duration(self):
        pcm = b"\x00\x00" * 22050  # 1 second at 22.05 kHz
        out = pcm16_to_pcm_rate(pcm, 22050, TELEPHONY_RATE)
        assert len(out) // 2 == TELEPHONY_RATE

    def test_frames_are_20ms_and_padded(self):
        ulaw = pcm16_to_ulaw(b"\x00\x00" * 8000)  # exactly 1 second at 8 kHz
        frames = list(frame_ulaw(ulaw))
        assert len(frames) == 1000 // FRAME_MS
        assert all(len(f) == ULAW_FRAME_BYTES for f in frames)

    def test_partial_frame_is_padded_with_silence(self):
        frames = list(frame_ulaw(b"\x01" * 5))
        assert len(frames) == 1
        assert len(frames[0]) == ULAW_FRAME_BYTES
        assert frames[0][5:] == b"\xff" * (ULAW_FRAME_BYTES - 5)

    def test_media_payloads_are_valid_base64_json(self):
        ulaw = pcm16_to_ulaw(b"\x00\x00" * 800)   # 800 samples = 800 ulaw bytes
        msgs = frames_to_media_payload(ulaw, "SM_TEST")
        assert len(msgs) == 800 // ULAW_FRAME_BYTES   # 5 frames of 20 ms
        for m in msgs:
            assert m["event"] == "media"
            assert m["streamSid"] == "SM_TEST"
            base64.b64decode(m["media"]["payload"])  # must not raise

    def test_wav_header_is_wellformed(self):
        pcm = b"\x00\x00" * 100
        header = wav_header(pcm, TELEPHONY_RATE)
        assert header[:4] == b"RIFF"
        assert header[8:12] == b"WAVE"
        assert len(header) == 44

    def test_empty_input_is_safe(self):
        assert pcm16_to_ulaw(b"") == b""
        assert ulaw_to_pcm16(b"") == b""
        assert pcm16_to_pcm_rate(b"", 22050, 8000) == b""


class TestProviders:
    def test_default_is_legacy(self):
        assert resolve_engine("any", env={}) == DEFAULT_ENGINE
        assert DEFAULT_ENGINE == VoiceEngine.LEGACY

    def test_unknown_engine_falls_back(self):
        assert resolve_engine("t", env={"APEX_VOICE_ENGINE": "gemini_liv"}) == VoiceEngine.LEGACY

    def test_disabled_engine_is_never_selected(self):
        env = {"APEX_VOICE_ENGINE": "gemini_live", "APEX_VOICE_ENABLED_ENGINES": "legacy"}
        assert resolve_engine("t", env=env) == VoiceEngine.LEGACY

    def test_enabled_engine_is_selected(self):
        env = {"APEX_VOICE_ENGINE": "local", "APEX_VOICE_ENABLED_ENGINES": "legacy,local"}
        assert resolve_engine("t", env=env) == VoiceEngine.LOCAL

    def test_per_tenant_override_wins(self):
        env = {
            "APEX_VOICE_ENGINE": "legacy",
            "APEX_VOICE_ENABLED_ENGINES": "legacy,local",
            "APEX_VOICE_TENANT_ACME": "local",
        }
        assert resolve_engine("acme", env=env) == VoiceEngine.LOCAL
        assert resolve_engine("other", env=env) == VoiceEngine.LEGACY

    def test_canary_is_stable_per_tenant(self):
        env = {
            "APEX_VOICE_ENGINE": "legacy",
            "APEX_VOICE_ENABLED_ENGINES": "legacy,local",
            "APEX_VOICE_CANARY_PERCENT": "50",
            "APEX_VOICE_CANARY_ENGINE": "local",
        }
        picks = {resolve_engine("stable_tenant", env=env) for _ in range(20)}
        assert len(picks) == 1

    def test_empty_allowlist_does_not_crash(self):
        env = {"APEX_VOICE_ENGINE": "gemini_live", "APEX_VOICE_ENABLED_ENGINES": "bogus"}
        assert resolve_engine("t", env=env) == VoiceEngine.LEGACY

    def test_canary_out_of_range_is_clamped(self):
        flags = EngineFlags.from_env({"APEX_VOICE_CANARY_PERCENT": "900"})
        assert flags.canary_percent == 100
        flags = EngineFlags.from_env({"APEX_VOICE_CANARY_PERCENT": "-5"})
        assert flags.canary_percent == 0


class TestBudget:
    def test_turn_cap_enforced(self):
        b = SessionBudget(max_turns=2)
        b.begin_turn()
        b.begin_turn()
        with pytest.raises(BudgetExceeded):
            b.begin_turn()

    def test_dollar_cap_enforced(self):
        b = SessionBudget(max_usd=0.01)
        b.spent_usd = 0.01
        with pytest.raises(BudgetExceeded):
            b.check_can_start_turn()

    def test_duration_cap_enforced(self):
        b = SessionBudget(max_duration_sec=0)
        with pytest.raises(SessionTimeout):
            b.check_can_start_turn()

    def test_token_costing(self):
        b = SessionBudget()
        b.note_tokens(1_000_000, 12.0)
        assert b.spent_usd == pytest.approx(12.0)

    def test_first_audio_timeout(self):
        b = SessionBudget(first_audio_timeout_sec=0.01)
        import time
        start = time.monotonic() - 1
        with pytest.raises(SessionTimeout):
            b.check_audio_timeouts(start)


@pytest.mark.skipif(not HAVE_EN, reason="English voice model not present")
class TestPiper:
    def _tts(self, cache=None):
        from apex_voice.piper_tts import PiperTTS, PiperVoice
        return PiperTTS(
            voices={"en": PiperVoice("en",
                VOICES / "en_US-ljspeech-medium.onnx",
                VOICES / "en_US-ljspeech-medium.onnx.json", "en_US", "public-domain")},
            max_concurrency=2, cache_dir=cache,
        )

    def test_synthesis_produces_audio(self):
        tts = self._tts()
        pcm = asyncio.run(tts.synthesize("Hello there.", "en", "t1"))
        assert len(pcm) > 1000
        assert len(pcm) % 2 == 0

    def test_synthesis_converts_to_telephony(self):
        tts = self._tts()
        pcm = asyncio.run(tts.synthesize("Hello there.", "en", "t1"))
        ulaw = piper_wav_to_ulaw_8k(pcm)
        expected = round(len(pcm) / 2 * TELEPHONY_RATE / 22050)
        assert abs(len(ulaw) - expected) <= 2

    def test_unclassified_licence_is_refused(self):
        from apex_voice.piper_tts import PiperTTS, PiperVoice, VoiceNotCommercial
        tts = PiperTTS(voices={"x": PiperVoice("x",
            VOICES / "en_US-ljspeech-medium.onnx",
            VOICES / "en_US-ljspeech-medium.onnx.json", "en_US", "unknown-licence")})
        with pytest.raises(VoiceNotCommercial):
            asyncio.run(tts.synthesize("hi", "x", "t1"))

    def test_unknown_voice_is_refused(self):
        from apex_voice.piper_tts import TTSUnavailable
        tts = self._tts()
        with pytest.raises(TTSUnavailable):
            asyncio.run(tts.synthesize("hi", "nope", "t1"))


class TestCacheKeys:
    def test_keys_separate_every_field(self):
        from apex_voice.piper_tts import CacheKey, text_digest
        d = text_digest("hello")
        base = CacheKey("t1", "piper", "m", "v", 22050, "pcm", d)
        variants = [
            CacheKey("t2", "piper", "m", "v", 22050, "pcm", d),
            CacheKey("t1", "gemini", "m", "v", 22050, "pcm", d),
            CacheKey("t1", "piper", "m2", "v", 22050, "pcm", d),
            CacheKey("t1", "piper", "m", "v2", 22050, "pcm", d),
            CacheKey("t1", "piper", "m", "v", 8000, "pcm", d),
            CacheKey("t1", "piper", "m", "v", 22050, "ulaw", d),
            CacheKey("t1", "piper", "m", "v", 22050, "pcm", text_digest("other")),
        ]
        digests = {base.digest()} | {v.digest() for v in variants}
        assert len(digests) == len(variants) + 1

    def test_tenant_speech_not_cached_by_default(self):
        from apex_voice.piper_tts import PiperTTS
        tts = PiperTTS(voices={}, cache_dir=None)
        assert tts._cache_tenant_speech is False


@pytest.mark.skipif(not HAVE_EN, reason="English voice model not present")
class TestSession:
    def _session(self):
        from apex_voice.piper_tts import PiperTTS, PiperVoice
        from apex_voice.session import VoiceSession
        tts = PiperTTS(voices={"en": PiperVoice("en",
            VOICES / "en_US-ljspeech-medium.onnx",
            VOICES / "en_US-ljspeech-medium.onnx.json", "en_US", "public-domain")})
        return VoiceSession("tenant_x", tts=tts, env={"APEX_VOICE_ENGINE": "legacy"})

    def test_say_returns_ulaw_audio(self):
        s = self._session()
        r = asyncio.run(s.say("Hello and welcome.", "en"))
        assert len(r.audio_ulaw) > 0
        assert r.first_audio_ms is not None

    def test_cancellation_returns_no_audio(self):
        s = self._session()
        s.cancel()
        r = asyncio.run(s.say("This should not be spoken.", "en"))
        assert r.audio_ulaw == b""

    def test_interruption_speaks_only_the_remainder(self):
        s = self._session()
        full = asyncio.run(s.say("I can book you in for Tuesday at two thirty.", "en"))
        part = asyncio.run(s.say("I can book you in for Tuesday at two thirty.", "en",
                                 already_played_seconds=1.0))
        assert len(part.audio_ulaw) < len(full.audio_ulaw)
        assert part.replayed_full_response is False


@pytest.mark.skipif(not HAVE_EN, reason="English voice model not present")
class TestSerializer:
    def test_deserializes_media_to_input_frame(self):
        pytest.importorskip("pipecat")
        from pipecat.audio import g711
        from apex_voice.serializers.signalwire import SignalWireFrameSerializer
        import numpy as np

        s = SignalWireFrameSerializer(stream_sid="SM1")
        pcm = (np.sin(np.linspace(0, 3.14, 160) * 10) * 3000).astype("<i2").tobytes()
        msg = json.dumps({"event": "media", "streamSid": "SM1",
                          "media": {"payload": base64.b64encode(g711.pcm_to_ulaw(pcm)).decode()}})
        frame = asyncio.run(s.deserialize(msg))
        assert frame is not None
        assert frame.sample_rate == 8000

    def test_declares_8khz(self):
        pytest.importorskip("pipecat")
        from apex_voice.serializers.signalwire import SignalWireFrameSerializer
        s = SignalWireFrameSerializer(stream_sid="SM1")
        assert s.audio_in_sample_rate == 8000
        assert s.audio_out_sample_rate == 8000

    def test_bad_payload_does_not_raise(self):
        pytest.importorskip("pipecat")
        from apex_voice.serializers.signalwire import SignalWireFrameSerializer
        s = SignalWireFrameSerializer(stream_sid="SM1")
        assert asyncio.run(s.deserialize("not json")) is None
        assert asyncio.run(s.deserialize(json.dumps({"event": "media",
                                                     "media": {"payload": "@@@"}}))) is None


class TestCostModel:
    def test_target_claim_is_infeasible_without_compression(self):
        """The $0.022 CAD/min claim must not be reproducible on unpressed context."""
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
        import cost_model as cm

        naive = cm.scenario(
            "naive", cm.RATES["signalwire_pstn_in_per_min"], False, True, 2, 3, 8
        )
        assert naive["per_minute"]["cad"] > 0.022

    def test_local_only_has_zero_marginal_cost(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
        import cost_model as cm
        local = cm.scenario("local", 0.0, False, True, 5, 3, 8,
                            context_compression=True)
        # Audio in and out are both local, so only text tokens remain, and they
        # dominate nothing. Voice cost itself is zero.
        assert local["breakdown_per_call_usd"]["gemini_audio_out"] == 0.0
        assert local["breakdown_per_call_usd"]["transport"] == 0.0
