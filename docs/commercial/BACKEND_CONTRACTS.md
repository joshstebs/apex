# ApexVoice Backend Interface Contracts

Audience: The backend agent working on ApexVoice reliability, Redis, SignalWire, voice processing, security, and staging deployment.
Purpose: Precise contracts between the commercial readiness frontend (onboarding, dashboard, sales demonstration) and the backend, so both sides can be built independently and integrated without guesswork.
Status: Proposal for agreement. No backend file has been modified to match this document yet. If implementation requires a change to any contract here, update this document in the same pull request as the code change.

Conventions used throughout:

- Base path for customer APIs: /api. Operator APIs keep their existing paths and tokens.
- All request and response bodies are JSON, UTF-8.
- All timestamps are ISO 8601 in UTC, for example 2026-11-28T14:05:00Z, except business local times inside configuration, which carry an explicit timezone field.
- All telephone numbers are E.164, for example +12267732234.
- All money values are integer cents with an explicit currency field, for example amount_cents 4900 and currency CAD. No floating point money anywhere.
- Identifiers are opaque strings with prefixes: tenant_ for tenants, call_ for calls, msg_ for messages, appt_ for appointments, sub_ for subscriptions.
- No em dashes are used in any customer-facing string in these examples. Customer-facing copy uses plain Canadian English.

## Authentication and authorization model

### Credential types

- Operator admin token: the existing APEX_ADMIN_TOKEN bearer token. Operator use only. Never sent to or stored in the customer frontend. Grants access to operator endpoints across tenants.
- Operations token: the existing APEX_OPERATIONS_TOKEN. Operator use only, for /api/operations and health-adjacent operational views.
- Customer session: issued by POST /api/auth/login, described below. A signed JWT or opaque session token presented as an Authorization Bearer header. Claims or session record must include user_id, tenant_id, and role. Expiry: 12 hours maximum for a session, with refresh handled by re-login in the first release.
- Billing webhook signature: provider signature header, verified against the provider webhook secret. Not a bearer token. See the billing webhook contract below.

### Roles

Four roles exist per tenant. A user belongs to exactly one tenant in the first release and holds one role in that tenant.

- owner: Full control. Manage configuration, users, billing, data export, and data deletion. Exactly the person accountable for the business account. Only an owner can delete the tenant's data or close the account.
- admin: Manage configuration, services, FAQs, and team invitations. Cannot manage billing, close the account, or request full data deletion.
- staff: Read and work with calls, messages, and appointments. Can update appointment status and message handled state. Cannot change configuration, users, or billing.
- viewer: Read-only access to dashboard, calls, messages, and appointments. Cannot change anything, including configuration.

Permission summary by resource:

- Configuration read: owner, admin, staff, viewer.
- Configuration write: owner, admin.
- Calls and transcripts read: owner, admin, staff, viewer.
- Messages read and update handled state: owner, admin, staff. Viewer is read-only.
- Appointments read: owner, admin, staff, viewer. Status update: owner, admin, staff.
- Usage read: owner, admin. Staff and viewer do not see cost figures in the first release.
- User management: owner only for role changes and removal, admin may invite staff and viewer.
- Billing read: owner only. Billing changes: owner only.
- Data export: owner, admin. Data deletion request: owner only.

### Authorization rules

- The tenant_id used for scoping always comes from the verified session. A tenant_id in a path, query, or body that disagrees with the session tenant is rejected with 403, not silently ignored.
- Every object lookup (call, message, appointment) must verify the object belongs to the session tenant. A valid identifier belonging to another tenant returns 404, not 403, so identifiers do not leak which tenant owns an object. Authorization failures on the tenant's own resources return 403.
- Operator endpoints are the only cross-tenant surface and must be on separate routes that require the operator tokens.

## Tenant resolution for telephony

Tenant resolution for inbound calls happens before any business logic.

