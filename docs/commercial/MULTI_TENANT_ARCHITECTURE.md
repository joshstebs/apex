# ApexVoice Multi-Tenant Architecture Assessment

Prepared for: Harbour & Main, ApexVoice commercial readiness
Scope: Assessment of whether the current ApexVoice application can securely support multiple paying businesses, and a phased plan to reach that state.
Status: Proposal only. No backend files were modified in preparing this document. All schema changes below are proposed migrations for the backend agent to implement and review.

## Executive summary

ApexVoice today is a single-tenant application. It serves one business, configured through environment variables, reached on one telephone number, protected by one shared admin token, and limited to one concurrent call globally. None of the core data tables carry a tenant identifier. That design is appropriate for a personal or single-business deployment. It is not ready for multiple paying customers without the changes described in this document.

The good news is that the seams for multi-tenancy already exist in recognizable places: SignalWire webhooks receive the dialed number, assistant templates are already structured JSON objects, Redis is already used for locks and budget counters, and the API is already organized around resources such as calls, messages, and assistants. The work is to thread a tenant identity through each of those seams consistently, and to replace shared credentials and global limits with per-tenant equivalents.

Ratings used in this document: Ready means the current design supports multiple tenants as is. Partial means some foundation exists but per-tenant work is required. Missing means there is no current support and the capability must be built.

## Current state evidence

The following facts about the current system are the basis for every rating below.

- Configuration comes from environment variables, including SIGNALWIRE_PHONE_NUMBER holding a single DID (+12267732234), RECEPTIONIST_BUSINESS_NAME, and INBOUND_ASSISTANT_ID set to tpl_hm_receptionist.
- The SQLite database has tables for assistants, calls, transcripts, and tts_clips. None of these tables has a tenant_id or business_id column.
- Authentication is a single shared APEX_ADMIN_TOKEN bearer token, plus a separate APEX_OPERATIONS_TOKEN for operations endpoints. There are no user accounts, sessions, or roles.
- Concurrency is controlled by a single global lock in Redis, apex:active_call_lock, with MAX_CONCURRENT_CALLS set to 1.
- Cost control is a single global Redis counter compared against MONTHLY_BUDGET_LIMIT_USD. There is no per-business budget or usage record.
- Production assistant templates are version-controlled, read-only JSON files in the prompts directory, using a fixed schema with fields for id, name, category, description, first_message, dynamic_variables, system_prompt, temperature, voice_provider, voice_id, and tools.
- Existing endpoints include GET /api/health, /api/settings, /api/operations, /api/dashboard, /api/calls, /api/calls/{id}, /api/receptionist/messages, /api/assistants, /api/templates, /api/voices, /api/cost/calculate, and POST webhooks at /webhooks/signalwire/voice, /webhooks/signalwire/gather, and /webhooks/signalwire/status.

## Assessment by area

### 1. Tenant isolation

Rating: Missing.

Evidence: No table carries a tenant identifier, Redis keys are global rather than namespaced, and there is a single global call lock. A call, transcript, or message stored today cannot be attributed to a business by the data model itself. Any query written against the current schema returns data for the one implicit tenant only because there is only one tenant.

What is required: A tenant_id column on every tenant-owned table, tenant scoping enforced in the data access layer rather than left to each endpoint, Redis keys namespaced per tenant, and automated tests that prove one tenant cannot read another tenant's calls, transcripts, or messages by guessing identifiers.

Risk if skipped: Cross-tenant data exposure is the single most damaging failure mode for a multi-business phone service. Call transcripts routinely contain names, phone numbers, and personal details. Isolation must be structural, not a convention.

### 2. Separate business configurations

Rating: Partial.

Evidence: The system already has a configuration concept: an assistant template with a business name, greeting, system prompt, voice, and tools, plus environment variables for the business name and inbound assistant. That proves the shape of a per-business configuration exists. However, the active configuration is selected by environment variables at deploy time, so only one configuration can be live, and changing it requires a redeploy or restart rather than a customer action.

What is required: A stored BusinessConfig per tenant (see BACKEND_CONTRACTS.md for the exact JSON schema), a mapping from tenant to assistant instance, and runtime resolution of configuration per call instead of at process start. The existing template system should remain as the starting point a tenant's configuration is created from, not as the live configuration itself.

### 3. Individual telephone numbers

Rating: Missing.

Evidence: SIGNALWIRE_PHONE_NUMBER holds exactly one DID, +12267732234. There is no table of numbers, no provisioning flow, and no lookup from dialed number to business.

