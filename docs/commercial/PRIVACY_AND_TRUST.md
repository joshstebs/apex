# ApexVoice Privacy and Customer Trust Analysis, Canada

Prepared for: Harbour & Main, ApexVoice
Date prepared: November 28, 2026
Status: Internal analysis and planning document. This is not legal advice. Canadian privacy, telecommunications, and consumer law points below must be confirmed by a qualified Canadian privacy lawyer before ApexVoice is sold commercially.

No em dashes are used in this document set by house style. Legal accuracy does not depend on punctuation, but customer facing wording does depend on review.

## Purpose

This document evaluates the privacy and trust requirements for selling ApexVoice, an AI receptionist service, to Canadian small businesses. It covers which laws likely apply, how call recording and transcription consent works in Canada, what the current product state means for disclosure wording, messaging rules for SMS follow ups, data residency, and recommended retention periods. The customer facing drafts that follow from this analysis are in the legal drafts folder. Every draft there is headed as a draft requiring professional legal review.

## Roles, who is who

Clear role allocation is the foundation of every document in this set.

- Harbour & Main is the service provider. It operates ApexVoice, engages the subprocessors listed below, and provides the software, telephony connection, AI processing, dashboard, and support.
- The business customer is the business that buys ApexVoice, configures the receptionist, and decides why calls are answered, what information is collected, and how messages and appointments are used. In privacy law terms, the business customer is generally the organization collecting the caller personal information for its own purposes.
- The caller is the individual who phones the business. The caller personal information can include name, phone number, voice, message content, appointment details, and anything the caller chooses to say, which can include sensitive information the business never asked for.
- Practical consequence: the business customer must give accurate configuration, lawful instructions, and correct business information. Harbour & Main must process caller information only on the business customer instructions, protect it, and help the business customer meet its own obligations. Contracts must say this plainly, and the product must support it with access controls, deletion tools, and audit records.

## PIPEDA applicability

- PIPEDA, the Personal Information Protection and Electronic Documents Act, is the federal private sector privacy law in Canada. It applies to personal information collected, used, or disclosed in the course of commercial activities, subject to provincial exceptions.
- Answering business calls, taking messages, and booking appointments for paying business customers is a commercial activity. Assume PIPEDA applies to ApexVoice operations.
- PIPEDA is built on ten fair information principles, including accountability, identifying purposes, consent, limiting collection, limiting use, disclosure and retention, accuracy, safeguards, openness, individual access, and challenging compliance. The privacy policy draft and the product controls should map to those principles, and a reviewer should check that mapping.
- Ontario has no general private sector privacy law of general application. Ontario has a health specific law, PHIPA, for health information in the health sector, but no general statute that replaces PIPEDA for ordinary businesses. For Ontario business customers and Ontario callers, PIPEDA is therefore the main private sector privacy statute.
- Alberta, British Columbia, and Quebec have provincial private sector privacy laws recognized as substantially similar in relevant respects. If ApexVoice sells outside Ontario, the applicable provincial law for customers in those provinces must be considered, and the privacy program should be built to the strictest applicable standard where practical.
- Health information warning: dental and medical office customers raise PHIPA in Ontario and similar health privacy laws elsewhere, plus professional regulator rules. A caller may disclose symptoms, treatment, or insurance details on a call. ApexVoice must not treat a general PIPEDA review as sufficient for health sector customers. Health sector onboarding needs a separate review, stricter retention and access rules, and a clear instruction to callers not to share detailed clinical information with the AI receptionist. See the service limitations draft.
- Employment and other exceptions exist in PIPEDA and provincial laws. Do not rely on an exception without legal advice on the specific facts.

## Quebec Law 25

- Quebec Law 25, the modernized Act respecting the protection of personal information in the private sector, applies if ApexVoice serves businesses in Quebec, serves Quebec callers in a way that triggers the Act, or processes personal information of Quebec residents.
- Notable Law 25 requirements to plan for, subject to legal confirmation: a designated privacy officer, privacy impact assessments in defined circumstances including communication of personal information outside Quebec, heightened consent requirements, transparency about automated decision making and profiling technologies, data portability and other individual rights, incident reporting to the Commission d acces a l information and notification to affected individuals where there is a risk of serious injury, and meaningful administrative and penal consequences for non compliance.
- Language: serving Quebec customers also raises French language requirements for contracts, interfaces, and communications under Quebec law. Do not launch in Quebec with English only materials on the assumption that federal rules are enough.
- Recommendation: either complete a Law 25 review before selling to Quebec based businesses, or explicitly exclude Quebec from the initial service area in the terms and in onboarding, and enforce that exclusion. A silent gap is the worst option.

