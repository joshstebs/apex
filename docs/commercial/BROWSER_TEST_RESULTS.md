# Browser test results for the Phase 2 commercial pages

Run 2026-11-28 in a real Chromium browser (Playwright, headless Chromium) against the pages from PR #7 served over local HTTP. Screenshots from this run are in this folder. The runnable script is scripts/browser_commercial_check.mjs in this branch.

## Result: 34 checks, 34 passed, 0 failed

Coverage by page and viewport:

* Onboarding, dashboard, and demo each loaded at mobile 390 by 844, tablet 834 by 1112, and desktop 1440 by 900, with no horizontal overflow and no page errors at any size.
* The demo shows its SIMULATED banner at every size.

Interaction checks, all passing:

* Onboarding validation blocks advancing past step 1 with required fields empty.
* Template selection prefills the greeting (101 characters loaded for the selected template) and business fields accept input.
* The wizard walks all steps to the review step.
* Download configuration produces a real download named apexvoice-business-config.json whose parsed JSON carries the entered business name plus contact and voice sections, matching the BusinessConfig schema.
* Dashboard with an unreachable API and a test token shows an honest error state instead of fabricated data.
* Browser voice preview: speechSynthesis is available in Chromium and the demo renders its Listen button, labelled as a browser voice preview.
* Demo booking flow (chip plus typed answers) produces the booking request card marked request only.
* The booking card's .ics download is a real calendar file containing BEGIN:VCALENDAR and BEGIN:VEVENT.
* Demo message flow produces the message taken card with the live message fields.
* Demo emergency flow directs the caller to 911.

## Issues found and fixed

* One failure during the first run was in the test script, not the pages: the script used lowercase element IDs while the demo page uses camelCase (userInput, sendBtn). The script was corrected and the full suite rerun clean. No page changes were needed.
* No page defects were found in this pass. Known limitation carried from Phase 2: the dashboard's live-data rendering paths (populated calls, messages, and usage) can only be exercised against a running backend, which belongs to the backend agent's staging work. The error and empty states, which are what a visitor hits first, are verified here.

## Screenshots in this folder

* onboarding-mobile.png, onboarding-tablet.png, onboarding-desktop.png, onboarding-step1-filled.png, onboarding-review.png
* dashboard-mobile.png, dashboard-tablet.png, dashboard-desktop.png, dashboard-error-state.png
* demo-mobile.png, demo-tablet.png, demo-desktop.png, demo-mobile-flow.png, demo-booking.png, demo-conversation.png