What is required: A tenant_phone_numbers table mapping each DID in E.164 format to a tenant_id, tenant resolution at the start of every SignalWire webhook using the To field of the inbound call, and a number provisioning and release process in SignalWire for onboarding and offboarding. Number porting, if offered later, is a separate operational process and should not be promised in the first commercial release.

### 4. Customer authentication

Rating: Missing for customers, Partial for internal administration.

Evidence: The only credentials are APEX_ADMIN_TOKEN and APEX_OPERATIONS_TOKEN, both shared bearer tokens intended for the operator. There are no customer accounts, no passwords, no sessions, and no login flow. A shared token cannot be handed to paying customers: it grants access to everything, cannot be revoked per customer, and leaves no audit trail of who did what.

What is required: Real customer accounts with hashed passwords or a managed identity provider, short-lived session tokens or signed JWTs carrying tenant_id and role claims, token revocation, and password reset flows. The existing admin and operations tokens should remain operator-only and must never be exposed to the customer frontend.

### 5. Role-based access control

Rating: Missing.

Evidence: With one shared token there is one implicit role: full administrator. Nothing distinguishes a business owner who can change billing and configuration from a staff member who should only read messages, or a viewer who should only see call history.

What is required: Four roles, defined in BACKEND_CONTRACTS.md: owner, admin, staff, and viewer. Every tenant-scoped endpoint must check both tenant membership and role. Role checks belong in middleware or a shared dependency so a new endpoint cannot accidentally ship without them.

### 6. Usage tracking per business

Rating: Partial.

Evidence: The system already tracks cost at a global level: a Redis counter against MONTHLY_BUDGET_LIMIT_USD and a GET /api/cost/calculate endpoint. The cost model therefore exists. What does not exist is attribution: usage events are not recorded against a tenant, a call, or a metered resource such as minutes, text to speech characters, or inference tokens in a durable per-tenant ledger.

What is required: A usage_events table recording tenant_id, call_id where applicable, event type, quantity, unit, and estimated cost, written at call completion and at each billable external call. Redis may keep fast per-tenant counters for live budget enforcement, but the durable record must be in the database so invoices and disputes can be audited. Per-tenant budget limits replace the single global limit for customer traffic, while a global ceiling should remain as an operator safety control.

### 7. Separate customer records

Rating: Missing.

Evidence: Calls, transcripts, and messages are stored without a tenant identifier, and there is no distinct customer or contact entity separated per business. The callers of one business and the callers of another would land in the same tables with no reliable way to separate them.

What is required: Tenant scoping on calls, transcripts, messages, and appointments, plus a contacts concept keyed by tenant_id and caller number so a business sees its own repeat callers only. Indexes must lead with tenant_id so per-tenant queries stay fast and so accidental unscoped queries are obvious in review.

### 8. Data retention and deletion

Rating: Missing.

Evidence: There is no documented retention period, no scheduled deletion job, and no per-tenant deletion capability in the current design. Transcripts and recordings accumulate indefinitely in a single-tenant store, which is tolerable for one operator and unacceptable when holding other businesses' customer data.

What is required: A written retention policy (see the privacy documentation deliverable), configurable retention per tenant within defined bounds, a deletion workflow that removes a tenant's calls, transcripts, messages, appointments, contacts, and stored audio, and a verifiable completion record. Deletion must also clear or expire related Redis keys and any cached text to speech clips for that tenant. Legal review is required before publishing retention commitments to customers.

### 9. Billing readiness

Rating: Missing.

Evidence: There is no subscription entity, no plan assignment, no payment provider integration, and no invoice or dunning flow. Cost tracking exists only as an internal budget guard. Nothing in the current system can charge a customer, suspend service for non-payment, or reconcile a payment against usage.

What is required: A subscriptions table linking tenant_id to plan, status, and billing period, a payment provider integration handled by the backend agent (Stripe is the expected choice given other Harbour & Main properties, but that decision belongs to the backend and business owners), a billing webhook endpoint to receive provider events, and service behaviour rules for past-due and cancelled states. No live billing should be activated as part of the commercial readiness frontend work. See BACKEND_CONTRACTS.md for the placeholder webhook contract.

## Target architecture

### Tenant identity and propagation

Tenant identity enters the system at exactly two boundaries, and everywhere else it is carried, never re-derived.

