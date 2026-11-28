# ApexVoice voice quality evaluation protocol

Status: Protocol only. No voice engine is changed by this document, and no candidate replaces the current production engine until it passes this rubric on the integrated staging application and Josh approves the switch.

## Candidates

From the Phase 3 voice registry (voice/cost_model.json, checked 2026-11-28), plus two candidates not in the registry.

| Candidate | Path | Synthesis cost, CAD per call minute | Status of the cost figure |
|---|---|---|---|
| ElevenLabs Turbo, voice Rachel | Direct API, current production engine | $0.1040 | Credit-effective rate from the Phase 2 audit; billing track unverified, see the billing verification plan |
| ElevenLabs Flash | Direct API | $0.0520 | Same credit basis as Turbo |
| SignalWire Say, Economy+ neural | Carrier synthesis | $0.0185 | Confirmed list price; the Phase 3 standard tier |
| Google Cloud TTS Neural2 | Direct API | $0.0092 | Confirmed list price |
| Amazon Polly Neural | Direct API | $0.0092 | Confirmed list price |
| Azure Speech Neural | Direct API | $0.0087 | Confirmed list price |
| Piper | Self-hosted | $0.0023 | Estimate, amortized infrastructure allowance, not a price |
| Kokoro | Self-hosted | $0.0029 | Estimate, amortized infrastructure allowance, not a price |
| Cartesia Sonic | Through SignalWire Say, Standard tier at $0.0001 per character | $0.0578 | Confirmed SignalWire tier list price |
| Gemini Live | Google real-time voice API | Not stated | Not in the Phase 3 cost model and no verified price is on record. Cost must be researched and recorded before this candidate can pass; do not quote a figure until then |

Synthesis cost uses the Phase 3 model: 425 spoken characters per call minute, 1 USD = 1.36 CAD. Full per-minute totals hold the other lines (transport, language model, recognition allowance) at the audited $0.031 CAD, which gives $0.135 for the current ElevenLabs Turbo setup and $0.0495 for the SignalWire Say standard tier.

Integration status differs by candidate and is part of the evaluation: ElevenLabs direct is integrated today. SignalWire Say is a backend change described in the Phase 3 voice work. Piper and Kokoro are self-hosted renders evaluated offline first. Gemini Live is a different interaction model (streaming audio in and out, replacing the gather and synthesize loop rather than only the synthesizer), so it is evaluated as a platform candidate, not a drop-in voice, and its recognition and transport costs would need their own verification before any comparison is final.

## Fixed test scripts

Every candidate renders or speaks exactly these scripts, unchanged, including punctuation. The harness records the exact character count of each script as rendered.

### Script 1: Greeting and disclosure

"Thank you for calling Harbour & Main. This is Harper, an AI receptionist for Harbour & Main. This call is transcribed so we can help you accurately. How can I help you today?"

Purpose: the disclosure wording must be complete and intelligible. Any swallowed or garbled word in the disclosure is an automatic fail for that sample regardless of other scores.

### Script 2: Booking request with dates and times

"I can take an appointment request for you. I have noted a website consultation with Sarah Thompson on Tuesday, January 12 at 10:30 in the morning, and a follow-up call on Friday, January 15 at 2:45 in the afternoon. Nothing is booked yet. Harbour & Main will call you back at 519-555-0142 to confirm. Is that number correct?"

Purpose: dates, times, a name, and a phone number spoken digit by digit in context. Scorers mark any date, time, or digit error as a pronunciation and accuracy defect.

### Script 3: Canadian names and place names

"Thank you, Mrs. Beaulieu. I have noted that you are calling from Amherstburg, and that your brother Luc Tremblay lives in LaSalle, near Windsor. We also take messages for customers in Tecumseh, Chatham-Kent, Leamington, and Kingsville. Did I say Amherstburg correctly?"

Purpose: Essex County and Ontario place names, plus French Canadian surnames, are the names this service will actually say. Scorers with local knowledge mark mispronunciations individually; each name is scored separately, not as an overall impression.

### Script 4: French segment

Receptionist, in French: "Merci d'avoir appelé Harbour & Main. Je suis Harper, une réceptionniste automatisée. Cet appel est transcrit afin de mieux vous servir. Comment puis-je vous aider aujourd'hui?"

