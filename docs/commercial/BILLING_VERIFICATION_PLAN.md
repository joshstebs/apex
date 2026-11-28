# ApexVoice billing verification plan

Status: PREPARATION ONLY. No traffic in this plan runs without Josh's explicit approval. This plan prepares a minimal-cost exercise to replace the two unverified cost items in TELEPHONY_COST_VERIFICATION.md with measured facts. Preparing the plan costs nothing and places no calls.

## What this exercise must settle

* The Gather speech recognition billing unit. SignalWire lists Speech-to-Text at $0.015 USD per 15 seconds per use, but how a Gather interaction maps to uses and segments is not published. This is the largest open cost question: the worst case adds roughly $0.075 CAD per call minute over the modelled allowance.
* The ElevenLabs billing track for the ApexVoice account: subscription credit-effective cost (modelled at $0.18 USD per 1,000 characters for Turbo) versus the direct API list track ($0.04 USD per 1,000 characters published for Flash and Turbo). The invoice and usage records decide which is real for this account.
* Confirmation that the confirmed list prices behave as expected for transport, transfers, and recording, and that failed or repeated webhook deliveries cost nothing.

All prices below are the verified list prices from TELEPHONY_COST_VERIFICATION.md (SignalWire official pricing page, Canada, checked 2026-11-28), in USD. CAD figures use the cost model rate of 1 USD = 1.36 CAD. Actual exchange and any taxes or account fees are part of what the reconciliation records.

## Test traffic matrix

Thirteen calls in five groups. Every call is capped at 5 minutes by the pilot limits. Calls run under the controlled live test plan's Stage 1 discipline: named testers only, pilot number only, usage checked after the session.

### Group A: Gather isolation, 6 calls

Prompts are spoken with SignalWire Say Economy+ so the synthesis cost is known and small. The tester varies the number and length of spoken answers, which are the Gather inputs. Everything else is held as constant as practical.

| Call | Gather count | Utterance lengths | Approx. call length |
|---|---|---|---|
| A1 | 1 | one 5 second answer | 1 minute |
| A2 | 1 | one 30 second answer | 1.5 minutes |
| A3 | 1 | one 60 second answer | 2 minutes |
| A4 | 4 | four 10 second answers | 2 minutes |
| A5 | 8 | eight 10 second answers | 3 minutes |
| A6 | 8 | eight 30 second answers | 5 minutes |

How this isolates the unit: if billing is per use with a one segment minimum, A1 and A2 cost the same for recognition despite a sixfold difference in answer length, and A4 costs about four times A1. If billing is per 15 second segment of recognized speech, A2 costs about twice A1, A3 about four times A1, and A6 is the most expensive call in the group. The pattern across six calls distinguishes the models, including mixed models such as per use plus per segment beyond the first.

Expected maximum cost, Group A:

* Transport: 15 minutes total at $0.0066 = $0.099.
* Recognition, worst case per segment: segments per call, rounding each utterance up to whole 15 second segments, are 1, 2, 4, 4, 8, and 16, totalling 35 segments at $0.015 = $0.525. (The per use model would cost 23 uses at $0.015 = $0.345, so the segment model is the binding worst case.)
* Say Economy+ synthesis: about 2,000 characters of prompts per call, 12,000 characters at $0.000032 = $0.384.
* Group A maximum: $1.01.

### Group B: TTS isolation, 3 calls

Each call synthesizes one fixed 3,000 character passage (the standard passage from the voice quality evaluation scripts) through a different path, with one short Gather answer so the calls resemble real traffic.

| Call | Synthesis path | Rate per character | Synthesis cost |
|---|---|---|---|
| B1 | SignalWire Say Economy (Polly standard class) | $0.000008 | $0.024 |
| B2 | SignalWire Say Standard (ElevenLabs Turbo served through SignalWire) | $0.0001 | $0.300 |
| B3 | ElevenLabs direct, current production path | $0.00018 credit-effective, or $0.00004 on the direct API list track | $0.540 at the higher track |

Expected maximum cost, Group B:

* Synthesis: $0.024 + $0.300 + $0.540 = $0.864, budgeting B3 at the higher credit-effective track. If the account is really on the direct API track, B3 costs $0.120 and the group total drops accordingly, which is itself one of the findings.
* Transport: 3 calls at about 2 minutes, 6 minutes at $0.0066 = $0.040.
* Recognition: one short answer per call, budgeted at 2 segments per call, 6 segments at $0.015 = $0.090.
* Group B maximum: $0.99.

Note on ElevenLabs subscriptions: a subscription bills credits monthly rather than per call, so B3 may appear as credit consumption in the ElevenLabs usage records rather than a discrete charge. The reconciliation reads credit consumption for the test window and values it both ways, which is what identifies the track.

### Group C: transfer, 1 call

One call that asks for a person and is transferred to the Harbour & Main main line, matching scenario S9 of the controlled live test plan.

* SIP Refer: $0.100.
* Outbound transfer leg: about 2 minutes at $0.0080 = $0.016.
* Inbound leg: about 3 minutes at $0.0066 = $0.020.
* Group C maximum: $0.14.

### Group D: recording, 1 call

