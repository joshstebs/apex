# ApexVoice Pricing and Profitability Analysis

Prepared for: Harbour & Main, ApexVoice (joshstebs/apex)
Date prepared: November 28, 2026
Status: Recommendations only. These are not approved prices. Do not activate billing, do not publish these prices, and do not quote them to customers until Josh approves a final price list and billing metering is live and verified.
Currency: All final recommendations are in Canadian dollars (CAD) unless a row is labelled USD. Competitor and supplier prices were published in USD.

## Executive summary

- ApexVoice assembles its own stack. It does not use the SignalWire AI runtime priced at $0.16 USD per minute. Its direct cost is driven mainly by ElevenLabs text to speech, not by telephony transport.
- Base case direct variable cost is estimated at $0.135 CAD per call minute. See the cost model below for every assumption and the range.
- At that cost, copying competitor included minutes at Canadian price points that look similar in number to United States prices loses money or leaves almost no margin. Example: 250 included minutes for $49 CAD is not viable once support time is counted.
- The hypothesised price points, Starter $49 CAD, Professional $99 CAD, Business $199 CAD, Enterprise custom, can work, but only with lower included minutes than the large United States competitors bundle at the same numeric price.
- Recommended included minutes at the hypothesised prices: Starter 120 minutes, Professional 350 minutes, Business 800 minutes, Enterprise custom with a $499 CAD per month minimum.
- Overage must be priced well above direct cost: $0.40 CAD per minute on Starter, $0.35 CAD on Professional, $0.30 CAD on Business.
- No tier in the recommended structure loses money on direct service costs at 100 percent utilisation of included minutes. All three tiers fall to thin contribution after a realistic support allowance at 100 percent utilisation, which is why included minutes were cut rather than prices raised. The trade off is stated explicitly in the tier section.
- Billing cannot go live safely until per tenant metering listed at the end of this document is built, tested, and reconciled against SignalWire and ElevenLabs invoices for at least one full billing cycle in staging.

## Sources and dating

- Supplier prices below are published list prices checked in November 2026. List prices change, promotional prices differ, and negotiated rates differ. Re check before any price is approved.
- Competitor prices below are published list prices checked in November 2026, from each provider public pricing page as provided in the research brief. Features, definitions of a call, a customer, and a minute differ between providers, so the table is a market reference, not a like for like feature comparison.
- No statistic in this document is fabricated. Where a figure is an internal estimate, it is labelled estimate and the assumption behind it is stated.

## Foreign exchange assumption and sensitivity

- Base assumption: 1 USD = 1.36 CAD, stated in the research brief, November 2026.
- Almost all ApexVoice direct costs are billed in USD, while customer revenue would be in CAD. That mismatch is the single largest pricing risk.
- Sensitivity of variable cost per call minute to the exchange rate, holding USD costs constant at the base case $0.0991 USD per minute:
  - At 1.25 CAD per USD: $0.124 CAD per minute
  - At 1.36 CAD per USD: $0.135 CAD per minute
  - At 1.45 CAD per USD: $0.144 CAD per minute
- Sensitivity of Business tier gross margin at 100 percent utilisation of 800 included minutes, $199 CAD price, $10 CAD fixed direct cost:
  - At 1.25 CAD per USD: cost $109.20 CAD, gross profit $89.80 CAD, gross margin 45.1 percent
  - At 1.36 CAD per USD: cost $118.00 CAD, gross profit $81.00 CAD, gross margin 40.7 percent
  - At 1.45 CAD per USD: cost $125.20 CAD, gross profit $73.80 CAD, gross margin 37.1 percent
- Guardrail: review prices if the rate moves beyond 1.42 CAD per USD for a full month, and write a foreign exchange review clause into annual contracts.

## Competitor landscape

Published list prices, November 2026. CAD conversions use 1 USD = 1.36 CAD and are rounded to the nearest cent. They are conversions of USD list prices, not prices those companies charge in Canada.

