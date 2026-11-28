# Carrier Compatibility Research: Canadian Telephone Number Onboarding for ApexVoice

Status: Research only. Checked 2026-11-28.
Scope: How a Canadian business that already has a phone number can send calls to an ApexVoice number on SignalWire, by forwarding, or move the number itself by porting.
Rule used in this document: A code, step, price, or condition is listed as verified only when it was read on an official carrier, regulator, or SignalWire page on the check date. Anything else is marked UNVERIFIED. Do not quote UNVERIFIED items to a customer as fact.
Character note: All codes use a normal hyphen and star notation as printed by the carrier.

## Summary recommendation

- Default recommendation for most small businesses: Path B conditional forwarding, meaning no-answer forwarding plus busy forwarding to the ApexVoice number. Staff answer first. ApexVoice takes overflow, busy, and unanswered calls. The existing number, carrier account, voicemail history, and bundled services stay in place, and rollback is a short star code or portal change.
- Use unconditional forwarding only when the business wants ApexVoice to answer every call, or for a defined after-hours window where the phone system supports schedules.
- Use scheduled forwarding only on systems verified below to support schedules: Rogers Advantage Voice (Unison), RingCentral, TELUS Business Connect, and Ooma Office through its Virtual Receptionist schedule. Traditional Bell, Rogers, and TELUS landlines do not offer clock-based forwarding on the official pages read; they require manual on and off each day.
- Use porting (Path C) only after the line audit in the onboarding worksheet is complete. Porting ends the old carrier service for that number and can break DSL internet, alarm monitoring, fax, and debit or point-of-sale lines that share the same physical line or account.
- Biggest product risk found: On TELUS traditional office lines, the official support article exists but its detailed star command content could not be fully read in this research session, and third-party summaries of TELUS documentation state that busy and no-answer forwarding on TELUS office lines go to a number TELUS sets, usually voicemail, rather than a customer-chosen number. That specific point is marked UNVERIFIED below because it was not confirmed on a readable official TELUS page. If it is true, TELUS landline customers cannot self-serve conditional forwarding to ApexVoice and need a TELUS support change, a Business Connect migration, or unconditional forwarding. Treat TELUS landline conditional forwarding as a pre-sale verification call, not a self-serve step.
- Second product risk: Rogers Mobility and Fido conditional forwarding does not work while voicemail is active, per the official Rogers mobile page. Rogers mobile customers must remove or disable carrier voicemail before conditional forwarding to ApexVoice will work, which is a real trade-off to disclose before sale.
- Third product risk: Bell Mobility call forwarding is pay-per-use at $0.25 per minute unless the feature is included in the rate plan, per official Bell pages. A busy business forwarding many minutes to ApexVoice on a Bell mobile could face a material per-minute carrier charge on top of ApexVoice fees.

## Paths at a glance

| Path | What happens to the existing number | Carrier change needed | Reversible | Best for |
|---|---|---|---|---|
| A. Dedicated ApexVoice number | Nothing. Business keeps it and also uses a new SignalWire number. | None | Yes, stop publishing or forwarding to the new number | New locations, a published after-hours number, a trial with zero risk to the main number |
| B1. Forwarding, unconditional | Stays with current carrier. Every call forwards. | Feature activation on current carrier | Yes, star code or portal off | Full-time ApexVoice answering, vacations, closures |
| B2. Forwarding, no answer | Stays. Phone rings first, then forwards after a set rings or seconds. | Feature activation | Yes | Default for most businesses. Staff answer first |
| B3. Forwarding, busy | Stays. Forwards only when the line is in use. | Feature activation, sometimes carrier provisioning first | Yes | Single-line shops that miss calls while on another call |
| B4. Forwarding, after-hours scheduled | Stays. Schedule in the phone system sends after-hours calls to ApexVoice. | Phone system with schedules only | Yes, edit schedule | Businesses with a cloud phone system and fixed hours |
| C. Porting | Number moves to SignalWire. Old service for that number ends. | Full port with signed authorization | Hard. Porting back is a new port | Businesses leaving their carrier or consolidating on ApexVoice |
| D. Human transfer target | No change at all. Business number is only a transfer destination. | None | Not applicable | Any path. ApexVoice hands a live caller to a human |

## SignalWire facts used by all paths

Verified on SignalWire official pages, checked 2026-11-28:

- Local DID price in Canada: $0.50 USD per month. Toll-free DID: $0.80 USD per month. Source: SignalWire pricing page, Canada section, https://signalwire.com/pricing
- Port-in: Both local and toll-free numbers can be ported into SignalWire for no charge. Port-out: $5.00 USD per number. Source: SignalWire pricing page, Canada section, https://signalwire.com/pricing
- SIP Refer: $0.10 USD per use, listed under Canada Voice Features on the SignalWire pricing page. Source: https://signalwire.com/pricing
- Canada programmable voice rates on the same page: local inbound $0.00660 USD per minute, local outbound $0.00800 USD per minute, SIP $0.00300 USD per minute. Source: https://signalwire.com/pricing
- Porting process: Submit from the SignalWire Dashboard at Phone Numbers, then Port Requests, then Initiate Port Request. A signed Letter of Authorization dated within the past 30 days is required before processing begins. SignalWire may also need Customer Service Record documentation or previous billing statements. Source: SignalWire porting guide, https://signalwire.com/docs/platform/porting-into-signalwire
- Information SignalWire asks for before a port: Project ID, number list, current provider name, current provider account number, account type (business or residential), company name, authorized name, billing phone number, phone service address, and PIN. Source: https://signalwire.com/docs/platform/porting-into-signalwire
- Port outcomes: Rejected means the carrier could not validate the information; SignalWire notifies by email and cancels the request if there is no response within a week. Scheduled means the carrier accepted and gave a Firm Order Commitment date, which is when the numbers become active in SignalWire. Source: https://signalwire.com/docs/platform/porting-into-signalwire
- Port timing published by SignalWire: Small orders usually complete within 7 business days without delays. Toll-free numbers, Canadian numbers, and off-net numbers can take up to two weeks. Source: https://signalwire.com/docs/platform/porting-into-signalwire
- Common delay causes published by SignalWire: invalid service address, billing address, or name fields; missing PINs; several orders with conflicting information; inactive numbers in the request. Source: https://signalwire.com/docs/platform/porting-into-signalwire
- E911 registrations do not transfer with a port. After a port completes, an emergency address must be assigned to the number in SignalWire. Source: https://signalwire.com/docs/platform/porting-into-signalwire
- A ported number that is not configured with a webhook will not work correctly when it goes live, so configuration must be done before the Firm Order Commitment date. Source: https://signalwire.com/docs/platform/porting-into-signalwire
- Verified Caller ID alternative: SignalWire documents Verified Caller ID as an outbound-only option that lets a business use an existing number as the outbound caller ID without porting it. It does not provide inbound calling or messaging on that number. Source: SignalWire blog, Verified Caller ID and Local Number Portability, https://signalwire.com/blog/verified-caller-id-local-number-portability

