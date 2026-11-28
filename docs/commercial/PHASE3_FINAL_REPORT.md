# ApexVoice Phase 3: final report

Prepared 2026-11-28. This branch (feature/apex-phase3-multitenant) is stacked on feature/apex-commercial-readiness (PR #7, commit 1567c01) and its PR targets that branch, so PR #7 is untouched and nothing here merges into main. Every file in this phase is an addition. No shared backend files were modified, no live calls were enabled, and no billing was activated.

## Implemented features

* Multi-tenant layer, package tenancy/ (stdlib only, importable standalone)
  * Individual business accounts with collision-checked ten_ tenant IDs, E.164 number normalization, and a phone number to tenant mapping table. Routing resolves the tenant from the called number and rejects unknown numbers and suspended tenants.
  * Secure customer authentication: PBKDF2-HMAC-SHA256 password hashing at 210,000 iterations with per-user salts, opaque session tokens stored only as SHA-256 hashes, 12 hour expiry, logout revocation, and password change revoking all sessions. Unknown email and wrong password return the identical error.
  * Roles owner, admin, staff, and viewer over the contract permission set. Only the owner can suspend or delete their own tenant. Harbour & Main as platform operator is a separate principal type and the only one allowed cross-tenant lifecycle actions.
  * Tenant-specific configuration validated against the frozen BusinessConfig schema, tenant-specific Redis keys and call admission (apex:t:{tenant_id}: builders for the call lock, monthly accounting, clips, call state, and config), and separate calls, messages, appointments, transcripts, customers, and usage, every record carrying tenant_id and every store query filtering by it. Two store implementations with identical behaviour: in-memory and SQLite.
  * Per-tenant usage metering (minutes rounded up per call, calls, TTS characters, STT seconds), plan limits from the recommended tiers, CAD-cent spend estimates, and a per-tenant hard stop.
  * Lifecycle: platform-gated create, suspend, reactivate, and delete with a full purge plus a platform audit entry that survives the purge. Migration builds the Harbour & Main tenant (ten_harbour_main) from either a full BusinessConfig or the legacy env-style settings, so the existing single-business installation becomes the first tenant with its number, config, and owner login resolving through the new layer.
* Voice provider system, package voice/
  * Registry of eight providers (SignalWire carrier Say, ElevenLabs Turbo and Flash, Azure Speech, Google TTS, Amazon Polly, Kokoro self-hosted, Piper self-hosted) with per-1,000-character rates, sources, and licences in voice/cost_model.json.
  * Per-tenant voice selection with standard and premium tiers and fallback chains that end at carrier speech exactly once. One tenant can run premium while another runs standard, with no shared state.
  * Phrase cache for greetings, disclosures, and other repeatable phrases, keyed by tenant, provider, voice, model, and text hash, with TTL and size caps. Caller-specific text is refused by kind and by content heuristics, and cache entries are never shared across tenants.
* Stripe billing readiness, package billing/ (test mode only)
  * Hard guard: any live mode configuration raises an error, and live-prefixed keys are rejected even in test mode. No network calls exist anywhere in the package.
  * Full webhook signature verification (HMAC SHA256 over timestamp and body, 300 second tolerance, secret rotation support, distinct error codes), a per-tenant subscription state machine with a 7 day payment failure grace period that flags suspension for a human decision instead of acting automatically, per-tenant usage reconciliation with drift detection, and pure payload builders for checkout, billing portal, and plan changes carrying tenant metadata and no secret material.
* Harbour & Main site pack, site/harbourandmain-ai-receptionist/
  * Draft product page with how it works, features, the eight industries, tier comparison, pricing marked in the file header as not approved for publication, AI and privacy disclosures, FAQ, and a request-a-demo form that works with no backend (validated form, on-page summary, mailto composition, copy button, nothing stored). Plus a demo embed wrapper driven by one documented URL variable, a copy pack, and integration instructions. The live website was not modified.
* Verified telephony costs, docs/commercial/TELEPHONY_COST_VERIFICATION.md, from SignalWire's official pricing page, Canada section, read in full on 2026-11-28.
* Browser testing of the PR #7 pages, docs/commercial/BROWSER_TEST_RESULTS.md with 15 screenshots in docs/commercial/browser-tests/ and the runnable script at scripts/browser_commercial_check.mjs.

## Multi-tenant security test results

* Full suite on this branch: 176 tests, all passing (82 tenancy, 27 voice, 56 billing, 11 commercial readiness from Phase 2).
* Isolation suite, run against both store implementations: tenant B cannot read, list, update, or delete tenant A's configuration, calls, messages, appointments, transcripts, customers, or usage, by direct ID or by list query. A forged update carrying the victim's record ID under the wrong tenant scope fails and leaves the data unchanged. Reassigning a phone number across tenants raises a conflict.
* Auth and RBAC suite: sessions are tenant-bound, expired and revoked sessions fail, tenant B's login always binds to tenant B's scope, viewers cannot write, staff cannot manage users or billing, admins cannot run lifecycle actions, and tenant principals are denied every action on another tenant.
* Usage and lifecycle suite: exhausting tenant A's 120 minutes hard-stops A while tenant B keeps its full 350. Redis keys and locks never collide across tenants, and releasing A's lock never releases B's. Suspension blocks routing for A only. Deleting A purges its config, number mapping, users, and every record kind while B stays fully intact, and the deletion remains auditable. Migration produces a working Harbour & Main tenant.

## Browser screenshots

* 34 of 34 checks passed in real Chromium at mobile 390 by 844, tablet 834 by 1112, and desktop 1440 by 900: page loads, no horizontal overflow, no page errors, onboarding validation and template prefill, full wizard to review, configuration JSON download verified by parsing, dashboard honest error state, demo booking flow with a verified real .ics download, message flow, 911 emergency flow, and voice preview button presence.
* Screenshots: docs/commercial/browser-tests/ (onboarding, dashboard, and demo at three sizes, plus filled step 1, review, dashboard error state, booking, conversation, and mobile flow captures). Two were visually inspected during the run and match the intended layout.
* One test-script defect was found and fixed during the run (lowercase versus camelCase element IDs in the script, not the pages). No page defects were found. The dashboard's populated live-data paths still need a running backend to exercise, which belongs to the backend agent's staging work.

## Verified operating costs and voice comparison

Confirmed from SignalWire's published Canada pricing, 2026-11-28: inbound local voice $0.0066 USD per minute, outbound $0.0080, local DID $0.50 USD per month, recording $0.002 per minute (off by default in ApexVoice, so $0 today), SIP Refer transfer $0.10 per refer plus the outbound leg, and text to speech per character from $0.000008 (Economy) through $0.000032 (Economy+, includes Google Neural2 and Amazon Neural) and $0.0001 (Standard, includes ElevenLabs Flash and Turbo served through SignalWire) to $0.0002 (Pro).

Per call minute totals at 425 spoken characters, FX 1.36, other lines held at the audited $0.031 CAD:

* Current premium, ElevenLabs Turbo direct: $0.135 CAD. The cost target work reconciles this with the Phase 2 audit to within $0.001, enforced by a test.
* New standard tier, SignalWire Say with an Economy+ neural voice: $0.0495 CAD, under the $0.07 target.
* Azure Neural about $0.0396, Google Neural2 and Polly Neural about $0.0402 each as hosted alternatives.
* Self-hosted estimates, labelled as estimates with infrastructure allowances and not as prices: Kokoro about $0.0339, Piper about $0.0333. The Oracle Always Free reality check, the idle reclamation risk, and the shared-with-other-bots warning are in VOICE_COST_OPTIMIZATION.md.
* Phrase caching at a modelled 30 percent repeatable share: standard about $0.0439, premium about $0.1038, with the caveat that carrier Say phrases must be pre-rendered to audio to benefit.
* VoiceStudio fork finding: it is a desktop AGPL-3.0 application whose default model weights are non-commercial, and its images target amd64 while the Oracle free tier is ARM. Patterns only, no code reused.

## Updated subscription profitability

At full use of included minutes with $7 CAD fixed cost per tenant per month, from VOICE_COST_OPTIMIZATION.md:

* On the standard voice tier: Starter $49 CAD with 120 minutes about 73.6 percent gross margin, Professional $99 with 350 about 75.4 percent, Business $199 with 800 about 76.6 percent.
* On the premium voice tier: Starter about 52.6 percent, Professional about 45.2 percent, Business about 42.2 percent.
* Recommendation: sell the standard tier as the default voice, offer ElevenLabs premium as a paid upgrade or as the Business tier voice, and meter transfer events per tenant because each SIP Refer costs $0.10 USD plus outbound minutes.

## Backend integration requirements

* docs/commercial/BACKEND_INTEGRATION_PATCH_SPEC.md lists the exact seven steps for the backend agent, marked do not apply until Command Code finishes: schema migration with backfill to ten_harbour_main before any not-null constraint, a TENANCY_ENABLED flag with legacy env settings demoted to fallback, tenant resolution hooked into the voice webhook after signature validation, replacing the global lock and accounting keys with the per-tenant builders, customer routes as thin adapters over the tenancy package with the shared admin token retired for customer routes only, phone inventory through the mapping table, and a staged rollout gated on this isolation suite passing against the integrated build.
* Voice integration points (provider selection at clip creation, Say versus Play decision, cache lookup before synthesis) and billing integration points (webhook, checkout, portal, and change-plan routes, plus the suspension flag hook) are documented in their respective docs.
* The site pack needs a coordinated deploy to harbourandmain.com with the demo URL variable set, and written pricing approval before the draft pricing is published.

## Remaining commercial launch blockers

* Backend integration of the tenancy, voice, and billing packages has not happened. Until the patch spec is applied by the backend agent after Command Code finishes, the running service is still single-tenant and this code is a tested library, not a live multi-tenant service.
* Speech recognition billing on Gather is still unverified. SignalWire lists Speech-to-Text at $0.015 USD per 15 seconds per use, but how Gather maps to uses and segments is not published. Worst case continuous billing adds up to roughly $0.075 CAD per minute over the modelled allowance and erases the standard tier advantage. Closing this needs a real invoice from representative test traffic, which needs Josh's approval to run.
* The ElevenLabs account's actual rate track (subscription credit-effective versus direct API list) is unverified and changes the premium tier cost materially. It is an account page or invoice check.
* Prices are still recommendations, not approved. Legal review of the Phase 2 drafts, Canadian GST/HST setup, and Josh's explicit approval are all required before Stripe could ever leave test mode, and the billing package is built to refuse live mode until its guard is deliberately revised.
* Carrier-side hard call duration cutoff and live provider verification remain open from RELEASE_STATUS.md and belong to the backend reliability work.
