# ApexVoice site integration instructions

For the future harbourandmain.com/ai-receptionist update. This pack was prepared as drop-in assets only. Nothing in the live Harbour & Main website has been modified, and this integration must be coordinated before anything is published.

## Do not publish warning

- The file `index.html` in this pack starts with the comment: DRAFT, PRICING NOT YET APPROVED FOR PUBLICATION, DO NOT PUBLISH AS IS.
- The pricing table shows recommended introductory pricing that is still under review (Starter $49 CAD, Professional $99 CAD, Business $199 CAD, Enterprise custom from $499 CAD). Do not publish the page, or reuse the pricing table anywhere public, until Harbour & Main approves final prices in writing.
- When final prices are approved, update the pricing table, the founding customer wording and the footer line together, then remove the draft comment from the top of `index.html` and `demo-embed.html`. Do not remove the draft comment before prices are approved.
- The pricing analysis behind these numbers also warns: do not advertise a feature limit or capability that the product does not yet enforce or deliver. Before publishing, check every row of the pricing and comparison tables against the live product with the backend agent, and cut or reword any row that is not real yet (for example dashboard user counts, locations, retention periods and delivery channels).

## What is in this pack

All files live in this folder, `site/harbourandmain-ai-receptionist/`:

- `index.html` - the product page: hero, how it works, features, industries, pricing, plan fit comparison, AI and privacy disclosures, FAQ, and the request-a-demo form.
- `demo-embed.html` - wrapper page that embeds the Phase 2 demo in an iframe and explains what to try. It contains no copy of the demo itself.
- `COPY.md` - the same product copy in markdown, plus announcement post drafts, for reuse in other channels.
- `INTEGRATION.md` - this file.

## Where the files go

- Publish `index.html` as the page served at `https://harbourandmain.com/ai-receptionist` (or the equivalent route in whatever stack the site runs on at integration time). Confirm the exact route and file placement with whoever owns the live site at that moment; do not assume the current stack.
- Publish `demo-embed.html` alongside it at a sibling path, for example `https://harbourandmain.com/ai-receptionist/demo`, because `index.html` links to it with a relative link (`demo-embed.html`) and it links back to `index.html` sections. If the two pages end up at different paths, update the relative links in both files in the same change.
- `COPY.md` and `INTEGRATION.md` are working documents. They do not need to be published. If the site build publishes every file in a folder, keep these two out of the published output.
- Both HTML pages are single files with inline CSS and JavaScript, no build step, no frameworks and no external assets. They can be dropped into a static host or pasted into a page template as-is, as long as the relative links between them keep working.

## Wiring the demo

- The demo itself is the Phase 2 page `demo.html` (with its `templates.json`) from `static/commercial/` in the ApexVoice repository (joshstebs/apex, PR #7 branch and its successors). It is not in this pack on purpose: there must be one source of truth for the demo, and this wrapper must never contain a pasted copy.
- Decide where the demo will be hosted (on the Harbour & Main site next to these pages, or on the ApexVoice app origin) and publish `demo.html` and `templates.json` together in the same folder there. The demo loads `templates.json` from its own folder and will not work without it.
- In `demo-embed.html`, set the demo address in exactly one place: the `APEXVOICE_DEMO_URL` value in the script at the bottom of the page. A large comment above the iframe in the same file explains this. The script sets both the iframe source and the fallback link from that one value.
- If the demo is hosted on a different origin than the marketing site, confirm that origin allows framing (no `X-Frame-Options: DENY` or restrictive `frame-ancestors` header), or the iframe will be blank and only the fallback link will work.
- The demo is labelled SIMULATED inside the demo itself, and the wrapper repeats that labelling above the iframe. Keep both.

## Request-a-demo form behaviour

- The form in `index.html` has no backend. On submit it validates the fields in the browser, then shows the visitor a composed summary with two working options: an "Open in my email app" mailto link addressed to `josh@harbourandmain.com` with the details prefilled, and a Copy button.
- The page copy states plainly that nothing is stored by the page and that pressing send in the visitor's email app completes the request. Keep that wording if the form is edited. Do not describe the form as submitting, sending or recording anything on the server.
- If a real form backend or CRM intake is added later, that is a separate change: update the page copy, the privacy wording and this file at the same time, and confirm where submissions are stored and who receives them.

## Coordination checklist before publishing

- Backend agent (ApexVoice): confirm the demo hosting location and framing headers, confirm the live service facts on the page still match the product (message fields, appointment request behaviour, recording off by default, English only), and confirm which pricing table rows the product actually enforces.
- Harbour & Main site owner: place the files, set `APEXVOICE_DEMO_URL`, check the relative links, and run the checks below on the staged page, not just the local files.
- Pricing approval: written sign-off on final prices before the draft comments come off and the page goes live.
- Legal and privacy: the AI and privacy section and the FAQ privacy answer must stay consistent with the current ApexVoice privacy documents (see `docs/commercial/PRIVACY_AND_TRUST.md` and `docs/legal-drafts/` in the ApexVoice repo). If those documents change, update this page in the same pass.

## Disclosure requirements that must stay on the page

Do not remove or soften any of these in edits:

- Callers are told at the start of a call that the receptionist is an AI. This appears in the hero area, the features list and the AI and privacy section.
- Transcription disclosure: callers are told their words may be transcribed so the business can follow up.
- Audio recording is off by default, and the page must not claim calls are recorded unless that default changes and the wording is updated everywhere, including the demo.
- Appointment wording: ApexVoice takes appointment requests that the business confirms. Never change this to say it books or confirms appointments on its own.
- Emergency wording: ApexVoice is not an emergency service and directs emergencies to 911.
- No advice wording: the receptionist does not give medical, legal or financial advice, and never asks for payment card numbers, banking details, passwords or health card numbers.
- No fabricated proof: no testimonials, customer counts, answer rates, savings percentages or performance statistics may be added until real, verified numbers exist and are approved for publication.

## Accessibility and mobile checks to run on the staged page

- Keyboard only pass: tab through the top navigation, FAQ expanders, the demo link and every form field and button. Focus must be visible on every stop (the pages use a yellow focus outline) and the order must be logical.
- Form errors: submit the request-a-demo form empty and with a bad email. Each error appears next to its field in text, not colour alone, and the result panel stays hidden until the form is valid.
- Screen reader basics: every form field has a label, the pricing and comparison tables use header cells, the iframe in `demo-embed.html` has a title, and the demo fallback link makes sense out of context.
- Mobile layout at a narrow width (around 360 CSS pixels): no horizontal scrolling except inside the pricing table wrapper, tap targets are full width buttons or padded links, and the hero heading wraps cleanly.
- Tablet and desktop widths: the two and three column grids in the features and industries sections line up, and the iframe demo is tall enough to use without nested scrolling frustration (900px desktop, 1100px on small screens, adjustable in the page CSS if the staged demo needs it).
- Reduced motion and zoom: check the page at 200 percent zoom. Nothing in these pages animates, so the main risk is table overflow, which the wrapper handles.
- Link check: every in-page anchor (#how, #features, #industries, #pricing, #privacy, #faq, #request-demo) lands on its section, the link to `demo-embed.html` works, and the mailto link in the footer and the form result opens the visitor's email app.

## After publishing

- Test the live demo embed end to end once, including the fallback link.
- Submit one real request-a-demo through the published page and confirm the email arrives at josh@harbourandmain.com with the full summary.
- Record the publish date, the approved prices used, and the final demo URL in this file, so the next person does not have to reconstruct them.
