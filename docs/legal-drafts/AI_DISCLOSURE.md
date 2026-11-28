# DRAFT, NOT LEGAL ADVICE, REQUIRES PROFESSIONAL LEGAL REVIEW BEFORE USE

# ApexVoice AI Disclosure

Provider: Harbour & Main, operating ApexVoice
Applies to: Business customers using ApexVoice, and callers who reach a business through ApexVoice
Date of draft: November 28, 2026

## Purpose

This document provides the caller facing disclosure scripts and the website disclosure for ApexVoice. The goal is simple: a caller should know, at the start of the call, that they are speaking with an AI receptionist, what will happen to the information they share, and how to reach a human.

Wording must match the actual configuration of each business. Do not use a script that mentions recording for a business that does not have recording enabled. Do not use a script that omits transcription when transcription is enabled.

## Current product state reflected in these scripts

- Audio recording is not enabled by default.
- Transcription is enabled.
- If a business enables audio recording in the future, the recording enabled script must be used for that business, and onboarding must record that choice.

## Caller facing script, transcription on, recording off

Use at the start of the call, in the configured greeting, spoken clearly and at a normal pace:

"Hello, thank you for calling [Business Name]. I am [Receptionist Name], an AI receptionist for [Business Name]. I can take a message, answer common questions, and help book an appointment. This call is transcribed so the business can review your message. It is not audio recorded. If you would prefer to speak with a person, say human at any time, and I will [transfer your call / take a message for a callback] as [Business Name] has set up. Please do not share detailed medical, legal, or other sensitive personal information on this call."

Short version, only where the full version has been provided elsewhere in the same call flow and legal review approves a short form:

"Hello, thank you for calling [Business Name]. I am an AI receptionist, and this call is transcribed for the business to review your message. How can I help you?"

## Caller facing script, recording enabled

Use only for businesses where audio recording is actually enabled for the call:

"Hello, thank you for calling [Business Name]. I am [Receptionist Name], an AI receptionist for [Business Name]. This call is recorded and transcribed so the business can review your message and help you. If you do not want to be recorded, please hang up and contact [Business Name] by [alternative contact method provided by the business]. If you would prefer a person, say human at any time. Please do not share detailed medical, legal, or other sensitive personal information on this call."

## If a caller asks if they are speaking to a human

The receptionist must answer truthfully, without qualification:

"I am an AI receptionist, not a person. I work for [Business Name] to take messages and help with bookings. I can take a message for the team, or help you with [services configured for the business]."

The receptionist must never claim to be human, claim to be a specific employee, claim to have personal experience, or continue a conversation on the basis that the caller believes it is human after it knows otherwise.

## If a caller asks for a human

- Follow the business configured escalation rule: transfer to the configured number if transfer is set up, or take a complete message and state the callback time frame the business has configured.
- Do not argue, do not repeat the offer of AI help more than once, and do not make the caller ask twice.
- If no human path is configured, say so honestly, take a message, and flag the business configuration gap in the dashboard. A business must configure a human path during onboarding.

## If a caller objects to transcription or recording

- Stop, acknowledge the objection, and offer the alternative the business has configured: a callback from a person, an email address, or another contact method.
- Mark the call record with the objection so the business can handle any related access or deletion request.
- Do not pressure the caller to continue.

## Website disclosure, for harbourandmain.com and the ApexVoice product pages

Suggested public wording, to be placed where the service is described and where a demonstration is offered:

"ApexVoice is an AI receptionist service from Harbour & Main. When a business uses ApexVoice, callers speak with an AI system, not a human receptionist. Calls handled by ApexVoice are transcribed so the business can review messages, and a business may also enable audio recording, in which case callers are told at the start of the call. ApexVoice can take messages, answer questions the business has provided answers for, and help book appointments based on the business configuration. It can make mistakes, it does not provide medical or legal advice, and it is not for emergency calls. Always call 911 in an emergency."

## Demonstration disclosure

Any public demonstration must state, on the same page as the demonstration and before the visitor starts it:

- What is simulated, for example a sample business, sample appointments, and sample dashboard data.
- What is connected to real services, if anything.
- That no real business will receive a message from the demonstration unless the page explicitly says so and the visitor confirms it.
- That demonstration conversations should not include real personal information.

Do not present demonstration data, sample calls, or sample statistics as real customer activity.

## Business customer responsibilities for disclosure

- Keep the business name, receptionist name, greeting, transfer number, callback promise, and alternative contact method accurate in the configuration.
- Tell Harbour & Main if recording is enabled through any other system on the same phone number, so caller wording stays accurate.
- Train staff who receive messages and transcripts on what the disclosure promised callers, including retention and the objection process.
- Do not instruct the receptionist to hide that it is an AI system. Harbour & Main will not configure a receptionist to claim to be human.

## Harbour & Main responsibilities for disclosure

- Provide the disclosure scripts, keep them current with the product configuration options, and make the recording on or off state visible in onboarding and in the dashboard.
- Build the greeting flow so the disclosure is spoken before personal information is collected, other than the greeting exchange itself.
- Record in the call record which disclosure version was used, where the system supports it.