- SignalWire sends webhooks to POST /webhooks/signalwire/voice, /webhooks/signalwire/gather, and /webhooks/signalwire/status (existing routes, unchanged paths).
- First, validate the SignalWire signature. An invalid signature returns 403 and is logged without caller details beyond the source address.
- For the initial voice webhook, read the To field (the dialed number) from the validated payload. Look up To in tenant_phone_numbers. Exactly one active tenant must match.
- If no tenant matches, respond with a brief generic spoken message stating the number is not in service, end the call, and write an operator log entry. Do not reveal configuration details.
- Create the call record with tenant_id and the matched phone_number_id at this moment. All later gather and status callbacks resolve the tenant from the stored call record identified by the provider call identifier, never from parameters supplied in the callback body.
- Load the tenant configuration from tenant_configs (through the per-tenant Redis cache, key apex:t:{tenant_id}:config) and select the tenant's assistant for the call. The environment variable INBOUND_ASSISTANT_ID remains only as the fallback for the original single-tenant deployment during migration and must not be used once a tenant is resolved.

## Error format and codes

All customer API errors use one shape:

```json
{
  "error": {
    "code": "validation_failed",
    "message": "Two fields need attention before this can be saved.",
    "fields": {
      "contact.email": "Enter an email address in the form name@example.com.",
      "hours.monday.open": "Opening time must be earlier than closing time."
    }
  }
}
```

The fields object is present only for validation errors. The message is customer-safe: it never includes stack traces, SQL, provider raw errors, or another tenant's data.

Standard codes and HTTP statuses:

- 400 validation_failed: The request body failed validation. Includes the fields map.
- 400 malformed_json: The request body is not valid JSON.
- 401 unauthenticated: No session, or the session is expired or revoked.
- 403 forbidden: The session is valid but the role does not permit this action, or the path tenant disagrees with the session tenant.
- 404 not_found: The resource does not exist, or it belongs to another tenant.
- 409 conflict: A uniqueness or state conflict, for example a phone number already assigned, or saving configuration with a stale version.
- 409 version_conflict: Configuration save attempted against an old version. The response includes the current version so the frontend can offer a reload.
- 429 rate_limited: Too many requests. Includes a Retry-After header.
- 402 plan_limit_reached: The tenant's plan limit blocks the action, for example included minutes exhausted with overage disabled. Used only where the product decides to block rather than bill overage.
- 502 provider_error: A telephony, voice, or inference provider failed. The frontend shows a plain retry message.
- 503 service_unavailable: A required dependency such as Redis or the database is unavailable.

## BusinessConfig schema

This is the exact JSON document the onboarding frontend produces and sends. The backend must accept this shape as the configuration write payload and return the same shape on read, wrapped as described in the configuration endpoints below. Field names are camelCase exactly as written here. No additional required fields may be added without a contract update, because the frontend will not send them.

