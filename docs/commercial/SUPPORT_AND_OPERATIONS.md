# ApexVoice support and operations manual

Prepared for: Harbour & Main, operator of ApexVoice, Phase 4
Status: Operating manual for the support and readiness tooling in the support/ package. Read with PRIVACY_AND_TRUST.md and the data retention draft, which govern anything this manual says about customer data.

## Support workflow, end to end

The support/ package implements the mechanics. This section is the human workflow around it.

* Intake. A request arrives as a ticket in the support store, created either by the customer from their dashboard (tenant viewer, their own tenant only) or by the operator on the customer's behalf after an email or call. Every ticket carries a tenant, a category (billing, technical, configuration, outage, other), a priority (low, normal, high, urgent), a subject, and a body. Customers are told not to paste caller sensitive information into tickets; if they do, the operator notes it and follows the retention rules for support communications.
* Triage. The operator reviews new tickets against the internal SLA targets in support/tickets.py. Those targets (for example, acknowledge an urgent ticket within 1 hour, a normal ticket within 8 hours) are internal operating targets only. They are never quoted to customers as promises and appear in no contract.
* Work. The operator moves the ticket through the statuses: open, acknowledged, in_progress, waiting_customer (blocked on the customer), resolved, closed. Every status change is written to the ticket's audit trail with the actor and the time. The customer can see their own tickets and their status, can close their own resolved ticket, and can reopen a resolved or closed ticket.
* Escalation. Either the customer or the operator can escalate a ticket, and a reason is always required. Escalation raises the priority one step and flags the ticket as escalated, with the reason in the audit trail. Escalated tickets are reviewed first at the next triage pass.
* Closure. A ticket is resolved when the underlying issue is fixed or answered, and closed when the customer confirms or after the operator resolves it and the customer does not reopen it. The audit trail is the record of what happened; do not edit history, add a new entry instead.
* Visibility rule. A tenant can never see another tenant's tickets, in any view or export. The platform operator sees all tickets. If a customer reports seeing anything from another business, treat it as a severity 1 incident (below), not a support ticket.

## Notification map

All notifications are payloads built by support/notifications.py. Nothing sends during testing: builders are wired to the Harbour & Main email infrastructure (Resend, sending from the harbourandmain.com domain, service mail from josh@harbourandmain.com) only by a separate, approved backend change. Until that wiring exists and is approved, every payload below is built and inspected only, and no customer communication is sent.

| Event | Payload builder | Recipient | Suppression |
|---|---|---|---|
| A provider outage affecting service begins | provider_outage_notice | The tenant's configured message delivery email addresses | Once per incident id per tenant; repeat builds for the same incident return nothing |
| Failed calls in a window reach the threshold (default 3) | failed_call_alert | The tenant's delivery email addresses | Once per tenant per window |
| Usage reaches 80 percent of included minutes in a period | usage_threshold_warning | The tenant's delivery email addresses | Once per tenant, per period, per threshold |
| Usage reaches 100 percent of included minutes in a period | usage_threshold_warning | The tenant's delivery email addresses | Once per tenant, per period, per threshold |
| Monthly period closes | monthly_usage_summary_email wrapping summaries.py output | The tenant's delivery email addresses | Built once per period by the operator's schedule |
| A subscription payment fails (verified billing webhook) | payment_failure_notice | The tenant's billing contact | Built once per verified failure event by the billing flow |

Notes on the map:

* The payment failure notice states the billing grace policy as implemented in billing/state.py: the subscription goes past due, service continues during the 7 day default grace period, and if grace expires unpaid the billing layer only recommends suspension. A human decides. The notice must never say service has been or will be automatically cut off, because it is not.
* Outage notices never name other affected tenants and never include any other customer's information.
* Notification bodies contain no caller personal information beyond counts and times. If a future notification needs caller details, it needs a privacy review first.

## Incident reporting

Severity levels:

* Severity 1: service down or unsafe. Examples: calls not answered across tenants, any cross-tenant data exposure, disclosure failure on live calls, suspected breach of security safeguards. Response: immediate, page the operator, stop the affected service if needed, open the incident record at once.
* Severity 2: service degraded for one or more tenants. Examples: a provider outage affecting some calls, repeated failed calls for one tenant, billing webhooks failing. Response: same business day, incident record opened, affected tenants notified through the notification map once the sending path is live and approved.
* Severity 3: single tenant problem with a workaround. Examples: a configuration error, one tenant's usage mismatch, a dashboard login problem. Response: handled as a support ticket, upgraded to an incident if it turns out to be wider.
* Severity 4: questions and minor issues. Handled as support tickets, no incident record.

