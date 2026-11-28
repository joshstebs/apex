# ApexVoice billing readiness: Stripe test mode

Status: preparation only. This package is test mode only, end to end. No live
keys, no real charges, no activated billing. Prices below are the recommended
tiers from the commercial audit. They are not approved prices.

Package layout, all standard library, no Stripe SDK, no network calls:

- billing/config.py: configuration with a hard test mode guard
- billing/tiers.py: tier definitions and the Stripe test dashboard checklist
- billing/webhooks.py: webhook signature verification and event parsing
- billing/state.py: per tenant subscription state machine
- billing/usage.py: per tenant usage totals and reconciliation
- billing/payloads.py: pure request payload builders that send nothing

## Hard guards

- BillingConfig refuses to construct unless the mode is test.
  APEX_BILLING_MODE unset means test. APEX_BILLING_MODE set to live, or to
  anything else, raises BillingModeError.
- A live Stripe key supplied by accident also raises BillingModeError, even
  when the mode says test.
- Secret values are never printed, logged, or shown in repr. Config reports
  only which environment variable names are in play and whether each is set.
- Tier Stripe identifiers (price_id, overage_price_id) stay None until a
  person creates the matching objects in the Stripe test dashboard. Payload
  builders substitute an obvious placeholder string, never a guessed id.
- Webhook handlers must verify before parsing. verify_and_parse is the only
  supported order.

## Stripe test mode setup checklist

Work through billing/tiers.py stripe_setup_checklist() in the test
dashboard. Summary:

- Confirm the Stripe account shows test mode before creating anything.
- Create one product per tier: ApexVoice Starter, Professional, Business,
  and Enterprise.
- Create recurring monthly CAD prices for the self serve tiers and record
  each id in tiers.TIERS price_id:
  - Starter: $49.00 CAD per month, 120 included minutes
  - Professional: $99.00 CAD per month, 350 included minutes
  - Business: $199.00 CAD per month, 800 included minutes
  - Enterprise: custom, from $499.00 CAD per month, sales assisted only, no
    self serve price and no checkout payload
- Create a billing meter named apexvoice_overage_minutes with summarize
  aggregation, and a metered overage price per self serve tier linked to it:
  Starter $0.40 CAD per minute, Professional $0.35, Business $0.30. Record
  each id in tiers.TIERS overage_price_id.
- Configure the customer billing portal in test mode: plan change,
  cancellation, invoice history, and payment method update enabled. The
  portal configuration lives in Stripe, not in code. Pass its test mode
  configuration id to build_billing_portal_payload only if a non default
  configuration is used.
- Create the webhook endpoint for the backend billing route (see integration
  points) in test mode, subscribed to the events in the table below, and
  store its signing secret under the environment variable name
  STRIPE_WEBHOOK_SECRET on the backend only.
- Run the full test suite against Stripe test clocks and test cards before
  anyone talks about real customers: successful payment, failed payment,
  recovery inside grace, grace expiry, upgrade, downgrade, cancellation.

## Event handling

All events arrive per tenant. The tenant id is read from the event object's
metadata.tenant_id, falling back to subscription metadata, then to
client_reference_id on checkout sessions. An event whose tenant id does not
match the subscription's tenant on file must be rejected and logged, never
applied to another tenant.

| Event | State effect | Notes |
| --- | --- | --- |
| checkout.session.completed | none, incomplete, or canceled to active | Also captures customer and subscription ids and tier from metadata |
| customer.subscription.created | none or incomplete to the status Stripe reports | trialing, active, or incomplete, mirrored from the object status |
| customer.subscription.updated | Mirrors the reported status | Plan changes and status changes both arrive here |
| customer.subscription.deleted | Any state to canceled | Clears past due bookkeeping |
| invoice.paid | past_due, unpaid, incomplete, or trialing to active | Recovery path. Clears failure count and past due start |
| invoice.payment_failed | active, trialing, or incomplete to past_due | Opens grace on first failure, increments failure count after |
| invoice.finalized | No state change | Recorded so the invoiced total can be reconciled against local usage |

Handlers are idempotent for repeat delivery of the same event id, and
unknown event types are noted in history and ignored rather than raising.

## Payment failure and grace policy

- Grace period: 7 days by default, configured per record as grace_days.
- On the first invoice.payment_failed the subscription goes past_due and
  service continues. The caller experience does not change during grace.
- Reminders to the business owner are a product decision still to be wired
  by the backend agent. This package only tracks state. Recommended: email
  on failure, again at day 3, and a final notice at day 6.
- If grace expires with no invoice.paid, evaluate_grace moves the record to
  unpaid and sets suspend_recommended. That flag is the hook for the tenancy
  lifecycle. Nothing in this package suspends a tenant, stops calls, or
  changes telephony by itself. A human approved backend process decides what
  suspension means and when it happens.