## Canadian number portability basics

Verified on the CRTC page Choosing a Local Home Phone Service, checked 2026-11-28, https://crtc.gc.ca/eng/phone/residence/local.htm :

- A customer can keep a phone number when changing phone companies as long as they stay within the local exchange area. Moving out of the local exchange area can make the number unavailable to keep.
- A number can move landline to landline, landline to cellphone, cellphone to cellphone, and cellphone to landline if the location served is within the exchange of the number.
- Do not cancel first. A customer must ask the new provider about keeping the number before cancelling current service, and can only keep a number that is currently being used. A suspended or disconnected number cannot be kept.
- The new provider handles the transfer from the former provider and tells the customer when it will complete. The customer does not need to manage the losing carrier directly.
- Authorization is required. The customer or their agent must authorize the switch, and also authorize any cancellation of other services the new provider is asked to cancel. Accepted forms listed by the CRTC include written consent, verified oral authorization, recorded oral authorization, electronic order authorization, and internet confirmation, as long as an objective documented record is created.
- The CRTC prohibits telephone providers from requiring 30 days notice of cancellation.
- Switching local phone company usually has no effect on other communications services, but the CRTC warns that internet access and television service may depend on how those services are provided by the current and new providers, and that changing wireless companies can affect long-distance services.
- Number portability is available in most, but not all, of Canada.

Practical consequences for ApexVoice onboarding, drawn from the verified items above:

- Wireless versus wireline difference that matters operationally: SignalWire treats Canadian numbers as a slower category, up to two weeks, regardless of wireless or wireline origin. Do not promise a wireless port will be faster in the SignalWire process. UNVERIFIED: Any general industry claim that Canadian wireless ports complete in hours. That was found only on non-official blogs and is not used in customer documents.
- Account mismatch is the main rejection driver in the SignalWire list: name, service address, billing address, account number, and PIN must match the losing carrier record exactly, including punctuation differences in a company name where the carrier record differs from the legal name the customer normally uses.
- Bundled services: If the number is the account anchor for internet, television, alarm, or a bundle discount, porting that number can cancel or reprice the bundle. The CRTC page confirms other services can be affected depending on how they are provided. The customer must confirm bundle impact with the losing carrier before signing the Letter of Authorization.
- Contract terms: The CRTC page notes a customer can return to a previous provider but may still have a contract with the current provider. Early cancellation fees or device balances are a customer and carrier matter. UNVERIFIED: Specific early cancellation amounts for Bell, Rogers, or TELUS business contracts. These vary by contract and were not published on the pages read.
- DSL, alarm, fax, and payment terminals: A traditional landline can carry DSL internet, a monitored alarm, a fax machine, or a dial-up payment terminal on the same line or account. When the number ports away, the old line service ends and those services can stop working. This is a safety issue for alarms. The worksheet in TELEPHONE_ONBOARDING.md requires the customer to list everything that uses the line before any port is started.

## Carrier matrix

Legend: Yes means verified on an official page on 2026-11-28. No means an official page states the opposite or the feature conflicts as noted. UNVERIFIED means no readable official page confirmed it in this session.

### Bell, business landline, Local Link

| Feature | Supported | Activation verified on official page | Notes and charges |
|---|---|---|---|
| Unconditional forwarding | Yes | Lift receiver, press *72 and the designated telephone number, listen for two beeps, hang up. Cancel with *73. | Called Call Forward Universal on the Bell business support page. |
| No-answer forwarding | Yes | Press *92 and the designated telephone number, listen for two beeps. Cancel with *93. Forwards if not answered after 4 rings. | Called Call Forward Do Not Answer Programmable. Ring count of 4 is stated on the page; no customer control of ring count is stated for this feature. |
| Busy forwarding | Yes | Press *90, when prompted key in the designated phone number, listen for two beeps. Cancel with *91. | Called Call Forward Busy Programmable. Page states it is only available with Local Link without voicemail or with optional programmable voicemail. |
| Scheduled or time-based forwarding | UNVERIFIED | No schedule feature appears on the official page read. | Treat as manual on and off only until Bell confirms otherwise for the specific account. |
| Forwarding to voicemail conflict | Yes, as a condition | Not a code. Page separates programmable features from fixed-to-voicemail features that Bell must program. | If the line has pre-programmed voicemail, busy and no-answer may be fixed to voicemail and need Bell programming to change. |

Source: Bell Business Phone support, How to use Call Forwarding, https://entreprise.bell.ca/Support/small-business/phone/calling-features/how-to-use-call-forwarding , page footer last updated October 27, 2014, checked 2026-11-28.

### Bell Total Connect, hosted business phone

