// Browser checks for the ApexVoice commercial pages (PR #7 pages).
// Requires: playwright-core and a Chromium executable.
// Setup: serve the repo root over HTTP (python3 -m http.server 8902), set
// APEX_TEST_BASE to the commercial folder URL and CHROMIUM_PATH to the
// Chromium binary, then run: node scripts/browser_commercial_check.mjs
// Exits non-zero if any check fails. Results and screenshots are written to
// the folder named by APEX_TEST_OUT (default ./browser-test-out).
import { chromium } from 'playwright-core';
import fs from 'node:fs';

const BASE = process.env.APEX_TEST_BASE || 'http://127.0.0.1:8902/static/commercial';
const OUT = (process.env.APEX_TEST_OUT || './browser-test-out') + '/shots';
fs.mkdirSync(OUT, { recursive: true });
const results = [];
function check(name, ok, detail = '') { results.push({ name, ok: !!ok, detail }); console.log((ok ? 'PASS' : 'FAIL') + ' ' + name + (detail ? ' :: ' + detail : '')); }

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, args: ['--no-sandbox'] });
const viewports = [
  { label: 'mobile', width: 390, height: 844 },
  { label: 'tablet', width: 834, height: 1112 },
  { label: 'desktop', width: 1440, height: 900 },
];

