# Voice cost optimization for ApexVoice

Prepared 2026-11-28. Companion code: voice/providers.py, voice/selection.py, voice/cache.py, voice/cost_model.json. Tests: test_voice_providers.py and test_voice_cache.py, 27 tests, all passing.

## The problem in one paragraph

The Phase 2 audit modelled ApexVoice at $0.135 CAD per call minute, with about $0.104 CAD of that being ElevenLabs speech on eleven_turbo_v2_5. Speech synthesis is the only cost line big enough to matter. Transport is about $0.009 CAD per minute, the language model about $0.007 CAD per minute, and the remaining $0.015 CAD is a speech recognition and platform allowance that is still unverified. Cut synthesis and the whole service gets cheap. Everything in this document follows from that.

## Modelling rules

- Spoken characters per call minute: 425, carried over from the Phase 2 audit. Providers bill for characters the receptionist speaks, not for silence or caller speech.
- FX: 1 USD = 1.36 CAD, same as the audit.
- Other lines per call minute, held constant across providers so the comparison isolates speech: SignalWire inbound transport $0.0090 CAD (confirmed list, $0.0066 USD), language model $0.0068 CAD (audit estimate), speech recognition and platform allowance $0.0152 CAD (audit residual, unverified).
- Fixed cost per tenant: $7 CAD per month (number rental plus hosting, Redis and support share), the assumption that reproduces the Phase 2 Starter and Professional margins.
- Confirmed list price means a published vendor rate checked on 2026-11-28. Estimate means a modelled figure. The two are never mixed in one cell without a label.

## Comparison table

Costs are CAD per call minute at 425 spoken characters, synthesis only, then total with the other lines above.

| Provider | Kind | Rate, USD per 1,000 chars | Rate status | Synthesis CAD/min | Total CAD/min | Streaming | Licence |
|---|---|---|---|---|---|---|---|
| SignalWire Say, Economy+ voice (Amazon Neural or Google Neural2 class) | Carrier | $0.032 | Confirmed list | $0.0185 | $0.0495 | Carrier rendered in the call | Carrier terms |
| ElevenLabs Turbo v2.5 (current default, Rachel) | Hosted | $0.18 effective | Subscription credit effective rate, see note | $0.1040 | $0.1350 | Yes, websocket | Commercial from Starter plan |
| ElevenLabs Flash v2.5 | Hosted | $0.09 effective | Subscription credit effective rate, see note | $0.0520 | $0.0830 | Yes, websocket, fastest model | Commercial from Starter plan |
| Azure Speech, Neural voices | Hosted | $0.015 | Confirmed list | $0.0087 | $0.0396 | Yes | Azure terms |
| Google Cloud TTS, Neural2 | Hosted | $0.016 | Confirmed list | $0.0092 | $0.0402 | Yes | Google Cloud terms |
| Amazon Polly, Neural | Hosted | $0.016 | Confirmed list | $0.0092 | $0.0402 | Yes | AWS terms |
| Kokoro-82M, self-hosted | Self-hosted | $0.005 allowance | Estimate, infra amortization | $0.0029 | $0.0339 | Yes, via Kokoro-FastAPI | Apache 2.0, model and weights |
| Piper, self-hosted | Self-hosted | $0.004 allowance | Estimate, infra amortization | $0.0023 | $0.0333 | Sentence level in this design | Engine and voice licences vary, see below |

Worked example, standard tier: 425 chars x $0.032 per 1,000 chars = $0.0136 USD per call minute, x 1.36 = $0.0185 CAD, plus $0.0310 CAD of other lines = $0.0495 CAD per call minute. That is 37 percent of the current $0.135 CAD.

### The ElevenLabs rate note, read this before quoting premium costs

ElevenLabs sells the same models on two tracks. On subscription plans, Turbo burns 1 credit per character and Flash burns 0.5 credits per character, and credits across the Creator and Pro tiers work out to roughly $0.17 to $0.20 per 1,000 credits. That credit basis is what the Phase 2 audit used, and this model keeps it so the premium tier reconciles with the audit to within $0.001 CAD per minute (test_premium_tier_reproduces_the_audit). Separately, ElevenLabs publishes a direct API pay as you go list of $0.04 per 1,000 characters for both Flash and Turbo, checked 2026-11-28. On that track the premium total would be about $0.054 CAD per call minute, not $0.135 CAD. Which track the ApexVoice account is actually billed on is unverified. Confirm it on a real invoice before restating premium pricing or signing a customer on premium margins. Either way, ElevenLabs stays the most natural voice in the table and the right premium tier. The open question is only what it costs.

### SignalWire native text to speech