| Feature | Supported | Activation verified on official page | Notes and charges |
|---|---|---|---|
| Unconditional forwarding | Yes | Dial *72, enter the number, then press #. Also selectable as Call Forward Always on the desk phone. | Page name: Call Forward All Calls. |
| No-answer forwarding | Yes | Dial *92, then enter the number. Also selectable on the desk phone. | Page name: Call Forward No Answer. No ring count is stated on the page read. |
| Busy forwarding | Yes | Dial *90, then enter the number. Also selectable on the desk phone. | Page name: Call Forward Busy. |
| Out of service forwarding | Yes | Dial *94 or enable in the web portal. | Forwards to a pre-established number when the device is unavailable, for example power or equipment failure. Useful as an ApexVoice safety net. |
| Scheduled or time-based forwarding | UNVERIFIED | The features page read lists a web portal for managing telephony features but does not describe time schedules. | Do not promise schedules on Total Connect without account-specific confirmation. |
| Charges | UNVERIFIED | No forwarding per-minute charge stated on the page read. | Confirm on the customer bill or with Bell. |

Source: Bell Total Connect packages and features, https://business.bell.ca/Support/medium-large/voice-unified-communications/total-connect/talk-package-features , checked 2026-11-28.

### Bell Mobility

| Feature | Supported | Activation verified on official page | Notes and charges |
|---|---|---|---|
| Unconditional forwarding | Yes | On the phone: Call Settings menu, then Call Forwarding, select the type, follow prompts to enter the destination. A free text message confirms activation. | Official page describes menu setup, not a star code, for current mobile service. |
| No-answer forwarding | Yes, with a distinction | Bell separates Call Forwarding (from the first ring) from No Answer Transfer (rings first, then forwards). On HSPA phones, the page describes voicemail-directed options without a separate No Answer Transfer subscription. | Whether no-answer forwarding to an external number such as ApexVoice needs a No Answer Transfer subscription on the specific plan is UNVERIFIED on the page read. Confirm before sale. |
| Busy forwarding | UNVERIFIED | The current mobile support page read does not give a busy-to-external-number procedure. | Do not promise Bell Mobility busy forwarding to ApexVoice without a test on the actual device and plan. |
| Scheduled forwarding | No evidence on official page | None found. | Treat as manual only. |
| Charges | Yes, stated | Pay-per-use call forwarding is $0.25 per minute if the customer does not subscribe to the service or it is not in the rate plan. Forwarding to a long-distance number bills applicable long-distance charges. Airtime treatment differs if forwarding to a landline versus another mobile. | This is the highest forwarding cost found among the big three mobile carriers in this research. |

Sources: Bell support, How to use Call Forwarding on my mobile phone, https://soutien.bell.ca/Mobility/Rate_plans_features/How_to_use_Call_Forwarding_on_my_mobile_phone , checked 2026-11-28. Bell Mobility features page listing call forwarding pay-per-use at $0.25 per minute, https://www.bell.ca/Mobility/Features/Call_features_applications.tab , checked 2026-11-28.
Device guide note: A Bell support device guide for the Huawei B882 Turbo Hub lists GSM style codes *21*number# for all calls, *67*number# for busy, and *61*number# for no answer, with #21#, #67#, and #61# to deactivate. That guide is for a specific legacy wireless home phone device, not for Bell Mobility generally, so those codes are not published in the customer document as general Bell Mobility codes. Source: https://support.bell.ca/_web/guides/User-Guides/Mobile/Huawei/Huawei-EN/Huawei-B882-User-Guide-EN.pdf , checked 2026-11-28.

### Rogers, business landline, Business Phone and IBLc

Two official Rogers sources were read. They describe related but distinct business phone products. Keep them separate for customers.

Rogers Business Phone (Rogers together with Shaw) support page:

| Feature | Supported | Activation verified on official page | Notes and charges |
|---|---|---|---|
| Unconditional forwarding | Yes | From the phone: lift receiver, dial *72, wait for dial tone, enter destination number, listen for the destination ring and answer it to activate; if busy or no answer, repeat and hang up on the second attempt. Turn off with *73 and hang up on the stutter tone. Also available in the My Rogers (Shaw) self-serve portal under Phone, Manage settings, Call Forwarding. | Available on Business Phone and Business Phone Plus plans. Works to Canada or US destinations only. Call Waiting does not work while Call Forward is on. Long-distance charges apply if the destination is long distance, with a 1 prefix. |
| No-answer forwarding | Yes, carrier provisioning first | A Rogers Business representative must set up Call Forward Busy and Call Forward No Answer before the customer can use them. Then, from the phone on site only: dial *92, enter destination, hang up on stutter tone. Off with *93. | Management is only possible from the phone on site, not through the self-serve portal and not by calling Rogers Support, per the page. No-answer forwards after a set number of rings; the page does not give the customer a ring count control. |
| Busy forwarding | Yes, carrier provisioning first | Same provisioning requirement. Dial *90, enter destination, hang up on stutter tone. Off with *91. | Cannot be used if the number is part of a Multi-line Hunt. |
| Scheduled forwarding | UNVERIFIED | No schedule feature on the page read. Simultaneous Ring to up to four numbers is offered instead. | Treat unconditional and conditional as manual. |
| Voicemail interaction | Yes, stated | Calls unanswered at the destination will not be sent back to Rogers voicemail. | Important for ApexVoice message handling expectations. |

Source: Rogers Business (Shaw) support, How to set up and use Call Forward for your Business Phone, https://business.shaw.ca/support/how-to-manage-call-forward-features , checked 2026-11-28.

Rogers IBLc Call Forward page:

| Feature | Supported | Activation verified on official page | Notes and charges |
|---|---|---|---|
| Unconditional forwarding | Yes | Dial *72, dial the full 10-digit number, and if someone answers stay on the line at least five seconds. If busy or no answer, dial *72 again and redial the number; two beeps confirm. Confirm status by dialling *72 and hearing a busy tone. Deactivate with *73, listen for two beeps. | Also manageable online with Business Online Manager, and remotely by Remote Access Number with a PIN. If voicemail is subscribed and calls are forwarded to an alternate number, voicemail will not take messages. Forwarding outside the local calling area bills long-distance charges if answered. Hunting members cannot have Call Forward. |
| Busy forwarding, Enhanced | Yes | Dial *90, listen for confirmation tone, enter the 10-digit number, stay at least five seconds if answered; if busy or no answer, repeat *90 and the number for two beeps. Deactivate with *91. | Part of Enhanced Call Forward. |
| No-answer forwarding, Enhanced | Yes | Dial *92, listen for confirmation tone, enter the 10-digit number, stay at least five seconds if answered, hang up; if busy or no answer, repeat for two beeps. Deactivate with *93. | If the customer subscribes to Business Voicemail, they cannot subscribe to Enhanced Call Forward, because all unanswered calls go to voicemail. This is a hard conflict to check at intake. |
| Scheduled forwarding | UNVERIFIED | Remote access is documented, schedules are not. | Manual or remote manual only. |
| Feature charges, general Rogers Business price list | Yes, stated on a separate official page | Not an activation item. | Rogers Business administrative charges page lists Call Forward at $6.00 and Enhanced Call Forward at $6.00 in its feature table, and pay-per-use Call Forward, Call Forward Busy, and Call Forward No Answer at 95 cents per use with a $4.75 cap in its pay-per-use table. Applicability depends on the customer product and plan, so quote only after checking the customer bill. Source: https://www.rogers.com/business/charges , checked 2026-11-28. |

Source: Rogers IBLc Call Forward, https://www.rogers.com/business/support/business-phone/iblc-call-forward , checked 2026-11-28.

### Rogers Advantage Voice (Unison), hosted business phone

| Feature | Supported | Activation verified on official page | Notes |
|---|---|---|---|
| Unconditional forwarding | Yes | MyBusiness Hub, Go to Rogers Unison, User Management, User Call Settings, View Details for the subscriber, toggle Call Forward on, enter the number, choose Forward all calls 24x7. | Portal only in the steps read. |
| Busy forwarding | Yes | Same portal path, choose Forward calls when the line is busy. |  |
| No-answer forwarding | Yes | Same portal path, choose Forward calls when no one answers. |  |
| Not reachable forwarding | Yes | Same portal path, choose Forward calls when not reachable. | Useful for outages. |
| Scheduled forwarding | Yes | In the same settings, select Use a schedule template or Create a new schedule, set time zone and times per day, mark closed days, save. | This is one of the few verified schedule options among the big carriers. Best Rogers path for after-hours ApexVoice. |
| Voicemail note | Yes, stated | Do Not Disturb can route callers directly to voicemail if voicemail is set up on the extension. | Check Do Not Disturb state during setup tests. |

Source: Rogers support, How to Use Call Forwarding with Advantage Voice, https://www.rogers.com/business/support/advantage-voice/user-features/call-forwarding , checked 2026-11-28.

### Rogers Mobility

| Feature | Supported | Activation verified on official page | Notes and charges |
|---|---|---|---|
| Unconditional forwarding | Yes | Dial **21* then the 10-digit number then # and Send, as printed on the Rogers page in the form **21*(number)#. Temporary deactivate #21#, reactivate *21#, cancel ##21#, status *#21#. | Page formatting compresses the leading stars. The sequence is reproduced here as Rogers prints the components: Activate shows 21 with the number and #, with star codes used for reactivate and status. Read the Rogers page with the customer if the handset rejects the first attempt. |
| Busy forwarding | Yes | Activate **67*(number)# Send. Temporary deactivate #67#, reactivate *67#, cancel ##67#, status *#67#. | Conditional forwarding will not work when voicemail is activated, per the page note. |
| No-answer forwarding | Yes | Activate *61*(number)# Send. Temporary deactivate #61#, reactivate *61#, cancel ##61#, status *#61#. | Same voicemail conflict. The customer must deal with carrier voicemail before conditional forwarding to ApexVoice works. |
| Not reachable forwarding | Yes | Activate *62*(number)# Send. Temporary deactivate #62#, reactivate *62#, cancel ##62#, status *#62#. | Same voicemail note applies to conditional forwarding generally. |
| Scheduled forwarding | No evidence on official page | None found. | Manual only. |
| Charges | UNVERIFIED | The mobile page read does not state a per-minute forwarding charge. | Check the customer plan. Do not assume forwarding minutes are included. |

Source: Rogers support, How to use wireless/mobile Call Forwarding, https://www.rogers.com/support/mobility/use-call-forwarding , checked 2026-11-28.

### TELUS, business landline, Office Phone

| Feature | Supported | Activation verified on official page | Notes and charges |
|---|---|---|---|
| Unconditional forwarding | Yes, feature exists | TELUS Business support has a dedicated article, Call Forward on your Office Phone, which states Call Forward automatically forwards calls to another number from an Office Phone and points readers to star commands for office phone. The full star command table on that article could not be rendered in this research session, so the exact sequence is UNVERIFIED here. | A separate official TELUS Quebec calling features page lists Automatic Call Forwarding as dial 72# to forward calls and dial 73# to stop. Quebec codes differ in format from the star format used elsewhere, which confirms regional variation and is a reason not to guess. Source for Quebec: https://www.telus.com/en/telephonie/options , checked 2026-11-28. |
| No-answer forwarding | UNVERIFIED | Not confirmed on a readable official page in this session. | Pre-sale verification call to TELUS required. See the product risk note in the summary. |
| Busy forwarding | UNVERIFIED | Not confirmed on a readable official page in this session. | Same as above. |
| Ring count control | UNVERIFIED for Office Phone | A TELUS forum answer, not a support article, describes *94 to set rings before voicemail from 2 to 9 on home phone. That is not sufficient evidence for a business Office Phone claim. | Do not publish *94 as a TELUS business step. |
| Scheduled forwarding | UNVERIFIED | No schedule feature confirmed. | Treat as manual only. |
| Charges | UNVERIFIED | No forwarding charge confirmed on a readable official page. | Check the customer bill. |