- An invoice.paid at any point before cancellation recovers the record to
  active, clears the failure count, and clears the suspension flag,
  including after grace expiry.

## Usage and reconciliation procedure

- Rounding: minutes round up per call, matching telephony practice. Period
  totals are sums of per call rounded minutes.
- Nightly, per tenant: summarize_usage totals the period from call records.
  Records belonging to other tenants are ignored by construction, so a mixed
  export cannot cross bill.
- Before period close: build the meter report with meter_report_payload
  (one summarize event per tenant per period carrying overage minutes) and
  hand it to the backend route that submits meter events. This package never
  submits it.
- After Stripe reports usage back: reconcile_usage compares locally metered
  overage minutes against reported minutes. Drift is the absolute
  difference. Drift greater than 5 minutes (the default threshold) is
  flagged for a human to investigate before the invoice is trusted. Drift at
  exactly the threshold is not flagged.
- Enterprise usage is tracked locally the same way, but overage is priced
  from the contract. summarize_usage deliberately returns None for
  enterprise overage rather than inventing a rate.

## Backend integration points

These are for the backend agent, after the reliability work lands. This
package does not modify any shared backend file.

- Add one route, POST /api/billing/webhook, in the backend. It reads the raw
  request body, takes the Stripe-Signature header, loads BillingConfig from
  the server environment, calls verify_and_parse, resolves the tenant from
  the event, loads that tenant's SubscriptionRecord, calls handle_event, and
  persists the record. Respond 200 only after the state is stored. Respond
  400 with the webhook error code on verification failure, and never log the
  secret or the full header.
- Add POST /api/billing/checkout for a signed in tenant owner or admin. It
  builds the payload with build_checkout_session_payload using return URLs
  on the Harbour & Main domain, then creates the session with the test key
  it loads itself. The tenant id in metadata and client_reference_id is what
  ties the returning webhook events back to the tenant.
- Add POST /api/billing/portal for a signed in tenant owner or admin. It
  builds the payload with build_billing_portal_payload from the tenant's
  stored Stripe customer id.
- Add POST /api/billing/change-plan for upgrades and downgrades. Upgrades
  use proration_behavior create_prorations or always_invoice. Downgrades
  should use none so the change lands at period end, unless Josh approves a
  different policy.
- Tenancy hook: the tenant lifecycle reads SubscriptionRecord state and the
  suspend_recommended flag. Suspension, when the backend implements it,
  means the tenant's receptionist stops accepting new calls and the
  dashboard shows a billing notice. It never deletes tenant data. Data
  deletion stays under the retention and deletion policy in
  docs/legal-drafts, not under billing.
- Storage: SubscriptionRecord is a plain dataclass. Persist it with the
  tenant's other records, keyed by tenant id, alongside the Stripe customer
  and subscription ids it carries.
- Scheduler: run evaluate_grace per past_due tenant at least daily, and run
  the usage reconciliation at every period close.

## Before live mode could ever be considered

None of this is done, and none of it is authorised by this document:

- Josh's explicit approval of live billing, in writing, for this service.
- Final approved prices. The tiers here are recommendations from the
  commercial audit, not approved prices.
- Professional legal review of the terms of service, privacy policy, and
  the rest of docs/legal-drafts.
- Canadian tax setup: GST and HST registration position confirmed, tax
  collection configured in Stripe Tax or an equivalent, province by province
  handling reviewed, and invoice wording checked. Quebec rules need their
  own review alongside the Law 25 decision.
- A live mode code change reviewed on its own: the BillingModeError guard
  in billing/config.py must be deliberately revisited, not bypassed, with
  live keys loaded from the vault and never from chat or files.
- Webhook endpoint, portal configuration, products, prices, and meter all
  recreated in live mode and retested, since test mode objects do not carry
  over.
- Reconciliation run in test mode for at least one full billing cycle with
  zero unexplained drift, and the failure and grace flow exercised with
  Stripe test clocks.
- A rollback plan: how subscriptions are paused and customers contacted if
  the first live invoices are wrong.

## Tests

- test_billing_webhooks.py: signature acceptance, tampered body, wrong
  secret, stale and future timestamps, missing and malformed headers,
  secret rotation with two v1 values, event parsing and tenant extraction.
- test_billing_state.py: checkout, trial, cancellation, and resubscribe
  paths, failure to grace, grace expiry to unpaid with the suspension flag,
  recovery inside and after grace, repeated failures, invalid transitions.
- test_billing_usage.py: per call rounding, overage math at each self serve
  tier at the limit and one minute over, cross tenant record isolation,
  meter payload shape, reconciliation drift thresholds, the live mode
  guard, and payload builders carrying tenant metadata with no secret
  material in any output.
