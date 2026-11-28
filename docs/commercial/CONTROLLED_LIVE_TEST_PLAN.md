# ApexVoice controlled live test plan

Prepared for: Harbour & Main pilot tenant, ApexVoice Phase 4
Status: Preparation only. Nothing in this plan authorizes a live call.

## Governing rules

* Live calling stays disabled until Josh approves each stage in writing. RECEPTIONIST_ENABLED stays off for the public through every stage in this plan.
* The pilot configuration is pilots/harbour_main_pilot.json. Its limits bind every stage: maximum call duration 5 minutes, total pilot spending cap $5.00 CAD, named test callers only, pilot window set by Josh.
* The billing verification plan (BILLING_VERIFICATION_PLAN.md) and this plan share the same $5.00 CAD cap. Spend observed under either plan counts against the same total.
* No stage starts until the previous stage's evidence is reviewed and Josh approves moving on.
* Every test call is logged with the evidence listed per scenario, and the session's provider usage is checked against the cap after each session.

## Stage 0: staging exercise, mock provider, $0 budget

Purpose: prove the integrated application behaves correctly end to end with no telephony spend.

* Environment: the integrated staging application, after the Phase 3 tenancy, voice, and billing packages are wired into the backend. The backend already supports a mock provider mode for local verification per RELEASE_STATUS, so Stage 0 runs entirely against the mock provider and simulated webhooks.
* Traffic: scripted simulated calls through the mock provider, covering every scenario in the table below that does not require a real phone line. Interruption, silence, and outage scenarios are simulated at the webhook and media level the mock supports; anything the mock cannot simulate is marked deferred to Stage 1, not skipped silently.
* Budget: $0. Any indication of a real provider charge during Stage 0 is itself a stop condition, because it means the mock boundary leaked.
* Exit criteria: all Stage 0 scenarios pass, multi-tenant isolation is re-verified in the integrated staging app (a test tenant's data never appears for the pilot tenant), usage records match simulated call durations, and Josh approves Stage 1 in writing.

## Stage 1: internal live calls, named testers only

Purpose: verify real telephony behaviour on the Harbour & Main pilot number with the pilot configuration.

* Callers: only the named test callers Josh lists in the pilot configuration's toConfirm resolution. Testers call from their own phones and identify themselves as testers at the start of each call log entry, not necessarily on the call itself.
* Number: the pilot number decided in the pilot configuration (existing legacy number or an approved new pilot number). The number is not published anywhere during the pilot, and the receptionist is not enabled for the public.
* Session discipline: calls run in scheduled sessions inside the pilot window. After each session, the operator records total minutes, compares SignalWire usage records against the app call records, and checks cumulative spend against the $5.00 CAD cap before any further session.
* Exit criteria: all Stage 1 scenarios pass on the real line, the billing verification matrix in BILLING_VERIFICATION_PLAN.md is complete, and Josh decides in writing whether the pilot ends, repeats, or advances to a separate limited customer pilot proposal. Advancing beyond internal testers is not part of this plan and needs its own approval.

## Scenario table

Each scenario lists setup, the caller script, expected behaviour, the pass criterion, and the evidence to capture. Scripts are spoken by the tester unless noted.

### S1. Inbound call basics

* Setup: Stage 0 mock call, repeated live in Stage 1. Pilot configuration loaded. Tester calls the pilot number.
* Script: Tester says: "Hello, I am testing. Can you hear me?" then waits.
* Expected behaviour: The call is answered, the greeting plays with the AI disclosure and the transcription notice, the tenant resolved is Harbour & Main, and the call appears in the pilot tenant's records only.
* Pass criterion: Greeting matches the pilot configuration word for word on the disclosure elements, correct tenant routing, call record created with the right number and direction.
* Evidence: call SID, call record export, transcript, tester note of what was heard.

### S2. Business questions from verified knowledge

* Setup: As S1.
* Script: "What does Harbour & Main do?" then "Do you build websites for small businesses?" then "Can you tell me about your AI receptionist service?"
* Expected behaviour: Answers in general terms matching the pilot configuration services. No prices, timelines, guarantees, or capabilities beyond the configuration.
* Pass criterion: No statement on the call goes beyond the verified configuration content.
* Evidence: full transcript reviewed line by line against the configuration.

### S3. Question the receptionist cannot answer

* Setup: As S1.
* Script: "How much does a website cost?" then "Can you guarantee I will be on the first page of Google?"
* Expected behaviour: The receptionist declines to state a price or make a guarantee, and offers to take a message.
* Pass criterion: No invented figure or promise appears in the transcript, and a message offer is made.
* Evidence: transcript.

### S4. Message taking

* Setup: As S1. Tester uses a scripted name and callback number.
* Script: "Please take a message. My name is Alex Martin. My number is 519, 555, 0142. I am calling about a new website for my bakery. Mornings are best to reach me."
* Expected behaviour: The receptionist collects name, callback number, reason, and preferred contact time, reads the callback number back, and saves the message for email and dashboard delivery per the configuration.
* Pass criterion: The saved message record contains all four fields accurately, and the read-back number matches the script.
* Evidence: message record export, delivery payload (built, and in Stage 1 the delivery path agreed for the pilot), transcript.

### S5. Appointment request, request only

* Setup: As S1.
* Script: "I would like to book an appointment for next Tuesday morning about a website project."
* Expected behaviour: The receptionist collects name, callback number, service, and preferred time, and states clearly that this is a request and Harbour & Main will call back to confirm. The word confirmed is never used about the appointment itself.
* Pass criterion: Appointment record exists with status requested, and the transcript contains the request-only wording.
* Evidence: appointment record export, transcript.

### S6. Interruption mid-sentence

* Setup: As S1. Tester interrupts the greeting and later interrupts a longer answer.
* Script: Tester starts speaking over the greeting with: "Sorry, I just need to leave a message." Later, during the services answer: "Stop, that is enough, thank you."
* Expected behaviour: The receptionist stops speaking promptly when the caller talks, listens, and follows the caller's new direction.
* Pass criterion: The receptionist does not talk over the caller for more than a brief overlap, and the conversation follows the interruption both times.
* Evidence: transcript with turn timing, tester note on overlap length.

### S7. Caller silence

* Setup: As S1. Tester stays silent after the greeting, then silent again mid-conversation.
* Script: Silence for the first prompt cycle, then answer one question, then silence again.
* Expected behaviour: One prompt, then a second prompt, then a polite closing and hangup, following the pilot configuration instructions. No repeated indefinite prompting.
* Pass criterion: The call ends politely after the configured prompts, and the call record shows a normal termination.
* Evidence: transcript, call duration, call record.

### S8. Incorrect caller information and correction

* Setup: As S1, message flow.
* Script: Tester gives callback number "519, 555, 0142", and when it is read back says: "No, that is wrong, it is 519, 555, 0124."
* Expected behaviour: The receptionist accepts the correction, repeats the corrected number back, and saves the corrected number.
* Pass criterion: The saved message record contains 0124, not 0142, and the transcript shows the corrected read-back.
* Evidence: message record export, transcript.

### S9. Human handoff request

* Setup: Stage 1 only, during a pilot window when the main business line can be answered or allowed to ring out deliberately. Two runs: transfer answered, and transfer not answered.
* Script: "I want to talk to a real person, please."
* Expected behaviour: The receptionist attempts the transfer to the Harbour & Main main line per the configuration. If the transfer connects, the receptionist exits cleanly. If it does not connect within the configured attempts, the receptionist apologizes briefly and takes a message.
* Pass criterion: Transfer attempted to the correct number in both runs, clean exit on connect, message fallback on no answer, and the SIP Refer charge appears in usage records for the billing reconciliation.
* Evidence: call record, transfer leg records, message record for the no-answer run, tester and recipient notes.

### S10. Emergency request

* Setup: As S1. Tester states a scripted emergency. Testers must agree the wording in advance and must not call any real emergency service as part of this test.
* Script: "There is a fire at my shop, I need help right now."
* Expected behaviour: The receptionist immediately tells the caller to hang up and call 911, does not attempt to handle the emergency, does not take a message first, and does not keep the caller on the line.
* Pass criterion: The 911 direction is the first substantive response, and no handling, booking, or message flow begins.
* Evidence: transcript. Any deviation is a stop condition for the whole pilot, not just this scenario.

### S11. Provider outage simulation

* Setup: Stage 0 at staging level: the provider integration is pointed at a failing endpoint or the mock provider is set to fail call setup. Stage 1 does not simulate an outage on the live line.
* Script: Simulated inbound call attempts during the simulated outage.
* Expected behaviour: Calls fail safe. No half-created records, no charges beyond the failed setup, the failure is visible in monitoring, and the failed call alert payload builds once the threshold is reached (payload built and inspected, not sent, during testing).
* Pass criterion: Failure is detected, logged, and alertable, with no phantom successful call records.
* Evidence: staging logs, monitoring view, built alert payload, usage records showing no unexpected charges.

### S12. Call termination and hangup handling

* Setup: As S1. Three runs: caller hangs up mid-greeting, caller hangs up mid-message, and a normal goodbye ending.
* Script: Hang up at the scripted points. Third run: "That is all, thank you, goodbye."
* Expected behaviour: Each call ends cleanly, the call lock for the tenant is released, partial messages are either saved as partial with the information collected so far or discarded per the message rules, and durations are recorded.
* Pass criterion: No stuck active call state after any run, the next test call is answered normally, and records match what was collected.
* Evidence: call records, tenant lock state check after each run, transcript fragments.

### S13. Usage recording accuracy

* Setup: Runs across all other Stage 1 scenarios; no separate calls.
* Script: Not applicable.
* Expected behaviour: Every live call produces a usage record for the pilot tenant with duration matching the SignalWire usage record for the same call SID, minutes rounded up per call per the tenancy metering rule, and TTS character counts recorded per call.
* Pass criterion: Per-call durations match the provider records for every call, and the session total matches the provider total within the per-call rounding rule.
* Evidence: side by side table of app usage records and provider usage records, kept with the billing verification results.

### S14. Cross-tenant appearance check

* Setup: Stage 0 and Stage 1. A second test tenant exists in staging with its own configuration and records.
* Script: After pilot calls, sign in as the second tenant and inspect its dashboard, messages, and exports.
* Expected behaviour: Nothing from the Harbour & Main pilot appears in the second tenant's views or export, and nothing of the second tenant appears in the pilot tenant's.
* Pass criterion: Both directions verified clean.
* Evidence: export files from both tenants, reviewer sign-off note.

## Stop conditions

Any one of these halts the pilot immediately, in any stage. The pilot does not resume until Josh reviews the evidence and approves resuming in writing.

* Any unexpected charge pattern: charges for calls not placed, charges materially above the billing verification estimates, spend reaching the $5.00 CAD cap, or any charge appearing during Stage 0.
* Any disclosure failure: a call answered without the AI disclosure, a recording claim made while recording is off, or the receptionist claiming to be human.
* Any cross-tenant data appearance: one tenant's calls, messages, configuration, or usage visible to another tenant, in any view, export, or log shown to a tenant.
* Any emergency handling failure under scenario S10.
* Any invented business fact stated to a caller: a price, a timeline, a guarantee, hours, or a capability not in the pilot configuration.
* Any call answered from a caller who is not a named test caller during Stage 1, which indicates the number or the enablement leaked beyond the pilot.
* Loss of the ability to end calls or release the tenant call lock.

## Session record template

For each test session record: date and pilot window, stage, tester names, scenarios run, call SIDs, pass or fail per scenario with evidence links, provider usage totals for the session, cumulative pilot spend against the cap, any stop condition observations, and the operator's recommendation for the next session.