Primary source attempted: TELUS Business support, Call Forward on your Office Phone, https://www.telus.com/business/support/article/use-call-forwarding-variable , checked 2026-11-28. The page exists and its title and opening lines were confirmed, but its detailed content renders with JavaScript and was not fully readable with the research tools available. This is a tooling limitation, not evidence that TELUS lacks the features.

### TELUS Business Connect, hosted phone (RingCentral platform)

| Feature | Supported | Activation verified | Notes |
|---|---|---|---|
| Call handling and forwarding to an external number | Yes | TELUS Business support article on changing rings confirms the portal path: as a user, Settings, then Call Handling and Forwarding, change Ring For time, Save. As an admin, in Voice Manager: Users, select the user, Call Handling and Forwarding, change Ring For, Save. | This verifies the portal location and ring duration control for Business Connect. Source: https://www.telus.com/en/business/support/article/business-connect-change-amount-rings-inbound-calls , checked 2026-11-28. |
| Separate business hours and after-hours handling | Yes, in product documentation | The TELUS Business Connect mobile app guide table of contents lists User Hours Call Handling and Forwarding and After-Hours Call Handling and Forwarding as separate sections, plus Call Handling, Advanced Rules. | The guide is an official TELUS resources PDF, dated in its file record as an older guide. Treat the structure as verified, and confirm current portal labels on the customer account during setup. Source: http://resources-business.telus.com/cms/files/files/000/001/066/original/TELUS_Mobile_App_Guide.pdf , checked 2026-11-28. |
| Forwarding to an outside number that is not on the account, press-1 announcement, and queue limitation | UNVERIFIED from TELUS official pages | These details appear in vendor integration documentation for a different receptionist product, not on a TELUS page read here. | Verify on the live account during the setup test calls, especially any press-1 or PIN-to-answer prompt, which would break an AI receptionist answer. |

### TELUS Mobility

| Feature | Supported | Activation verified on official page | Notes and charges |
|---|---|---|---|
| Unconditional forwarding | Yes | TELUS Business support article states Call Forwarding Unconditional can be used on any device, and that forwarding is managed in the device Call Settings section or by dialling specific star and pound commands. The article text available in this session did not include the full code table, so specific codes are UNVERIFIED here. | Do not publish TELUS Mobility GSM codes from third-party sites as TELUS-verified. Use the device Call Settings menu path, which TELUS does verify, and test on the handset. |
| No-answer and busy forwarding | Yes, device dependent | Same article: the other forwarding features are device dependent and may not be compatible with every business device. The selected option determines when a call forwards, for example immediately, after 3 rings, or only if the line is busy. | Confirm on the actual device before promising conditional forwarding. |
| Text messages | No, stated | Text and multimedia messages cannot be forwarded and continue to be delivered to the device. | Relevant if the business expects SMS on the same number to move. It does not. |
| Scheduled forwarding | No evidence on official page | None found. | Manual only. |
| Charges | UNVERIFIED in detail | The article has a billing information section and warns about potential long-distance charges and that forwarding another number to the mobile continues to use minutes included in the rate plan. A specific per-minute forwarding rate was not readable in this session. | Check My TELUS and the rate plan before projecting costs. |

Source: TELUS Business support, Set up call forwarding on business mobile device, https://www.telus.com/en/business/support/article/call-forward-mobile , checked 2026-11-28.

### RingCentral

TELUS Business Connect is built on the RingCentral platform, and many Canadian small businesses buy RingCentral directly, so RingCentral is documented on its own official support pages here.

| Feature | Supported | Activation verified on official page | Notes |
|---|---|---|---|
| Forward all calls | Yes | In the RingCentral app: Settings, Phone, Edit next to Call handling, toggle Forward all calls, choose a contact or phone number, optionally specify start and end dates, Save. Forward all overrides work hours and after-hours handling. | Admin portal has equivalent company-level controls. |
| Work hours and after-hours rules | Yes | Edit schedule to set a specific work schedule. Separate call handling can then be set for work hours and after hours. If the schedule is 24 hours, 7 days a week, after-hours settings match work settings. | This is a verified schedule path for after-hours ApexVoice. |
| Missed call forwarding to an external number | Yes | In Call handling for work or after hours, under Missed calls choose Forward to external number and enter the number, then Save. Incoming calls can ring in order or all at once before the missed call rule applies. | Ring in order with the business devices first, then the missed call rule to ApexVoice, is the cleanest RingCentral pattern for staff-first answering. |
| Busy forwarding as a separate named rule | UNVERIFIED on the pages read | The official app support page read describes missed calls handling rather than a distinct busy rule at user level. Call queue wait settings handle busy and full queue cases at admin level in other RingCentral documentation not fully read here. | Use missed call and queue overflow testing on the live account. |
| Charges | UNVERIFIED | No forwarding charge stated on the pages read. Forwarding to an external PSTN number normally consumes plan minutes on hosted systems, but that is not stated here and is not claimed. | Check plan terms. |

Sources: RingCentral support, Setting up user call forwarding in the RingCentral app, https://support.ringcentral.com/shared/content/app/setting-up-user-call-forwarding-in-the-ringcentral-app-desktop-a.html , checked 2026-11-28. RingCentral support PDF, Configuring your extension call handling settings, https://support.ringcentral.com/content/dam/support/us/en/pdf/get-started/v2/RCA_Configuring_Your_Extensions_Call_Handling_Settings.pdf , checked 2026-11-28.

### Vonage Business and Vonage Enterprise

| Feature | Supported | Activation verified on official page | Notes |
|---|---|---|---|
| Always forwarding | Yes | Sign in to the Vonage Enterprise Portal, go to Voice Settings, then Call Forwarding, enable Always and set the destination. | Depending on account permissions, Call Forwarding settings may not be accessible in the portal, per the page note. |
| Busy forwarding | Yes | Same portal path, enable Busy. |  |
| No-answer forwarding | Yes | Same portal path, enable No Answer. The page describes forwarding when the user does not answer after a specific number of rings. | Ring count is referenced but the setting location detail is limited on the page read. |
| Not reachable forwarding | Yes | Same portal path, enable Not Reachable for when the phone is not reachable or there is a network issue. | Good outage safety net. |
| Scheduled forwarding | UNVERIFIED | Not described on the official page read. | Do not promise Vonage schedules from this research. |