- Voice boundary: SignalWire webhooks (voice, gather, status) receive the dialed number in the To field. The first step of webhook handling is a lookup of that number in tenant_phone_numbers to resolve tenant_id. If no tenant matches, the call is rejected with a safe generic message and logged for the operator. The resolved tenant_id is attached to the call record at creation and used for every subsequent lookup in that call's lifecycle, including gather and status callbacks, which should resolve the tenant from the stored call record rather than trusting request parameters alone.
- API boundary: Authenticated API requests carry a session token or JWT with tenant_id and role claims, verified by middleware. The tenant_id from the verified token, never from a request body or query parameter, scopes every query. Operator endpoints using APEX_OPERATIONS_TOKEN are the only exception, and they must be clearly separated in routing.

Internal propagation rule: every function that reads or writes tenant data receives tenant_id as an explicit parameter. No global or environment-derived tenant is permitted after the boundary resolution step.

### Redis key namespacing

All tenant-scoped Redis keys move to the prefix pattern apex:t:{tenant_id}: followed by the resource name.

- Active call lock: apex:t:{tenant_id}:active_call_lock, replacing the global apex:active_call_lock for customer traffic. A separate operator-level concurrency ceiling may remain as a global key to protect shared provider accounts.
- Monthly usage counter: apex:t:{tenant_id}:usage:{yyyy_mm}, replacing the single global budget counter for per-tenant enforcement.
- Session and rate limit keys: apex:t:{tenant_id}:ratelimit:{subject} and apex:session:{session_id} with the tenant stored in the session value.
- Cache keys for configuration: apex:t:{tenant_id}:config, invalidated on every configuration update.

Keys that are genuinely global (provider health, template catalogue version) keep the apex: prefix without a tenant segment, and the distinction should be documented where the key is created.

### Proposed database changes

The following are proposed migrations only, written for the backend agent to review, adapt, and apply through the project's normal migration process. They are not applied by this document and no backend file has been changed.

Proposed new tables:

- tenants: id (primary key, text, prefixed tenant identifier), legal_name, display_name, status (trial, active, past_due, suspended, cancelled), timezone, created_at, updated_at.
- tenant_users: id, tenant_id (foreign key), email (unique per tenant), password_hash or external identity reference, role (owner, admin, staff, viewer), status, created_at, last_login_at.
- tenant_phone_numbers: id, tenant_id (foreign key), phone_number (unique, E.164), provider (signalwire), provider_number_id, status, created_at, released_at.
- tenant_configs: tenant_id (primary key, foreign key), config_json (the BusinessConfig document defined in BACKEND_CONTRACTS.md), version (integer, incremented on each save), updated_by, updated_at.
- subscriptions: id, tenant_id (foreign key), plan_id, status, current_period_start, current_period_end, provider, provider_customer_id, provider_subscription_id, created_at, updated_at.
- usage_events: id, tenant_id (foreign key), call_id (nullable foreign key), event_type (call_minute, tts_character, inference_token, storage_byte_day), quantity, unit, estimated_cost_usd, created_at.
- appointments: id, tenant_id (foreign key), call_id (nullable), contact_name, contact_phone, service_name, requested_start, requested_end, status (requested, confirmed, declined, cancelled), notes, created_at, updated_at. Note that an appointment begins as a request and only becomes confirmed through an explicit confirmation step, matching the template tool wording.
- contacts: id, tenant_id (foreign key), phone_number, display_name, first_seen_at, last_seen_at, notes. Unique constraint on (tenant_id, phone_number).

Proposed alterations to existing tables:

- assistants: add tenant_id (nullable for shared system templates, required for tenant-owned assistants), add index on tenant_id.
- calls: add tenant_id (required after backfill), add phone_number_id or dialed_number, add index on (tenant_id, started_at).
- transcripts: add tenant_id (required after backfill), add index on (tenant_id, call_id).
- tts_clips: add tenant_id (required after backfill).

Backfill strategy for the existing single business: create one tenant record representing the current Harbour & Main deployment, assign the existing DID +12267732234 to it, and backfill tenant_id on all existing rows with that tenant's id before adding not-null constraints. This preserves current production data and gives the existing deployment a normal tenant identity rather than a special case.

Migration safety rules: each migration must be reversible or paired with a documented rollback, must be tested against a copy of production data in staging, and must not be applied while the backend reliability agent is mid-change on database.py. Coordination with that agent is a hard prerequisite.

### Configuration model

Each tenant has one BusinessConfig document (schema in BACKEND_CONTRACTS.md). On save, the backend validates the document, increments its version, stores it, invalidates the cached config in Redis, and derives or updates the tenant's assistant configuration from it. The version-controlled templates in prompts remain the catalogue of starting points. A tenant configuration is data, not code, and must never require a redeploy to change.

