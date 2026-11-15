// Browser check of the production React UI served by the .NET Server (Chromium, the WebView2 engine): sign-in page, sign-in, React shell,
// Role Lookup with imported data, and the list of API routes that answered errors (not-migrated routes answer 501). Development tool; needs Playwright.
//   node browser_check.js https://HOST:PORT TOKEN SCREENSHOT_DIR      (import data first through /api/v1/imports)
const { chromium } = require('playwright');
(async () => {
  const [base, token, shots] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const errors = [], failed = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('response', r => { if (r.url().includes('/api/') && r.status() >= 400) failed.push(`${r.status()} ${new URL(r.url()).pathname}`); });
  await page.goto(base + '/');
  console.log('landed on', new URL(page.url()).pathname);
  await page.fill('input[name=token]', token);
  await page.click('button[type=submit]');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1500);
  console.log('after sign-in', new URL(page.url()).pathname, '| title:', await page.title());
  console.log('nav buttons:', (await page.locator('nav button, nav a').allInnerTexts()).map(t => t.trim()).filter(Boolean).slice(0, 12).join(' | '));
  await page.screenshot({ path: shots + '/react-dashboard.png' });
  console.log('alerts:', (await page.locator('[role=alert]').allInnerTexts()).slice(0, 3));
  const back = page.getByRole('button', { name: 'Back to SAP Lens' });
  if (await back.count()) { await back.click(); await page.waitForTimeout(800); }
  await page.getByRole('link', { name: 'Role Lookup' }).or(page.getByRole('button', { name: 'Role Lookup', exact: true })).first().click();
  await page.waitForLoadState('networkidle'); await page.waitForTimeout(1500);

  await page.screenshot({ path: shots + '/react-roles.png' });
  console.log('role rows visible:', await page.getByText(/ZC:|ZO:/).count());
  console.log('API failures:', [...new Set(failed)].join(', '));
  console.log('console errors:', errors.slice(0, 5));
  await browser.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
