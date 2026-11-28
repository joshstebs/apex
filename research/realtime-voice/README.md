# ApexVoice V2 realtime voice research

Independent verification of the Pipecat / Gemini Live / local Piper cost-reduction
research, with working prototypes benchmarked on the existing Oracle Ampere A1
instance. **Nothing here is wired into production call routing, and no live calls
were placed or answered.**

Run date: 2026-11-28. Host: `arm-free-1`, Oracle Cloud Ampere A1, 2 vCPU, 11.7 GB
RAM, 45 GB disk, ARM64, Ubuntu 26.04, Python 3.14.4.

## 1. Infrastructure available for voice

| Measure | Value |
| --- | --- |
| CPU cores | 2 (Neoverse-N1, aarch64) |
| RAM | 11.7 GB total, 3.4 GB in use by existing services, 8.3 GB available |
| Disk | 45 GB, 29 GB used (65%), 16 GB free |
| Docker | not installed on the host (container config provided, unbuilt) |
| Existing load | 5 application processes, Telegram gateway, tunnel, Ollama |

Voice work was benchmarked **while those services were running**, so the numbers
are what production would actually get, not an idle box.

## 2. Verification of the research claims

Each claim is marked verified, contradicted, or unverifiable, with the evidence.

### Gemini Live pricing and the $0.022 CAD/minute claim: **not achievable as stated**

Verified rates (Google AI pricing page, read 2026-11-28):
audio in $3.00/1M tokens, audio out $12.00/1M tokens, text out $4.50/1M tokens,
billed at 25 tokens per second of audio. Bank of Canada USD/CAD on 2026-11-26:
1.4243.

SignalWire transport (signalwire.com/pricing): PSTN inbound $0.0066/min, SIP leg
$0.0030/min, AI Agent Runtime $0.16/min.

Computed with `research/cost_model.py` (`python research/cost_model.py`):

| Scenario | CAD/minute |
| --- | --- |
| Gemini native audio in+out, PSTN, 2 min call | 0.0461 |
| Gemini native audio in+out, PSTN, 5 min call | 0.0749 |
| Gemini audio in + local Piper out, PSTN, 2 min | 0.0358 |
| Gemini audio in + local Piper out, PSTN, 5 min | 0.0646 |
| same, SIP leg, 2 min | 0.0307 |
| same, SIP leg, 5 min, context compression | 0.0115 |
| same, PSTN, 5 min, context compression | 0.0166 |
| **Target claim** | **0.0220** |

**Verdict: $0.022 CAD/min is reachable only with context compression plus a SIP
leg (0.0115) and is missed on plain PSTN at 0.0166 to 0.0646 depending on call
length.** The critical variable the claim glosses over is that Gemini Live
re-bills accumulated context each turn, so cost per minute **rises with call
length**: 2-minute calls look cheap and 5-minute calls cost roughly double.

The cheapest configuration is not Gemini at all. Fully local (Piper + a
self-hosted model) has **zero marginal voice cost**; only transport remains.

### Pipecat: **verified, with one contradiction**

- BSD-2-Clause, confirmed from the repository LICENSE file. Safe for commercial
  embedding.
- Version 1.17.0 installs cleanly on Python 3.14 ARM64.
- **Contradicted: Pipecat has no SignalWire serializer.** The 1.17 package ships
  serializers for Twilio, Telnyx, Plivo, Vonage, Genesys, Exotel and Jambonz only.
  A SignalWire serializer is therefore implemented here
  (`apex_voice/serializers/signalwire.py`), modelled on the Twilio one but using
  SignalWire's LaML REST path for hang-up. Sending a Twilio-shaped hang-up would
  fail and leave the caller connected.
- Gemini support does exist as `pipecat.services.google.gemini_live`, so Gemini
  Live can be a conversational engine rather than a TTS call, as the brief requires.

### Piper TTS: **works on ARM64; licensing is the real blocker, not performance**

- `piper-tts` 1.8.0 installs on Python 3.14 aarch64 with onnxruntime 1.32.0.
- Real synthesis measured at **RTF 0.10** (10x faster than real time).
- **The engine is GPL-3.0-or-later.** For a proprietary commercial product this is
  a licensing decision, not a technical one.