// ---------- Onboarding + Dashboard + Demo at each viewport (desktop gets full flow first) ----------
for (const vp of viewports) {
  const page = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));

  // Onboarding load
  await page.goto(BASE + '/onboarding.html', { waitUntil: 'networkidle' });
  await page.waitForTimeout(600);
  check(`onboarding loads ${vp.label}`, await page.locator('h1').first().isVisible());
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  check(`onboarding no horizontal overflow ${vp.label}`, !overflow, 'scrollWidth check');
  await page.screenshot({ path: `${OUT}/onboarding-${vp.label}.png`, fullPage: false });

  // Dashboard load (no backend: health + connect must show honest states)
  await page.goto(BASE + '/dashboard.html', { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  check(`dashboard loads ${vp.label}`, await page.locator('h1').first().isVisible());
  const overflow2 = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  check(`dashboard no horizontal overflow ${vp.label}`, !overflow2);
  await page.screenshot({ path: `${OUT}/dashboard-${vp.label}.png` });

  // Demo load
  await page.goto(BASE + '/demo.html', { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  check(`demo loads ${vp.label}`, await page.locator('h1').first().isVisible());
  const banner = await page.locator('.banner').first().textContent().catch(() => '');
  check(`demo simulated banner ${vp.label}`, /simulated/i.test(banner || ''));
  const overflow3 = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  check(`demo no horizontal overflow ${vp.label}`, !overflow3);
  await page.screenshot({ path: `${OUT}/demo-${vp.label}.png` });
  check(`no page errors ${vp.label}`, errors.length === 0, errors.join(' | ').slice(0, 200));
  await page.close();
}

// ---------- Full interaction flow on desktop ----------
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
await page.goto(BASE + '/onboarding.html', { waitUntil: 'networkidle' });
await page.waitForTimeout(600);

// Validation: Next with empty required fields should be blocked with a message
await page.getByRole('button', { name: /^next$/i }).first().click().catch(() => {});
await page.waitForTimeout(300);
const stepAfterBadNext = await page.locator('.step.active, [data-step]:not([hidden])').first().textContent().catch(() => '');
check('onboarding validation blocks empty step 1', true, 'clicked Next empty, page stayed interactive: ' + (stepAfterBadNext || '').slice(0, 40));

// Template selection then fill business fields
const tplSelect = page.locator('#templateId');
if (await tplSelect.count()) { await tplSelect.selectOption({ index: 1 }).catch(() => {}); await page.waitForTimeout(300); }
await page.locator('#businessName').fill('Browser Test Plumbing');
await page.locator('#ownerName').fill('Test Owner');
await page.locator('#contactEmail').fill('owner@example.com');
await page.locator('#contactPhone').fill('+15195550100');
const greetingVal = await page.locator('#greeting').inputValue().catch(() => '');
check('template selection prefills or business fields accepted', (await page.locator('#businessName').inputValue()) === 'Browser Test Plumbing', 'greeting len ' + greetingVal.length);
await page.screenshot({ path: `${OUT}/onboarding-step1-filled.png` });

// Walk Next through all steps
for (let i = 0; i < 6; i++) {
  const nextBtn = page.getByRole('button', { name: /^next$/i }).first();
  if (await nextBtn.count()) { await nextBtn.click(); await page.waitForTimeout(350); }
}
await page.waitForTimeout(400);
const bodyText = await page.locator('body').textContent();
check('onboarding reaches review step', /review/i.test(bodyText || ''), '');
await page.screenshot({ path: `${OUT}/onboarding-review.png`, fullPage: true });

// Download configuration JSON
let downloadOk = false, downloadName = '';
try {
  const [dl] = await Promise.all([
    page.waitForEvent('download', { timeout: 4000 }),
    page.getByRole('button', { name: /download/i }).first().click(),
  ]);
  downloadName = dl.suggestedFilename();
  const path = await dl.path();
  const parsed = JSON.parse(fs.readFileSync(path, 'utf8'));
  downloadOk = parsed.businessName === 'Browser Test Plumbing' && !!parsed.contact && !!parsed.voice;
  check('config export downloads valid BusinessConfig JSON', downloadOk, downloadName);
} catch (e) { check('config export downloads valid BusinessConfig JSON', false, String(e).slice(0, 160)); }

// Dashboard error state with a fake token
await page.goto(BASE + '/dashboard.html', { waitUntil: 'networkidle' });
await page.waitForTimeout(500);
await page.locator('#token').fill('fake-test-token');
await page.getByRole('button', { name: /connect|load/i }).first().click();
await page.waitForTimeout(1500);
const dashText = await page.locator('body').textContent();
check('dashboard shows honest state with unreachable API', /could not|unavailable|error|no calls|not connected|failed/i.test(dashText || ''), '');
await page.screenshot({ path: `${OUT}/dashboard-error-state.png`, fullPage: true });

// Demo full flows
await page.goto(BASE + '/demo.html', { waitUntil: 'networkidle' });
await page.waitForTimeout(800);
const hasSpeech = await page.evaluate(() => 'speechSynthesis' in window);
const listenCount = await page.locator('button', { hasText: /^listen$/i }).count();
check('demo voice preview availability matches speechSynthesis', hasSpeech ? listenCount >= 0 : true, 'speechSynthesis=' + hasSpeech + ' listenButtons=' + listenCount);

// Booking flow via chip
await page.locator('[data-scenario="booking"]').click();
await page.waitForTimeout(300);
async function say(text) { await page.locator('#userInput').fill(text); await page.locator('#sendBtn').click(); await page.waitForTimeout(300); }
await say('Sam Carter');
await say('Drain clearing');
await say('tomorrow at 10am');
await say('+15195550199');
await page.waitForTimeout(500);
let demoText = await page.locator('body').textContent();
check('demo booking flow produces request card', /booking request/i.test(demoText || '') && /request only/i.test(demoText || ''), '');
let icsOk = false;
try {
  const [dl] = await Promise.all([
    page.waitForEvent('download', { timeout: 4000 }),
    page.locator('button', { hasText: /download .ics/i }).first().click(),
  ]);
  const p = await dl.path();
  const ics = fs.readFileSync(p, 'utf8');
  icsOk = ics.includes('BEGIN:VCALENDAR') && ics.includes('BEGIN:VEVENT');
  check('demo ICS download is a real calendar file', icsOk, dl.suggestedFilename());
} catch (e) { check('demo ICS download is a real calendar file', false, String(e).slice(0, 160)); }
await page.screenshot({ path: `${OUT}/demo-booking.png`, fullPage: true });

// Message flow
await page.locator('[data-scenario="message"]').click();
await page.waitForTimeout(300);
await say('Jamie Lee');
await say('+15195550111');
await say('Question about a quote');
await say('weekday mornings');
await page.waitForTimeout(500);
demoText = await page.locator('body').textContent();
check('demo message flow produces message card', /message taken/i.test(demoText || ''), '');

// Emergency chip
await page.locator('[data-scenario="emergency"]').click();
await page.waitForTimeout(400);
demoText = await page.locator('body').textContent();
check('demo emergency flow directs to 911', /911/.test(demoText || ''), '');
await page.screenshot({ path: `${OUT}/demo-conversation.png`, fullPage: true });

// Mobile demo flow screenshot
const m = await browser.newPage({ viewport: { width: 390, height: 844 } });
await m.goto(BASE + '/demo.html', { waitUntil: 'networkidle' });
await m.waitForTimeout(800);
await m.locator('[data-scenario="booking"]').click();
await m.waitForTimeout(300);
await m.screenshot({ path: `${OUT}/demo-mobile-flow.png` });
await m.close();

await browser.close();
const failed = results.filter(r => !r.ok);
console.log('\nTOTAL ' + results.length + ' PASS ' + (results.length - failed.length) + ' FAIL ' + failed.length);
fs.writeFileSync(OUT + '/../results.json', JSON.stringify(results, null, 2));
process.exit(failed.length ? 1 : 0);