Source: Vonage Business Support, Configure Call Forwarding, https://businesssupport.vonage.com/articles/answer/Configure-Call-Forwarding , page updated 2020-10-05 as shown on the page, checked 2026-11-28.

### Ooma Office

| Feature | Supported | Activation verified on official page | Notes |
|---|---|---|---|
| Forward all calls from an extension | Yes | From an Ooma desk phone: dial *72, wait for the prompt, enter the receiving phone number followed by #. Toggle forwarding with *74. Also in the Desktop App call handling preferences: choose Forward it immediately, select My External Number, enter the number, Save. | When calls are forwarded to a phone number, the user devices will not ring, per the Ooma Office user guide. |
| Forward when devices are offline | Yes | Desktop App preferences include the option: if my phone is offline, forward it to an external number. Ooma feature list describes call forwarding as forwarding to a cell phone or landline when Ooma Office devices are offline. | This is an outage safety net, not a general busy rule. |
| No-answer handling | Partial | Desktop App: choose Ring my phone, use the For menu for ring duration (default 24 seconds, described as four rings), then use Then send to for what happens if the call is not answered. Ooma feature comparison lists Call forward on no answer as a feature. | Whether Then send to can target an arbitrary external number on every plan is UNVERIFIED on the pages read. Test on the account. |
| Scheduled or after-hours forwarding | Yes, through Virtual Receptionist | Ooma Office includes a Virtual Receptionist on all plans listed on Ooma Canada pricing pages, and the Desktop App and portal structure support separate call handling. The detailed Virtual Receptionist schedule steps were not read on an official Ooma support page in this session, so the step sequence is UNVERIFIED here. | Confirm the after-hours action can target an external number on the customer plan before sale. A third-party note says a Shared External Line may be required and may be limited to higher plans and one per account. That is UNVERIFIED from Ooma. |
| Require key press on answer | Yes, stated, and it is a hazard | Ooma Office mobile app preferences include Require key press on answer for forwarded calls, described as preventing callers from reaching the external number voicemail if unanswered. | For ApexVoice, this must be OFF for the forwarding destination. An AI receptionist cannot press 1 to accept. Add this to the test call checklist for every Ooma customer. |
| Charges | UNVERIFIED | No forwarding charge stated on the official pages read. | Check plan terms. |

Sources: Ooma support, Yealink IP phone user guide, Calling features, https://support.ooma.com/office/yealink-cordless-ip-phone-user-guide/ , checked 2026-11-28. Ooma support, Ooma Desktop App FAQs, https://support.ooma.com/regus/ooma-desktop-app-faqs/ , checked 2026-11-28. Ooma support, Ooma Office Mobile App FAQs, Preferences: Call Forward, https://support.ooma.com/regus/ooma-office-mobile-app-faqs/ , checked 2026-11-28. Ooma support, Ooma Office user features index, https://support.ooma.com/office/user-features/ , checked 2026-11-28.

### VoIP.ms

| Feature | Supported | Activation verified on official page | Notes and charges |
|---|---|---|---|
| Forward a DID to any number | Yes | Customer Portal, DID Numbers, Call Forwarding: create a Call Forwarding entry with the destination phone number. Then DID Numbers, Manage DID, Edit DID, set Routing to Call Forwarding and select the entry, apply changes. The same entry can be assigned to many DIDs. | Canada and US numbers can be entered as 10 digits or with a 1 prefix. International forwarding requires International Calls enabled on the account. |
| Conditional, busy, or no-answer forwarding as a DID routing rule | No, not as described on the page | The Call Forwarding page describes direct routing of a DID to a forwarding entry. Conditional behaviour is handled in VoIP.ms through other constructs such as ring groups, time conditions, and failover, which were not researched in this session and are UNVERIFIED here. | For a VoIP.ms customer, expect to build the staff-first pattern with a ring group plus time condition or failover to the forwarding entry, and verify in the portal. Do not quote steps not yet researched. |
| Scheduled forwarding | UNVERIFIED | Time conditions exist as a VoIP.ms concept but were not verified in this session. | Research before first VoIP.ms onboarding. |
| Charges | Yes, stated in part | The wiki states that when forwarding a call, normal inbound charges apply according to the DID plan, and outbound charges apply for the forwarded leg. The full charge paragraph was truncated in the page read, so exact rates are UNVERIFIED here. | Customer pays both legs on VoIP.ms. Confirm current per-minute rates in the customer portal. |

Source: VoIP.ms Wiki, Call Forwarding, https://wiki.voip.ms/article/Call_Forwarding , checked 2026-11-28.

### Fongo Home Phone and Fongo Mobile, including FreePhoneLine

| Feature | Supported | Activation verified on official page | Notes and charges |
|---|---|---|---|
| Follow Me forwarding | Yes | Fongo Home Phone: log in at Fongo, Settings, Follow Me Settings, set Status to Enable, Submit, then Follow Me Numbers, add numbers, Back, choose Ring Mode Simultaneous or Sequential, Submit. Fongo Mobile app: side menu, Account, Settings, Phone Service, Call Forwarding, choose mode, enter numbers and rings before forwarding. | Sequential rings the home or Fongo number first, then the Follow Me numbers, which fits staff-first answering. |
| Forward when unavailable | Yes | Follow Me Mode includes Call Forward When Unavailable on Home Phone per Fongo documentation summaries; the Home Phone support page read describes Always Call Forward under Simultaneous mode and the Follow Me mode settings. | Test the unavailable mode on the account before relying on it. |
| Destination limits | Yes, stated | Forwarding destinations must be Canadian numbers in the 10 provinces for free forwarding. Territories are excluded. US forwarding needs World Credits on Fongo Mobile and is not available to toll-free numbers. International forwarding numbers cannot be added on Home Phone. | An ApexVoice Canadian local DID is a valid destination type. An ApexVoice toll-free number would not be, on Fongo Mobile. Use a local ApexVoice number for Fongo customers. |
| Scheduled forwarding | No evidence on official page | None found. | Manual or Follow Me only. |
| Auto-disable risk | Yes, stated | Follow Me settings reset to off if the account has not been used to place an outgoing call for 30 days on Fongo Mobile, and 90 days on FreePhoneLine. Home Phone also requires the adapter to stay connected to the internet for forwarding to function. | This is a reliability risk for a business line. Fongo is a weak fit for a primary business number that must forward unattended for months. Flag at intake. |
| Charges | Partial | Free to Canadian provincial numbers within the stated limits. US forwarding consumes World Credits where allowed. |  |