```json
{
  "businessName": "Harbour Plumbing and Heating",
  "contact": {
    "ownerName": "Alex Martin",
    "email": "alex@example.com",
    "phone": "+15195550123",
    "address": "123 Main Street, Amherstburg, ON",
    "website": "https://example.com"
  },
  "hours": {
    "monday": { "open": "08:00", "close": "17:00", "closed": false },
    "tuesday": { "open": "08:00", "close": "17:00", "closed": false },
    "wednesday": { "open": "08:00", "close": "17:00", "closed": false },
    "thursday": { "open": "08:00", "close": "17:00", "closed": false },
    "friday": { "open": "08:00", "close": "17:00", "closed": false },
    "saturday": { "open": null, "close": null, "closed": true },
    "sunday": { "open": null, "close": null, "closed": true }
  },
  "holidays": [
    { "date": "2026-12-25", "name": "Christmas Day", "closed": true, "note": "Emergency calls only." }
  ],
  "receptionistName": "Harper",
  "greeting": "Thank you for calling Harbour Plumbing and Heating. This is Harper, an automated assistant. Calls may be recorded and transcribed to help us serve you. How can I help you today?",
  "services": [
    { "name": "Drain clearing", "price": "From $149", "description": "Residential drain clearing, same day when available." },
    { "name": "Water heater install", "price": "Quoted after assessment", "description": "Supply and install of standard residential units." }
  ],
  "faqs": [
    { "q": "Do you offer emergency service?", "a": "Yes, after-hours emergency calls are transferred to our on-call technician." },
    { "q": "What areas do you serve?", "a": "We serve Amherstburg, LaSalle, and Windsor." }
  ],
  "bookingPrefs": {
    "enabled": true,
    "mode": "request_only",
    "leadTimeHours": 2,
    "slotLengthMinutes": 60,
    "bufferMinutes": 15,
    "maxAdvanceDays": 30,
    "collectFields": ["name", "phone", "service", "preferred_time", "address"],
    "confirmationMethod": "callback",
    "notes": "Do not promise a specific technician."
  },
  "transferRules": {
    "enabled": true,
    "numbers": [
      { "label": "Office", "phone": "+15195550100", "when": "business_hours" },
      { "label": "On-call technician", "phone": "+15195550101", "when": "emergency" }
    ],
    "triggers": ["caller asks for a person", "emergency", "billing dispute", "caller is distressed"],
    "maxAttempts": 2,
    "fallback": "take_message"
  },
  "afterHours": {
    "behaviour": "take_message_and_offer_emergency_transfer",
    "greeting": "Thank you for calling Harbour Plumbing and Heating. Our office is currently closed. This is Harper, an automated assistant. Calls may be recorded and transcribed. For a plumbing emergency, I can connect you to our on-call technician. Otherwise, I can take a message and we will call you back on the next business day.",
    "emergencyTransferEnabled": true,
    "emergencyNumber": "+15195550101",
    "expectedCallback": "next business day by 10:00"
  },
  "messageDelivery": {
    "methods": ["email", "dashboard"],
    "emailTo": ["alex@example.com"],
    "smsTo": [],
    "urgentOnlySms": true,
    "dailySummary": true,
    "dailySummaryTime": "08:00"
  },
  "voice": {
    "voiceId": "21m00Tcm4TlvDq8ikWAM",
    "personality": "warm, clear, and efficient",
    "speakingRate": "normal",
    "language": "en-CA"
  },
  "instructions": "Always confirm the callback number by reading it back. Never quote a final price for repairs; starting prices only, and every job is quoted after assessment. If a caller reports flooding or a gas smell, treat it as an emergency.",
  "industry": "plumbing_hvac",
  "timezone": "America/Toronto"
}
```

Field notes for the backend:

- businessName: string, required, 1 to 120 characters. Used for the {{business_name}} dynamic variable in prompts.
- contact: object, required. email is required and must be a valid email address. phone is required, E.164. ownerName, address, and website are optional strings; the frontend sends an empty string when not provided, and the backend should store an empty string as absent.
- hours: object, required, with exactly the seven weekday keys monday through sunday. Each day has open and close in 24-hour HH:MM local time in the tenant timezone, or null when closed is true. When closed is false, both open and close are required and open must be earlier than close. Overnight hours are not supported in the first release and must be rejected with validation_failed.
- holidays: array, may be empty. Each item has date in YYYY-MM-DD, name, closed boolean, and an optional note. A holiday with closed false represents special hours, described in the note, because structured special hours are out of scope for the first release.
- receptionistName: string, required, 1 to 40 characters. The name the assistant uses for itself.
- greeting: string, required, 10 to 600 characters. Must be the first message used during business hours. The frontend ensures it includes AI disclosure and a recording and transcription notice; the backend should warn, not block, if those phrases are absent, because owners may need approved wording variations. The warning surfaces as a non-blocking notice in the save response.
- services: array, may be empty, maximum 50 items. Each item has name (required), price (free text string, may be empty; the assistant must only state prices exactly as written here and never invent one), and description (optional).
- faqs: array, may be empty, maximum 100 items. Each item has q and a, both required non-empty strings. The assistant answers only from these FAQs and the services list on factual questions.
- bookingPrefs: object, required. enabled boolean. mode is one of request_only or direct_booking; the first commercial release supports request_only end to end, and direct_booking must be rejected until a calendar integration is live, with validation_failed explaining that only request mode is available. leadTimeHours, slotLengthMinutes, bufferMinutes, and maxAdvanceDays are non-negative integers. collectFields is an array of field keys from the set name, phone, service, preferred_time, address, notes. confirmationMethod is one of callback, email, sms. notes is free text passed into the assistant instructions for booking.
- transferRules: object, required. enabled boolean. numbers is an array of label, phone (E.164), and when, where when is one of business_hours, after_hours, emergency, always. triggers is an array of free text trigger descriptions used in the system prompt. maxAttempts is an integer from 1 to 3. fallback is one of take_message or voicemail_prompt.
- afterHours: object, required. behaviour is one of take_message, take_message_and_offer_emergency_transfer, transfer_only, closed_message_only. greeting is required and follows the same disclosure guidance as greeting. emergencyTransferEnabled boolean. emergencyNumber is E.164 and is required when emergencyTransferEnabled is true or behaviour offers an emergency transfer. expectedCallback is free text the assistant may state, for example next business day by 10:00.
- messageDelivery: object, required. methods is a non-empty array drawn from email, sms, dashboard. emailTo is an array of email addresses, required non-empty when methods includes email. smsTo is an array of E.164 numbers, required non-empty when methods includes sms. urgentOnlySms boolean. dailySummary boolean, and dailySummaryTime in HH:MM local time when dailySummary is true.
- voice: object, required. voiceId is a voice identifier from GET /api/voices; the default template voice is 21m00Tcm4TlvDq8ikWAM on provider elevenlabs. personality is free text, maximum 200 characters, used to shape tone in the system prompt. speakingRate is one of slow, normal, fast. language is a BCP 47 tag, default en-CA.
- instructions: string, may be empty, maximum 4000 characters. Business-specific instructions and knowledge that do not fit the structured fields. Treated as untrusted content by the prompt builder: it may inform answers but must never override the system guardrails (no invented prices, no medical or legal advice, emergency handling).
- industry: string, required, one of plumbing_hvac, auto_repair, dental_medical, real_estate, salon_barbershop, restaurant, professional_services, general_small_business. Matches the template identifiers in the template catalogue.
- timezone: string, required, an IANA timezone name such as America/Toronto. All hours, holidays, and summary times are interpreted in this timezone.

## Endpoints

### Authentication and session

POST /api/auth/login

Request:

```json
{ "email": "alex@example.com", "password": "correct horse battery staple" }
```

Response 200:

```json
{
  "sessionToken": "sess_9f2exampletoken",
  "expiresAt": "2026-11-29T02:00:00Z",
  "user": { "id": "user_01", "email": "alex@example.com", "role": "owner" },
  "tenant": { "id": "tenant_01", "displayName": "Harbour Plumbing and Heating", "status": "active" }
}
```

Errors: 401 unauthenticated with a generic message for both unknown email and wrong password (never reveal which), 429 rate_limited after repeated failures.

POST /api/auth/logout

Header: Authorization Bearer session token. Response 204 with no body. The session is revoked server-side.

GET /api/auth/session

Header: Authorization Bearer session token. Response 200 with the same user and tenant object as login, plus role. Errors: 401 unauthenticated.

POST /api/auth/password-reset/request and POST /api/auth/password-reset/confirm

Request reset with { "email": "..." } always returns 202, whether or not the account exists. Confirm accepts { "token": "...", "newPassword": "..." } and returns 204, or 400 validation_failed for an expired or invalid token. Tokens are single use and expire within 1 hour. (Email delivery is a backend responsibility; the frontend only needs these contracts.)

### Tenants

POST /api/tenants (operator only, APEX_ADMIN_TOKEN)

Creates a tenant in trial status. Customer self-serve signup is out of scope until billing and abuse controls are ready; onboarding begins from an operator-created tenant in the first release.

Request:

```json
{
  "displayName": "Harbour Plumbing and Heating",
  "legalName": "Harbour Plumbing and Heating Inc.",
  "timezone": "America/Toronto",
  "ownerEmail": "alex@example.com",
  "ownerName": "Alex Martin",
  "planId": "professional"
}
```

Response 201:

```json
{
  "id": "tenant_01",
  "displayName": "Harbour Plumbing and Heating",
  "status": "trial",
  "timezone": "America/Toronto",
  "ownerUserId": "user_01",
  "invitationSent": true,
  "createdAt": "2026-11-28T14:00:00Z"
}
```

Errors: 400 validation_failed, 409 conflict when ownerEmail already owns a tenant in the first release.

GET /api/tenants/{tenantId} (session, any role, own tenant only; or operator token for any tenant)

Response 200:

```json
{
  "id": "tenant_01",
  "displayName": "Harbour Plumbing and Heating",
  "legalName": "Harbour Plumbing and Heating Inc.",
  "status": "active",
  "timezone": "America/Toronto",
  "phoneNumbers": [{ "id": "num_01", "phoneNumber": "+12265550199", "status": "active" }],
  "planId": "professional",
  "createdAt": "2026-11-28T14:00:00Z"
}
```

PATCH /api/tenants/{tenantId} (session, owner or admin, own tenant only)

Updates displayName, legalName, and timezone only. Configuration lives under the config endpoint, not here. Request is a partial object with any of those three fields. Response 200 returns the full tenant object as in GET. Errors: 400, 401, 403, 404.

GET /api/tenants (operator only, APEX_ADMIN_TOKEN)

Lists tenants for operations, paginated as described under Pagination. Supports a status query filter. Never available to customer sessions.

### Tenant configuration

GET /api/tenants/{tenantId}/config (session, any role, own tenant only)

Response 200:

```json
{
  "version": 7,
  "updatedAt": "2026-11-28T14:05:00Z",
  "updatedBy": "user_01",
  "config": { "...": "the full BusinessConfig document exactly as defined above" }
}
```

A tenant that has not completed onboarding returns 404 with code config_not_started, so the frontend can route the owner into onboarding instead of showing an error page. Add config_not_started to the error catalogue for this endpoint only.

PUT /api/tenants/{tenantId}/config (session, owner or admin)

Creates or replaces the configuration. The frontend always sends the complete document, never a patch, to keep save semantics simple for a nontechnical owner.

Request:

```json
{
  "expectedVersion": 7,
  "config": { "...": "the full BusinessConfig document exactly as defined above" }
}
```

expectedVersion is 0 when creating the first configuration. Response 200:

```json
{
  "version": 8,
  "updatedAt": "2026-11-28T15:00:00Z",
  "notices": [
    { "field": "greeting", "message": "Your greeting does not mention that calls may be recorded. The recommended wording is available in onboarding." }
  ]
}
```

On success the backend must validate the document against the BusinessConfig schema, persist it, increment version, invalidate the Redis cache key apex:t:{tenant_id}:config, and refresh the tenant assistant so the next call uses the new configuration without a restart. Errors: 400 validation_failed with the fields map keyed by dotted paths inside config (for example config.hours.monday.open), 409 version_conflict when expectedVersion does not match the stored version, with the current version in the error body under currentVersion.

PATCH /api/tenants/{tenantId}/config (session, owner or admin)

Reserved. The frontend does not use PATCH for configuration in the first release. If implemented later, it must follow the same version rules. Returning 405 is acceptable until then.

### Usage

GET /api/tenants/{tenantId}/usage (session, owner or admin)

Query parameters: period, either current (default) or a YYYY-MM month.

Response 200:

```json
{
  "tenantId": "tenant_01",
  "periodStart": "2026-11-01T00:00:00Z",
  "periodEnd": "2026-12-01T00:00:00Z",
  "planId": "professional",
  "includedMinutes": 500,
  "usedMinutes": 213,
  "overageMinutes": 0,
  "callCount": 96,
  "estimatedCost": { "amount_cents": 3812, "currency": "CAD", "basis": "estimated from recorded usage events" },
  "overageRate": { "amount_cents": 25, "currency": "CAD", "per": "minute" }
}
```

