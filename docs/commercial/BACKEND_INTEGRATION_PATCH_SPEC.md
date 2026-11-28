# Backend Integration Patch Spec: Wiring the Tenancy Layer into ApexVoice

Status: DO NOT APPLY until Command Code finishes its backend reliability work and the integration is scheduled as its own reviewed change.

This document describes the exact, small, reviewable changes the backend agent must later make in the shared backend files so the isolated tenancy package (tenancy/) becomes the live multi-tenant path. Nothing in this spec has been applied. No shared backend file (app.py, config.py, database.py, telephony.py, voice_engine.py) was modified by the tenancy work, and the tenancy package imports none of them.

Contracts implemented by the package: docs/commercial/BACKEND_CONTRACTS.md and docs/commercial/MULTI_TENANT_ARCHITECTURE.md. Where this spec and those documents disagree, the contracts win and this spec must be updated in the same pull request.

## What the tenancy package already provides

- tenancy.store: TenantStore protocol with InMemoryStore and SQLiteStore. All record access is tenant-scoped in the data layer itself.
- tenancy.auth: AuthService with PBKDF2-HMAC-SHA256 password hashing, opaque tenant-bound sessions (only token hashes stored), 12 hour expiry, logout revocation, and password change with session revocation.
- tenancy.rbac: TenantPrincipal and PlatformOperator principals, the four roles, and require() checks.
- tenancy.routing: TenantRouter (DID to tenant from the dialed number), per-tenant Redis key builders, and CallAdmission against a redis-like client.
- tenancy.usage: UsageMeter with per-tenant plan limits (starter 120, professional 350, business 800 included minutes, enterprise custom), per-call round-up billable minutes, and per-tenant hard stops.
- tenancy.lifecycle: TenantLifecycle (create, suspend, reactivate, delete with purge and platform audit) and migrate_single_tenant for the existing Harbour & Main installation.
- tenancy.api_models: pure shaping functions for every customer endpoint in the contract, including the {error: {code, message}} body and cursor pagination.

## Step 1, database.py: schema additions (one migration, reversible)

Apply as a single migration after a staging rehearsal on a copy of production data.

- Add tables mirroring the tenancy SQLite design: tenants, tenant_configs, phone_mappings, tenant_users, sessions, records (generic tenant-owned records with payload), audit_log. Every tenant-owned table has a tenant_id column and an index leading with tenant_id. In the existing relational schema, prefer typed tables (calls, messages, appointments, transcripts, customers, usage_events) over the generic records table where the backend already has typed models; the requirement is the tenant_id column and the index, not the generic table.
- Add tenant_id to the existing assistants, calls, transcripts, and tts_clips tables, nullable at first.
- Backfill: create the Harbour & Main tenant by calling migrate_single_tenant with tenant id ten_harbour_main, the legacy env config, DID +12267732234, and the owner account. Then set tenant_id = ten_harbour_main on every existing assistants, calls, transcripts, and tts_clips row.
- Only after the backfill is verified in staging, add NOT NULL constraints on tenant_id for calls, transcripts, and tts_clips.
- Rollback: the migration is additive until the NOT NULL step. Rollback before that step is dropping the new tables and columns. The NOT NULL step ships separately so it can be reverted on its own.

## Step 2, config.py: settings additions

- Add TENANCY_ENABLED (default false during rollout), TENANCY_DB_PATH or reuse the existing database configuration, and SESSION_TTL_SECONDS (default 43200, the 12 hour contract maximum).
- Keep SIGNALWIRE_PHONE_NUMBER, RECEPTIONIST_BUSINESS_NAME, and INBOUND_ASSISTANT_ID as the migration source and as a fallback only while TENANCY_ENABLED is false. Once a tenant resolves, none of these may influence the call.
- MONTHLY_BUDGET_LIMIT_USD stays as the platform-level safety ceiling. It stops being the customer-facing budget; per-tenant caps come from tenancy.usage.

## Step 3, app.py: tenant resolution at the voice webhook boundary

In the SignalWire voice webhook handler, in this order:

- Validate the SignalWire signature exactly as today. Invalid signature: 403, no tenant work.
- If TENANCY_ENABLED, resolve the tenant before any business logic: tenant = TenantRouter(store).resolve(payload To field). UnknownNumber: respond with the generic not-in-service message and end the call, with an operator log entry and no configuration details. TenantNotActive: polite closed message and end the call.
- Create the call record with the resolved tenant_id and the matched phone mapping. Gather and status callbacks must resolve the tenant from the stored call record by provider call identifier, never from callback parameters.
- Load configuration from the store through the cache key tenancy.routing.config_key(tenant_id), that is apex:t:{tenant_id}:config, and select the tenant's assistant and voice from its TenantConfig (voice.voiceId, receptionistName, greeting). The legacy global assistant selection applies only to the un-migrated fallback path.
- Admission: replace the single global lock acquisition with CallAdmission.try_admit(tenant_id, call_id) using tenancy.routing.active_call_lock_key. Keep a platform-level concurrency ceiling check in addition, sized to provider account limits.
- On call completion, record usage through UsageMeter.record_call(tenant_id, duration_seconds, tts_characters, stt_seconds, call_id) so minutes, TTS characters, and STT seconds land in the tenant's own ledger.