Sources: Fongo support, Call Forwarding on Fongo Home Phone, https://support.fongo.com/hc/en-us/articles/212437566-Call-Forwarding-on-Fongo-Home-Phone , checked 2026-11-28. Fongo support, Call Forwarding on Fongo Mobile, https://support.fongo.com/hc/en-us/articles/212434466-Call-Forwarding-on-Fongo-Mobile , checked 2026-11-28. FreePhoneLine support, About Call Forwarding (Follow Me), https://support.freephoneline.ca/hc/en-us/articles/212430386-About-Call-Forwarding-Follow-Me , checked 2026-11-28.

## Path D: Human transfer behaviour

No carrier setup is required for Path D, and it is independent of Paths A, B, and C.

- How a transfer works: The caller is connected to ApexVoice on a SignalWire number. That is leg one, an inbound leg. When ApexVoice transfers the caller to a human, it creates leg two, an outbound call from SignalWire to the transfer target number. The two legs are bridged so the caller and the human speak directly. If the transfer uses SIP Refer, SignalWire hands the call off at the carrier level instead of keeping both legs bridged for the full conversation.
- Verified SignalWire prices that apply: Canada local outbound is $0.00800 USD per minute on the pricing page. SIP Refer is listed at $0.10 USD per use in Canada Voice Features. A bridged transfer therefore costs outbound minutes for the duration of the human conversation. A SIP Refer transfer costs the flat refer fee and ends SignalWire involvement in the media path, subject to how ApexVoice implements transfer in its backend, which is a product implementation detail and not a carrier fact. Sources: https://signalwire.com/pricing , checked 2026-11-28.
- The business existing number can be the transfer target with no forwarding setup at all. The business does not need to forward anything to ApexVoice for ApexVoice to call them. Forwarding controls how calls reach ApexVoice. Transfer controls how ApexVoice reaches a human. They are opposite directions and are configured separately.
- Practical rules: The transfer target should be a number a human actually answers during the hours ApexVoice promises a handoff. It should not be the same number that unconditionally forwards back to ApexVoice, or the caller will loop. If the business main number forwards conditionally to ApexVoice and is also the transfer target, a transferred call that rings unanswered can forward back to ApexVoice. Set the transfer target to a direct staff line or mobile that does not forward to ApexVoice, or accept the loop risk knowingly and test it.
- Caller ID on the transfer leg: UNVERIFIED in this research for the ApexVoice implementation. Whether the human sees the original caller number, the ApexVoice number, or the business number depends on SignalWire configuration and verified caller ID settings. Test during pilot and document the observed result per tenant.

## Explicit unverified items list

Do not present any of the following to a customer as confirmed. Each item names what would close it.

- TELUS Office Phone exact star sequences for unconditional, busy, and no-answer forwarding, and whether the busy and no-answer destinations are customer-chosen or TELUS-set. Close by: reading the TELUS star commands support article in a full browser, or a test call session on a TELUS Office Phone line with TELUS support on the phone.
- TELUS Office Phone ring count control and forwarding charges. Close by: same as above, plus the customer bill.
- TELUS Mobility specific GSM forwarding codes and per-minute forwarding rate. Close by: TELUS mobile forwarding article full text, device test, and My TELUS plan details.
- TELUS Business Connect external forwarding details: press-1 announcement behaviour, PIN to answer, queue versus extension forwarding, and current portal labels. Close by: live account test during first Business Connect onboarding.
- Bell Mobility busy forwarding to an external number, and whether no-answer forwarding to an external number requires a No Answer Transfer subscription on current plans. Close by: device and plan test with Bell support confirmation.
- Bell Total Connect scheduled forwarding and forwarding charges. Close by: Bell account confirmation.
- Bell Local Link ring count control for no-answer forwarding beyond the stated 4 rings. Close by: Bell support confirmation for the specific line.
- Rogers Mobility per-minute forwarding charges and whether forwarding minutes are included in common business mobile plans. Close by: customer plan documents.
- Rogers Business Phone (Shaw) scheduled forwarding. Close by: Rogers support confirmation. Assume manual until confirmed.
- Vonage scheduled forwarding and no-answer ring count setting location. Close by: Vonage portal walkthrough on a customer account.
- Ooma Office Virtual Receptionist schedule steps to an external number, plan requirements for a Shared External Line, and whether Then send to can target an external number on all plans. Close by: Ooma portal walkthrough on a customer account.
- VoIP.ms time conditions, ring group failover steps, and exact forwarding leg rates. Close by: VoIP.ms wiki research on Time Conditions and Ring Groups plus portal rate check.
- Fongo Home Phone Follow Me Mode exact options as rendered in the current portal. Close by: portal walkthrough.
- Early cancellation fees and contract terms for any carrier. Close by: customer contract and carrier confirmation, per customer.
- Caller ID presentation on ApexVoice transfer legs. Close by: pilot test calls.
- Any claim that Canadian wireless ports complete in hours. Close by: an official carrier or SignalWire source. SignalWire publishes up to two weeks for Canadian numbers and that is the only timeline used in customer documents.

## Carrier limitations that change the product recommendation