## Call recording and transcription consent in Canada

Two different legal questions are often confused. Keep them separate.

### Criminal Code interception rules

- Canada is commonly described as a one party consent country for recording private communications. Under section 184 of the Criminal Code, intercepting a private communication is generally an offence unless, among other exceptions, one of the parties to the communication consents to the interception.
- For ApexVoice, the business, through its configured receptionist acting on its behalf, is a party to the call with the caller. That is the basis businesses commonly rely on for recording their own calls.
- One party consent under the Criminal Code does not by itself satisfy privacy law consent and transparency requirements. A recording can be lawful under the Criminal Code and still be a privacy problem if the caller was never told, the purpose was never identified, or the recording is kept or used beyond that purpose.

### Privacy law consent and transparency

- PIPEDA requires knowledge and consent for collection, use, and disclosure of personal information, subject to defined exceptions, and requires that purposes be identified at or before collection.
- Best practice for ApexVoice, and the approach taken in the drafts: tell the caller at the start of the call, in plain language, that they are speaking with an AI receptionist, that the call may be transcribed and, if enabled, recorded, why that happens, and what to do if they do not agree, for example hanging up, asking for a human callback, or contacting the business by another method.
- Disclosure must match reality. Wording that says a call is recorded when it is not is misleading. Wording that omits transcription when transcription is happening is also misleading.

### Current ApexVoice state, and why wording matters

- Current state as provided for this review: audio recording is NOT enabled by default. Transcription IS on.
- Consequences:
  - Caller facing disclosure must say the call is transcribed, and must only say the call is recorded if recording is actually enabled for that business and that call.
  - The dashboard and onboarding must show, per business, whether recording is on or off, and the disclosure script must change with that setting. A single static greeting that mentions recording for everyone is wrong for businesses with recording off.
  - If recording is later enabled as a feature, it needs its own onboarding toggle, its own disclosure wording, its own retention setting, and staff training material for the business customer.
  - Transcripts are personal information. They need the same safeguards, access controls, retention limits, and deletion support as recordings would.
  - Call summaries generated by a language model are derived personal information. They can contain errors and they can repeat sensitive details a caller mentioned. Treat summaries with the same care as transcripts.
- Recommended default disclosure line, to be adapted per business and reviewed legally, is in the AI disclosure draft in the legal drafts folder.

## AI disclosure and automated processing transparency

- Callers should be told they are interacting with an AI system, not a human. This is a trust requirement, a transparency requirement under privacy principles, and, for Quebec, part of a broader set of duties around automated processing.
- The receptionist must not claim to be human, must not claim to be a named employee of the business, and must correct a caller who believes they are speaking to a human.
- If a caller asks for a human, the system should follow the business escalation rule, take a message if no human is available, and never argue with the caller or block access to a human path.
- Website and sales disclosure must be consistent with call disclosure. Do not market the service as indistinguishable from a human receptionist.

## CRTC, CASL, and SMS or email follow ups

- CASL, Canada anti spam legislation, governs commercial electronic messages, including SMS and email sent for commercial purposes. Appointment confirmations, reminders, and follow up messages can fall under CASL depending on content and context. Transactional messages are not automatically exempt from every CASL requirement.
- Planning points, to be confirmed legally:
  - Identify the sender clearly in every message, with contact information as CASL requires.
  - Rely on a valid consent basis for marketing style follow ups, and keep consent records, who consented, when, how, and to what.
  - A caller booking an appointment has, at most, a basis for messages about that appointment. That is not consent to general marketing texts.
  - Include a working unsubscribe mechanism in marketing messages, and honour withdrawals promptly.
  - The business customer is usually the sender of messages to its own customers. Harbour & Main is providing the sending tool. Contracts and onboarding must allocate who obtains consent, who is identified as sender, and who handles unsubscribe and complaint requests. The product must store consent and unsubscribe state per contact and must stop messages when consent is withdrawn.
