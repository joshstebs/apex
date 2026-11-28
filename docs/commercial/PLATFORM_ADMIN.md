# ApexVoice platform administration

Status: Phase 4 deliverable. The ops package (ops/aggregation.py,
ops/actions.py, ops/health.py) and the operator page
(static/platform-admin.html) are built and unit tested in isolation.
The HTTP routes below are a contract for the backend integration; they
do not exist in the running service until the backend agent adds them,
following BACKEND_INTEGRATION_PATCH_SPEC.md, after Command Code
confirms its backend work is complete. Nothing here enables live
calling or live billing.

## What this surface is

The platform administration surface is how Harbour and Main operates
ApexVoice across every customer business: tenant status, plan and
subscription state, assigned numbers, usage, estimated operating cost,
revenue and contribution estimates, provider health, failed calls,
active calls, onboarding progress, spending limits, support summary,
and the audit log, plus controlled actions to create, suspend,
reactivate, delete, and cap tenants.

It is a separate surface from the customer dashboard. A customer sees
only their own business. The platform operator sees aggregates across
businesses, under the data minimization rule below.

## Authorization model

- Platform actions and platform reads require a PlatformOperator
  principal from the tenancy RBAC module. That principal is not a
  tenant user, holds no tenant role, and is the only principal the ops
  actions layer accepts. Customer scoped principals are refused for
  every platform action, including actions a tenant owner may perform
  on their own tenant through customer self service.
- Transport: the operator page sends the platform operator token in
  the X-Platform-Token header. The backend route resolves that token
  to a PlatformOperator principal and passes the principal into the
  ops layer. The token is a platform credential, distinct from:
  - customer session tokens (issued by the tenancy auth service to
    tenant users, scoped to one tenant), and
  - the legacy shared admin token (APEX_ADMIN_TOKEN) and operations
    token (APEX_OPERATIONS_TOKEN) from the single tenant service.
- The legacy tokens must not become the platform credential. As an
  interim measure only, while the platform token is being provisioned,
  the new /api/platform/ routes may sit behind the existing operations
  token route protection, and this must be recorded as interim in the
  deployment notes and removed when the platform token lands. The ops
  layer itself never accepts a raw token; it accepts principals, so
  swapping the route protection does not change ops behaviour.
- Failed authorization returns the contract error body with code
  forbidden (HTTP 403). Unknown tenants return not_found (404).
  Validation problems return validation_failed (400). Conflicts return
  conflict (409). Error bodies follow the tenancy api_models shape:
  {"error": {"code": ..., "message": ..., "fields": {...}}}.

## API contract

All responses are JSON. All money is integer CAD cents with a currency
field. All periods are yyyymm strings in UTC, matching the tenancy
usage module.

### GET /api/platform/overview

Query: period (optional, defaults to the current period).

Response: the document built by ops.aggregation.build_platform_overview.

- generated_at: ISO timestamp of when the overview was built.
- period: the yyyymm period the figures cover.
- totals.tenant_count: number of tenant registry rows.
- totals.tenants_by_status: counts keyed by trial, active, past_due,
  suspended, deleted. All five keys are always present.
- totals.tenants_without_billing_record: tenants for which no billing
  state record was supplied. Their revenue is unknown and excluded
  from the revenue and contribution totals.
- totals.current_period: period, used_minutes, call_count,
  estimated_cost_cents, revenue_cents, contribution_cents.
