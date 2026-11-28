# ApexVoice Commercial Release Gates

The rule, stated once and applied to every gate below: a feature is not production ready merely because its isolated unit tests pass. Isolated unit tests are supporting evidence only. A gate is satisfied only by evidence produced by the integrated staging application, meaning the real backend with the tenancy, voice, and billing packages wired in, running in the container deployment, exercised through its real HTTP and telephony surfaces with the mock provider or with explicitly approved test traffic.

Current status, stated plainly: every gate below is UNPROVEN at staging level. The integrated application does not exist yet, because the backend integration patch has not been applied. Package level results (176 Phase 3 tests, 45 Phase 4 integration tests, 34 browser checks) are real but they are not staging evidence, and RELEASE_STATUS.md on main continues to say NOT production ready. PR #12's qa/production-evidence.json agrees: its seven categories (credential_history, webhook_controls, model_boundaries, emergency_handoff, customer_data, provider_readiness, oracle_soak) are all currently blocked.

Owners: Josh decides and approves. Edison owns the commercial layer evidence (contracts, packages, browser checks, billing reconciliation). Command Code owns backend and staging evidence (the integrated build, the qa harness, provider behaviour).

## Gate 1, backend reliability

- Criterion: the integrated service handles calls and API traffic without the known reliability defects: no duplicate TTS charges, no leaked database connections, no runaway calls, and a call duration limit that does not depend solely on a 60 second in container enforcement cycle.
- Staging evidence required: the qa harness offline call suite passing against the integrated build; a soak run in staging (the oracle_soak category) with repeated simulated calls and zero duplicate clip charges, zero connection errors, and every call terminating inside its limit; deployment logs from the container showing clean startup and the watchdog firing on an over long simulated call.
- Partial evidence that exists: PR #12's qa harness and production_gate.py define the checks; main already carries the duplicate TTS charge fix and the SQLite lifecycle fix. None of it has run against an integrated multi tenant build.
- Status: unproven. Owner: Command Code, with Josh approving any live provider validation.

## Gate 2, multi tenant isolation in the integrated application

- Criterion: in the running application, no tenant can read, list, update, or delete another tenant's configuration, calls, messages, appointments, transcripts, customers, or usage, by direct identifier, list query, forged update, or session misuse, and telephony routing never serves one tenant's configuration on another tenant's number.
- Staging evidence required: PR #12's qa/test_tenant_contract.py running unskipped against staging and passing, including the 401, 403, and identical code 404 rules; the Phase 3 isolation suites passing against the integrated store; a staging exercise with two test tenants and two test DIDs where simultaneous calls stay on their own configurations, locks, and usage ledgers.
- Partial evidence that exists: 82 tenancy tests including the isolation suite on both store implementations, and 45 Phase 4 integration tests simulating the journey and the contract rules at package level. All package level; the HTTP fixture is still pending, which is exactly why the qa contract test still skips.
- Status: unproven. Owner: Edison for package evidence, Command Code for the fixture and staging run.

## Gate 3, live telephone verification

- Criterion: a real inbound call to a real ApexVoice number is answered with the correct tenant's greeting and configuration, takes a message, records usage, and ends cleanly, on the production carrier path.
- Staging evidence required: this gate cannot be satisfied in staging alone; it requires a controlled live pilot on the Harbour & Main tenant with Josh's explicit approval, following the controlled live test plan: inbound call, business questions, message taking, appointment request, interruption, silence, incorrect caller information, human handoff attempt, emergency request handling, and clean termination, each with the call record, transcript, and usage entry inspected afterwards. Provider outage behaviour is verified by the mock provider in staging, not by waiting for a real outage.
- Partial evidence that exists: none at live level. RELEASE_STATUS.md records that live provider validation has never been executed. The pilot configuration and test plan are prepared in Phase 4; live calling stays disabled (RECEPTIONIST_ENABLED=false, outbound disabled) until Josh approves.
- Status: unproven, and blocked on an explicit approval that has not been given. Owner: Josh approves, Command Code executes the backend side, Edison verifies records and usage.

## Gate 4, accurate billing