- CRTC and telecommunications notes: telemarketing rules, the National Do Not Call List, and CRTC unsolicited telecommunications rules mainly govern outbound telemarketing. ApexVoice is primarily inbound, but any outbound calling feature, callback campaigns, or promotional calling would need a separate CRTC review before it is built or sold. Caller identification accuracy also matters: outbound calls and messages must not display misleading caller information.
- Short code and carrier rules for SMS in Canada impose additional practical requirements. Verify with the messaging provider before promising SMS features.

## Data residency and subprocessors

Current stack and residency notes, based on the architecture provided for this review. Regions must be verified in the live accounts before any residency claim is made to a customer.

- SignalWire: telephony provider, processes call audio, call metadata, and, if used, transcription data. Region and retention depend on account configuration and SignalWire terms.
- ElevenLabs: text to speech provider, receives the text the receptionist will speak. That text can contain caller names, appointment details, or other personal information if responses are generated carelessly. Prompts and response design should avoid sending unnecessary personal information to the speech provider.
- Hugging Face router and the language model: receives conversation content needed to generate responses and summaries. Conversation content is caller personal information. Data handling depends on the endpoint type and terms. Verify whether prompts are retained or used for training under the actual account terms, and record the answer.
- Upstash Redis: stores application data, which may include call state, transcripts, messages, or cached content depending on implementation. Upstash region is configurable. Record the actual region in use.
- Vercel: hosting for the application and dashboard. Function and data regions depend on project configuration. Record the actual regions in use.
- Residency recommendation: choose and document a primary data region, prefer a Canadian region where a provider offers one that meets performance needs, and otherwise disclose that data is processed in the United States or other named countries. Cross border processing is not prohibited by PIPEDA for most private sector uses, but organizations remain accountable for information transferred to a service provider, must use contractual and other means to provide a comparable level of protection, and must be transparent about it. Quebec Law 25 adds assessment duties for communication outside Quebec.
- Do not advertise Canadian data residency unless every subprocessor in the chain supports it and the configuration has been verified. A partial claim is a misleading claim.
- Maintain a public subprocessor list with provider name, purpose, data categories, and region, and a process to notify business customers of material subprocessor changes.

## Safeguards and access control

Privacy promises are only credible if the multi tenant product enforces them. The following are product requirements, cross referenced to the multi business architecture work, not claims that they are all built today:

- Tenant isolation on every record and every query, enforced in code and tested, so one business can never see another business calls, transcripts, contacts, or appointments.
- Authentication for dashboard users, with strong password rules or a reputable identity provider, session controls, and protection against credential stuffing.
- Role based access: owner, manager, and staff style roles with least privilege defaults. Transcript and recording access should be a distinct permission, not available to every user by default.
- Audit logs for viewing, exporting, and deleting caller data, and for configuration changes.
- Encryption in transit everywhere, and encryption at rest through the storage providers, verified by configuration review.
- Export controls: bulk export of transcripts and contacts should be logged, rate limited, and restricted by role.
- Incident response plan: detection, containment, assessment of risk of significant harm, notification duties under PIPEDA to the Privacy Commissioner of Canada and to affected individuals where the legal threshold is met, and a record of every breach of security safeguards, kept for the period PIPEDA requires. Quebec has its own incident duties. The plan needs legal review and a named owner.

## Retention recommendations

Retention periods below are recommendations to be adopted in policy, configured in the product, and reviewed legally. They balance business need, storage cost, and the PIPEDA principle of limiting retention.