- **Separate and worse: Piper makes no licence grant over voice models.** From the
  project's own LICENSING.md: the model card `License` line covers that voice's
  *dataset only*; whether weights are a derivative work is legally unsettled; and
  their stated guidance is to take legal advice for commercial use.
- The commonly cited `en_US-lessac-medium` voice is trained on the **Blizzard 2013
  research corpus**, not a commercial licence. It should not ship commercially.
- Voices used here: English `en_US-ljspeech-medium` (**public domain** dataset),
  French `fr_FR-siwis-medium` (**CC-BY 4.0**, attribution required).

Full audit in `docs/LICENSING.md`.

### Others

- **SignalWire bidirectional Media Streams**: verified as the transport; protocol
  is the JSON `connected`/`start`/`media`/`dtmf`/`stop` envelope, 8 kHz mu-law.
- **Kokoro TTS**: not evaluated on this host. It needs a GPU or far more CPU than
  2 shared vCPUs can spare without disturbing production, and the brief forbids
  starting paid GPU instances.
- **Deepgram / Cartesia / ElevenLabs / OpenAI Realtime**: pricing pages exist but
  **no API credentials are present on this host**, so live verification was not
  possible. Not reported as verified.

## 3. What was built

```
apex_voice/
  audio.py        explicit resampling + G.711 mu-law (bit-exact via audioop-lts)
  providers.py    engine selection with feature flags, allowlist, stable canary
  budget.py       session spending caps and first-audio/chunk/total timeouts
  piper_tts.py    persistent models, bounded concurrency, licence-aware, cache keys
  session.py      one call: budget, cancellation, no-replay fallback
  serializers/signalwire.py   SignalWire Media Streams (missing from Pipecat)
  serve.py        authenticated WebSocket entrypoint
benchmarks/       cold/warm, conversation, concurrency, sample generation
research/         cost_model.py
tests/            35 automated tests
```

Weaknesses in the supplied design, and what fixed each:

- **Gemini as a TTS provider** -> engine abstraction; Gemini is `gemini_live`, a
  conversational service, and the local path is a separate modular pipeline.
- **Implicit audio formats** -> `audio.py` names every rate; the serializer
  declares 8 kHz in and out; conversion is an explicit function call.
- **Cache keys too narrow** -> `CacheKey` includes tenant, provider, model, voice,
  sample rate, format and text digest. Tested to produce distinct digests for each.
- **Caching customer speech by default** -> off by default
  (`cache_enabled_for_tenant_speech=False`).
- **Fallback replaying the whole response** -> `say(already_played_seconds=...)`
  speaks only the remainder; if audio already played the caller hears a short
  handoff line, never the full answer again. Verified in benchmark.
- **No timeouts** -> first-audio (3s), inter-chunk (2s) and total response (25s)
  all enforced in `budget.py`.
- **Cancelled streams leaking** -> cancellation returns no audio and the
  concurrency slot is released; verified (`audio_returned_bytes: 0`).
- **Unmeasured subprocess cost** -> measured below (CPU time, peak RSS).
- **Wrong-language models** -> English and French are separate models, and the
  French case is benchmarked with the French voice.
- **Piper-only fallback with no handoff** -> `SAFE_HANDOFF_LINE` covers it; a
  Piper-only pipeline with no ASR/LLM must hand off rather than guess.

## 4. Benchmark results (real, on this host, production services running)

### Piper single utterance

| Case | Median first audio | p95 | RTF | Audio |
| --- | --- | --- | --- | --- |
| Greeting | 367 ms | 373 ms | 0.103 | 3.58 s |
| Business question | 613 ms | 618 ms | 0.099 | 6.07 s |
| Appointment | 413 ms | 417 ms | 0.102 | 4.01 s |
| Message taking | 471 ms | 479 ms | 0.101 | 4.68 s |
| Long pause | 310 ms | 310 ms | 0.104 | 2.95 s |
| French | 425 ms | 441 ms | 0.102 | 4.17 s |

### Cold vs warm