Caller, in French: "Bonjour, je m'appelle Marie-Claire Dubois. Je voudrais laisser un message au sujet d'un site web pour ma boulangerie à LaSalle. Vous pouvez me rappeler au 519-555-0173, le matin de préférence."

Expected receptionist behaviour, in French: take the message, collect the same four fields as the English message flow, read the callback number back, and confirm that Harbour & Main will call back. If the candidate cannot operate in French, it must say so in French and offer the message flow in English, and must not invent French business content.

Purpose: French greeting quality, French comprehension of the caller's message, correct handling of the French name and the callback number, and graceful behaviour from candidates with weak French. Context from the Phase 2 privacy analysis: Quebec is excluded from the initial service area, so French is scored for information and for Ontario francophone callers, and is not by itself a launch gate unless the service area changes.

### Script 5: Numbers and prices spoken aloud

"To confirm the details: the invoice total is one thousand four hundred fifty dollars, the deposit is seven hundred twenty-five dollars, and the balance of seven hundred twenty-five dollars is due in fifteen days. Your confirmation number is 8 4 1 6. The office opens at 9:00 and closes at 5:00, and your appointment window is between 12:30 and 1:15."

Purpose: money amounts, a digit string, and times. Note for scorers: these figures are test content only, spoken to test number handling. They are not Harbour & Main prices and must never appear in a live configuration.

### Script 6: Interruption test

The receptionist begins a long answer: "Our website design service covers the full process of planning, designing, and building a website for a local small business, including the pages most businesses need, such as a home page, a services page, an about page, and a contact page, and it also includes..."

At the marked point, the caller interrupts: "Sorry, stop, I only need to leave a message."

Expected behaviour: the receptionist stops within a short overlap, acknowledges briefly, and moves to the message flow without repeating the long answer or showing confusion. For offline renders that cannot be interrupted, this script is run live in the staging harness only, and the render is scored on the long answer alone with the interruption dimension marked not applicable.

### Script 7: Noisy line simulation

Run Scripts 1 and 4 over a degraded channel: in the staging harness, play the caller side through a band-limited, low volume feed with background noise (a recording of a worksite or a busy kitchen at moderate volume) mixed under the caller's speech. For offline synthesis candidates, this script tests the recognition side only where the candidate includes recognition (Gemini Live), and is otherwise marked not applicable rather than scored zero.

Expected behaviour: the receptionist asks the caller to repeat a detail it could not hear, rather than guessing it, and never records a guessed callback number.

### Script 8: Standard passage for cost and consistency checks

A single passage of about 3,000 characters, used by the billing verification plan (call B series) and for spotting consistency problems across a long render. The passage is the concatenation of Scripts 1, 2, 3, and 5, followed by Script 6's long answer, repeated as needed to reach the target length. The harness records the exact character count as rendered, and that count, not the target, is what cost checks use.

## Scoring rubric

Each dimension is scored 1 to 5 by each scorer, independently, before any discussion. Anchors:

* Naturalness. 5: indistinguishable in rhythm and emphasis from a careful human reader for most listeners. 4: clearly synthetic on attention, but pleasant and never distracting. 3: understandable throughout, with robotic passages. 2: frequently robotic or oddly emphasized, tiring to listen to. 1: distracting or unpleasant throughout.
* Pronunciation. Scored from the defect list, not impression: count mispronounced or garbled items in Scripts 2, 3, and 5 (each name, place, date, time, amount, and digit string is one item). 5: zero defects. 4: one defect, not in the disclosure or a callback number. 3: two defects, or one in a callback number that the flow's read-back would catch. 2: three or four defects. 1: five or more, or any garbled word in the Script 1 disclosure (also an automatic sample fail).
* Canadian English fit. 5: local place names and surnames handled the way a Windsor-Essex local says them, Canadian spelling forms irrelevant to audio but Canadian phrasing natural. 3: mostly fine with noticeable American or British renderings of local names. 1: local names unrecognizable.
* French handling. 5: greeting natural, caller message understood, fields collected, number read back correctly, all in French. 4: minor accent or phrasing issues, task completed. 3: task completed with noticeable strain, or a clean, honest fallback to English offered in French. 2: partial task completion. 1: French attempted and wrong, or French input ignored. Not applicable is recorded for candidates evaluated only as English synthesizers, with the reason noted.
* Interruption behaviour. 5: stops almost immediately, acknowledges, follows the new direction. 3: stops after a noticeable overlap or needs the caller to repeat the interruption. 1: talks over the caller or ignores the interruption. Live harness only; renders mark not applicable.
* Response latency. Measured, not impression scored. Two measurements per script in the harness: synthesis latency, from the timestamp the synthesis request is issued to the timestamp the first audio is available; and end-to-end turn latency, from the timestamp the caller stops speaking (voice activity detection endpoint) to the timestamp response audio starts playing. Report median and 95th percentile across the script set. Bands: median end-to-end under 800 milliseconds is excellent, under 1,500 acceptable for a phone receptionist, over 2,500 is a fail for live use regardless of other scores. Offline renders report synthesis latency only.
* Reliability. Percentage of scripts completed without an error, a timeout, a truncated render, or a dropped call, across at least three runs of the full set. 100 percent over three runs is required for a pass; any disclosure script failure counts double.
* Cost per minute. Taken from the table above and, after the billing verification exercise, from measured figures. Not scored 1 to 5; reported beside the scores so quality is never traded against an unstated price.