| Provider | Published USD price | Converted CAD price | What is included, as published | Notes |
|---|---|---|---|---|
| Rosie AI | $49 USD per month | $66.64 CAD per month | 250 minutes | Entry tier |
| Rosie AI | $149 USD per month | $202.64 CAD per month | 1,000 minutes | Mid tier |
| Rosie AI | $299 USD per month | $406.64 CAD per month | 2,000 minutes | High tier |
| Goodcall | $79 USD per month | $107.44 CAD per month | 100 unique customers, unlimited minutes as published | Priced per unique customer, not per minute, so minute comparison is not valid |
| Goodcall | $129 USD per month | $175.44 CAD per month | 500 unique customers, unlimited minutes as published | Same note as above |
| Goodcall | $299 USD per month | $406.64 CAD per month | 2,000 unique customers, unlimited minutes as published | Same note as above |
| Smith.ai, AI Receptionist | Free | Free | 25 calls | Trial style entry |
| Smith.ai, AI Receptionist Pro | $150 USD per month | $204.00 CAD per month | 75 calls, overage $2.50 USD per call ($3.40 CAD per call) | Priced per call, not per minute. At an assumed 3 minute average call, that is about $1.13 CAD per minute of overage |
| Smith.ai, human receptionist plans | From $300 USD per month | From $408.00 CAD per month | Human staffed service | Different cost base, premium trust positioning |
| Ruby, human receptionist | $250 USD per month | $340.00 CAD per month | 50 minutes | Human staffed, about $6.80 CAD per included minute at this tier |
| Ruby, human receptionist | $1,725 USD per month | $2,346.00 CAD per month | 500 minutes | Human staffed, about $4.69 CAD per included minute at this tier |
| My AI Front Desk | $99 USD per month, or $79 USD per month billed annually | $134.64 CAD per month, or $107.44 CAD per month billed annually | 200 voice minutes | Closest small business comparator |

Reading of the market:

- United States AI receptionist entry prices cluster near $49 to $99 USD per month, which is $66.64 to $134.64 CAD. A $49 CAD Starter is therefore priced well below the converted United States entry price. That is a deliberate local and small business positioning choice, and it only works with a smaller minute bundle.
- Human receptionist services, Smith.ai human plans and Ruby, cost several times more. ApexVoice should not claim human equivalence. It should compete on price, after hours coverage, and instant setup, with clear disclosure that it is an AI service.
- Per call pricing, per unique customer pricing, and per minute pricing are not interchangeable. Sales material must state ApexVoice pricing in minutes, define a minute, and state how partial minutes are billed, before launch.
- No competitor figure in this table is a testimonial, a market share claim, or a performance claim. Do not turn these prices into claims about ApexVoice call quality or savings percentages without measured ApexVoice data.

## Bottom up cost model per call minute

Stack in scope, as built: SignalWire inbound voice, ElevenLabs text to speech using eleven_turbo_v2_5 with voice Rachel, Hugging Face router large language model meta-llama/Llama-3.1-8B-Instruct, Upstash Redis, Vercel hosting. SignalWire AI runtime is not used.

Assumptions, all stated:

- Average call length for per call cost spreading: 3 minutes, estimate. Used only to spread the per call language model estimate into a per minute figure.
- Receptionist speaks about half of a typical call. Spoken output averages roughly 750 to 900 characters per minute of speech. Modelled spoken characters per call minute: 400 to 450, base case 425.
- ElevenLabs published rate used: roughly $0.18 USD per 1,000 characters, November 2026 list estimate from the research brief. Actual cost depends on the ElevenLabs plan tier and character credits actually purchased, so this must be reconciled to real invoices.
- Language model cost: $0.01 to $0.02 USD per call, estimate from the research brief, base case $0.015 USD per call.
- Speech to text: ApexVoice has transcription on. Code verification on 2026-11-28: the gather handler in app.py reads the SpeechResult parameter from the SignalWire webhook, so recognition is carrier gather speech, and the codebase makes no separate Transcription API call. What SignalWire bills for gather speech recognition is not established by the code, so the cost model carries an allowance, not a confirmed invoice line. If it were billed at the native transcription rate of $0.020 USD per 15 seconds for every minute, that alone is $0.080 USD per minute and the model breaks. See the warning after the table.
- Partial minutes: modelled as continuous minutes. If suppliers bill in increments, real cost will be higher.

Variable cost per call minute:

| Cost component | Assumption | USD per call minute, low | USD per call minute, base | USD per call minute, high | CAD per call minute, base at 1.36 |
|---|---|---|---|---|---|
| SignalWire PSTN inbound | Published $0.0066 USD per minute | 0.0066 | 0.0066 | 0.0066 | 0.0090 |
| ElevenLabs text to speech | 400 to 450 chars per call minute at $0.18 USD per 1,000 chars, base 425 chars | 0.0720 | 0.0765 | 0.0810 | 0.1040 |
| Language model inference | $0.01 to $0.02 USD per call spread over a 3 minute call, base $0.015 USD | 0.0033 | 0.0050 | 0.0067 | 0.0068 |
| Speech to text allowance | Allowance only, estimate, not a confirmed supplier rate | 0.0080 | 0.0100 | 0.0150 | 0.0136 |
| Redis, logging and storage variable share | Allowance, estimate | 0.0010 | 0.0010 | 0.0020 | 0.0014 |
| Total variable cost per call minute | Sum of above | 0.0909 | 0.0991 | 0.1113 | 0.1348 |

Base case used in all tier tables below: $0.135 CAD per call minute, rounded.

Key findings from the model:

- ElevenLabs is about 77 percent of base case variable cost. Any saving must come from shorter spoken responses, response caching for repeated answers such as hours and directions, a cheaper voice tier after a quality check, or negotiated character pricing. Cutting telephony cost saves almost nothing.
- Spoken length is a design decision with a direct margin effect. Prompts and templates should be written for short spoken answers, and the onboarding and template work should include a spoken length guideline.
- Warning on transcription: at the published SignalWire transcription rate of $0.020 USD per 15 seconds, transcription is $0.080 USD per minute, or $0.109 CAD per minute, which would raise total variable cost to about $0.230 CAD per minute. At that cost, Starter and Professional lose money at full utilisation at any plausible included minute count. Before billing goes live, confirm in the codebase and on a real SignalWire invoice exactly which service produces transcripts, what it charges, and whether it can be priced, capped, or replaced. Do not launch paid tiers until this line is verified, not allowed for.

## Fixed direct cost per tenant per month

Estimates, November 2026, converted at 1.36 CAD per USD where the supplier bills in USD. These are allocations at an early scale of roughly 10 to 30 paying tenants. At fewer tenants the hosting share per tenant is higher.

| Fixed item | Assumption | CAD per tenant per month |
|---|---|---|
| Local telephone number, DID | Published $0.50 USD per month per number | 0.68 per number |
| Vercel hosting share | Pro plan and bandwidth allocated across tenants, estimate | 3.00 |
| Upstash Redis share | Pay as you go allocation, estimate | 2.00 |
| Storage, backups and log retention | Estimate | 1.00 |
| Monitoring and transactional email share | Estimate | 0.32 |
| Total fixed direct cost, one number, Starter and Professional | Sum of above | 7.00 |
| Total fixed direct cost, Business | Above plus one extra DID and higher storage allocation, estimate | 10.00 |
| Total fixed direct cost, Enterprise | Priced per contract, minimum allocation used in this analysis | 25.00 |

Not included in fixed direct cost, and handled separately below: payment processing fees, sales tax collection and remittance, chargebacks, and human support time. Payment processing, for example Stripe at a published Canadian rate that must be re checked before launch, would take roughly 2.9 percent plus a fixed per transaction fee, which is about $1.72 CAD on a $49 CAD charge before the fixed fee. That further reduces net margin and is another reason annual discounts must be capped.

Support time allowance, for contribution analysis only:

- Internal support cost assumption: $40 CAD per hour, estimate, representing Harbour & Main owner and contractor time at a modest internal rate. Real cost is higher if support is hired.
- Starter: 0.25 hours per month, $10.00 CAD
- Professional: 0.50 hours per month, $20.00 CAD
- Business: 1.00 hour per month, $40.00 CAD
- Enterprise: priced into the contract, minimum 2 hours per month
- Gross margin in the tier tables below excludes support time, following normal practice. Contribution after support is shown as a separate line so the real economics are not hidden. A tier that only works if support is free does not work.

## Evaluation of the hypothesised tiers

Hypotheses to test, from Josh, not approved prices: Starter $49 CAD per month, Professional $99 CAD per month, Business $199 CAD per month, Enterprise custom.

First test: what happens if ApexVoice matches competitor style minute bundles at these CAD prices?

