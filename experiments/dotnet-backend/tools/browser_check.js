// Browser check of the embedded prototype UI against a running Server (Chromium, the WebView2 engine): sign-in, import, Role Lookup, User Access,
// Compare Users, token never visible to page script. Development tool; needs Playwright.
//   node browser_check.js http://127.0.0.1:PORT TOKEN roles.csv users.csv SCREENSHOT_DIR
const { chromium } = require('playwright');
(async () => {
  const [base, token, roles, users, shots] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const problems = [];
  page.on('console', m => { if (m.type() === 'error') problems.push(m.text()); });
  page.on('pageerror', e => problems.push(e.message));
  await page.goto(base + '/');
  await page.waitForSelector('#status a');
  console.log('unauthenticated status:', await page.textContent('#status'));
  await page.click('#status a');
  await page.fill('input[name=token]', token);
  await page.click('button[type=submit]');
  await page.waitForSelector('#app:not([hidden])');
  console.log('signed in status:', await page.textContent('#status'));
  for (const [source, file] of [['roles', roles], ['users', users]]) {
    await page.selectOption('select[name=source]', source);
    await page.setInputFiles('input[name=file]', file);
    await page.click('#import-form button[type=submit]'); await page.waitForFunction(() => !/Imported|failed|Held/.test(document.querySelector('#import-result').textContent));
    await page.waitForFunction(() => /Imported|failed|Held/.test(document.querySelector('#import-result').textContent), null, { timeout: 60000 });
    console.log(source, '->', await page.textContent('#import-result'));
  }
  await page.waitForFunction(() => document.querySelectorAll('#datasets tr').length >= 2); console.log('datasets rows:', await page.locator('#datasets tr').count());
  await page.click('nav button[data-tab=roles]');
  await page.fill('#roles-form input[name=search]', 'ZC:FI*');
  await page.click('#roles-form button[type=submit]');
  await page.waitForSelector('#roles tr');
  console.log('roles:', await page.textContent('#roles-summary'), 'first:', await page.textContent('#roles tr td'));
  await page.screenshot({ path: shots + '/ui-roles.png' });
  await page.click('nav button[data-tab=users]');
  await page.click('#users-form button[type=submit]');
  await page.waitForSelector('#users tr');
  console.log('users:', await page.textContent('#users-summary'));
  await page.click('nav button[data-tab=compare]');
  await page.fill('#compare-form input[name=left]', 'USER00001'); await page.fill('#compare-form input[name=right]', 'USER00008');
  await page.selectOption('#compare-form select[name=validity]', 'all');
  await page.click('#compare-form button[type=submit]');
  await page.waitForFunction(() => document.querySelector('#compare-summary').textContent.length > 0);
  console.log('compare:', await page.textContent('#compare-summary'));
  console.log('token visible to page script:', (await page.content()).includes(token) || (await page.evaluate(() => document.cookie)).length > 0);
  console.log('console errors:', problems.length ? problems : 'none');
  await browser.close();
})().catch(e => { console.error('FAILED', e.message); process.exit(1); });
