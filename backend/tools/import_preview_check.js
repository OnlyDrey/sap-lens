// MIG-009 browser check: the production React UI against a .NET Server (shared-token, loopback). For Role Catalogue and User Access it uploads a
// synthetic CSV, opens "Advanced import format and column mapping", detects columns, sets a manual mapping (re-inspection), previews the import and
// lists every /api response >= 400. Development tool; needs Playwright.
//   node import_preview_check.js http://127.0.0.1:PORT TOKEN DIR      (DIR holds roles.csv, users.csv and a shots/ folder;
//   copy tests/SapLens.Tests/Fixtures/imports/roles_default.txt and users_default.txt)
const { chromium } = require('playwright');
const [base, token, dir] = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const failed = [], previews = [];
  page.on('response', async r => { const p = new URL(r.url()).pathname;
    if (p.startsWith('/api/') && r.status() >= 400) failed.push(`${r.status()} ${r.request().method()} ${p}`);
    if (/\/api\/(user-)?import\/(headers|preview)$/.test(p)) previews.push(`${r.status()} ${p}`); });
  try {
    await page.goto(base + '/'); await page.fill('input[name=token]', token); await page.click('button[type=submit]');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Open settings', exact: true }).click();
    await page.getByRole('tab', { name: 'Data Sources', exact: true }).click();
    for (const [tab, file, detect, preview, label] of [['Role Catalogue', 'roles.csv', 'Detect columns', 'Preview import', 'Role Catalogue'], ['User Access', 'users.csv', 'Detect user columns', 'Preview user import', 'User Access']]) {
      await page.getByRole('tab', { name: new RegExp(tab) }).first().click();
      await page.getByLabel(`Upload ${label} CSV`).setInputFiles(dir + '/' + file);
      await page.getByText('Uploading, validating and importing CSV…').waitFor({ state: 'detached', timeout: 60000 }).catch(() => {});
      await page.waitForLoadState('networkidle');
      await page.getByText('Advanced import format and column mapping').click();
      const headersCall = page.waitForResponse(r => /import\/headers$/.test(r.url()), { timeout: 15000 });
      await page.getByRole('button', { name: detect, exact: true }).click();
      console.log(tab, 'headers:', (await headersCall).status());
      await page.waitForTimeout(800);
      console.log(tab, 'status:', (await page.locator('[role=status]').allInnerTexts()).filter(Boolean).slice(0,3).join(' / '));
      const mapping = page.locator('.import-mapping-grid .mapping-field');
      console.log(tab, 'mapping fields:', await mapping.count(), '| states:', (await mapping.locator('.ui-description, small').allInnerTexts()).slice(0, 3).join(' / ').replace(/\s+/g, ' '));
      const field = mapping.filter({ hasText: tab === 'Role Catalogue' ? 'SAP field: TEXT' : 'SAP field: EMAIL' }).first();
      const again = page.waitForResponse(r => /import\/(headers|preview)$/.test(r.url()), { timeout: 15000 });
      await field.getByRole('combobox').click(); await page.getByRole('option', { name: tab === 'Role Catalogue' ? 'TEXT' : 'EMAIL', exact: true }).click();
      console.log(tab, 're-inspection after mapping:', (await again).status()); await page.waitForLoadState('networkidle'); await page.waitForTimeout(1500);
      console.log(tab, 'manual state:', (await field.innerText()).replace(/\s+/g, ' ').slice(0, 120));
      await page.getByRole('button', { name: preview, exact: true }).click();
      await page.locator('section[aria-label="Import preview"]').waitFor({ timeout: 30000 });
      const section = page.locator('section[aria-label="Import preview"]');
      console.log(tab, 'preview:', (await section.innerText()).split('\n').slice(0, 14).join(' | '));
      await page.screenshot({ path: `${dir}/shots/${file}.png`, fullPage: false });
      await page.getByText('Advanced import format and column mapping').click();
    }
  } catch (e) { console.log('FAILED', e.message.split('\n')[0]); await page.screenshot({ path: dir + '/shots/failure.png' }); }
  console.log('preview calls:', previews.join(', '));
  console.log('API failures:', [...new Set(failed)].join(', ') || 'none');
  await browser.close();
})();