Rules: figures must be computed from recorded usage_events, never estimated from call counts alone. usedMinutes is the sum of billable call minutes rounded up per call, and the rounding rule must be documented here when implemented. If usage data is incomplete for a period, return a dataQuality field with the value partial and a plain note, rather than presenting a confident total.

### Calls

GET /api/tenants/{tenantId}/calls (session, any role)

Query parameters: pagination (below), plus optional from and to ISO dates, status filter (answered, missed, voicemail, failed), and a search string matched against caller number and contact name.

Response 200:

```json
{
  "items": [
    {
      "id": "call_01",
      "startedAt": "2026-11-28T13:42:00Z",
      "endedAt": "2026-11-28T13:46:00Z",
      "direction": "inbound",
      "fromNumber": "+15195550177",
      "toNumber": "+12265550199",
      "status": "answered",
      "durationSeconds": 244,
      "contactName": "Jordan Lee",
      "summary": "Caller asked about a furnace noise and requested a visit this week.",
      "appointmentId": "appt_01",
      "messageId": null,
      "recordingUrl": null
    }
  ],
  "page": { "limit": 25, "nextCursor": "cur_abc123", "total": 96 }
}
```

Rules: summary is present only when the backend has generated one from the real transcript; otherwise null. recordingUrl is a short-lived signed URL or null when no recording exists or retention has removed it. The frontend never fabricates a summary, a recording, or a status.

GET /api/tenants/{tenantId}/calls/{callId} (session, any role)

Response 200 returns the list item fields plus transcript and recording metadata:

```json
{
  "id": "call_01",
  "startedAt": "2026-11-28T13:42:00Z",
  "status": "answered",
  "fromNumber": "+15195550177",
  "toNumber": "+12265550199",
  "durationSeconds": 244,
  "summary": "Caller asked about a furnace noise and requested a visit this week.",
  "transcript": [
    { "speaker": "assistant", "text": "Thank you for calling. How can I help you today?", "atSeconds": 0 },
    { "speaker": "caller", "text": "My furnace is making a rattling noise.", "atSeconds": 4 }
  ],
  "recording": { "available": false, "reason": "Recording was not enabled for this call." }
}
```

Errors: 404 not_found for unknown or other-tenant call identifiers.

### Messages

GET /api/tenants/{tenantId}/messages (session, any role)

Query parameters: pagination, plus optional handled filter (true or false) and urgent filter.

Response 200 items:

```json
{
  "id": "msg_01",
  "callId": "call_01",
  "receivedAt": "2026-11-28T13:46:00Z",
  "callerName": "Jordan Lee",
  "callbackNumber": "+15195550177",
  "reason": "Furnace rattling noise, would like a visit this week.",
  "preferredTime": "Weekday mornings",
  "urgent": false,
  "handled": false,
  "delivery": ["email", "dashboard"]
}
```

PATCH /api/tenants/{tenantId}/messages/{messageId} (session, owner, admin, or staff)

Request: { "handled": true }. Response 200 returns the updated message. This is the only message mutation in the first release. Messages are never edited for content, because they are records of what a caller said.

### Appointments

GET /api/tenants/{tenantId}/appointments (session, any role)

Query parameters: pagination, plus optional status filter and from and to dates on requested_start.

Response 200 items:

```json
{
  "id": "appt_01",
  "callId": "call_01",
  "createdAt": "2026-11-28T13:46:00Z",
  "contactName": "Jordan Lee",
  "contactPhone": "+15195550177",
  "serviceName": "Furnace inspection",
  "requestedStart": "2026-12-01T14:00:00Z",
  "requestedEnd": "2026-12-01T15:00:00Z",
  "status": "requested",
  "notes": "Caller prefers a call before arrival."
}
```

Status values: requested, confirmed, declined, cancelled. The assistant creates appointments only in requested status. Confirmation is a human or calendar-system action, never an assistant claim.