SignalWire publishes four per-character tiers, checked 2026-11-28: Economy at $0.000008 per character (Amazon Polly Standard, Google Standard and WaveNet, legacy Azure Standard), Economy+ at $0.000032 (Amazon Neural, Amazon Generative, Google Neural2), Standard at $0.0001 (Azure Neural, ElevenLabs Flash, Turbo and v3 Conversational, several others), and Premium and Pro above that (Google Chirp 3 HD, Azure Neural HD, ElevenLabs Multilingual v2 and v3). Two consequences:

- The standard tier in this design uses an Economy+ voice rendered by the carrier with the same Say mechanism ApexVoice already falls back to in degraded mode. No new vendor account, no audio files to host, no extra network round trip, and nothing to cache or expire.
- Routing ElevenLabs through SignalWire at the Standard tier rate ($0.10 per 1,000 chars) is more expensive than ElevenLabs direct on either track for Turbo, so there is no saving in buying ElevenLabs through the carrier. The carrier is the cheap path only for carrier voices.

### Naturalness, latency and fit, qualitative

These are vendor positioning and architecture facts, not measured scores. No listening test was run for this work, and no MOS figure is quoted because none was verified.

- ElevenLabs Turbo and Flash: positioned as the most natural and expressive in this set, with voice cloning and the current Rachel voice callers already hear. Flash is the vendor's low latency model, published at about 75 ms model latency, and is positioned slightly below Turbo on expressiveness for long passages. For short receptionist replies the difference is small, which is why Flash is the premium fallback rather than a downgrade path callers would notice.
- Azure Neural, Google Neural2, Polly Neural: the mature cloud neural tier. Natural, even, professional voices, a clear step below ElevenLabs on expressiveness and a clear step above the older Standard and WaveNet voices. All three stream, all three offer Canadian or North American regions, and Azure publishes under 300 ms response for its standard voices. For a receptionist that mostly reads greetings, questions and confirmations, this tier is the value sweet spot.
- SignalWire Economy+ voices are these same Amazon Neural and Google Neural2 voice families rendered by the carrier, so standard tier naturalness is the cloud neural tier, not a robotic fallback. Economy tier voices (Polly Standard, Google Standard) are noticeably flatter and are not recommended as a primary caller voice.
- Kokoro: the strongest self-hosted option. An 82M parameter model, Apache 2.0, repeatedly reported faster than realtime on plain CPU (about 2.5x realtime through the Kokoro-FastAPI CPU build in third party testing). Preset voices only, no cloning, English voices strongest. Naturalness sits close to the cloud neural tier for short replies in published comparisons, but that is community reporting, not a measurement made here.
- Piper: fastest and smallest, about 63 MB per voice, runs on almost anything. Naturalness is a step below Kokoro. In this design Piper is a last-resort self-hosted fallback, not a primary voice.

## Caching repeated phrases

A receptionist repeats itself on every call: greeting, AI disclosure, hold and transfer lines, closing, after-hours greeting, and a short list of FAQ answers. voice/cache.py caches the rendered audio for exactly those phrase kinds, keyed by a hash of tenant, provider, voice, model and text, with a 7 day TTL, entry and character caps, and hit and miss statistics.

Two hard rules, both enforced in code and covered by tests:

- Caller-specific and sensitive text is never cached. Message, transcript, appointment and caller-specific kinds are refused by kind, and text containing phone-like digit runs, email addresses, postal codes or street addresses is refused on content under any kind. A cache that replayed one caller's details to the next caller would be a privacy failure, not an optimization.
- Keys are tenant-scoped. Identical text for two businesses is two entries, and a lookup for one tenant can never return the other tenant's audio. clear_tenant removes a tenant's phrases on suspension or deletion.

Modelled impact, assumption stated: a typical 3 minute call speaks about 1,275 characters. The greeting (about 110 characters) and the disclosure (about 190 characters) occur on every call, which is about 24 percent of spoken characters. Hold, transfer and closing lines plus repeat FAQ answers add a modelled 5 to 10 points on the calls that use them. This design models a 30 percent repeatable share, range 25 to 35 percent. That figure is derived from the phrase inventory, not measured from production transcripts, because no production call volume exists yet to measure. Measure it from real transcripts before using it in a customer-facing claim.

Cache savings at the 30 percent modelled share, synthesis lines only:

| Tier | Total CAD/min, no cache | Total CAD/min, 30 percent cached | Saving |
|---|---|---|---|
| Standard (SignalWire Say) | $0.0495 | $0.0439 if phrases are played from cache | $0.0055 |
| Premium (ElevenLabs Turbo) | $0.1350 | $0.1038 | $0.0312 |