### Concurrency and budget model

MAX_CONCURRENT_CALLS becomes a per-plan, per-tenant limit enforced with the namespaced lock and a per-tenant active call counter, rather than a single global value of 1. A global provider-level ceiling remains for operator protection, sized to the SignalWire and voice provider account limits. Per-tenant monthly budgets derive from plan included minutes plus a configurable hard cap, enforced from the per-tenant Redis counter with the durable usage_events ledger as the source of truth at billing time.

## Risks

- Cross-tenant data leakage through an unscoped query, a guessed object identifier, or a webhook that trusts caller-supplied identifiers. Mitigation: tenant scoping in the data layer, authorization tests with two tenants in every test run, and resolving tenant from stored records on callbacks.
- Webhook spoofing. SignalWire webhooks must be signature-validated before tenant resolution is trusted, and the resolved tenant must come from the dialed number, not from any caller-supplied field.
- Migration risk on a live single-tenant production database. Mitigation: staged backfill, staging rehearsal, and scheduling outside the backend agent's active work windows.
- Concurrency change risk. Moving from a global lock of 1 to per-tenant limits increases simultaneous load on shared provider accounts. Mitigation: keep a global ceiling, load test in staging, and set conservative per-plan limits at launch.
- Cost attribution gaps. If any billable external call (telephony, text to speech, inference) is not recorded as a usage event, margins erode silently. Mitigation: usage recording in shared provider client code, not per endpoint, plus a daily reconciliation check against provider invoices.
- Number inventory and carrier compliance. Canadian numbers, 10DLC-style registration where applicable, and call recording consent rules vary by province. Mitigation: confirm SignalWire requirements for Canadian DIDs before onboarding the first paying tenant, and obtain legal review of recording disclosure wording.
- Secrets and token sprawl. Per-tenant tokens increase the number of credentials in circulation. Mitigation: hashed token storage, short session lifetimes, and revocation support from day one.

## Phased implementation plan

Phase 0, contracts and staging (no production change):
- Agree the contracts in BACKEND_CONTRACTS.md with the backend agent.
- Stand up staging with two test tenants and two test DIDs.
- Write the two-tenant isolation test suite before schema work begins, so the tests define done.

Phase 1, identity foundation (backend agent):
- Apply proposed migrations: tenants, tenant_users, tenant_phone_numbers, tenant_configs, and tenant_id columns with backfill for the existing business.
- Implement tenant resolution at the SignalWire webhook boundary and tenant scoping in the data access layer.
- Namespace Redis keys per tenant, keeping the global operator ceiling.
- Gate: isolation test suite passes in staging, existing single-business behaviour unchanged for the backfilled tenant.

Phase 2, customer access (backend agent, frontend in parallel):
- Implement customer authentication, sessions, and the four roles.
- Implement tenant configuration endpoints consumed by the onboarding frontend.
- Implement per-tenant calls, messages, and appointments read endpoints for the dashboard.
- Gate: a test business owner can sign in, complete onboarding, and see only their own data, verified on mobile and desktop.

Phase 3, usage and limits (backend agent):
- Implement usage_events recording for telephony minutes, text to speech, and inference.
- Implement per-tenant budgets, plan limits, and per-tenant concurrency.
- Implement operator reporting that reconciles recorded usage against provider costs.
- Gate: a staging month of simulated traffic reconciles within an agreed tolerance.

Phase 4, billing readiness (backend agent and business owner, separate approval):
- Implement subscriptions and the billing webhook placeholder, in test mode only.
- Define past-due and suspension behaviour and test it in staging.
- Legal review of terms, privacy policy, and recording disclosure before any live charge.
- Gate: explicit written approval from the business owner before live billing is activated. Nothing in the commercial readiness frontend work activates billing.

Phase 5, controlled launch:
- Onboard a small number of friendly businesses, each with its own DID, configuration, and owner account.
- Monitor isolation logs, usage reconciliation, and support requests daily for the first month.
- Only after a clean month, open general onboarding.

## Dependencies on the backend agent

This plan intentionally does not modify app.py, config.py, database.py, telephony.py, or voice_engine.py, which another agent owns. The frontend, onboarding, dashboard, templates, and documentation deliverables are built against the contracts in BACKEND_CONTRACTS.md. If the backend agent changes a contract, the change must be recorded in that document first so the frontend and backend stay in step.