## Pass bar for replacing or adding a production voice

A candidate passes only if all of the following hold, on the integrated staging application, not on renders alone:

* No dimension averages below 3 across scorers, and naturalness and pronunciation average at least 4.
* Zero disclosure defects in Script 1 across all runs.
* Median end-to-end turn latency under 1,500 milliseconds in the staging harness, with no script set run over 2,500.
* Reliability at 100 percent over three full runs.
* A verified cost figure is on record for the candidate, from the cost model or the billing verification results.
* Josh approves the switch in writing. Until then, the current ElevenLabs engine remains the production and pilot voice, including in the pilot configuration.

## Blind scoring procedure

* Samples are labelled with random two-letter codes. The mapping from code to provider is held by whoever prepares the samples and is not shared with scorers until scores are submitted.
* All candidates render the same scripts with the same text. Where a candidate has multiple voices, the single closest match to the current production voice's profile (adult, warm, professional, Canadian or neutral English) is used, and the voice identifier is recorded in the sealed mapping.
* Samples are loudness matched as closely as the tooling allows, presented in a different random order per scorer, and scored on the rubric sheet with defect lists, not just totals.
* Scorers: at minimum Josh and one other listener familiar with the local place names. Scores are submitted independently, then compared. Disagreements of two points or more on any dimension are re-listened to together and the defect list decides.
* French samples are scored by a French-speaking scorer for the French dimensions. If no French-speaking scorer is available, the French dimensions are recorded as unscored rather than guessed.

## Coordination with the Oracle research agent

Ask the Oracle research agent to run the self-hosted side of this evaluation on the Oracle box, where a self-hosted stack would actually live:

* Install or use the existing Piper and Kokoro setups on the Oracle box and render Scripts 1, 2, 3, 5, and the Script 8 passage, with the closest available voices to the production profile. Record the exact model and voice identifiers, the box specifications, and per-script render timings (request to completed audio) so synthesis latency is comparable.
* Return the audio files and a timing sheet, labelled by script number only. The files are then code-labelled and mixed into the blind set by whoever prepares the samples, so self-hosted candidates are scored blind like the hosted ones.
* Note in the return: any voice that had to be substituted, any script that failed to render, and the observed resource use. The Phase 3 cost model already records the Oracle Always Free warnings (idle reclamation, no SLA, capacity limits), and those warnings are part of the reliability assessment for any self-hosted candidate: a self-hosted voice that the box cannot guarantee to keep running cannot be the only voice path, and any self-hosted pass still requires a hosted fallback in the selection configuration.
* Gemini Live and Cartesia are not part of the Oracle ask. Gemini Live needs a separate harness evaluation because it changes the interaction model, and Cartesia through SignalWire is rendered through the carrier path in staging.

## Records

Keep with the evaluation: the sealed code mapping (opened after scoring), each scorer's sheet with defect lists, the latency measurements per script per candidate, the reliability run log, the final comparison table with measured costs, and the decision record. If no candidate passes, that is a valid outcome and the current engine stays.