PATCH /api/tenants/{tenantId}/appointments/{appointmentId} (session, owner, admin, or staff)

Request: { "status": "confirmed" } with optional notes replacement. Response 200 returns the updated appointment. Invalid transitions (for example confirming a cancelled appointment) return 409 conflict.

### Billing webhook placeholder

POST /webhooks/billing/{provider}

Status: placeholder contract only. Do not activate live billing against this contract without the separate business approval described in MULTI_TENANT_ARCHITECTURE.md.

Behaviour required when implemented:

- Verify the provider signature header against the webhook secret before parsing the event. Invalid signature returns 400 with no state change and an operator log entry.
- Accept and durably record every verified event before processing, keyed by the provider event identifier, so duplicate deliveries are idempotent. A repeated event identifier returns 200 with no duplicate state change.
- Event types the backend must handle: subscription created, subscription updated (plan change), subscription cancelled, payment succeeded, payment failed, subscription past due.
- Effects: update the subscriptions row for the tenant identified by the provider customer metadata, set tenant status to past_due on payment failure after the provider's retry cycle begins, and to suspended only under the documented grace policy. Never delete tenant data on a billing event.
- Response: 200 with { "received": true } for all verified events, including event types not yet handled, so the provider does not retry indefinitely. Unhandled types are logged for the operator.
- The endpoint never requires a customer session and must not accept a bearer token as a substitute for signature verification.

Companion read endpoint: GET /api/tenants/{tenantId}/subscription (session, owner only) returns plan, status, current period, and provider portal availability. It returns null subscription data with status none for trial tenants without a subscription. No endpoint in this contract creates a charge.

### Existing endpoints relied on by the frontend

These existing endpoints keep their current contracts; the frontend uses them as follows and they must not break:

- GET /api/health: used for the service status indicator in the dashboard. Must remain unauthenticated and cheap.
- GET /api/templates: source of the template catalogue. The commercial templates in prompts/templates follow the existing template schema and should appear here once loaded by the backend.
- GET /api/voices: source of selectable voices in onboarding. Each voice entry needs at minimum id, name, and provider so the picker can render. If preview audio is ever added, it must be a real sample URL or absent, never a placeholder player.
- GET /api/cost/calculate: operator and sales estimation use. Not a substitute for per-tenant usage.
- GET /api/settings, /api/operations, /api/dashboard, /api/calls, /api/calls/{id}, /api/receptionist/messages, /api/assistants: existing operator surfaces. During migration these should be re-scoped to the original backfilled tenant for operator use, and customer traffic should move to the tenant-scoped endpoints above. The customer dashboard must not be built on the unscoped versions once tenant endpoints exist.

## Pagination

List endpoints use cursor pagination:

- Query parameters: limit (default 25, maximum 100) and cursor (opaque, from a previous response).
- Response page object: limit, nextCursor (null on the last page), and total where the backend can provide it cheaply; total may be omitted rather than computed expensively, and the frontend must handle its absence.
- Ordering is stable and documented per endpoint: calls by startedAt descending, messages by receivedAt descending, appointments by requestedStart ascending.

## Versioning and change control

- Contracts are versioned by this document's pull request history. Breaking changes (removed fields, renamed fields, new required fields, changed status codes) require a contract update agreed by both agents before code ships on either side.
- Additive changes (new optional response fields, new endpoints) are safe and only need a note in this document.
- The BusinessConfig schema is frozen for the onboarding frontend build. Any new required configuration field must first be added here as optional, shipped in the backend as accepted-but-optional, and only promoted to required after the frontend sends it.

## Open questions for the backend agent

- Session mechanism: signed JWT or opaque server-side session token. The frontend works with either, but revocation behaviour differs and must be stated here once chosen.
- Billable minute rounding rule for usage (per call round up to the next minute is assumed above).
- Whether appointment confirmation will integrate a calendar system in the first release or remain a manual dashboard action. The contract supports both; the frontend copy assumes manual until told otherwise.
- Recording storage location and signed URL lifetime, which the dashboard needs to render the recording control honestly.
