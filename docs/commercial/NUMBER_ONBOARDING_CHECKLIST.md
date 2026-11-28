# Number Onboarding Checklist: Internal Operator Version

Purpose: Mirror of TELEPHONE_ONBOARDING.md for the Harbour and Main operator running an ApexVoice number onboarding. Complete every section in order. Do not skip the verification calls.
Companion research: CARRIER_COMPATIBILITY.md in this folder. Items marked UNVERIFIED there must not be promised to the customer.
Hard rule: No carrier setting is changed and no port is submitted without the customer written approval recorded in Section 3 and, for ports, a signed Letter of Authorization dated within the past 30 days.
Last updated: 2026-11-28.

## Section 1: Intake

Customer and tenant record:

- [ ] Business legal name and operating name recorded
- [ ] ApexVoice tenant created or identified, tenant ID recorded
- [ ] Primary contact name, email, and mobile recorded
- [ ] Message delivery preference recorded (email, SMS, both) and destination addresses verified by a test message where the product supports it
- [ ] Transfer target number recorded and confirmed as answered by a human during promised handoff hours
- [ ] Business hours and time zone recorded
- [ ] Greeting script and business information approved by the customer in the onboarding flow before any number work starts

Worksheet collected (from TELEPHONE_ONBOARDING.md pre-setup worksheet):

- [ ] Worksheet received and filed
- [ ] Business name as it appears on the carrier bill matches the worksheet, or the difference is noted
- [ ] Account holder name exactly as on the bill recorded
- [ ] Carrier and product identified (example: Bell Local Link, Rogers Business Phone Shaw, Rogers IBLc, Rogers Advantage Voice, TELUS Office Phone, TELUS Business Connect, TELUS Mobility, Bell Mobility, Rogers Mobility, RingCentral, Vonage, Ooma Office, VoIP.ms, Fongo)
- [ ] Service address and billing address recorded
- [ ] All numbers in scope listed, with the main published number flagged
- [ ] Contract status and end date asked and recorded, or recorded as unknown with customer acknowledgement

Line audit, ask about each item out loud, do not rely on the form alone:

- [ ] Internet on the same line or account (DSL is a port blocker until replaced)
- [ ] Alarm or security monitoring on the line (port blocker until the alarm company confirms an alternate path)
- [ ] Fax machine or fax service on the line
- [ ] Debit or credit terminal that dials out on the line
- [ ] Other lines on the account, hunt groups, or rollover arrangements
- [ ] Voicemail product on the line and whether the customer wants to keep it
- [ ] Toll-free number pointing at this number
- [ ] Customer texting on this number
- [ ] Any phone-system prompts that ask an answering party to press a key (screening, call announce, PIN to answer). If present, plan to disable for the ApexVoice destination, especially on Ooma Office and TELUS Business Connect

## Section 2: Path selection

Choose one primary path and record the reason in the tenant notes:

- [ ] Path A, dedicated ApexVoice number: chosen when the customer wants zero change, a new published number, or the carrier cannot forward as needed
- [ ] Path B1, unconditional forwarding: full-time answering or a defined closure
- [ ] Path B2 plus B3, no-answer and busy forwarding: default recommendation, staff answer first
- [ ] Path B4, scheduled after-hours forwarding: only on Rogers Advantage Voice, RingCentral, TELUS Business Connect, or Ooma Office Virtual Receptionist after the schedule-to-external-number behaviour is confirmed on the account. Not offered on traditional Bell, Rogers, or TELUS landlines
- [ ] Path C, porting: only when Section 1 line audit is clean or every conflict has a documented resolution, and contract impact has been confirmed by the customer with their carrier
- [ ] Path D, transfer target: configured for every path, not a standalone selection

Carrier-specific preconditions checked before scheduling the setup session:

- [ ] Bell Local Link: If the line has pre-programmed voicemail, busy and no-answer may be fixed to voicemail. Customer has asked Bell to enable programmable features if needed
- [ ] Bell Mobility: Pay-per-use forwarding cost of $0.25 per minute disclosed if the feature is not in the plan. Busy and no-answer to an external number flagged for live testing because Bell treats no-answer as a separate feature in its documentation
- [ ] Rogers Business Phone (Shaw): Customer has called Rogers Business to provision Call Forward Busy and Call Forward No Answer in advance. Multi-line Hunt membership checked, because busy forwarding cannot be used in a hunt
- [ ] Rogers IBLc: Business Voicemail conflict disclosed. If the customer has Business Voicemail, Enhanced Call Forward cannot be added, and the customer has chosen which one to keep
- [ ] Rogers Mobility: Carrier voicemail conflict disclosed in writing. Customer understands conditional forwarding will not work until voicemail is removed or disabled, and that ApexVoice takes messages instead
- [ ] TELUS Office Phone: Conditional forwarding treated as UNVERIFIED. A TELUS confirmation or a live test is booked before any staff-first promise is made. Fallback options discussed (unconditional, Business Connect, Path A, Path C)
- [ ] TELUS Mobility: Device dependent forwarding disclosed. Setup session includes handset testing
- [ ] TELUS Business Connect: Forward from an extension, not a call queue, if the press-1 announcement cannot be disabled for queues. Voicemail on the extension reviewed, because it can intercept before the fallback
- [ ] RingCentral: Work schedule set to real hours before after-hours rules are configured. Forward All left off unless full-time forwarding is intended, because it overrides schedules
- [ ] Vonage: Portal permission for Call Forwarding settings confirmed with the account admin
- [ ] Ooma Office: Require key press on answer confirmed OFF for the ApexVoice destination. Main number after-hours routing method confirmed for the plan (Virtual Receptionist action or shared external line)
- [ ] VoIP.ms: Customer understands inbound plus outbound leg charges apply. Ring group and time condition routing to be built in the portal during setup, not assumed
- [ ] Fongo or FreePhoneLine: Auto-disable after 30 days (Fongo Mobile) or 90 days (FreePhoneLine) without an outgoing call disclosed. Local ApexVoice number assigned, not toll-free, because Fongo Mobile cannot forward to toll-free numbers. Monthly outgoing test call added to the support routine

ApexVoice side preparation:

- [ ] SignalWire DID assigned to the tenant and recorded (local number, published price $0.50 USD per month)
- [ ] DID routing points to the tenant ApexVoice configuration and answers in pre-production testing
- [ ] Tenant call limits and spending limits from the pilot configuration are in place before any forwarding goes live
- [ ] Message and escalation rules match the approved onboarding configuration

## Section 3: Customer approval record

Complete before any change. File with the tenant record.

- [ ] Path and settings to be applied written in plain language (example: Forward unanswered calls after 4 rings and busy calls from 519-555-0100 to the ApexVoice number 519-555-0199)
- [ ] Carrier charges disclosed that apply to this customer (examples: Bell Mobility pay-per-use $0.25 per minute, Rogers feature or pay-per-use charges, VoIP.ms two-leg charges, long-distance on forwarded calls where the ApexVoice number is not local to the customer line)
- [ ] Voicemail impact disclosed (forwarded calls no longer reach carrier voicemail; on Rogers Mobility and Rogers IBLc, a voicemail change may be required)
- [ ] Rollback steps explained and provided to the customer in writing
- [ ] Customer written approval received (email approval is acceptable if it names the path, the numbers, and the date). Record: approved by name, date, and channel
- [ ] For ports only: Signed Letter of Authorization received, dated within the past 30 days, signature matches the authorized name on the carrier account
- [ ] For ports only: Customer confirms in writing that the line audit items (internet, alarm, fax, terminal, bundle) have been resolved or accepted
- [ ] Operator name and date recorded for this approval

## Section 4: Setup execution

- [ ] Customer is present or on the phone, using their own carrier account access or their own phone handset. Operator never takes the customer carrier password
- [ ] Existing forwarding state recorded before changes (what was forwarded, to where, and any voicemail settings). Take portal screenshots or write the star code state down. This is the rollback baseline
- [ ] Settings applied exactly as approved in Section 3, using the carrier steps in TELEPHONE_ONBOARDING.md
- [ ] Any deviation from the approved settings stopped and re-approved before continuing
- [ ] For ports only: Port request submitted in the SignalWire Dashboard at Phone Numbers, Port Requests, Initiate Port Request, with the Letter of Authorization attached. Case number recorded. Customer told the published timing (small orders usually within 7 business days, Canadian numbers up to two weeks) and that no faster date is promised
- [ ] For ports only: Number configured in SignalWire with its webhook and tenant routing before the Firm Order Commitment date, because an unconfigured ported number will not work when it goes live
- [ ] For ports only: E911 emergency address assignment planned for the day the port completes, because E911 registrations do not transfer