One call with call recording switched on for this call only, with the disclosure wording adjusted for that call and Josh's approval for the recording test specifically. Recording is off by default and stays off outside this call.

* Recording: about 3 minutes at $0.002 per minute = $0.006.
* Transport: 3 minutes at $0.0066 = $0.020.
* Recognition: budgeted at 4 segments at $0.015 = $0.060.
* Group D maximum: $0.09.

Recording transcription: NOT APPLICABLE today. TELEPHONY_COST_VERIFICATION.md records, code-verified, that ApexVoice makes no recording transcription API call, so there is nothing to test. If a future change enables it, the listed price is $0.020 per 15 seconds and a new test group and approval are required before any traffic.

### Group E: failed and repeated requests, 2 calls

Two calls that are abandoned during setup, plus deliberate duplicate delivery of the resulting webhook events in staging tooling.

* Expected telephony cost: $0 beyond minimal transport for the abandoned setups. Budgeted at 2 minutes total at $0.0066 = $0.02.
* Expected webhook cost: $0. Webhook deliveries are not a billed SignalWire item on the pricing page. The reconciliation verifies that no charge line appears for them and that duplicate deliveries create no duplicate records or charges in the app.

### Telephone number rental

No new number is required. The exercise uses the existing Harbour & Main number, whose rental is already being paid and is a known $0.50 USD per month at list. Incremental cost: $0. If Josh instead approves a dedicated pilot number, its $0.50 USD monthly rental counts inside the same cap below. Port-in is listed as free, and no porting is part of this exercise.

## Total expected maximum and hard cap

| Group | Expected maximum, USD |
|---|---|
| A, Gather isolation | $1.01 |
| B, TTS isolation | $0.99 |
| C, transfer | $0.14 |
| D, recording | $0.09 |
| E, failed and repeated | $0.02 |
| Subtotal | $2.25 |
| Contingency at 25 percent for taxes, fees, rounding, and timing differences | $0.56 |
| Expected maximum total | $2.81 USD, about $3.82 CAD |

Hard cap: the exercise stops the moment total observed spend across SignalWire and ElevenLabs for the pilot reaches $5.00 CAD (about $3.68 USD at the model rate), the same cap as the pilot configuration. An optional new pilot number at $0.50 USD would bring the expected maximum to about $3.31 USD (about $4.50 CAD), still inside the cap, but the cap does not move. Observed spend is checked after every session, not at the end, and the controlled live test plan's stop conditions apply throughout: any unexpected charge pattern halts everything.

## Per-call records to capture

For every call in the matrix, record all of the following. A call without a complete record does not count toward the matrix and may need to be repeated inside the cap.

* Call SID, and the transfer leg SID where applicable.
* From and to numbers, and the tenant the call routed to.
* Start and end timestamps, app-recorded duration in seconds, and the provider billed duration for the same SID.
* Gather count for the call, and the duration in seconds of each individual utterance (from application logs of gather start and result times).
* Synthesis path and tier for every spoken response, and the exact character count synthesized per call per path.
* Recording on or off for the call, and recording duration if on.
* Transfer attempted or not, refer result, and outbound leg duration.
* Webhook deliveries for the call, including any duplicates, with delivery timestamps.
* The app's usage record for the call (minutes after per-call rounding, TTS characters, STT seconds as recorded by the app).

## Reconciliation procedure

* SignalWire side: read the per-call usage records in the SignalWire project for the test window, and the itemized invoice or usage export for the same period. Match each matrix call by SID. Extract, per call, the transport charge, any speech-to-text line, any text-to-speech line, any recording line, and any refer charge, exactly as the provider labels them.
* ElevenLabs side: read the account usage history for the test window. Record credits consumed by the B3 call window and any API charges, and note which of the two published tracks the consumption matches.
* App side: pull the tenancy call and usage records for the pilot tenant for the same window. Use the billing package's reconcile_usage to compare the app's metered totals against the provider totals and report drift per call and in total.
* Analysis: regress the Group A recognition charges against the two candidate models (per use, per segment) and against mixed models. Six calls with deliberately different gather counts and utterance lengths make the models predict visibly different totals, so the matching model should be identifiable from charges alone. Record the residuals for each model, not just the winner.
* Write-back: record the conclusion, with the evidence table, in an update to TELEPHONY_COST_VERIFICATION.md moving Gather billing and the ElevenLabs track from unverified to measured, and add the measured rates to voice/cost_model.json as a new measured entry alongside the list prices. If the measured Gather cost changes the per-minute totals, update PRICING_AND_PROFITABILITY.md margins and the voice cost optimization figures in the same change, and flag the change to Josh explicitly, because the standard tier's under $0.07 CAD claim depends on it.
* Report: a short results memo listing, per charge type, the list price, the measured price, and the variance, plus the final per-minute cost for the standard and premium voice tiers using measured figures only.

## What this plan does not do

* It places no calls and incurs no charges. Approval from Josh is required before any group runs, and Group D needs its own specific approval because it turns recording on for one call.
* It does not test toll-free rates, outbound calling (disabled in code), CNAM or number lookup (not used), or high-throughput call-per-second tiers (not needed at pilot scale).
* It does not settle taxes or account-specific discounts beyond observing them on the invoice if they appear.
