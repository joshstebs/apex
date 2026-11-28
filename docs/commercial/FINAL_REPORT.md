# ApexVoice commercial readiness: final report

Prepared 2026-11-28 on branch feature/apex-commercial-readiness, based on main at e1c55e2. This branch adds new files only. It does not modify app.py, config.py, database.py, telephony.py, voice_engine.py, api/index.py, or the existing operations page, so it cannot conflict with the backend reliability work in progress.

## Implemented

* Business onboarding: static/commercial/onboarding.html
  * Seven steps covering business and contact details, operating hours and holidays, receptionist name and greeting, services with pricing, FAQs, appointment booking preferences, call transfer and escalation rules, after-hours behaviour, message delivery preferences, voice and personality settings, and business instructions and knowledge.
  * Template picker prefills editable defaults from templates.json. Draft autosaves in the browser, validation covers required business name, email and phone, and the review step offers working Download JSON and Copy actions.
  * Honest limit stated on the page: the draft lives in the browser until the backend config endpoint exists. The emitted JSON matches the frozen BusinessConfig schema in BACKEND_CONTRACTS.md exactly.
* Customer dashboard: static/commercial/dashboard.html
  * Reads the real same-origin API: GET /api/health without a token, GET /api/dashboard and GET /api/receptionist/messages with the admin token, which stays in tab memory only and is never written to localStorage or a URL.
  * Recent calls, messages and inquiries, customers derived only from real message callback numbers, usage and estimated cost labelled as estimated application spend and not a carrier invoice, receptionist configuration and knowledge from the onboarding draft, and connection status.
  * Missed calls are derived only from real call status fields. Appointments show an honest empty state naming the missing backend endpoint. No statistics, activity, or testimonials are fabricated anywhere.
* Interactive sales demo: static/commercial/demo.html
  * Built for later embedding at harbourandmain.com/ai-receptionist. Configurable sample business from the eight templates, working rule-based conversation, booking request flow with a real downloadable .ics file, message flow matching the live message schema, emergency handling that directs to 911 with no booking, and a dashboard preview that renders only cards created in that demo session.
  * Voice preview uses the browser speech engine only when available and is labelled as a browser preview, with the live phone voice identified as different. A simulated versus live table is on the page. No fake audio controls, no testimonials, no invented statistics.
* Industry templates: prompts/templates/ plus static/commercial/templates.json
  * Eight templates in the exact Apex prompt schema: plumbing and HVAC, automotive repair, dental and medical, real estate, salon and barbershop, restaurant, professional services, and general small business.
  * Each covers greeting with AI disclosure, FAQs, message workflow, escalation rules, and after-hours behaviour. Dental and medical refuses medical advice and diagnosis and never requests health records or health card numbers. Professional services refuses legal and financial advice and includes the conflict check note. Restaurants never collect payment cards.
* Multi-business assessment: docs/commercial/MULTI_TENANT_ARCHITECTURE.md and BACKEND_CONTRACTS.md
  * Verdict: ApexVoice cannot securely serve multiple paying businesses today. Tenant isolation, individual numbers, customer authentication, role-based access, separate customer records, retention and deletion, and billing readiness are all rated Missing, with separate configurations and per-business usage rated Partial. Evidence is the single DID, env-var configuration, tables with no tenant column, one shared admin token, one global call lock, and one global budget counter.
  * The contracts freeze what the backend agent needs to build: tenant resolution from the called number, Redis key namespacing, proposed schema additions, per-tenant endpoints, session auth with owner, admin, staff and viewer roles, and a billing webhook placeholder. Nothing here activates billing.
* Pricing: docs/commercial/PRICING_AND_PROFITABILITY.md (recommendations, not approved prices)
* Privacy: docs/commercial/PRIVACY_AND_TRUST.md plus seven drafts in docs/legal-drafts/, every one headed as a draft requiring professional legal review.
* Integration review: docs/commercial/INTEGRATION_REVIEW.md for cal.diy, chatwoot, VoiceStudio, and openproject.

