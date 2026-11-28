# ApexVoice Phase 4: final report

Prepared 2026-11-28. This branch (feature/apex-phase4-operations) is stacked on feature/apex-phase3-multitenant (PR #9) and its PR targets that branch. Nothing was merged, no conflicting backend files were modified, live calling stays disabled, Stripe stays in test mode, and no carrier settings, numbers, or website content were changed. The only modifications to earlier-phase files are additive changes to four tenancy package files, listed under gap closure below; everything else is new.

## Repository audit and merge order

State verified against GitHub on 2026-11-28 before any Phase 4 work:

* main is at d4349605, four commits past the base PR #7 and PR #9 were stacked on. Command Code's work landed there: container hosting (Dockerfile, Render config, Oracle plus Cloudflare Tunnel deployment docs), the duplicate TTS charge fix (clip IDs derived from a voice plus text hash), the in-container call duration watchdog, and the SQLite connection lifecycle fix.
* PR #12 (feature/apex-security-qa, Command Code) is an open, mergeable draft adding a qa/ harness: offline call tests, a production readiness gate whose evidence file lists all seven categories as blocked, and an HTTP tenancy contract test that currently skips because the integrated tenant fixture is pending.
* PR #7 and PR #9 remain conflict free against current main: every file still shows as an addition.
* RELEASE_STATUS.md on main still says not production ready: live provider validation never executed, no deployment provisioned yet, billing reconciliation is application estimates only, Redis transcripts held up to 24 hours with no operator deletion control, human handoff and booking unimplemented beyond message capture. Safety state: RECEPTIONIST_ENABLED=false, outbound disabled in code, staging forces a $0 budget and the mock provider.

Merge order (full reasoning in integration/INTEGRATION_AND_MERGE_PLAN.md):

* Command Code finishes and merges PR #12 first. It blocks nothing and nothing blocks it.
* Then PR #7 merges to main, then PR #9 retargeted to main, then this Phase 4 branch.
* Then Command Code, as backend owner, applies the backend integration patch on current main in its own reviewed PRs, following the patch spec's seven steps as updated in the plan for container hosting and the clip ID change, each step with verification and rollback.
* Then the qa tenant fixture lands so PR #12's skipped contract tests actually run, and staging evidence collection begins against the release gates.
* Route decision: adopt PR #12's HTTP surface (/api/tenants/{id}/config, /usage, /calls, /messages, /appointments, /subscription) with the tenancy package unchanged underneath. The Phase 2 contract froze the same surface and the Phase 2 frontend never calls tenant routes directly, so adoption costs nothing.

One drift warning for Command Code, recorded in the plan: main's new clip IDs hash voice plus text without the tenant. Once calls are tenant scoped, clip storage keys must use the per-tenant clip key builders from the tenancy routing module, otherwise two tenants share clip object names and tenant purge correctness breaks. The content would be identical, so it is a deletion hygiene issue, not a content leak.

## Integration tests

* tests at the repository root: test_integration_journey.py and test_integration_contract_alignment.py, 45 tests, all passing against the packages in this stack.
* The journey suite runs the complete flow on both store implementations: platform creation from an onboarding BusinessConfig, owner login, config round trip, DID routing with unknown number rejection, call admission while a second tenant is suspended, plan limit hard stop, per-tenant usage metering, the billing arc through signature-verified webhook events (active, past due on failure, duplicate delivery as a no-op, recovery on payment, grace expiry flagging suspension without billing suspending anyone), tampered signature rejection, reconciliation agreeing exactly between tenancy metering and billing summary, premium versus standard voice selection, and phrase cache behaviour including refusal of caller-specific text.
* The alignment suite maps every PR #12 contract route to what the packages prove today, marking each assertion package-proven, HTTP-only, or gap. It proves no HTTP behaviour; that remains for the integrated fixture.

## Gap closure in this branch

The integration review found package level gaps between PR #12's contract and the Phase 3 packages. The ones closable without touching backend files were closed here, with the alignment tests updated in the same change:

* shape_subscription added (status none for tenants without a subscription; billing period bounds are honest nulls until the billing package stores them).
* version_conflict and config_not_started error classes added. The remaining four contract codes are transport level (malformed_json, rate_limited, provider_error, service_unavailable) and stay owned by the HTTP adapter by design.
* shape_usage emits periodEnd and whole minute integers.
* CallRecord gained ended_at, shape_call emits endedAt, and shape_call_detail combines a call with its transcript turns and an explicit recording object.
* MessageRecord gained a delivery field, emitted by shape_message.
* shape_tenant phone entries carry a distinct num_ identifier.
* Still open by decision, pinned as known gaps in the tests: the contract document's tenant_ prefix wording versus the implemented ten_ prefix, and tenant creation starting active rather than trial. Both need a one-line decision with Command Code at integration.

## Platform administration

* ops/ package: aggregation producing the platform overview (tenants by status, plan and subscription state, assigned numbers, onboarding completeness by section presence, current and historical usage, estimated operating cost per tenant using the voice cost model, revenue and contribution estimates, spending versus plan limit and cap, failed call counts and error rates computed only from supplied call records, active calls, provider health, support block, audit access), and actions (create, suspend, reactivate, delete, set spending cap) that require a PlatformOperator principal, require a reason for suspend and delete, require an explicit confirm for delete, and write an audit entry for every action.
* Data minimization is enforced by construction: the overview builder never reads transcript, message, appointment, or customer records. A test plants the Phase 3 fixtures' content strings and asserts none appear in the serialized overview.
* Provider health is an input registry, not a measurement: every provider (signalwire, elevenlabs, llm, redis, stripe) reports unknown with no timestamp until a real probe result is recorded. Failed call metrics report an explicit no-data state when no records are supplied, and active calls report unknown rather than a fabricated zero when no registry is injected.
* static/platform-admin.html: the operator dashboard, verified in real Chromium at desktop and mobile widths with no page errors and no horizontal overflow (screenshots in docs/commercial/browser-tests/). It keeps the operator token in tab memory only and renders honest empty and error states.
* Named gaps for backend integration (in PLATFORM_ADMIN.md): billing subscription records have no store yet, tenant spending caps are an in-memory ops registry until the backend persists them, there is no support record kind in the tenancy store, and there is no active call registry. Each is handled by injection today.

## Telephone number onboarding

Research from official carrier sources, checked 2026-11-28, in docs/commercial/CARRIER_COMPATIBILITY.md, with customer instructions in TELEPHONE_ONBOARDING.md (paths: dedicated ApexVoice number, call forwarding in its four variants, number porting, and human transfer behaviour) and the internal NUMBER_ONBOARDING_CHECKLIST.md.

* Verified: SignalWire Canada DID $0.50 USD per month, port-in free, Canadian ports up to two weeks with a Letter of Authorization dated within 30 days; CRTC porting rules; Bell Local Link and Total Connect star codes for all-calls, busy, and no-answer forwarding; Rogers business phone provisioning requirements, the full Rogers Mobility GSM code table, RingCentral, Vonage, Ooma, VoIP.ms, and Fongo forwarding behaviour.
* Findings that change the product recommendation: TELUS traditional landline conditional forwarding could not be verified from official sources (the official article's detail table was not readable), so TELUS landline customers must not be sold a self-serve staff-first setup until that is closed on a live line. Rogers Mobility and Rogers IBLc make conditional forwarding incompatible with carrier voicemail, which must be disclosed at intake. Bell Mobility pay-per-use forwarding at $0.25 per minute can exceed product margin. Traditional landlines from all three major carriers have no clock-based forwarding, so conditional forwarding all day is the honest default and automatic after-hours schedules are a hosted-system feature.
* Nothing was purchased, ported, or changed on any carrier account.

## Support and operational readiness

* support/ package: tenant-scoped support tickets with escalation audit trails (platform sees all, a tenant sees only its own), pure notification payload builders for the Harbour & Main email infrastructure (provider outage with per-incident deduplication, failed call alerts, 80 and 100 percent usage warnings firing once per period, monthly summaries, payment failure notices reflecting the 7 day grace policy) with nothing sent and a documented approval step before any wiring to the real sender, monthly summary generation from usage records, and data export plus config backup built from field allowlists. Export tests plant a real password hash, a plaintext password, and a session token hash in fixtures and assert none appear in the export.
* SUPPORT_AND_OPERATIONS.md: the operating manual with the notification map, incident template and severities, recovery procedures (provider outage, Redis loss including the orphaned call lock check, config corruption, accidental suspension), troubleshooting, and the cancellation and data deletion procedure ending in the tenancy lifecycle purge.
* Retention figures in the export module are the Phase 2 analysis recommendations pending legal review, recorded as such, not adopted policy.

## Harbour & Main pilot preparation

* pilots/harbour_main_pilot.json: the pilot BusinessConfig built only from verified facts (Harbour & Main, josh@harbourandmain.com, (548) 561-0651 as transfer target, website design and AI receptionist services in general terms, AI disclosure and transcription notice in the greeting, 911 direction, four message fields with read-back, never-guess fallback, request-only booking), with pilot limits of a 5 minute maximum call and a $5 CAD spending cap. A test asserts the website pricing figures appear nowhere in the config.
* Not invented, listed as to-confirm in the pilot document: business hours (the config carries the migration module's conservative placeholder, flagged inside the config itself as PLACEHOLDER, NOT VERIFIED, and the hours FAQ never states them), after-hours specifics, transfer availability hours, pilot dates and named testers, pilot number choice (the existing number versus a new dedicated one, which is a purchase needing approval), the receptionist name, and confirmation that recording stays off.
* CONTROLLED_LIVE_TEST_PLAN.md: Stage 0 on the mock provider at $0, Stage 1 named testers only with written approval per stage and RECEPTIONIST_ENABLED off for the public, 14 scenarios covering every case in the request (interruptions, silence, incorrect caller information, human handoff, emergency direction to 911, provider outage at staging level, call termination, usage recording accuracy), each with pass criteria and evidence, plus seven stop conditions including unexpected charges, disclosure failure, and any cross-tenant data appearance.

## Billing verification plan

BILLING_VERIFICATION_PLAN.md prepares the minimal exercise that settles the two open cost questions from Phase 3 (Gather speech billing unit, ElevenLabs rate track). Thirteen calls in five groups isolating transport, Gather recognition (varying utterance counts and lengths to reveal the billing unit), TTS through SignalWire tiers and ElevenLabs direct, one SIP Refer transfer, and one recorded call, with the exact per-call fields to record and the reconciliation procedure against SignalWire usage records and the ElevenLabs usage page. Expected maximum $2.81 USD (about $3.82 CAD) including 25 percent contingency; hard cap $5.00 CAD total observed spend, checked after every session, the same cap as the pilot. Recording transcription is marked not applicable because the code makes no transcription call. No traffic runs without Josh's explicit approval.

## Voice quality evaluation

VOICE_QUALITY_EVALUATION.md defines the standardized comparison: ten candidates (the eight Phase 3 registry providers with computed costs, Cartesia through the SignalWire Standard tier, and Gemini Live, whose cost is explicitly unstated because no verified price is on record and must be researched before it can pass), eight written test scripts including Canadian place names (Windsor, Amherstburg, LaSalle, Tecumseh, Chatham-Kent) and a French segment, an anchored scoring rubric for naturalness, pronunciation, Canadian English, French, interruption behaviour, measured latency, reliability, and cost, blind scoring by sample code, and the coordination ask for the Oracle research agent (Piper and Kokoro renders of the same scripts with timings). No production voice switch until an alternative passes on the integrated staging application with Josh's written approval.

## Commercial release gates

integration/RELEASE_GATES.md defines eleven gates (backend reliability, integrated multi-tenant isolation, live telephone verification, accurate billing, secure authentication, customer onboarding, mobile usability, privacy compliance, data retention, incident recovery, spending controls), each with its criterion, the staging evidence required, the existing artifacts that supply partial evidence (including PR #12's seven blocked production-evidence categories), its current status, and its owner. All eleven are currently unproven at staging level because the integrated application does not exist yet, and the document states the rule plainly: isolated unit tests alone never satisfy a gate.

## Test results

* Full suite on this branch: 298 tests, all passing (176 from Phases 2 and 3, 45 integration, 30 platform ops, 47 support and pilot).
* Platform admin page browser check: loads at desktop 1440 by 900 and mobile 390 by 844 in real Chromium, no page errors, no horizontal overflow, screenshots in docs/commercial/browser-tests/.

## Remaining blockers

* Command Code's backend work (PR #12) must finish and merge before the commercial stack can follow it into main, and the backend integration patch remains Command Code's to apply. Until then the integrated application does not exist and every release gate stays unproven at staging level.
* Deployment: no host provisioned yet per RELEASE_STATUS (Docker image unbuilt in that environment, Oracle SSH and Render account actions outstanding). That is a Josh and backend decision, not a code gap.
* Live provider verification has never been executed. The billing verification plan and the controlled live test plan are prepared and capped, and both wait on Josh's explicit approval before any billable traffic.
* TELUS landline conditional forwarding is unverified and gates one onboarding path for TELUS customers.
* Decisions for Josh at integration time: tenant creation starting in trial versus active, the contract document's tenant_ prefix wording, the pilot to-confirm list (hours first), pricing approval, and legal review of the Phase 2 drafts plus retention recommendations.
