// MIG-008 browser check: the production React UI against a .NET Server (shared-token, loopback). Settings → Runtime & Scheduling: enables the
// scheduled refresh, switches to a cron expression, reads the live preview (description, next runs), shows the validation message of an invalid
// expression, applies the settings and reads the saved status; then runs the global Refresh and lists every /api response >= 400.
//   node refresh_schedule_check.js http://127.0.0.1:PORT TOKEN DIR       (DIR/shots receives screenshots)
const { chromium } = require('playwright');
const [base, token, dir] = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const failed = [];
  page.on('response', r => { const p = new URL(r.url()).pathname; if (p.startsWith('/api/') && r.status() >= 400) failed.push(`${r.status()} ${p}`); });
  try {
    await page.goto(base + '/'); await page.fill('input[name=token]', token); await page.click('button[type=submit]');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Open settings', exact: true }).click();
    await page.getByRole('tab', { name: 'Runtime & Scheduling', exact: true }).click();
    const card = page.getByRole('region', { name: 'Scheduled refresh' });
    await card.getByRole('switch').or(card.getByRole('checkbox')).first().click();
    await card.getByRole('radio', { name: /Advanced/ }).or(card.getByRole('button', { name: /Advanced/ })).first().click();
    const cron = card.getByLabel('Cron expression');
    await cron.fill('*/2 * * * *');
    await page.waitForTimeout(1200);
    console.log('invalid:', (await card.innerText()).match(/Refreshes must be[^\n]*/)?.[0] ?? '(no message)');
    await cron.fill('30 6 * * 1-5');
    await card.locator('.schedule-summary').waitFor({ timeout: 10000 });
    console.log('preview:', (await card.locator('.schedule-summary').innerText()).replace(/\s+/g, ' '));
    const save = page.waitForResponse(r => new URL(r.url()).pathname === '/api/configuration' && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Apply settings' }).click();
    console.log('save:', (await save).status());
    // Applying settings returns to the Dashboard (v1); reopen the section to read the saved status.
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Open settings', exact: true }).click();
    await page.getByRole('tab', { name: 'Runtime & Scheduling', exact: true }).click();
    await page.waitForLoadState('networkidle');
    console.log('status:', (await page.getByLabel('Scheduled refresh status').innerText()).replace(/\s+/g, ' '));
    await page.screenshot({ path: `${dir}/shots/schedule.png` });
    await page.getByRole('button', { name: 'Back to SAP Lens' }).click();
    const refresh = page.waitForResponse(r => new URL(r.url()).pathname === '/api/refresh');
    await page.getByRole('button', { name: 'Refresh role data from CSV' }).click();
    const response = await refresh;
    const body = await response.json();
    console.log('refresh:', response.status(), body.refresh.status, body.refresh.sources.map(s => `${s.source}=${s.status}${s.reason ? '/' + s.reason : ''}`).join(' '));
  } catch (e) { console.log('FAILED', e.message.split('\n')[0]); await page.screenshot({ path: `${dir}/shots/failure.png` }); }
  console.log('API failures:', [...new Set(failed)].join(', ') || 'none');
  await browser.close();
})();
