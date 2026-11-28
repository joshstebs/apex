# ApexVoice Integration Review: Existing Forked Repositories

Purpose: Review four repositories Josh has forked, cal.diy, chatwoot, VoiceStudio, and openproject, and decide what, if anything, ApexVoice should take from each to improve the commercial product without adding unnecessary dependencies or recurring subscription costs.

Method and limits: This review is based on each project's known purpose, architecture, and licence as recorded in the fork information provided for this review. Code was not copied from any of these repositories in preparing this document, and no repository was modified. Before any code reuse, a developer must re-verify the licence of the exact version and files in question, including any licence files in subdirectories, because large projects sometimes carry different terms for different parts.

General rule applied throughout: Reading a project to learn a proven pattern, then writing original ApexVoice code that follows the pattern, is low risk for every licence below. Copying code is a different act with licence consequences, and the stricter the licence, the stronger the reason to learn the pattern and write our own implementation. ApexVoice is a commercial subscription service, so licence obligations that trigger on distribution or on offering the software as a network service matter directly.

## Summary of recommendations

- cal.diy: Use patterns only, with code reuse permitted if ever needed under MIT terms with attribution. Highest practical value of the four.
- chatwoot: Use patterns only. Do not copy code until the licence position of the specific edition and files is confirmed by legal review, because the fork licence is recorded as Other / NOASSERTION and the project includes enterprise material under separate proprietary terms.
- VoiceStudio: Use patterns only. Do not copy code. AGPL-3.0 code must not be copied into ApexVoice without legal review.
- openproject: Do not incorporate. Low relevance to ApexVoice, and GPL-3.0 code must not be copied into ApexVoice without legal review.

## cal.diy

Repository: Fork of calcom/cal.diy. Licence: MIT for the cal.diy open source edition.

What it is: A scheduling and booking platform: event types, availability schedules, booking pages, and calendar conflict handling.

What is reusable for ApexVoice:

- Availability modelling. The pattern of a weekly schedule with per-day working hours, date-specific overrides for holidays, and a default schedule per bookable resource maps directly onto ApexVoice business hours and holiday handling in the BusinessConfig schema. ApexVoice already stores hours and holidays in that shape, and cal.diy is a useful reference for edge cases such as holidays that fall on normally closed days.
- Booking request flow. The separation between a booking being requested, held, confirmed, and cancelled, with clear status transitions and notifications at each step, is exactly the lifecycle ApexVoice appointments need. ApexVoice templates already describe appointment tool calls as requests, not confirmations. cal.diy demonstrates how to keep that distinction honest in a user interface: show requested times as pending until a human or a calendar confirms them.
- Slot calculation patterns. Computing bookable slots from opening hours minus existing bookings, with lead time, buffer time, and maximum advance booking windows, matches the bookingPrefs fields in the BusinessConfig schema (leadTimeHours, slotLengthMinutes, bufferMinutes, maxAdvanceDays). If ApexVoice later moves from request-only booking to direct booking, this is the reference implementation to study first.
- Timezone handling discipline. A scheduling product that serves many businesses is a good reference for storing times in UTC, interpreting business hours in the business timezone, and presenting times to each viewer in their own timezone. ApexVoice stores a per-tenant IANA timezone for the same reason.

Licence risk: Low. MIT permits copying, modification, and commercial use, including in a closed source product, provided the copyright notice and licence text are preserved for the copied portions. Attribution bookkeeping is the only real obligation.

Recommendation: Use patterns only for now. ApexVoice's first commercial release uses request-only booking, which does not need a scheduling engine, so importing cal.diy code or running cal.diy as a service would add weight without a matching benefit. If direct booking is approved later, first choice is still to implement slot calculation natively in ApexVoice following these patterns. Reuse of specific MIT-licensed utility code is acceptable at that point with licence compliance: keep the MIT notice with the copied code, record the source and version in a third-party notices file, and confirm the files taken are from the MIT-licensed edition and not from any separately licensed enterprise portion of the wider Cal.com project.