## Step 4, database.py and voice_engine.py: replace global Redis keys

- Replace apex:active_call_lock with tenancy.routing.active_call_lock_key(tenant_id) for customer traffic.
- Replace the global account counter apex:acct with tenancy.routing.account_key(tenant_id, yyyymm) for per-tenant budget enforcement. The platform ceiling keeps its own key.
- Replace clip storage keys with tenancy.routing.clip_key(tenant_id, clip_id), and call state keys with tenancy.routing.call_key(tenant_id, call_id). Every clip and call-state read must use the tenant resolved from the call record.
- Config cache invalidation on every configuration save: delete tenancy.routing.config_key(tenant_id).

## Step 5, app.py: customer API routes and session auth

- Add the contract routes, each a thin adapter over the tenancy package: POST /api/auth/login, POST /api/auth/logout, GET /api/auth/session, POST /api/tenants (operator), GET and PATCH /api/tenants/{tenantId}, GET and PUT /api/tenants/{tenantId}/config, GET /api/tenants/{tenantId}/usage, GET /api/tenants/{tenantId}/calls and /calls/{callId}, GET and PATCH /api/tenants/{tenantId}/messages/{messageId}, GET and PATCH /api/tenants/{tenantId}/appointments/{appointmentId}, GET /api/tenants/{tenantId}/subscription.
- Authentication for customer routes: AuthService.authenticate on the bearer token, then build a TenantPrincipal from the session user. The tenant scope for every query comes from the session, never from the path. A path tenant_id that disagrees with the session tenant returns 403 per the contract; object lookups under the session tenant that miss return 404, including IDs belonging to other tenants.
- Authorization: call tenancy.rbac.require(principal, permission, tenant_id) at the top of every handler with the permission names from the contract matrix (config.read, config.write, calls.read, messages.read, messages.write, appointments.read, appointments.write, customers.read, usage.read, billing.read, users.manage, tenant.suspend, tenant.delete).
- Responses: shape every body with tenancy.api_models (shape_tenant, shape_config_response, shape_call, shape_message, shape_appointment, shape_usage, login_response, list_response) and every error with api_models.error_body or error_body_from_exception so the {error: {code, message}} shape is uniform.
- Configuration save: validate with the TenantConfig model (validation errors surface as 400 validation_failed with the fields map), enforce expectedVersion optimistic locking (409 version_conflict with currentVersion), increment the version, persist, then invalidate the config cache key from Step 4.
- Operator routes keep working unchanged: /api/health, /api/settings, /api/operations, /api/dashboard, and the existing unscoped operator surfaces continue to require APEX_ADMIN_TOKEN or APEX_OPERATIONS_TOKEN. The shared admin token is retired for customer routes only; it must never be sent to or accepted from the customer frontend as a customer credential.
- Billing webhook POST /webhooks/billing/{provider}: implement only the placeholder behaviour in the contract (signature verification, idempotent event recording, no charge creation) and only in test mode until the separate billing approval exists.

## Step 6, telephony.py: number inventory

- Number provisioning and release for onboarding and offboarding go through the phone_mappings table: a DID is usable only while a mapping row with status active exists. Releasing a number deletes or retires the mapping in the same transaction as the SignalWire release, so routing can never point at a tenant that no longer owns the number.
- No change to signature validation or provider call mechanics is required for tenancy.

## Step 7, rollout sequence

- Ship Steps 1 and 2 with TENANCY_ENABLED false. Verify the backfilled Harbour & Main tenant in staging with the tenancy test suites plus the existing backend suites.
- Enable TENANCY_ENABLED in staging with two test tenants and two test DIDs. Gate: the full isolation suite (test_tenancy_isolation, test_tenancy_auth_rbac, test_tenancy_usage_lifecycle) passes against the integrated build, and the existing single-business behaviour for ten_harbour_main is unchanged.
- Enable in production for ten_harbour_main only. Monitor cross-tenant access denials and usage reconciliation daily.
- Onboard the first external tenant only after one clean week.

## Explicitly out of scope for this integration

- Live billing activation, real charges, and number purchases (separate approvals).
- Direct booking mode for appointments (the contract keeps request_only until a calendar integration is live).
- Any change to the staging branch or to Command Code's reliability work in flight.