- tenants: one row per tenant, the same rows GET /api/platform/tenants
  returns. Row fields:
  - tenant_id, business_name, legal_name, status, plan_tier,
    timezone, created_at.
  - subscription: {status: available or no_record, state, tier_id}.
    State is one of the billing state machine values (none, trialing,
    active, past_due, unpaid, canceled, incomplete) or the string
    unknown when no record was supplied.
  - phone_numbers: assigned DID strings in E.164 form.
  - onboarding: {status: not_started, partial, or complete, present,
    missing, percent, config_version}. Present and missing list
    BusinessConfig section names only, never configuration values.
  - voice: {tier, provider} from the tenant voice configuration.
  - usage: {period, used_minutes, call_count, tts_characters,
    stt_seconds} for the requested period.
  - usage_history: one entry per period with recorded usage:
    {period, used_minutes, call_count, estimated_cost_cents}, sorted
    by period.
  - estimated_cost_cents: used minutes times the tenant voice
    provider's full per minute cost from the voice package, plus the
    700 cent fixed monthly allowance, for the requested period.
    Deleted tenants report 0. These are pricing model estimates, not
    invoice verified charges.
  - revenue_cents: the billing tier monthly list price while the
    subscription state is active or past_due, 0 in other known states,
    null when no billing record was supplied.
  - contribution_cents: revenue minus estimated cost, null when
    revenue is null.
  - currency: "CAD".
  - spending: {plan_limit_minutes (null for enterprise),
    used_minutes, remaining_minutes, percent_used, cap, status}.
    Cap is {cap_minutes, cap_cad_cents} or null. Status is one of
    within_limit, near_limit (at or over 80 percent of the plan
    limit), at_or_over_limit, cap_exceeded, unlimited, closed
    (deleted tenants).
  - calls: {status: available or no_data, total, failed, error_rate}.
    Counts come only from call records the backend supplies for the
    period. With none supplied, status is no_data and the counts are
    null. An empty supplied list is available data with total 0 and a
    null error rate. Failed means the record status is one of failed,
    error, busy, no_answer, no-answer, unanswered. Only the status
    field of each record is read.
- call_metrics: platform rollup of the per tenant calls blocks:
  {status: available, partial, or no_data, total, failed, error_rate}.
- provider_health: array of {provider, status, checked_at, source}.
  Status is unknown, up, degraded, or down. Every provider defaults
  to unknown with checked_at null until a real probe records a result
  through the health registry. The overview surfaces records as-is.
- active_calls: {status: unknown or available, count, calls,
  by_tenant}. With no active call provider wired, status is unknown
  and count is null. When available, calls carry metadata only:
  call_id, tenant_id, started_at, direction, status.
- support: {status: no_data or available, open_total, by_tenant}.
  No support data source exists yet (see gaps), so until one is
  wired this is the no_data form with null counts.

### GET /api/platform/tenants

Response: {"items": [tenant rows], "page": {...}} using the tenancy
api_models pagination shape. Rows are identical to the tenants array
in the overview. Query: period, limit, cursor, and an optional status
filter.

### GET /api/platform/health

Response: {"providers": [provider health records]}. Same record shape
as overview.provider_health. This endpoint never probes anything
itself; it returns the registry contents.

### GET /api/platform/audit

Query: tenant_id (optional), limit, cursor.
Response: {"entries": [audit entries], "page": {...}}. An audit entry
is {id, tenant_id, action, actor, at, details}. Actor is
"platform:{operator_id}" for ops actions. Lifecycle actions taken
through the ops layer also produce the tenancy lifecycle's own entries
(for example tenant.suspended), so one operator action can appear as
both a lifecycle entry and a platform.* entry; the platform.* entry is
the one that carries the operator reason.

### POST /api/platform/tenants/{tenant_id}/actions

Body: {"action": ..., "reason": ..., "confirm": ...}.

Actions and rules:

- create: posted to /api/platform/tenants instead (see below).
- suspend: reason required. Delegates to the lifecycle suspend.
- reactivate: reason optional.
- delete: reason required and confirm must be true. Purges the tenant
  and everything it owns. Audit entries survive the purge.
- set_spending_cap: body carries cap_minutes and/or cap_cad_cents, at
  least one, each non-negative, plus an optional reason.

Success response: {ok: true, action, tenant_id, actor, at, audit_id}
plus action specific fields (status, cap, owner_user_id for create).
Failures return the contract error body with the tenancy error codes.

### POST /api/platform/tenants

Body: {legal_name, owner_email, owner_password, display_name,
plan_tier, timezone, config, did, tenant_id, reason}. Creates the
tenant, its owner user, and optionally its first configuration and
phone mapping, through the tenancy lifecycle. Response is the action
result shape above with status and owner_user_id.