One architectural caveat that decides whether the standard row is real: a carrier Say rendering cannot reuse cached audio. The cache pays off when audio is played back, which is how ApexVoice already serves hosted clips. So the standard tier gets the cache benefit only for its standard phrases, pre-rendered once per tenant through a hosted or self-hosted provider and played, while live replies use carrier speech. The premium tier, which is already play-based, gets the full benefit with no new architecture. Treat the uncached standard figure as the planning number and the cached figure as upside.

## Self-hosting on Oracle, the reality check

Josh's Oracle tenancy already runs other bots, and the Always Free Ampere A1 allowance is shared across everything in the tenancy. Current Oracle documentation, checked 2026-11-28, gives pure Free Tier tenancies the first 1,500 OCPU hours and 9,000 GB hours per month free, equivalent to a 2 OCPU and 12 GB instance always on, while Pay As You Go tenancies get the first 3,000 OCPU hours and 18,000 GB hours free, equivalent to 4 OCPU and 24 GB. Block storage is 200 GB and outbound transfer 10 TB per month, both far beyond what speech audio needs. Oracle's own pages and console have disagreed about the A1 allowance during 2026 and enforcement has been inconsistent, so verify the tenancy type and the current limit in the OCI console before building on either figure.

What that buys: Kokoro needs roughly 1 to 2 GB of RAM and runs faster than realtime on 1 to 2 A1 cores for short replies, so a speech sidecar fits comfortably inside even the smaller allowance alongside the existing bots. Piper needs far less. Marginal billed cost inside the allowance is zero, which is why the cost model carries self-hosted speech as a small amortization allowance ($0.005 and $0.004 USD per 1,000 chars) for operations time, monitoring, storage and overflow headroom instead of pretending it is free to run.

What it does not buy:

- No SLA. Always Free instances can be reclaimed when Oracle judges them idle, and A1 capacity is frequently unavailable in busy regions. A phone service cannot have a reclaimable box as a single point of failure, which is why self-hosted speech sits behind hosted fallbacks in every chain in voice/selection.py.
- Not unlimited. Past the free allowance, A1 compute bills per OCPU hour and GB hour at published PAYG rates, and a second region or a bigger shape is simply a paid instance.
- Operations time is a real cost. Patching, model updates, monitoring and on-call for a speech sidecar are Harbour & Main labour, and at low call volume the hosted neural tiers at about $0.009 CAD per call minute are cheaper than the labour of running a box. Self-hosting wins on cost only at volume, or as a resilience layer.

Recommendation on self-hosting: do not launch on it. Launch standard on carrier speech, keep Kokoro as the first self-hosted candidate behind the Azure fallback once call volume justifies the operations time, and re-run this comparison with measured volume then.

## VoiceStudio fork finding

Josh's fork of debpalash/VoiceStudio was reviewed for reusable code. Findings:

- It is a desktop voice studio (Electron, formerly Tauri) for voice cloning, voice design, video dubbing, dictation, transcription and audiobooks, running locally with swappable engines and an OpenAI-compatible local API. It is a content production tool, not a telephony speech server.
- Licence: the application is AGPL-3.0, and its default engine's model weights (OmniVoice) are CC-BY-NC, which is non-commercial. Both facts independently block copying code or using the default engine in ApexVoice. Per the Phase 2 licence rule, this fork is patterns only, and no code was copied.
- Practical blocker on top of the licence: its published Docker images are linux/amd64 only, while Oracle's A1 instances are ARM, so even a sidecar deployment would need a self-build.
- Patterns worth borrowing, and already reflected in this design: a registry where each engine is a named, selectable entry; showing each engine's licence next to the engine so the choice is informed; and an OpenAI-compatible speech endpoint shape, which is the right interface for a future Kokoro sidecar (Kokoro-FastAPI already speaks it).

## Recommended two-tier design

Implemented in voice/selection.py as per-tenant configuration. One business can be premium while the next is standard, and the store tests prove neither choice leaks into the other tenant.

- Standard tier (default for new tenants): primary signalwire_say with an Economy+ neural voice, then azure_speech, google_tts, amazon_polly, kokoro_selfhost. Total $0.0495 CAD per call minute, under the $0.07 CAD target with room to spare, using the carrier path ApexVoice already has.
- Premium tier: primary elevenlabs_turbo with the tenant's chosen ElevenLabs voice, then elevenlabs_flash, azure_speech, google_tts, and carrier speech last. Total $0.1350 CAD per call minute on the audit's credit basis, or about $0.054 CAD if the account proves to be on the direct API track.
- Every chain ends at carrier speech exactly once, the path with no dependency outside the call itself. A total synthesis outage degrades the voice, it does not drop the call.
- Voice and personality settings from the Phase 2 BusinessConfig (voice.voiceId, voice.voiceLabel, voice.personality) map onto TenantVoiceConfig fields (provider, voice_id, tier), so onboarding needs no schema change. The tier itself is a billing attribute and belongs on the tenant's subscription record, not in caller-facing configuration.