Cost note: Self-hosted, no subscription required for the open source edition. Running it as a separate service would still carry hosting and maintenance cost, which is a further reason to prefer patterns over a live dependency for now.

## chatwoot

Repository: Fork of chatwoot/chatwoot. Licence: Recorded as Other / NOASSERTION for the fork, which means automated licence detection could not settle the terms. The upstream project is known to combine an open source core with enterprise features under a separate proprietary licence.

What it is: An omnichannel customer support platform: a shared inbox for conversations from many channels, agent assignment, labels, automation rules, and customer contact records.

What is reusable for ApexVoice:

- Inbox concepts for the business dashboard. ApexVoice messages and call follow-ups are, in product terms, an inbox: items arrive, need a responsible person, need a handled or resolved state, and benefit from urgency flags and filtering. Chatwoot's inbox model (unassigned, assigned to me, resolved, filters by status and channel) is a proven pattern for the ApexVoice messages view, which in the first release has a simple handled flag. If the dashboard later adds assignment and resolution states, this is the pattern to follow.
- Conversation timeline pattern. Presenting everything about one customer contact in a single chronological thread (calls, messages, notes, appointment requests) is the right long-term shape for an ApexVoice contact view. Chatwoot demonstrates this pattern at scale.
- Contact record patterns. A lightweight contact with channels, first seen and last seen timestamps, and a history of interactions matches the contacts concept proposed in the multi-tenant architecture document.
- Notification and digest ideas. Per-agent notification preferences and summary digests inform the messageDelivery settings in BusinessConfig (per-message email or SMS, urgent-only SMS, daily summary time).

Licence risk: High until clarified. A NOASSERTION licence recording means the fork's terms are not machine-verified, and the upstream project deliberately separates open source and enterprise code with different rights. Copying the wrong file could mean copying proprietary enterprise code with no right to use it commercially, or code whose obligations have not been assessed. This is not a risk to take on inference.

Recommendation: Use patterns only. Do not incorporate chatwoot code, in whole or in part, unless a legal review first identifies the exact files, confirms their licence, and confirms the intended use is permitted. The product ideas above are general concepts, and concepts are not protected by a code licence; ApexVoice can implement an inbox, assignment, and contact timelines in its own codebase without chatwoot code. There is also a practical reason to avoid a live dependency: chatwoot is a large Rails application with its own database, background workers, and upgrade cycle, which is heavy infrastructure for a feature ApexVoice needs only a small slice of.

Cost note: The open source edition is self-hosted with no subscription, but self-hosting a second large platform carries real server and maintenance cost. The enterprise edition is paid. Patterns cost nothing, which is the right price here.

## VoiceStudio

Repository: Fork of debpalash/VoiceStudio. Licence: AGPL-3.0.

What it is: A studio-style application for working with synthetic voices: browsing and previewing voices, testing text with different voices, and managing generated audio.

What is reusable for ApexVoice:

- Voice preview user experience concepts. ApexVoice onboarding asks a nontechnical owner to pick a receptionist voice. VoiceStudio-style interaction patterns are directly relevant: a list of voices with plain-language descriptions, a short sample line the owner can hear before choosing, and a try-your-own-text field so the owner can hear the voice say their own business name and greeting. Hearing the actual greeting in the actual voice is the single most confidence-building step in onboarding.
- Voice comparison pattern. Playing the same sample text across two or three candidate voices, one after another, is a better selection experience than reading voice names. The onboarding voice picker should adopt this pattern.
- Sample text conventions. Using realistic domain sample lines (a greeting, a booking sentence, an after-hours sentence) rather than a generic test sentence helps owners judge a voice for the job it will actually do.