| Test bundle | Direct cost at 100 percent utilisation | Result |
|---|---|---|
| Starter $49 CAD with 250 minutes | 250 times $0.135 = $33.75, plus $7.00 fixed = $40.75. Gross profit $8.25, gross margin 16.8 percent. After $10.00 support allowance, contribution is negative $1.75 | Fails. Loses money after support at full utilisation |
| Professional $99 CAD with 1,000 minutes | 1,000 times $0.135 = $135.00, plus $7.00 fixed = $142.00. Gross loss $43.00 | Fails. Loses money on direct costs alone |
| Business $199 CAD with 2,000 minutes | 2,000 times $0.135 = $270.00, plus $10.00 fixed = $280.00. Gross loss $81.00 | Fails. Loses money on direct costs alone |

Conclusion: the prices are workable, the competitor minute bundles at those prices are not. The fix applied below is to reduce included minutes, not to raise the hypothesised prices. Trade off, stated plainly: ApexVoice will advertise fewer included minutes than Rosie AI or My AI Front Desk at a similar numeric price, because its price is in CAD and theirs is in USD. Sales copy must make the CAD pricing and the total cost comparison clear instead of competing on headline minutes.

### Recommended tier structure

| Feature | Starter | Professional | Business | Enterprise |
|---|---|---|---|---|
| Recommended price, CAD per month | 49 | 99 | 199 | Custom, minimum 499 |
| Included minutes per month | 120 | 350 | 800 | Custom, pooled, negotiated |
| Overage, CAD per minute | 0.40 | 0.35 | 0.30 | Contract rate, floor 0.25 |
| Telephone numbers included | 1 local DID | 1 local DID, toll free available as a paid add on at cost plus margin, price to be set after toll free rates are verified | 2 local DIDs | Custom |
| Locations | 1 | 1 | Up to 3 | Custom |
| Dashboard users | 1 | 3 | 10 | Custom, role based |
| Receptionist configurations | 1 | 1 | Up to 3 | Custom |
| Industry templates | General and one industry template | All industry templates | All industry templates plus custom template edits | Custom templates |
| Appointment booking | One calendar connection | Multiple calendars, booking rules | Multiple calendars, multiple locations, escalation rules | Custom integrations |
| Message delivery | Email | Email and SMS, subject to CASL and consent rules in the privacy document | Email, SMS, and webhook or CRM delivery where built | Custom |
| Call transfer and escalation rules | Basic transfer number | Transfer plus fallback message rules | Multi step escalation | Custom |
| Business knowledge entries | Up to 25, limit to be confirmed against storage cost | Up to 100 | Up to 500 | Custom |
| Transcript and call history retention | 90 days, recommended default | 12 months | 24 months, configurable within policy limits | Contract term |
| Support | Email, business hours | Email and scheduled calls | Priority email and scheduled calls | Named contact, contract response times |
| Reporting | Basic usage page | Usage and cost estimate exports | Multi location usage reporting | Custom reporting |

Feature limits are recommendations to be confirmed against what the product actually enforces in code. Do not advertise a limit or a feature that the dashboard does not yet enforce or deliver.

### Margin math by tier

Formula used in every row: minutes used = included minutes times utilisation. Variable cost = minutes used times $0.135 CAD. Total direct cost = variable cost plus fixed direct cost. Gross profit = price minus total direct cost. Gross margin = gross profit divided by price. Contribution after support = gross profit minus the support allowance for that tier.

Starter, $49 CAD, 120 included minutes, $7.00 fixed, $10.00 support allowance:

| Utilisation | Minutes used | Variable cost CAD | Total direct cost CAD | Gross profit CAD | Gross margin | Contribution after support CAD |
|---|---|---|---|---|---|---|
| 40 percent | 48 | 6.48 | 13.48 | 35.52 | 72.5 percent | 25.52 |
| 65 percent | 78 | 10.53 | 17.53 | 31.47 | 64.2 percent | 21.47 |
| 100 percent | 120 | 16.20 | 23.20 | 25.80 | 52.7 percent | 15.80 |

Professional, $99 CAD, 350 included minutes, $7.00 fixed, $20.00 support allowance:

| Utilisation | Minutes used | Variable cost CAD | Total direct cost CAD | Gross profit CAD | Gross margin | Contribution after support CAD |
|---|---|---|---|---|---|---|
| 40 percent | 140 | 18.90 | 25.90 | 73.10 | 73.8 percent | 53.10 |
| 65 percent | 227.5 | 30.71 | 37.71 | 61.29 | 61.9 percent | 41.29 |
| 100 percent | 350 | 47.25 | 54.25 | 44.75 | 45.2 percent | 24.75 |

Business, $199 CAD, 800 included minutes, $10.00 fixed, $40.00 support allowance:

| Utilisation | Minutes used | Variable cost CAD | Total direct cost CAD | Gross profit CAD | Gross margin | Contribution after support CAD |
|---|---|---|---|---|---|---|
| 40 percent | 320 | 43.20 | 53.20 | 145.80 | 73.3 percent | 105.80 |
| 65 percent | 520 | 70.20 | 80.20 | 118.80 | 59.7 percent | 78.80 |
| 100 percent | 800 | 108.00 | 118.00 | 81.00 | 40.7 percent | 41.00 |

Enterprise, illustrative only, $499 CAD minimum, 1,800 pooled minutes assumed for illustration, $25.00 fixed, $80.00 support allowance:

| Utilisation | Minutes used | Variable cost CAD | Total direct cost CAD | Gross profit CAD | Gross margin | Contribution after support CAD |
|---|---|---|---|---|---|---|
| 40 percent | 720 | 97.20 | 122.20 | 376.80 | 75.5 percent | 296.80 |
| 65 percent | 1,170 | 157.95 | 182.95 | 316.05 | 63.3 percent | 236.05 |
| 100 percent | 1,800 | 243.00 | 268.00 | 231.00 | 46.3 percent | 151.00 |

Flags and interpretation:

- No recommended tier loses money on direct costs at 100 percent utilisation. Gross margins at full utilisation are 52.7 percent, 45.2 percent, and 40.7 percent.
- Target gross margin: set a floor of 40 percent at 100 percent utilisation for any published tier. Business sits just above that floor, so any increase to Business included minutes, any deeper annual discount, or any move to a more expensive voice must be re modelled first.
- Realised margin will usually look better than the 100 percent column because most small businesses will not use every included minute every month. Do not price on that hope. Price on the 100 percent column and treat lower utilisation as upside.
- Overage margin: at $0.135 CAD variable cost, overage at $0.40, $0.35, and $0.30 CAD per minute gives a per minute gross margin of about 66 percent, 61 percent, and 55 percent respectively, before fixed costs. Overage is profitable and should never be discounted without re modelling.
- Minutes do not roll over in this recommendation. Rollover effectively raises utilisation in later months and breaks the margin model unless it is capped, for example rollover capped at 25 percent of the monthly bundle for one month only. If rollover becomes a sales requirement, re model it as a higher effective bundle.
- Average call length matters. If real average call length is much longer than 3 minutes, the per call language model spread improves slightly, but total minutes per customer rise, so customers reach overage sooner. Monitor both minutes and call count.

## Annual discount guardrails

- Maximum annual discount: 10 percent off the monthly price, paid annually in advance. That gives effective monthly prices of about $44.10 CAD for Starter, $89.10 CAD for Professional, and $179.10 CAD for Business.
- Do not offer two months free, which is about 16.7 percent, and do not offer the 20 percent annual discount style used by some United States competitors. At Business tier, a 20 percent discount drops the price to $159.20 CAD and, at 100 percent utilisation, drops gross margin to about 25.9 percent, below the floor.
- Annual prepayment improves cash flow and reduces payment fees and failed payments, which is the real reason to offer it, not acquisition pressure.
- Annual plans need a written policy on downgrades, cancellation, and refunds before they are sold, and that policy needs legal review. See the legal drafts folder.
- No stacking: annual discount cannot combine with setup fee waivers beyond the stated setup policy, promotional credits, or partner commissions without a fresh margin check.
- Partner or agency pricing, if offered later, must come out of a separate margin model that includes the partner share. Do not apply a partner split to these retail margins.

## Setup fee discussion