## Section 5: Setup verification calls

Run all of these with the customer. Record pass or fail and the time of each test in the tenant notes. A failed test stops the onboarding until fixed or rolled back.

- [ ] Direct ApexVoice test: Call the ApexVoice DID. Correct business name and greeting, correct hours answer, AI disclosure present as configured
- [ ] During hours test: Call the business number. Staff phone rings first where conditional forwarding is set. ApexVoice does not answer before the agreed rings
- [ ] Ring-through test: Call the business number and let it ring unanswered. ApexVoice answers after the expected rings or seconds. Timing recorded
- [ ] Busy test: Occupy the business line, then call from a third phone. ApexVoice answers instead of a busy signal, where busy forwarding was set
- [ ] After-hours test: Outside hours, or with the schedule temporarily shifted, call the business number. ApexVoice answers immediately where scheduled all-calls forwarding is set, or per the agreed after-hours behaviour. Schedule restored and re-confirmed after the test
- [ ] Outage or not reachable test, where the product supports it (Rogers Advantage Voice not reachable, Vonage Not Reachable, Ooma offline forwarding): Take the device offline or simulate the condition, call, confirm ApexVoice answers
- [ ] Message test: Leave a test message with a spoken name and callback number. Confirm delivery to the right destination, with name and number captured correctly
- [ ] Transfer test: Call, request a person, confirm the transfer reaches the transfer target, audio is clear in both directions, and record what caller ID the receiving phone displays
- [ ] Loop test: With the transfer target equal to or related to the main number, confirm an unanswered transfer behaves as agreed (message taken, no infinite loop)
- [ ] Voicemail test: Confirm no test message landed in carrier voicemail for forwarded calls, and confirm where messages now land is understood by the customer
- [ ] Key press test, hosted systems: Confirm no press-1, PIN, or screening prompt blocks ApexVoice from answering a forwarded call
- [ ] Rollback rehearsal: Turn forwarding off with the customer, call and confirm normal ringing, then turn it back on and confirm ApexVoice answers. Customer keeps the written off steps
- [ ] For ports only, on the Firm Order Commitment date: Test inbound calls from a mobile and from a landline, test an outbound call if the tenant uses outbound, confirm E911 address is assigned, and confirm the old carrier service for the number has ended as expected

## Section 6: Rollback record

Complete at the end of the setup session, even if everything passed.

- [ ] Rollback baseline from Section 4 filed (prior forwarding state and voicemail state)
- [ ] Exact off steps for this customer carrier and product written on the customer setup summary and in the tenant record
- [ ] Customer has the setup summary, including: ApexVoice number, business number, path used, settings applied, off steps, and Harbour and Main contact
- [ ] If setup failed and was rolled back: Failure reason, carrier error or behaviour observed, and next step recorded. Customer informed the same day. No silent failures
- [ ] If a port was submitted: Case number, submitted date, expected window, and Firm Order Commitment date when received, all recorded. Rejection watch assigned to a named operator, because SignalWire cancels a rejected request if there is no response within a week
- [ ] Follow-up test call scheduled (recommended: next business day, and one week later) and added to the support routine. For Fongo lines, a monthly outgoing call reminder is set so Follow Me does not auto-disable
- [ ] Tenant notes updated with carrier, product, path, settings, test results, and any UNVERIFIED items that remain open for this customer

## Section 7: Cancellation and number release (when a customer leaves)

- [ ] Customer instructed to remove forwarding using their off steps, or forwarding removed together on a call
- [ ] Confirm with a test call that the business number no longer reaches ApexVoice
- [ ] If the number was ported to SignalWire: Explain that keeping the number means a new port to their chosen carrier, that SignalWire charges $5.00 USD per number to port out, and that timing follows the new carrier process. Do not release the DID until the port out completes or the customer confirms in writing they do not want the number
- [ ] DID released only after the above is complete
- [ ] Tenant data handled under the account cancellation and data deletion procedure for ApexVoice (separate document)