| Data category | Recommended default retention | Notes |
|---|---|---|
| Call audio recordings, if recording is enabled | 30 to 90 days, business configurable within set bounds | Not enabled by default in the current state. Shorter is better. State the period in onboarding |
| Call transcripts | 90 days on Starter, 12 months on Professional, 24 months on Business, as proposed in the pricing document | Longer retention is a paid feature and a privacy cost. Make the period visible in the dashboard |
| AI call summaries and messages | Same period as transcripts for that tier | Summaries are derived from transcripts and should not outlive them without a reason |
| Appointment records | Kept by the business customer in its own booking system as the system of record. ApexVoice copy follows transcript period unless the business needs it as its only record, in which case a written exception is required | Avoid ApexVoice becoming an unmanaged permanent archive |
| Customer contact records created from calls | Until the business customer deletes them or the account is closed, subject to the deletion process | The business customer controls purpose and accuracy |
| Call metadata, date, time, duration, number | 24 months for billing, dispute, and security purposes | Needed to explain invoices. Minimize what is kept beyond that |
| Billing records | Kept as required by Canadian tax and accounting law, confirmed by an accountant | Billing retention is a legal duty and is an exception to deletion on request, disclosed in the deletion policy |
| Support tickets and emails | 24 months | Includes any caller information a business pastes into a ticket, which onboarding should discourage |
| Security and audit logs | 12 to 24 months | Needed for incident investigation |
| Backups | Rolling backups deleted within 30 days of source deletion, where the provider supports it | Deletion is complete when backups cycle out. Say so honestly in the deletion policy |

Deletion and anonymization:

- On account closure, business customers should be able to export their data for a defined window, recommended 30 days, after which personal information is deleted or anonymized on the schedule in the data retention draft.
- Individual access and correction requests from callers go to the business customer as the collecting organization. Harbour & Main must have a process to help locate, correct, export, or delete that caller records within the business tenant, within a defined response time.
- Aggregated statistics may be kept only if they are genuinely anonymized so no individual or business can be identified. Do not call data anonymized if a tenant ID or phone number is still attached.

## Customer trust practices

Beyond legal minimums, these practices decide whether businesses and callers trust the service:

- Plain language disclosure at the start of every call, in the voice of the business, without legal jargon.
- A public privacy page for Harbour & Main, a business facing privacy policy, and a short caller facing explanation a business can link or read out.
- No sale of personal information. State it plainly, and do not share caller information for advertising.
- No training of shared models on customer call content by default. If any provider in the stack uses submitted content under its standard terms, that must be identified, assessed, and either changed to terms that do not, or disclosed. This point must be verified against actual SignalWire, ElevenLabs, and model provider terms before launch.
- Accuracy honesty: AI summaries can be wrong. The dashboard should label summaries as AI generated, show the transcript beside the summary where available, and provide a way to correct or flag a summary.
- Human fallback: every business configuration must include a real escalation path, a transfer number or a callback promise with a time frame, configured during onboarding. A receptionist with no human path is a trust failure.
- Accessibility and language: consider callers who cannot easily use voice menus, callers with hearing or speech disabilities using relay services, and callers who prefer French. At minimum, do not design flows that block relay calls, and plan French language support before serving markets that need it.

## Items requiring professional legal review before launch

- Final privacy policy, terms of service, and all drafts in the legal drafts folder.
- Caller disclosure scripts for transcription on, recording off, and for recording on.
- PIPEDA compliance program as a whole, plus provincial law analysis for any province beyond Ontario where the service is sold, and a Law 25 assessment if Quebec is in scope.
- Health sector customers: PHIPA and regulator requirements, and whether ApexVoice should serve health customers at launch at all.
- CASL review of every automated SMS and email template the product sends.
- Cross border transfer wording and subprocessor contract terms.
- Breach response plan and notification thresholds.
- Data processing addendum or contract clauses between Harbour & Main and business customers allocating privacy responsibilities.
- Employment, contractor, and support access practices for anyone at Harbour & Main who can view transcripts.
- Consumer protection and automatic renewal rules for subscription sales in each province of sale, including Quebec.

## Open verification tasks for the product team

These are factual checks, not legal questions, and they block accurate customer facing wording:

- Confirm which service produces transcripts, its region, its retention, and its cost.
- Confirm whether call audio is stored anywhere, including temporary storage, provider logs, or debugging tools, even though recording is not enabled by default. Temporary processing is different from a recording a user can play back, and the disclosure and policy must describe both accurately.
- Confirm Upstash and Vercel regions in the live and staging projects.
- Confirm language model endpoint terms on retention and training use.
- Confirm ElevenLabs terms on voice data, generated audio retention, and training use.
- Confirm log tools and error tracking tools do not capture transcript text, audio, or phone numbers in plain form.
- Confirm deletion actually removes data from Redis, storage, and provider systems, and test it in staging with a test tenant.
