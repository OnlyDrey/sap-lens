// MIG-010 browser check: the production React UI against a .NET Server (shared-token, loopback). Uploads a synthetic Role Catalogue twice (DIR/before.csv,
// DIR/after.csv; copy tests/SapLens.Tests/Fixtures/imports/report_roles_*.txt), opens "View changes", filters by change type and text, opens a
// record's details, exports the changes CSV and lists every /api response >= 400. Development tool; needs Playwright.
//   node refresh_report_check.js http://127.0.0.1:PORT TOKEN DIR
const { chromium } = require('playwright');
const [base, token, dir] = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  const failed = [];
  page.on('response', r => { const p = new URL(r.url()).pathname; if (p.startsWith('/api/') && r.status() >= 400) failed.push(`${r.status()} ${p}`); });
  try {
    await page.goto(base + '/'); await page.fill('input[name=token]', token); await page.click('button[type=submit]');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Open settings', exact: true }).click();
    await page.getByRole('tab', { name: 'Data Sources', exact: true }).click();
    await page.getByRole('tab', { name: /Role Catalogue/ }).first().click();
    for (const file of ['before.csv', 'after.csv']) {
      const done = page.waitForResponse(r => /uploads\/roles\/activate$/.test(r.url()), { timeout: 60000 });
      await page.getByLabel('Upload Role Catalogue CSV').setInputFiles(`${dir}/${file}`);
      console.log(file, 'activate:', (await done).status());
      // The UI refreshes its dependent views after an import; the next upload waits for "Completed".
      await page.waitForFunction(() => /Completed ·/.test(document.body.innerText) && !/Updating dependent views|Uploading, validating/.test(document.body.innerText), null, { timeout: 60000 });
      await page.waitForLoadState('networkidle');
    }
    const details = page.waitForResponse(r => /data-sources\/reports\/[0-9a-f]+\?/.test(r.url()));
    await page.getByRole('button', { name: 'View changes', exact: true }).click();
    console.log('details:', (await details).status());
    const dialog = page.getByRole('dialog');
    await dialog.getByText(/matching changes/).waitFor();
    console.log('all:', await dialog.getByText(/matching changes/).innerText(), '| rows:', await dialog.locator('table tbody tr').count());
    await dialog.getByLabel('Change type').selectOption('modified').catch(async () => { await dialog.getByLabel('Change type').click(); await page.getByRole('option', { name: /Modified/ }).click(); });
    await page.waitForLoadState('networkidle'); await page.waitForTimeout(500);
    console.log('modified:', await dialog.getByText(/matching changes/).innerText());
    await dialog.getByLabel('Search changes').fill('variant');
    await page.waitForLoadState('networkidle'); await page.waitForTimeout(800);
    console.log('modified + "variant":', await dialog.getByText(/matching changes/).innerText());
    await dialog.getByLabel('Search changes').fill('');
    await page.waitForLoadState('networkidle'); await page.waitForTimeout(800);
    const download = page.waitForEvent('download');
    await dialog.getByRole('button', { name: 'Export changes CSV' }).click();
    const file = await download; await file.saveAs(`${dir}/changes.csv`);
    console.log('export:', file.suggestedFilename(), require('fs').readFileSync(`${dir}/changes.csv`, 'utf8').split('\r\n').length - 2, 'lines');
    await dialog.getByRole('button', { name: /View details for/ }).first().click();
    console.log('record evidence:', (await dialog.getByRole('region', { name: 'Change record evidence' }).innerText()).split('\n').slice(0, 4).join(' | '));
    await page.screenshot({ path: `${dir}/shots/changes.png` });
  } catch (e) { console.log('FAILED', e.message.split('\n')[0]); await page.screenshot({ path: `${dir}/shots/failure.png` }); }
  console.log('API failures:', [...new Set(failed)].join(', ') || 'none');
  await browser.close();
})();
