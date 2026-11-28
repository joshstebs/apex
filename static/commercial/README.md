# ApexVoice Commercial Frontend

Static pages for ApexVoice commercial readiness. Plain HTML, CSS and JavaScript only. No build step, no frameworks and no external assets. All styles and scripts are inline in each page.

Location in this delivery: `static/commercial/`

## Pages

### onboarding.html
Seven step business onboarding wizard covering business details, hours and holidays, receptionist name and greeting, services and FAQs, booking preferences, transfer and after-hours rules plus message delivery, and voice, personality, instructions and review.

* Industry templates are loaded from `templates.json` in the same folder. Picking a template prefills editable defaults.
* Drafts are saved to browser local storage under the key `apex_business_config` on every change and reloaded on return.
* The final step provides a working Download configuration (JSON) button and a Copy configuration button.
* Important limitation, stated on the page: saving here stores the draft in this browser only. Connecting it to the live phone service is a backend step. The intended endpoint is `POST /api/tenants/{id}/config`, which is not yet live. This page does not assign a phone number, place calls or start billing.

### dashboard.html
Customer dashboard that reads real data from the ApexVoice API on the same origin.

* Service status uses the public `GET /api/health` endpoint and works without a token.
* The admin token is entered in a password field, kept in tab memory only, never saved to local storage and never placed in the URL. Disconnect clears it.
* Connect loads `GET /api/dashboard` and `GET /api/receptionist/messages` with an `Authorization: Bearer` header.
* Recent calls, messages, customers and usage come only from API responses. Empty states are shown when there is no data.
* Missed calls are derived only from recent calls whose status or outcome indicates missed or no-answer. If no calls exist, the page says missed call tracking appears once calls are recorded.
* Appointments: no appointments endpoint exists yet. The page shows an honest empty state naming the backend dependency, `GET /api/appointments`, and renders appointment or booking data if a future payload includes it.
* Receptionist configuration and business knowledge are summarised from the local `apex_business_config` created in onboarding, with edit links back to onboarding.
* Usage shows budget `spend_usd` and `cap_usd` from the API, labelled as estimated application spend, not a carrier invoice.

### demo.html
Interactive sales demonstration, repeatedly labelled SIMULATED.

* Banner states: Interactive simulation. No real phone call is placed and no data leaves your browser.
* Pick an industry template from `templates.json`, edit the sample business name and greeting, and the simulated receptionist uses that greeting.
* Rule based chat in the browser with typed input and scenario chips for booking, hours, price, message and emergency.
* Booking flow collects name, service, preferred time and phone, then creates a request card labelled as request only, with a working Download .ics button that generates a real calendar file in the browser.
* Message flow collects name, callback number, reason and preferred contact time, matching the live message fields.
* Price and hours answers come only from the selected template sample data and say so.
* Emergency wording such as gas smell or chest pain returns call 911 guidance and does not book.
* Listen buttons use `window.speechSynthesis` only when available, labelled as a browser voice preview. The live service uses a different phone voice. Buttons are hidden when speech synthesis is unavailable.
* Dashboard preview shows only cards created in this demo session and links to the real dashboard.
* A table explains what is simulated versus live. No testimonials, statistics or counters are included.

### templates.json
Configurable receptionist templates for plumbing and HVAC, automotive repair, dental and medical, real estate, salons and barbershops, restaurants, professional services and general small business. Each includes greetings, services, FAQs, escalation keywords, after-hours greeting and instructions. Dental, medical and professional templates include privacy and safety restrictions and prohibit medical or legal advice.

## How to open locally

From the repository root, run:

```bash
python3 -m http.server 8000
```

Then open:

* http://localhost:8000/static/commercial/onboarding.html
* http://localhost:8000/static/commercial/dashboard.html
* http://localhost:8000/static/commercial/demo.html

Onboarding and the demo work from the static server alone, apart from loading `templates.json`. The dashboard health, dashboard and messages sections need the FastAPI service running on the same origin, so for full dashboard testing serve these pages through the ApexVoice application or a proxy to it, rather than a separate static port.

## Backend dependencies

* `GET /api/health` - public, sanitized. Used for service and connection status.
* `GET /api/dashboard` - requires `Authorization: Bearer <APEX_ADMIN_TOKEN>`. Expected fields include budget, telephony provider, environment, live call, recent calls, messages, notices and errors.
* `GET /api/receptionist/messages` - requires the same bearer token. Message fields include caller name, callback number, reason and preferred contact time.
* `POST /api/tenants/{id}/config` - not yet live. Needed to persist onboarding configuration server side, assign tenant isolation and provision a business phone number.
* `GET /api/appointments` - not yet live. Needed for a real appointments section in the dashboard.
* Multi-tenant authentication, role based access, per-business usage tracking, data retention and deletion, and billing are backend work. These pages do not implement or simulate them.

## Honesty rules followed

* No fabricated calls, statistics, testimonials or activity anywhere.
* Demo content is labelled simulated throughout, and demo sample data is identified as template sample data.
* Every button and form control on these pages is wired to a working action in the browser or to a real API call described above.