- TELUS traditional landline is the weakest verified position in the matrix. Until the TELUS Office Phone conditional forwarding question is closed, do not sell a TELUS landline customer a self-serve staff-first setup. Sell unconditional forwarding, a TELUS-supported change, Business Connect, or a dedicated ApexVoice number, and verify with test calls before taking payment for onboarding.
- Rogers Mobility conditional forwarding requires voicemail to be inactive. For a business mobile that is the main number, removing carrier voicemail is a real loss. ApexVoice can take messages instead, but the customer must choose that knowingly. Put it in writing at intake.
- Rogers IBLc Enhanced Call Forward cannot be subscribed at the same time as Business Voicemail. Same trade-off, on a landline product.
- Rogers Business Phone (Shaw) busy and no-answer features require a Rogers representative to provision them first, and can only be managed from the phone on site. Onboarding for these customers needs a carrier call before the setup session, and remote troubleshooting by Harbour and Main is limited.
- Bell Mobility pay-per-use forwarding at $0.25 per minute can exceed the ApexVoice margin on a high-volume mobile. Quote Bell Mobility customers the subscribed feature or an included plan, or steer them to a dedicated number or porting after a cost comparison.
- Hosted systems are the best fit for after-hours schedules: Rogers Advantage Voice, RingCentral, and TELUS Business Connect all support separate after-hours handling. Traditional landlines from all three big carriers need a human to dial codes at open and close, which fails in practice. For landline customers who want automatic after-hours coverage, the honest recommendation is conditional forwarding all day, which gives most of the benefit with no daily ritual.
- Fongo Follow Me auto-disables after 30 to 90 days without an outgoing call, depending on the product. Do not onboard a Fongo number as a set-and-forget business line without warning the customer and adding a periodic test call to the support routine.
- Ooma Require key press on answer must be off for any forwarding destination that is ApexVoice. Add it to the Ooma test checklist.
- VoIP.ms customers pay inbound and outbound leg charges on forwarded calls. Small amounts, but they belong in the cost conversation.

## Source list

All sources checked 2026-11-28.

- SignalWire pricing, https://signalwire.com/pricing
- SignalWire porting guide, https://signalwire.com/docs/platform/porting-into-signalwire
- SignalWire, Verified Caller ID and Local Number Portability, https://signalwire.com/blog/verified-caller-id-local-number-portability
- CRTC, Choosing a Local Home Phone Service, https://crtc.gc.ca/eng/phone/residence/local.htm
- Bell Business, How to use Call Forwarding, https://entreprise.bell.ca/Support/small-business/phone/calling-features/how-to-use-call-forwarding
- Bell Total Connect packages and features, https://business.bell.ca/Support/medium-large/voice-unified-communications/total-connect/talk-package-features
- Bell support, How to use Call Forwarding on my mobile phone, https://soutien.bell.ca/Mobility/Rate_plans_features/How_to_use_Call_Forwarding_on_my_mobile_phone
- Bell Mobility features, https://www.bell.ca/Mobility/Features/Call_features_applications.tab
- Bell support device guide, Huawei B882 Turbo Hub, https://support.bell.ca/_web/guides/User-Guides/Mobile/Huawei/Huawei-EN/Huawei-B882-User-Guide-EN.pdf
- Rogers Business (Shaw), How to set up and use Call Forward for your Business Phone, https://business.shaw.ca/support/how-to-manage-call-forward-features
- Rogers, IBLc Call Forward, https://www.rogers.com/business/support/business-phone/iblc-call-forward
- Rogers Business administrative charges, https://www.rogers.com/business/charges
- Rogers, How to Use Call Forwarding with Advantage Voice, https://www.rogers.com/business/support/advantage-voice/user-features/call-forwarding
- Rogers, How to use wireless/mobile Call Forwarding, https://www.rogers.com/support/mobility/use-call-forwarding
- TELUS Business, Call Forward on your Office Phone, https://www.telus.com/business/support/article/use-call-forwarding-variable
- TELUS Business, Set up call forwarding on business mobile device, https://www.telus.com/en/business/support/article/call-forward-mobile
- TELUS Business, Changing the amount of rings for inbound calls, Business Connect, https://www.telus.com/en/business/support/article/business-connect-change-amount-rings-inbound-calls
- TELUS calling features, Quebec, https://www.telus.com/en/telephonie/options
- TELUS Business Connect mobile app guide, http://resources-business.telus.com/cms/files/files/000/001/066/original/TELUS_Mobile_App_Guide.pdf
- RingCentral support, Setting up user call forwarding in the RingCentral app, https://support.ringcentral.com/shared/content/app/setting-up-user-call-forwarding-in-the-ringcentral-app-desktop-a.html
- RingCentral support, Configuring your extension call handling settings, https://support.ringcentral.com/content/dam/support/us/en/pdf/get-started/v2/RCA_Configuring_Your_Extensions_Call_Handling_Settings.pdf
- Vonage Business Support, Configure Call Forwarding, https://businesssupport.vonage.com/articles/answer/Configure-Call-Forwarding
- Ooma support, Yealink IP phone user guide, https://support.ooma.com/office/yealink-cordless-ip-phone-user-guide/
- Ooma support, Ooma Desktop App FAQs, https://support.ooma.com/regus/ooma-desktop-app-faqs/
- Ooma support, Ooma Office Mobile App FAQs, https://support.ooma.com/regus/ooma-office-mobile-app-faqs/
- Ooma support, Ooma Office user features, https://support.ooma.com/office/user-features/
- VoIP.ms Wiki, Call Forwarding, https://wiki.voip.ms/article/Call_Forwarding
- Fongo support, Call Forwarding on Fongo Home Phone, https://support.fongo.com/hc/en-us/articles/212437566-Call-Forwarding-on-Fongo-Home-Phone
- Fongo support, Call Forwarding on Fongo Mobile, https://support.fongo.com/hc/en-us/articles/212434466-Call-Forwarding-on-Fongo-Mobile
- FreePhoneLine support, About Call Forwarding (Follow Me), https://support.freephoneline.ca/hc/en-us/articles/212430386-About-Call-Forwarding-Follow-Me