Cold model load **350-400 ms**; warm synthesis ~100 ms of CPU per second of audio.
Warming both voices at startup removes the cold penalty from the first call.
Peak RSS for one voice: **274 MB**; two voices resident: **310 MB**.

### Concurrency (5 turns per session)

| Sessions | Wall | Aggregate RTF | Peak RSS | Real-time feasible |
| --- | --- | --- | --- | --- |
| 1 | 1.91 s | 0.103 | 260 MB | yes |
| 2 | 4.24 s | 0.226 | 330 MB | yes |
| 4 | 8.13 s | 0.430 | 498 MB | yes |

Four concurrent sessions still synthesise at 0.43x real time, so audio arrives
ahead of playback. **Practical capacity on 2 shared vCPUs is 4 to 6 concurrent
calls**; beyond that the first-audio budget of 3 s becomes the binding constraint.
This is TTS-only capacity: adding local ASR and an LLM on the same cores would
reduce it, which is why the recommended deployment keeps reasoning on a remote API.

### Behavioural checks

- Interruption: remainder 22,849 bytes vs 30,372 full, `replayed_full_response: false`.
- Cancellation: 0 bytes returned, cleanly flagged.
- Provider outage mid-response: handoff line used, partial flagged, no replay.
- Budget control: turns blocked after the cap, spend stops at the cap.
- Engine flags: default `legacy`; typos fall back; disabled engines never selected;
  per-tenant override honoured; canary stable per tenant.

## 5. Recommended configurations

**Standard (recommended):** Pipecat orchestrating **Gemini Live for conversation**
and **local Piper for voice output**, with context compression on. Measured cost
**0.0166 CAD/min PSTN**, **0.0115 CAD/min SIP**, versus 0.2279 CAD/min for
SignalWire's own AI runtime. Uses ~300 MB RAM and 0.1 RTF per call.

**Premium:** Gemini Live native audio both ways, no local TTS. Natural voice and
prosody, at **0.0461 to 0.0749 CAD/min**. Chosen when call quality matters more
than unit cost.

**Budget / fully local:** local ASR + remote or self-hosted LLM + Piper. Zero
marginal voice cost; only transport applies. Needs ASR added to the pipeline
before it can replace a conversational engine.

## 6. Integration instructions

Engine selection is per tenant and defaults to the existing engine, so nothing
changes until a flag is set:

```
APEX_VOICE_ENGINE=legacy                     # default, current behaviour
APEX_VOICE_ENABLED_ENGINES=legacy,local      # allowlist; authoritative
APEX_VOICE_CANARY_PERCENT=10                 # optional staged rollout
APEX_VOICE_CANARY_ENGINE=local
APEX_VOICE_TENANT_ACME=local                 # force one tenant
```

To adopt in ApexVoice:

1. Copy `apex_voice/` into the app, or install it as an internal package.
2. Choose the engine with `resolve_engine(tenant_id)` at session start; do not
   branch on provider names anywhere else.
3. Keep the existing call-duration limits, Redis ownership checks, spending
   controls, AI disclosure and verified appointment booking **in the existing
   code path**. This module supplies voice, not those guarantees.
4. Wire `SignalWireFrameSerializer` into the existing SignalWire bridge.
5. Leave `APEX_VOICE_ENABLED_ENGINES=legacy` in production until a staging call
   has been placed and reviewed.

## 7. Blockers

- **Live telephony unverified.** Only synthetic audio was tested. Whether
  SignalWire's stream behaves identically to this serializer has not been proven
  and must be tested on a staging number with a real call.
- **Piper licensing** needs a commercial decision: GPL engine plus unsettled voice
  weights. Either accept GPL, isolate Piper behind a process boundary, or choose a
  permissively licensed engine.
- **Gemini Live not exercised live**: no Gemini API key was used, so its
  latency and barge-in behaviour are unmeasured here.
- **Deepgram, Cartesia, ElevenLabs, OpenAI Realtime** unverified: no credentials.
- **Docker image not built**: Docker is not installed on this host, and installing
  it was out of scope for a zero-spend, no-disruption brief.
- **Kokoro** not evaluated: no spare GPU and no permission to start one.