- Criterion: what a tenant is charged matches what the tenant used, on real provider and payment records, not on application estimates: metered minutes equal billed minutes, overage is priced at the tier rate, a failed payment moves the tenant to past due without cutting service inside the grace period, and recovery restores active status.
- Staging evidence required: a full test mode Stripe cycle against the integrated staging application using signed webhook deliveries to the real endpoint: checkout completion activating a test tenant, invoice paid, invoice payment failed moving to past due, grace expiry flagging suspension for a human, and invoice paid recovering to active; plus a reconciliation report comparing UsageMeter totals against the billing summary for the same test period with zero unexplained drift. Separately, the billing verification plan's minimal live traffic (separately approved) reconciles SignalWire and ElevenLabs invoice lines against recorded usage, which is the only way to close the Gather speech billing question and the ElevenLabs rate track question.
- Partial evidence that exists: the billing package's 56 tests, webhook signature verification, and the Phase 4 journey test that runs the full state machine arc against signed test events at package level. No webhook has yet been delivered to a running application, and no invoice has ever been reconciled.
- Status: unproven. Owner: Edison for reconciliation evidence, Command Code for the endpoint wiring, Josh for any live traffic approval and for price approval before test mode could ever change.

## Gate 5, secure authentication

- Criterion: customer sessions in the integrated application are issued, expire, and revoke as contracted; operator tokens never function as customer credentials; no credential material from the project's history grants access.
- Staging evidence required: the contract tests' 401 and 403 cases passing over real HTTP against staging; a staging check that the shared admin token is rejected on customer routes and accepted only on operator routes; session expiry and logout revocation demonstrated against the running application; and the credential_history category in production-evidence.json cleared, meaning any credential that ever appeared in git history or logs has been rotated and the rotation verified.
- Partial evidence that exists: the tenancy auth package (PBKDF2 hashing, hashed opaque session tokens, 12 hour expiry, revocation, identical failure messages) with its 27 auth and RBAC tests, plus package level expiry and revocation tests in the Phase 4 alignment suite. No HTTP level proof exists yet, and the credential history review belongs to PR #12's blocked categories.
- Status: unproven. Owner: Command Code for staging proof and rotations, Edison for the auth contract.

## Gate 6, customer onboarding

- Criterion: a new business can be taken from operator created tenant to a working, correctly configured receptionist using only the documented flow: tenant creation, owner login, configuration save from the onboarding frontend's BusinessConfig document, number assignment or forwarding setup, and a first test call.
- Staging evidence required: one complete onboarding run against staging using the real onboarding pages and the integrated API, ending with the tenant's configuration live (a config save invalidates the cache and the next simulated call uses the new greeting without a restart), the version conflict path exercised by saving against a stale version, and the config_not_started path exercised for a tenant that has not begun. The telephone onboarding documentation (dedicated number, conditional forwarding variants, porting) reviewed against at least one Canadian carrier's published instructions.
- Partial evidence that exists: the onboarding frontend passes 34 of 34 real browser checks, the BusinessConfig schema is frozen and validated by the package, and tenant creation plus config round trip are proven at package level in the Phase 4 journey suite. The endpoint the frontend would save to does not exist yet.
- Status: unproven. Owner: Edison for the flow and documentation, Command Code for the endpoints.

## Gate 7, mobile usability

- Criterion: the customer facing pages (onboarding, dashboard, demo, and the platform admin once integrated) are fully usable on a phone: no horizontal overflow, no page errors, every control reachable and operable, at 390 by 844, 834 by 1112, and 1440 by 900.
- Staging evidence required: the browser check suite rerun against the staging deployment of the integrated application, not the static pages: all onboarding steps completed on the mobile viewport against the live API, the dashboard rendering real staging tenant data on mobile, and screenshots captured from staging for the record.
- Partial evidence that exists: 34 of 34 browser checks with 15 screenshots against the Phase 2 pages served locally, including the full wizard, the config export download, and the demo flows. That proves the pages, not the integrated product; the dashboard's populated live data views have never rendered real API data in a browser.
- Status: unproven at staging level. Owner: Edison.

## Gate 8, privacy compliance

