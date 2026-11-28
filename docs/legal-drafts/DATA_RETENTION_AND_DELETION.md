# DRAFT, NOT LEGAL ADVICE, REQUIRES PROFESSIONAL LEGAL REVIEW BEFORE USE

# ApexVoice Data Retention and Deletion, Draft

Provider: Harbour & Main, operating ApexVoice
Applies to: Business customers, dashboard users, and caller personal information processed on behalf of business customers
Date of draft: November 28, 2026

## Principles

- Keep personal information only as long as needed for the purpose it was collected for, the business customer instructions, service operation, and legal requirements.
- Make retention periods visible. A business should be able to see, in onboarding and in the dashboard, how long its transcripts, recordings, messages, and related records are kept.
- Deletion must be real. When data is deleted, it must be removed from live systems and from caches and replicas within a stated period, and from backups when backups cycle out. If a provider cannot delete on request, that limit must be disclosed, not hidden.
- Legal and billing records are an exception, explained below, and that exception is narrow.

## Retention schedule, recommended defaults

These periods are recommendations for adoption after legal review and product confirmation that the system can enforce them. Do not publish a period the system does not actually enforce.

| Data | Default retention | Who can change it | Notes |
|---|---|---|---|
| Audio recordings, only where recording is enabled | 30 days, business may select 30 to 90 days where offered | Business owner role | Recording is off by default |
| Call transcripts | Starter 90 days, Professional 12 months, Business 24 months, as proposed in pricing | Business may shorten within the dashboard where that control exists. Lengthening beyond the plan period requires a plan change | Transcripts are the main review record for messages |
| AI summaries and message records | Same as transcripts for that tenant | Same as transcripts | Summaries should not outlive the transcript they came from |
| Appointment records held in ApexVoice | Same as transcripts, unless the business designates ApexVoice as its only record, which requires a written exception and a different period agreed in writing | Business owner role, with Harbour & Main agreement for an exception | The business booking system should normally be the long term record |
| Contact records created from calls | While the account is active, until the business deletes them | Business, by record or in bulk where supported | Accuracy is the business responsibility |
| Call metadata, date, time, duration, numbers, plan usage counters | 24 months | Not customer adjustable | Needed for billing explanation, disputes, fraud and security review |
| Business configuration and knowledge content | While the account is active, plus the export window on closure | Business | Configuration may contain staff names and contact numbers, which are personal information in some cases |
| Billing and tax records | Period required by Canadian law, to be confirmed by an accountant, commonly several years | Not deletable on request | Kept separately from call content, access limited |
| Support communications | 24 months | Not customer adjustable, subject to deletion of personal information not needed for that period | Businesses should not paste caller sensitive information into tickets |
| Security, access, and audit logs | 12 to 24 months | Not customer adjustable | Needed for incident investigation and breach records |
| Breach of security safeguards records | Period required by PIPEDA, to be confirmed by legal review, currently understood as at least 24 months after the incident is determined | Not deletable on request | Kept by Harbour & Main as part of its legal duties |
| Backups | Rolling, deleted within 30 days after source deletion, where the provider supports it | Not adjustable | Deletion is fully complete when affected backups have cycled out |

## Customer data deletion, by request

Business initiated deletion:

- A business owner can delete individual call records, transcripts, messages, and contacts in the dashboard where those controls are built, and can request bulk deletion through support where they are not.
- Harbour & Main will confirm what was deleted, what was kept and why, for example a billing record, and the date deletion will be complete including backups.
- Target completion time for a standard deletion request: to be stated after product confirmation, recommended 30 days at most for live systems, sooner where the dashboard deletes immediately.

Caller initiated deletion, through the business:

- A caller asks the business, as the collecting organization. The business verifies identity in a proportionate way, locates the record, and either deletes it in the dashboard or asks Harbour & Main for help.
- Harbour & Main will support the business to locate and delete the caller records within that business tenant only, and will confirm completion to the business.
- If a caller contacts Harbour & Main directly, Harbour & Main will explain that the business controls the record, offer to pass the request to the business with the caller permission, and not disclose the content of any call record to the caller without the business involvement and identity checks, subject to legal advice on direct requests.

Limits on deletion:

- Information that must be kept by law, including billing and tax records and breach records, is kept for the required period and then deleted.
- Information subject to a genuine legal hold, an active billing dispute, or an active security investigation may be kept until that matter closes, with the reason recorded and the requester informed.
- Deleting a transcript does not delete an appointment in the business own booking system, a message already delivered to the business email or messaging system, or a copy the business exported. The business is responsible for those copies, and the deletion confirmation will say so.

## Account closure

- On closure, the business has a recommended 30 day export window to download its configuration, contacts it created, messages, and transcripts it still holds, through the dashboard or by request.
- After the export window, caller personal information and business configuration in the tenant are deleted on the schedule above for backups, except billing, tax, security, and breach records kept by law.
- Telephone numbers assigned through ApexVoice may be released after closure, with notice of the release date. A released number can be assigned to another customer by the carrier. A business that needs to keep a number must arrange porting before closure, where porting is supported.
- Harbour & Main will provide a closure confirmation listing data categories deleted, categories kept by law, and the backup completion date.

## Anonymized and aggregated information

Harbour & Main may keep information that has been genuinely anonymized so that no individual and no business can be identified, for reliability and service improvement. Data is not anonymized if it still contains a phone number, a transcript, a tenant identifier that can be linked back, or a combination of details that could identify a person or business. Anonymization method and any use of aggregated statistics in marketing require review, and no statistic may be published unless it is based on real, measured service data with its period and basis stated.

## Harbour & Main duties

- Build and test deletion in staging, including Redis, storage, dashboard search indexes, and provider systems where deletion is supported, before promising deletion times to customers.
- Train support staff on deletion requests, identity checks, and the limits above.
- Log deletion actions, who requested, who performed, what categories, and when completed, without keeping the deleted content in the log.
- Review this schedule at least annually, and when a provider, feature, or law changes.

## Business customer duties

- Keep retention settings aligned with the business own privacy policy and any sector rules that apply to the business, for example health or legal sector rules.
- Respond to caller requests within the time the law requires of the business, and involve Harbour & Main early enough for Harbour & Main to help.
- Delete or correct information in the business own systems, exports, email, and booking tools, which Harbour & Main cannot reach.
- Do not ask Harbour & Main to keep caller information indefinitely as an unmanaged archive. If a long term record is legally required for the business, the business should keep it in its own system of record.