Incident record template:

* Incident id, date and time opened, opened by, severity.
* Summary: what is happening, in plain language.
* Scope: which tenants, numbers, and providers are affected, and how that was determined.
* Timeline: detection, decisions, actions, provider responses, resolution, each with times.
* Customer impact: calls affected, messages delayed or lost, charges affected.
* Communications: which notification payloads were built and, once sending is live, sent, to whom, and when.
* Root cause and evidence links.
* Follow-up actions with owners and dates.
* Privacy assessment: whether caller or customer personal information was exposed, and if so, the breach record and notification duties from PRIVACY_AND_TRUST.md are triggered and legal review is engaged.

## Recovery procedures

### Provider outage

* Confirm the outage is the provider's (provider status and a test call), not our configuration.
* Build the outage notice payloads for affected tenants (they send only once the approved sending path is live).
* If the provider supports failing over to a secondary path or voice provider, follow the voice selection fallback configuration rather than improvising.
* During the outage, confirm the safe failure behaviour: calls that cannot be handled fail cleanly and are logged as failed calls, which feeds the failed call alert threshold.
* On restoration, run one test call per affected tenant before declaring recovery, reconcile failed call counts, and close the incident with the timeline.

### Redis loss

Redis holds live call state, per-tenant call locks, accounting counters, and cached clips in the current architecture. Losing it mid-service:

* Expect in-flight call state to be lost. Calls in progress may drop or fail to complete their records. That is the known cost; do not promise otherwise.
* On Redis recovery, check for stuck per-tenant call locks before resuming service for a tenant. A lock left behind by a dead call blocks that tenant's next call, so the recovery check is: for each active tenant, confirm no active call lock exists without a matching live call, and clear orphaned locks with the action recorded in the incident or ticket audit.
* Rebuild accounting expectations from the durable call and usage records in the store, and compare against the Redis counters. Where they differ, the durable records win, and the difference is noted for the usage reconciliation.
* Resume service tenant by tenant with a test call each, not all at once.

### Configuration corruption

* Symptoms: a tenant's receptionist behaves as if it has the wrong business information, or config validation fails on load.
* Restore from the configuration backup produced by support/exports.py config_backup, which is the same BusinessConfig document the onboarding wizard downloads. Re-validate through TenantConfig before storing; a backup that does not validate is not restored, it is investigated.
* If no backup exists, rebuild from the tenant's onboarding answers with the customer on the call, and treat the gap as a process failure: every configuration change from then on takes a backup first.
* Record what was corrupted, what was restored, and the version numbers involved, in the ticket or incident record.

### Accidental suspension

* Confirm the suspension was accidental (check the lifecycle audit entry: who suspended, when, and whether a billing suspension recommendation was involved).
* Reactivate through the tenancy lifecycle, which is a platform operator action and writes its own audit entry. Never edit the tenant status directly in the store.
* Run a test call to the tenant's number before telling the customer service is back.
* If the suspension came from a billing grace expiry, confirm the payment position with the customer first; reactivating billing-suspended tenants without resolving the payment restarts the same cycle.

## Troubleshooting guide

### Call not routed (caller reaches nothing, or the wrong business)

* Check the phone mapping: is the dialled number mapped, and to which tenant? An unmapped number is rejected by design.
* Check the tenant status: suspended and deleted tenants do not route.
* Check the provider side: is the number's webhook configuration pointing at the current application, and is the provider reporting delivery of the call webhook?
* Check the per-tenant call lock: a stuck lock from a dead call presents as calls not being answered. Clear it per the Redis recovery procedure and record the action.
* If the caller reached the wrong business, stop and treat it as severity 1 until tenant resolution is proven correct, because wrong routing is one step from cross-tenant exposure.

### Tenant locked out (dashboard login failing)

* Distinguish a forgotten password from a disabled user and from an expired or revoked session. Sessions expire after 12 hours by design; that alone is not a lockout.
* Password reset goes through the auth service, which stores only password hashes; support never sees or sets a plaintext password for a customer.
* Check the user status and role in the tenant's user list. A user set to a non-active status cannot sign in.
* If the owner is locked out and no other owner or admin exists for the tenant, identity verification is required before the operator creates or resets an owner account: verify against the contact details and billing identity on the account, and record the verification in the ticket audit. Never bypass this because a caller sounds convincing.

### Usage mismatch (customer disputes minutes or charges)