## Test results

* New suite test_commercial_readiness.py: 11 tests, all passing. It validates the eight prompt templates against the Apex schema and guardrails, the picker template alignment, the onboarding schema coverage, the dashboard endpoints and token handling, the demo simulation labelling and ICS generation markers, the legal draft headers, and the pricing and contract contents.
* Inline JavaScript in all three pages passes node --check.
* Local HTTP smoke test: onboarding, dashboard, demo, and templates.json all return HTTP 200.
* No external assets, no em or en dashes, and no fabricated-data phrases in any delivered file.
* Layouts are mobile-first responsive with labelled controls and visible focus states. A rendered visual check in a real browser was not run for these static pages; the pages reuse the existing operations page patterns and were verified structurally. This is a stated gap, not a hidden one.
* Existing backend test suites were not run because this branch changes no backend code and the working tree for the backend agent was left untouched.

## Pricing recommendation and estimated profitability

Base variable cost is modelled at $0.135 CAD per call minute at 1 USD = 1.36 CAD, driven mostly by ElevenLabs speech (about $0.104 CAD per minute). SignalWire transport is about $0.009 CAD per minute. Full assumptions, sources, and FX sensitivity are in PRICING_AND_PROFITABILITY.md.

Recommended tiers, not approved and not activated:

* Starter: $49 CAD per month, 120 included minutes, $0.40 CAD per minute overage, gross margin about 52.7 percent at full use of included minutes.
* Professional: $99 CAD per month, 350 included minutes, $0.35 CAD per minute overage, gross margin about 45.2 percent at full use.
* Business: $199 CAD per month, 800 included minutes, $0.30 CAD per minute overage, gross margin about 40.7 percent at full use.
* Enterprise: custom, from $499 CAD per month.

The original minute bundles seen in competitor plans lose money if copied at these CAD prices, so included minutes were cut rather than raising the hypothesised prices. Annual discount capped at 10 percent, and a setup fee of $99 to $149 CAD is recommended to cover onboarding time.

Critical cost blocker: speech recognition. Code verification shows the gather handler reads SpeechResult from the SignalWire webhook, so recognition is carrier gather speech and the codebase makes no separate transcription API call. What SignalWire bills for that recognition is not yet confirmed on an invoice. If it were billed at the published transcription rate, variable cost rises to about $0.230 CAD per minute and Starter and Professional lose money at full use. Confirm the billed rate before any paid tier launches.

## Remaining integration requirements

* Backend agent: implement the tenant contracts (tenant table and tenant columns, DID to tenant lookup at the voice webhook, per-tenant Redis namespacing and budget counters, per-tenant call admission instead of the single global lock, session auth and roles, config save endpoint the onboarding page posts to, appointments endpoint the dashboard reads, per-tenant usage metering including speech recognition seconds and ElevenLabs characters).
* Serve static/commercial/ from the deployment, or copy the three pages into the Harbour & Main site for the public demo. The dashboard and onboarding pages must be same-origin with the API to work as written.
* Legal review of every draft in docs/legal-drafts/ before any customer sees them, plus a Quebec Law 25 decision (support it properly or exclude Quebec clients at launch).
* Verify the SignalWire speech recognition billed rate and ElevenLabs plan cost against a real invoice, then reconcile the pricing model.
* Decide final prices. The tiers above are recommendations only.

## Outstanding blockers

* Multi-tenancy does not exist yet, so no second paying business can be onboarded safely until the backend contracts are implemented. This is the launch blocker.
* Speech recognition cost unverified (see above).
* Carrier-side hard call duration cutoff, provider live verification, and billing reconciliation remain open from RELEASE_STATUS.md and belong to the backend agent.
* No live billing is active, by design. Stripe or any payment activation needs Josh's explicit approval and the metering checklist in the pricing document completed first.