- Recommend a one time setup fee of $149 CAD for Professional and Business, and $99 CAD for Starter, covering number provisioning, configuration review, test calls, greeting and knowledge setup, and staff handover.
- Rationale: onboarding time is real, estimated at 1 to 2 hours per business for review and testing even with a self serve flow, and a setup fee keeps that time from being absorbed by the first month margin.
- Waiver guardrail: the setup fee may be waived on an annual plan only, one waiver per business, and the waiver should be recorded as a discount in the billing system so true acquisition cost is visible.
- Do not advertise free setup as a permanent policy. Time limited promotions are a Josh decision, with a margin note attached.
- Enterprise setup is quoted per contract based on integrations and locations.

## Add ons to consider later, not in the launch price list

Each add on needs its own cost check before it is priced. Candidates: extra local number at a monthly price covering the $0.68 CAD DID cost plus account overhead, extra location, additional retention period, additional dashboard users beyond the tier limit, and custom voice work. Do not build or price add ons until core metering works.

## What must be metered before billing can go live

Billing must not be activated until every item below is built, tested in staging, and reconciled. This list is an interface contract for the backend work, not backend work performed in this document set.

- Per tenant, per billing period minute counter, keyed by tenant ID, summing billable call duration from SignalWire call records, with the billing increment, rounding rule, and treatment of calls under a minimum duration defined in writing and implemented in one place.
- Per call record linkage: every call, transcript, message, and appointment must carry a tenant ID, a call identifier, start and end timestamps, duration, and direction, so a customer invoice can be explained line by line.
- ElevenLabs character usage per tenant per period, captured from the application at synthesis time, not estimated after the fact.
- Language model usage per tenant per period: calls, requests, and token counts where the provider exposes them, with the per call cost estimate replaced by measured cost.
- Speech to text usage per tenant per period, in seconds, with the actual provider and rate identified. This resolves the transcription warning in the cost model.
- DID inventory per tenant: numbers assigned, dates assigned and released, and type, local or toll free.
- Overage engine: automatic calculation of minutes above the bundle, the tier overage rate applied, threshold alerts to the customer at 80 percent and 100 percent of the bundle, and an optional customer set hard cap or soft cap.
- Plan and limit enforcement: included minutes, numbers, locations, users, knowledge entries, and retention period enforced by the system, not by policy text alone.
- Invoice reconciliation report: monthly comparison of metered totals against SignalWire, ElevenLabs, and other supplier invoices, with a variance threshold that blocks invoice sending if exceeded. Recommended threshold: investigate any variance above 5 percent.
- Tax handling: correct Canadian sales tax treatment by customer province, including HST in Ontario and the separate Quebec rules if Quebec customers are served, set up with professional accounting and legal advice. Do not hard code tax rates from this document.
- Failed payment, dunning, suspension, and data retention on non payment flows, defined in the terms of service and implemented before the first charge.
- Audit log of plan changes, credit issuance, and manual adjustments, with the actor recorded.
- A staging test that runs a known set of test calls, produces an invoice, and matches hand calculated totals, repeated after any change to metering code.

## Risks and open questions

- Transcription cost is unverified and could change the entire model. Highest priority verification.
- ElevenLabs plan structure may make the effective per character cost higher or lower than the $0.18 USD per 1,000 characters estimate. Reconcile to the actual plan and invoice.
- Hosting and Redis allocations are estimates at low tenant counts. The first ten customers will carry higher per tenant fixed costs than this model shows.
- Support time is the most likely cost to be underestimated, especially for nontechnical owners during the first month. Track actual support minutes per tenant from the first pilot.
- Pilot recommendation: run a small paid or time limited pilot with a handful of businesses, measure real minutes per business, average call length, characters per minute, and support time, then re run this model with measured figures before publishing prices.
- These recommendations do not constitute financial advice. Have an accountant review tax, revenue recognition for annual prepayments, and payment processing setup before launch.

## Final recommendation summary

- Adopt, subject to Josh approval: Starter $49 CAD with 120 minutes and $0.40 CAD overage, Professional $99 CAD with 350 minutes and $0.35 CAD overage, Business $199 CAD with 800 minutes and $0.30 CAD overage, Enterprise custom from $499 CAD.
- Cap annual discount at 10 percent. Charge a setup fee, waivable only on annual plans.
- Hold billing activation until metering, transcription cost verification, and tax setup are complete.