* Pull the tenant's usage records and the summaries.py monthly summary for the period, and the provider usage records for the same window.
* Check the known mechanics first: minutes are rounded up per call, so many short calls produce more billable minutes than the raw talk time suggests. Most mismatches are this.
* Reconcile with billing/usage.py reconcile_usage and report drift per call. Where the app over-recorded, correct the record and note the correction in the ticket. Where the provider record differs from both, escalate to the provider with the call SIDs.
* Remember the standing caveat until the billing verification exercise completes: Gather recognition billing is measured, not assumed, only after that exercise. Do not assert a recognition charge explanation to a customer before then.

### Webhook failures (billing or telephony events not arriving or failing verification)

* For billing webhooks: check the signature verification result first. The billing package rejects events with invalid signatures by design; a spike in rejections can mean a rotated secret that was not updated, which is an operator fix, not a customer problem.
* Check for duplicate deliveries: handlers are idempotent, so duplicates are expected noise, not errors. Look for gaps instead: a subscription change with no matching event.
* For telephony webhooks: check provider delivery logs against application logs by call SID. A call with a provider record and no application record means the webhook path is broken, which is severity 2, or severity 1 if calls are being missed.
* Never resolve a webhook problem by disabling signature verification, even temporarily.

## Backup and export schedule

* Configuration backups: a config_backup export is taken on every configuration change, before the change is stored, and kept with the tenant's records. This is what makes the corruption recovery procedure possible.
* Full tenant export: support/exports.py export_tenant_data produces the tenant record, configuration, number assignments, public user list, and call, message, appointment, and usage records, with credential and session material excluded by construction and verified by the export safety scan. Exports are produced on customer request, before any destructive lifecycle action, and on account closure (see below).
* Operator schedule: weekly, confirm configuration backups exist for every active tenant; monthly, run a restore-readiness check (support/exports.py restore_readiness_check) against a sample of backups so a corrupt backup is found in a drill, not during an incident.
* Retention of exports and backups follows RETENTION_DEFAULTS in support/exports.py, which mirrors the Phase 2 privacy analysis recommendations (transcripts 90 days on Starter, 12 months on Professional, 24 months on Business; recordings 30 days where enabled; call metadata 24 months; support communications 24 months; backups rolling and deleted within 30 days of source deletion). Those figures are recommendations pending legal review and adoption, and this manual must be updated when the adopted policy lands.

## Cancellation and data deletion procedure

* Request. Cancellation or deletion starts from a request by the tenant's owner, in the dashboard or in writing. Support confirms the requester's identity against the account's owner user and billing contact before acting.
* Export offer. Before anything is deleted, the customer is offered a full export of their data through export_tenant_data, and the closure export window from the retention draft applies: a recommended 30 days to download configuration, contacts they created, messages, and transcripts still held.
* Confirmation of scope. The customer is told, in plain language, what will be deleted (tenant configuration, call records, messages, appointments, transcripts, contacts, usage records, dashboard users, phone mappings), what is kept and why (billing and tax records for the period Canadian law requires, security and audit logs for their retention period, and the platform audit entry recording the deletion itself), and that backups cycle out within the backup retention period, after which deletion is complete.
* Purge. Deletion is executed through the tenancy lifecycle delete_tenant, by the platform operator or the tenant's own owner. The lifecycle purges every record the tenant owns and leaves the platform audit entry, so the deletion remains verifiable. No one deletes tenant data by hand from the store.
* Number handling. The customer is told the release date for any number assigned through ApexVoice and that a released number can be reassigned by the carrier. A customer who needs to keep a number must arrange porting before closure, where porting is supported. Support never ports a number as part of a cancellation without a separate instruction.
* Confirmation. After the purge and after backups have cycled out, the customer receives a closure confirmation listing the categories deleted, the categories kept by law, and the backup completion date. During testing and before the sending path is approved, this confirmation is prepared as a document for the operator, not sent.
* Caller requests. A caller who asks for their own information to be deleted is directed to the business customer, which controls the record; support helps the business locate and delete the caller's records inside that business's tenant only, per the retention draft.

## Standing rules for operators

* Never view a tenant's transcripts or messages beyond what the task requires, and never copy customer data out of the export path.
* Never send a customer communication from a builder payload during testing. Payloads are inspected, not sent, until the sending wiring is built and approved.
* Never invent an explanation. If a charge, a behaviour, or a failure is not yet verified, say so, in the ticket and to the customer, and record what would verify it.
* Every destructive or account-changing action goes through the lifecycle and auth services so it lands in an audit trail. If a tool would bypass the audit trail, do not use it.
