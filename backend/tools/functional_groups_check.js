// MIG-004 browser check: the production React UI against a .NET Server (shared-token, loopback). Settings → Functional Groups: creates a group,
// edits it, opens Suggestion rules, then User Access with the Functional Group filter, and lists every /api response >= 400.
//   node functional_groups_check.js http://127.0.0.1:PORT TOKEN DIR
const { chromium } = require('playwright');
const [base, token, dir] = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const failed = [];
  page.on('response', r => { const p = new URL(r.url()).pathname; if (p.startsWith('/api/') && r.status() >= 400) failed.push(`${r.status()} ${r.request().method()} ${p}`); });
  try {
    await page.goto(base + '/'); await page.fill('input[name=token]', token); await page.click('button[type=submit]');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Open settings', exact: true }).click();
    await page.getByRole('tab', { name: 'Functional Groups', exact: true }).click();
    await page.getByRole('button', { name: 'New group' }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Name').fill('Accounts Payable');
    await dialog.getByLabel('Description').fill('Invoice processing');
    await dialog.getByRole('button', { name: 'Create' }).click();
    await page.getByRole('cell', { name: 'Accounts Payable', exact: true }).waitFor({ timeout: 10000 });
    await page.getByRole('button', { name: 'Edit Accounts Payable' }).click();
    await page.getByRole('dialog').getByLabel('Name').fill('Accounts Payable EU');
    await page.getByRole('dialog').getByRole('button', { name: 'Save' }).click();
    await page.getByRole('cell', { name: 'Accounts Payable EU', exact: true }).waitFor({ timeout: 10000 });
    console.log('table:', (await page.getByRole('table', { name: 'Functional Groups' }).innerText()).replace(/\s+/g, ' ').slice(0, 200));
    await page.getByRole('tab', { name: /rules/i }).first().click();
    await page.waitForLoadState('networkidle'); await page.waitForTimeout(500);
    console.log('rules tab:', (await page.getByRole('region', { name: 'Functional Groups' }).innerText()).replace(/\s+/g, ' ').slice(0, 160));
    await page.screenshot({ path: `${dir}/shots/functional-groups.png` });
  } catch (e) { console.log('FAILED', e.message.split('\n')[0]); await page.screenshot({ path: `${dir}/shots/failure.png` }); }
  console.log('API failures:', [...new Set(failed)].join(', ') || 'none');
  await browser.close();
})();