## Audit guarantees

- Every successful ops action appends an audit entry before returning:
  platform.tenant_created, platform.tenant_suspended,
  platform.tenant_reactivated, platform.tenant_deleted,
  platform.spending_cap_set. The entry records actor, action, tenant,
  timestamp, and a details object that always includes the operator
  reason for suspend and delete (both refuse to run without one).
- Failed actions write no platform audit entry. The refusal is
  returned to the caller as a typed error.
- The audit log lives in the store's platform audit table, not in
  tenant owned records. Tenant purge does not delete audit entries,
  so suspensions and deletions remain verifiable after the tenant is
  gone. The Phase 3 isolation suite already proves tenant data does
  not leak across tenants; audit reads here are platform only.

## Data minimization rule

The platform overview never includes one tenant's call content,
transcripts, message bodies, appointment details, or customer personal
data. This is enforced by construction in ops/aggregation.py: the
builders read tenant registry rows, phone mapping identifiers,
configuration section presence, usage records, supplied billing state
records, and the status field of supplied call records. Transcript,
message, appointment, and customer records are never read. The ops
test suite proves this by scanning the serialized overview for content
strings planted in tenant records and asserting none appear. Operator
access to an individual tenant's call content, if ever needed for
support, belongs in a separate, separately audited support tool, not
in this overview.

## Backend integration points

For the backend agent, once Command Code confirms the backend work is
complete. All of these are new routes; no existing route changes shape.

- Add the five routes above to the backend, each resolving the
  platform token to a PlatformOperator principal, then calling:
  - overview and tenants: ops.aggregation.build_platform_overview and
    build_tenant_row over the live TenantStore, with these providers
    wired: billing state records from wherever the billing module's
    SubscriptionRecords are persisted, call records for the period
    from the calls store (status field only), the live call registry
    for active calls, the voice config store, the spending cap store,
    and the health registry.
  - health: ops.health.HealthRegistry contents. Probe jobs (carrier
    status, ElevenLabs status, Redis ping, language model health,
    Stripe status) record into the registry on their own schedule;
    the route only reads.
  - audit: ops.aggregation.build_audit_view over store.list_audit.
  - actions and create: ops.actions.OpsActions over the same store
    and lifecycle the customer API uses, so platform and customer
    actions share one audit log and one state.
- Serve static/platform-admin.html on an operator only path, behind
  the same platform token check. It must not be linked from customer
  pages.
- Interim protection: until a dedicated platform operator token is
  provisioned, the routes may reuse the existing operations token
  route protection, named as interim in the deployment notes. The
  dedicated token replaces it without ops layer changes.
- Persistence work the integration owns: billing SubscriptionRecords
  and spending caps need durable storage (see gaps). The ops layer
  accepts both by injection precisely so the backend can choose the
  storage without changing aggregation or actions.

## Known gaps in the Phase 3 packages, worked around by injection

- Billing SubscriptionRecords have no store in the Phase 3 packages.
  Aggregation takes them as an injected mapping or callable. Until the
  backend persists them, subscription state shows as unknown.
- The Tenant model has no spending cap field. Caps live in the ops
  SpendingCaps registry (in-memory) and are injected into aggregation.
  They are not durable across restarts and are not enforced during
  live calls; both are backend integration work.
- There is no support or escalation ticket record kind in the tenancy
  store. The overview support block accepts injected counts only and
  reports no_data until a support store exists.
- There is no active call registry in the Phase 3 packages. Active
  calls are injected; without a provider the overview reports
  unknown, never zero.
- Provider health has no probes in the Phase 3 packages. The registry
  records results; it does not produce them.
- Tenant deletion in the lifecycle purges the tenant row, so a deleted
  tenant no longer appears in tenant listings. Deleted tenants remain
  visible through the audit log. A tenant row that still exists with
  status deleted (for example a soft deleted registry entry) is
  represented in the overview with zeroed cost and revenue and
  spending status closed.