Licence risk: High for code reuse. AGPL-3.0 is a strong copyleft licence with a network use clause: if AGPL code is incorporated into a service offered over a network, the operator can be obliged to offer the complete corresponding source of the combined work to the users of that service. For a closed commercial subscription product, that obligation is a fundamental business decision, not a detail. AGPL code must NOT be copied into ApexVoice without legal review. This includes copying substantial structure or translated versions of its code, not only literal file copies.

Recommendation: Use patterns only. Do not incorporate VoiceStudio code. Build the voice picker in ApexVoice's own frontend, calling the existing GET /api/voices endpoint and real preview audio generated through ApexVoice's own authorized voice provider account where authorization permits. Previews must be genuine audio of the listed voice or clearly absent; a fake player control that plays nothing, or plays a different voice, would mislead customers and is explicitly out of scope for the commercial build. If a future decision ever favours reusing VoiceStudio itself as a separate internal tool, that separate-tool use still needs legal review first because AGPL obligations can attach to network use, and it must never be merged into the ApexVoice codebase on a developer's own initiative.

Cost note: Self-hosted, no subscription. The cost of the patterns-only route is ApexVoice's own text to speech usage for preview generation, which is small, cacheable per voice and sample text, and already within the existing provider relationship.

## openproject

Repository: Fork of opf/openproject. Licence: GPL-3.0.

What it is: A project management platform: work packages, timelines, boards, budgets, and team planning for organizations managing many projects.

What is reusable for ApexVoice:

- Very little. ApexVoice is a telephony and receptionist product. Its internal needs are a support queue, a feature backlog, and an onboarding checklist for new businesses, none of which require project management software embedded in the product. The one transferable idea is generic: a structured checklist with owners and states, which ApexVoice can represent in its existing tooling. There is no customer-facing ApexVoice feature that openproject functionality would improve.
- Nothing in openproject addresses ApexVoice's actual gaps, which are tenant isolation, telephony, voice, booking, and billing. Those are covered by the architecture and contracts documents, not by this repository.

Licence risk: High for code reuse, and moot given the low relevance. GPL-3.0 is a strong copyleft licence: distributing a combined work that includes GPL code can oblige distribution of the combined work under GPL terms. GPL code must NOT be copied into ApexVoice without legal review. There is no benefit case here that would justify even starting that review.

Recommendation: Do not incorporate. Do not copy code, do not add as a dependency, and do not self-host it as part of the ApexVoice stack. If Harbour & Main wants project tracking for the ApexVoice build itself, use a tool the team already operates, kept entirely separate from the product codebase. Revisit only if a concrete customer-facing requirement appears that openproject uniquely answers, which is not expected.

Cost note: The community edition is self-hosted with no subscription, but self-hosting a large Rails platform has real server and maintenance cost, and spending it would buy ApexVoice nothing its customers can use.

## Cross-cutting conclusions

- Patterns are the harvest from all four forks. Booking lifecycle and availability from cal.diy, inbox and contact timeline design from chatwoot, and voice preview interaction from VoiceStudio each improve ApexVoice, and each can be implemented in original ApexVoice code at no licence risk and no subscription cost.
- Only cal.diy code could be reused with routine licence compliance (MIT, keep the notice), and even there the recommendation is patterns first, because request-only booking does not yet need a scheduling engine.
- AGPL-3.0 (VoiceStudio) and GPL-3.0 (openproject) code must not be copied into ApexVoice without legal review. Chatwoot code must not be copied until its licence position is clarified by legal review, because the fork licence is Other / NOASSERTION and upstream includes proprietary enterprise material.
- No fork should be added as a running dependency of the commercial launch. Each would add hosting cost, upgrade burden, and another system holding customer data, which would complicate the privacy and retention commitments ApexVoice makes to its own customers.
- Maintain a third-party notices file in the ApexVoice repository from the first instance of any code reuse, recording source project, version or commit, licence, and the files or functions reused. Starting this habit now is cheap; reconstructing it later is not.