Integration points for the backend agent, no shared files were modified by this work: resolve the tenant from the called number, load its TenantVoiceConfig, pass provider and voice into the existing clip creation path in place of the fixed ElevenLabs settings, use the existing carrier speech switch when the chain reaches signalwire_say, and consult the phrase cache before synthesis for the standard phrase kinds. Meter spoken characters per tenant per provider, because that is the unit every rate in this document is priced in.

## Updated margins at the Phase 2 recommended prices

Gross margin at full use of included minutes, $7 CAD fixed cost per tenant per month included. Phase 2 premium margins for comparison: Starter 52.7 percent, Professional 45.2 percent, Business 40.7 percent (the Business difference is a slightly higher support allowance in Phase 2; the method is the same).

| Plan | Price and minutes | Premium tier margin | Standard tier margin | Standard plus phrase cache margin |
|---|---|---|---|---|
| Starter | $49 CAD, 120 min | 52.6 percent | 73.6 percent | 75.0 percent |
| Professional | $99 CAD, 350 min | 45.2 percent | 75.4 percent | 77.4 percent |
| Business | $199 CAD, 800 min | 42.2 percent | 76.6 percent | 78.8 percent |

Read on the business: at Phase 2 prices, a standard tier tenant is profitable at roughly three quarters gross margin even if they use every included minute, which removes the Phase 2 pressure to police minute usage. Premium stays a paid upgrade for businesses that want the ElevenLabs voice and cloning, priced by the tier, not by hoping customers use fewer minutes. Overage rates from Phase 2 ($0.40, $0.35, $0.30 CAD per minute) remain comfortably above standard tier cost and above premium cost, so overage is safe on both tiers.

## Unverified items, flagged

- Which ElevenLabs billing track the ApexVoice account is on (subscription credits versus direct API list). This swings premium cost between $0.135 and about $0.054 CAD per call minute. Verify on an invoice.
- The speech recognition and platform allowance of $0.0152 CAD per minute is an audit residual, not a verified SignalWire Gather charge. It is held constant across providers, so it does not distort the comparison, but it does move every total.
- The 30 percent cacheable share is modelled from the phrase inventory, not measured from production transcripts.
- Self-hosted per-character figures are amortization allowances, not prices, and Kokoro and Piper speeds quoted here are third party reports, not benchmarks on Josh's A1 instance. Benchmark on the actual box before committing to self-hosted capacity numbers.
- Oracle Always Free A1 limits are stated from current documentation; the console has disagreed with the documentation in 2026, so verify in the tenancy.
- Piper voice licences: the voice repository is MIT as a whole, but individual voices derive from corpora with their own terms and some are non-commercial. Any Piper voice must be licence-checked individually before commercial use. The current Piper engine line (piper1-gpl) is GPL-3.0, while the original rhasspy/piper engine was MIT; pin the MIT engine or accept the GPL terms deliberately.
- Naturalness comparisons are qualitative vendor positioning. No listening test was run and no caller experience claim should be made to customers from this document alone. Run a blind check with real callers on the standard voice before launch.

## Sources, checked 2026-11-28

- SignalWire pricing, voice transport, number rental and text to speech tiers: https://signalwire.com/pricing
- ElevenLabs API pricing (Flash and Turbo at $0.04 per 1,000 characters, Multilingual v2 and v3 at $0.08): https://elevenlabs.io/pricing/api
- ElevenLabs plan and credit pricing: https://elevenlabs.io/pricing
- Azure Speech pricing (Neural voices at $15 per million characters): https://azure.microsoft.com/pricing/details/ai-speech/
- Google Cloud Text-to-Speech pricing (Standard and WaveNet $4, Neural2 $16, Chirp 3 HD $30, Studio $160 per million characters): https://cloud.google.com/text-to-speech/pricing
- Amazon Polly pricing (Standard $4, Neural $16, Generative $30, Long-Form $100 per million characters): https://aws.amazon.com/polly/pricing/
- Kokoro-82M, Apache 2.0, 82M parameters: https://github.com/hexgrad/kokoro
- Piper and piper-voices, engine and voice licences: https://github.com/rhasspy/piper and https://huggingface.co/rhasspy/piper-voices
- Oracle Cloud Always Free resources, Ampere A1 allowances: https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm
- VoiceStudio, AGPL-3.0, engine catalogue and model licences: https://github.com/debpalash/VoiceStudio
