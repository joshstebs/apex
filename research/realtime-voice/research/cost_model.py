#!/usr/bin/env python3
"""ApexVoice V2 cost model.

Every rate below is a published figure with its source and read date. The point of
this script is that the $0.022 CAD/minute claim is arithmetic, so it is computed
rather than asserted.

Sources (read 2026-11-28):
  Gemini Live audio in  $3.00 / 1M tokens, 25 tokens per second of audio
                        (ai.google.dev/gemini-api/docs/pricing)
  Gemini Live audio out $12.00 / 1M tokens, same 25 tokens/sec
  Gemini Live text out  $4.50 / 1M tokens
  SignalWire PSTN inbound (10DLC) $0.0066 / min
  SignalWire SIP/WebRTC leg       $0.0030 / min
  SignalWire AI Agent Runtime     $0.16 / min (bundled STT+LLM+TTS, for comparison)
  Bank of Canada USD/CAD          1.4243 (2026-11-26)
"""
from __future__ import annotations

import json

USD_CAD = 1.4243
TOKENS_PER_SEC_AUDIO = 25

RATES = {
    "gemini_audio_in_per_1m": 3.00,
    "gemini_audio_out_per_1m": 12.00,
    "gemini_text_out_per_1m": 4.50,
    "signalwire_pstn_in_per_min": 0.0066,
    "signalwire_sip_per_min": 0.0030,
    "signalwire_ai_runtime_per_min": 0.16,
    "piper_local_per_min": 0.0,
    "oracle_arm_compute_per_min": 0.0,
}


def audio_tokens(seconds: float) -> float:
    return seconds * TOKENS_PER_SEC_AUDIO


def per_min(cost_usd: float) -> dict:
    return {"usd": round(cost_usd, 5), "cad": round(cost_usd * USD_CAD, 5)}


def scenario(
    name: str,
    transport_per_min: float,
    gemini_speaks: bool,
    local_tts: bool,
    call_minutes: float,
    turns_per_min: float,
    output_seconds_per_turn: float,
    text_tokens_per_turn: int = 40,
    context_compression: bool = False,
) -> dict:
    """Model one call, including the context re-billing that Gemini Live incurs.

    Gemini Live re-sends accumulated context on every turn, so input tokens grow
    with call length. That term is the one a naive per-minute calculation omits.
    """
    # Audio input: the caller's speech is re-sent as context on later turns.
    # First turn sees 60s of their audio; growth is linear, so the mean over the
    # call is half the accumulated total at the end.
    if context_compression:
        # Compression keeps a bounded recent window; assume ~60s of retained audio.
        effective_input_seconds = call_minutes * 60
    else:
        mean_accumulated = (call_minutes * 60) / 2
        effective_input_seconds = call_minutes * 60 + turns_per_min * call_minutes * mean_accumulated
    in_cost = audio_tokens(effective_input_seconds) / 1_000_000 * RATES["gemini_audio_in_per_1m"]

    # Audio output only if Gemini is the voice; local Piper replaces it.
    out_seconds = turns_per_min * call_minutes * output_seconds_per_turn
    out_cost = 0.0
    if gemini_speaks and not local_tts:
        out_cost = audio_tokens(out_seconds) / 1_000_000 * RATES["gemini_audio_out_per_1m"]

    text_cost = (turns_per_min * call_minutes * text_tokens_per_turn) / 1_000_000 * RATES["gemini_text_out_per_1m"]
    transport = transport_per_min * call_minutes
    total = transport + in_cost + out_cost + text_cost

    return {
        "scenario": name,
        "call_minutes": call_minutes,
        "turns_per_min": turns_per_min,
        "context_compression": context_compression,
        "per_call": {"usd": round(total, 5), "cad": round(total * USD_CAD, 5)},
        "per_minute": per_min(total / call_minutes),
        "breakdown_per_call_usd": {
            "transport": round(transport, 5),
            "gemini_audio_in": round(in_cost, 5),
            "gemini_audio_out": round(out_cost, 5),
            "gemini_text_out": round(text_cost, 5),
        },
    }


def main() -> None:
    target_cad = 0.022
    results = {
        "exchange_rate_usd_cad": USD_CAD,
        "target_claim_cad_per_min": target_cad,
        "target_claim_usd_per_min": round(target_cad / USD_CAD, 5),
        "scenarios": [
            scenario("A: Gemini native audio both ways, PSTN inbound, 2 min call",
                     RATES["signalwire_pstn_in_per_min"], True, False, 2, 3, 8),
            scenario("B: Gemini native audio both ways, PSTN inbound, 5 min call",
                     RATES["signalwire_pstn_in_per_min"], True, False, 5, 3, 8),
            scenario("C: Gemini audio in + local Piper out, PSTN inbound, 2 min",
                     RATES["signalwire_pstn_in_per_min"], False, True, 2, 3, 8),
            scenario("D: Gemini audio in + local Piper out, PSTN inbound, 5 min",
                     RATES["signalwire_pstn_in_per_min"], False, True, 5, 3, 8),
            scenario("E: Gemini audio in + local Piper out, SIP leg, 2 min",
                     RATES["signalwire_sip_per_min"], False, True, 2, 3, 8),
            scenario("F: as E with context compression, 5 min",
                     RATES["signalwire_sip_per_min"], False, True, 5, 3, 8, context_compression=True),
            scenario("G: as C with context compression, 5 min PSTN",
                     RATES["signalwire_pstn_in_per_min"], False, True, 5, 3, 8, context_compression=True),
        ],
        "comparisons": {
            "signalwire_ai_runtime_all_in": {
                "usd_per_min": RATES["signalwire_ai_runtime_per_min"],
                "cad_per_min": round(RATES["signalwire_ai_runtime_per_min"] * USD_CAD, 4),
                "note": "vendor-quoted $0.163-0.168/min all-in on their own page",
            },
            "fully_local_piper_plus_self_hosted_llm": {
                "cad_per_min": 0.0,
                "note": "zero marginal voice cost on Oracle Free Tier; only transport applies",
            },
        },
    }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