- Criterion: the integrated service honours the published commitments: AI disclosure at call start, recording and transcription notice, audio recording off by default, no health card or similarly sensitive data collected, caller specific text never cached or replayed, and one tenant's data never exposed to another.
- Staging evidence required: a staging call exercise (mock provider) whose transcript shows the disclosure greeting from the tenant's own configuration; the greeting notice behaviour demonstrated on a save that omits disclosure wording (warn, not block); configuration and cache inspection in staging proving the phrase cache holds only tenant authored standard phrases for that tenant; the customer_data category in production-evidence.json cleared by Command Code's review of what the integrated application stores and logs.
- Partial evidence that exists: the privacy analysis and legal drafts from Phase 2 (all still drafts requiring professional legal review), the cache refusal rules with tests, and the greeting notice shaping in the package. Legal review itself is outstanding and is Josh's to commission; no staging run has demonstrated the disclosure path end to end.
- Status: unproven. Owner: Edison for product behaviour, Josh for legal review, Command Code for the customer_data evidence category.

## Gate 9, data retention

- Criterion: retention limits are enforced by the running system, not just described: Redis transcripts expire within 24 hours, recordings follow their stated retention, and an operator can delete a tenant's data completely, with the deletion auditable afterwards.
- Staging evidence required: a staging tenant populated with calls, transcripts, messages, and clips, then deleted through the lifecycle path, with post deletion queries proving no config, records, cache entries, clips, or number mapping remain, and the audit entry for the deletion still readable; a transcript ageing check in staging showing expiry at the configured limit; the operator deletion control that RELEASE_STATUS.md notes is missing, demonstrated working.
- Partial evidence that exists: the lifecycle purge is proven at package level (deleting tenant A removes everything it owns while tenant B stays intact and the audit entry survives). The integrated gaps are real: Redis transcript retention and operator deletion controls are backend concerns that do not exist yet, and clip storage becomes tenant addressed only at patch step 4.
- Status: unproven. Owner: Command Code for backend retention mechanics, Edison for the lifecycle contract.

## Gate 10, incident recovery

- Criterion: the service recovers from the failures it is most likely to meet: provider outage, Redis unavailability, container restart, and a bad configuration save, without losing tenant data or serving the wrong tenant.
- Staging evidence required: staging drills with recorded results: kill and restart the container mid call and show clean recovery; make Redis unavailable and show the contracted 503 behaviour rather than a crash or a fallback to another tenant's data; exercise the mock provider outage path and show the fallback voice chain engaging; roll back the integration flag (TENANCY_ENABLED off) and show the legacy single tenant path serving ten_harbour_main unchanged. A written incident report from at least one drill, filed with the operational documentation.
- Partial evidence that exists: the voice fallback chains are defined and tested at package level, the flag based rollback is designed into every patch step, and the support and incident documentation is prepared in Phase 4. No drill has been run; there is no integrated staging to drill against.
- Status: unproven. Owner: Command Code for drills, Edison for documentation and verification.

## Gate 11, spending controls

- Criterion: no tenant and no failure mode can run up unbounded provider cost: per tenant included minute hard stops hold in the integrated application, the platform budget ceiling still applies, staging cannot spend real money by accident, and transfer and overage costs are metered per tenant.
- Staging evidence required: a staging tenant driven past its included minutes against the integrated build, with admission refused at the limit while a second tenant continues unaffected; the platform ceiling demonstrated with the staging $0 budget and mock provider configuration confirmed in writing by Command Code; per tenant usage and estimated cost visible in the platform admin populated from real staging records; transfer events appearing in a tenant's usage once transfers exist.
- Partial evidence that exists: the per tenant hard stop is proven at package level (the Phase 4 journey suite exhausts a starter tenant and shows admission refused while another tenant keeps its full allowance), and staging's $0 budget with the mock provider is main's current safety state. The integrated demonstration has not happened, and transfer metering is not yet in the usage rates.
- Status: unproven. Owner: Edison for metering evidence, Command Code for the platform ceiling and staging configuration.

## How gates get cleared

- Evidence is collected per gate against a named staging build (commit recorded with the evidence), and the result is written into this document and, where a category matches, into PR #12's production-evidence.json by its owner.
- A gate with any required evidence missing stays unproven. Partial evidence is recorded as partial, never rounded up.
- All eleven gates must be cleared, or explicitly waived in writing by Josh with the risk stated, before the first external paying tenant is onboarded. The Harbour & Main pilot (Gate 3) additionally requires Josh's explicit approval for live calling, separate from any gate waiver.
