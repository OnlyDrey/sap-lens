import { test, expect } from "@playwright/test";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";

const headers = { "X-SAP-Lens": "browser-test-session" };
const fixture = path.resolve("../backend/tests/fixtures/user-access.csv");
const catalogue =
  "FUNCTION_KEY,AGR_NAME,CHILD_AGR,TCODE,CHILD_AGR_TEXT,TTEXT\nMM,ZC:MM:BUY:EN*,ZS:BUY,ME23N,Synthetic purchasing display role,Display purchase order\nFI,ZC:FI:VIEW:*,ZS:VIEW,ME23N,Synthetic accounting display role with a longer description that remains readable when the window is narrow,Display purchase order\nFI,ZC:FI:VIEW:*,ZS:VIEW,FB03,Synthetic accounting display role with a longer description that remains readable when the window is narrow,Display accounting document\n";
let directory = "";
test.beforeEach(async ({ request }) => {
  expect(
    (await request.post("/api/configuration/reset", { headers })).ok(),
  ).toBeTruthy();
  directory = mkdtempSync(path.join(tmpdir(), "sap-lens-access-"));
  const file = path.join(directory, "catalogue.csv");
  writeFileSync(file, catalogue);
  const settings = (
    await (await request.get("/api/configuration", { headers })).json()
  ).settings;
  settings.data_csv_path = file;
  settings.user_csv_path = fixture;
  expect(
    (
      await request.post("/api/configuration", { headers, data: settings })
    ).ok(),
  ).toBeTruthy();
});
test.afterEach(async ({ request }) => {
  try {
    expect(
      (await request.post("/api/configuration/reset", { headers })).ok(),
    ).toBeTruthy();
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("user to role to transactions and reverse role or transaction investigation preserves evidence", async ({
  page,
}) => {
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/#session=browser-test-session");
  const navigation = page.getByRole("navigation", { name: "Main navigation" });
  await expect(navigation.getByRole("button")).toHaveCount(3);
  await navigation
    .getByRole("button", { name: "User Access", exact: true })
    .click();
  await page
    .getByLabel("Search users", { exact: true })
    .fill("alpha@example.invalid");
  await page.getByRole("button", { name: "DEMO_ALFA", exact: true }).click();
  const detail = page.getByRole("region", {
    name: "User details",
    exact: true,
  });
  await expect(detail).toContainText("GROUP_A, GROUP_B");
  await expect(detail).toContainText("Business Roles — ZC:*");
  await detail
    .getByRole("button", {
      name: "Copy role identifier ZC:MM:BUY:ENP",
      exact: true,
    })
    .click();
  await expect(
    detail.getByRole("status").filter({ hasText: "Copied" }),
  ).toBeVisible();
  await detail
    .getByRole("button", { name: "Role details: ZC:MM:BUY:EN*", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("ZS:BUY");
  await expect(dialog.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Back to users");
  await dialog
    .getByRole("button", { name: "Assigned users", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "User Access", exact: true }),
  ).toContainText("Evidence filter: Role ZC:MM:BUY:EN*");
  await expect(
    page.getByRole("button", { name: "DEMO_ALFA", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "DEMO_GAMMA", exact: true }),
  ).toHaveCount(0);
  await navigation
    .getByRole("button", { name: "Role Lookup", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: "View details for ZC:MM:BUY:EN*",
      exact: true,
    })
    .click();
  await dialog
    .getByRole("button", { name: "Expand single role ZS:BUY", exact: true })
    .click();
  await dialog
    .getByRole("button", { name: "Investigate users with ME23N", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "User Access", exact: true }),
  ).toContainText("Evidence filter: Transaction ME23N");
  await expect(
    page.getByRole("button", { name: "DEMO_ALFA", exact: true }),
  ).toHaveCount(1);
  await expect(
    page.getByRole("button", { name: "DEMO_DELTA", exact: true }),
  ).toHaveCount(1);
});

test("directory-only users, expired and future assignments, unknown validity and locked accounts are separate", async ({
  page,
}) => {
  await page.goto("/#session=browser-test-session");
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "User Access", exact: true })
    .click();
  await page.getByRole("button", { name: "DEMO_GAMMA", exact: true }).click();
  const detail = page.getByRole("region", {
    name: "User details",
    exact: true,
  });
  await expect(detail).toContainText("expired");
  await expect(detail).toContainText("No assignments in this section");
  await page.getByLabel("Assignment status", { exact: true }).selectOption("all");
  await expect(detail).toContainText("ZC:MM:BUY:ENK");
  await detail
    .getByRole("button", { name: "Release Roles — ZO:*", exact: true })
    .click();
  await expect(detail).toContainText("future");
  await detail
    .getByRole("button", { name: "Back to users", exact: true })
    .click();
  await page.getByRole("button", { name: "DEMO_BETA", exact: true }).click();
  await expect(
    detail.getByRole("definition").filter({ hasText: "Locked" }),
  ).toBeVisible();
  await detail
    .getByRole("button", { name: "Back to users", exact: true })
    .click();
  await page.getByRole("button", { name: "DEMO_EMPTY", exact: true }).click();
  await expect(detail).toContainText("0 assignment records retained");
  await detail
    .getByRole("button", { name: "Back to users", exact: true })
    .click();
  await page.getByRole("button", { name: "DEMO_DELTA", exact: true }).click();
  await expect(detail).toContainText("unknown");
  await expect(detail).toContainText("ZC:FI:VIEW:ENS");
});

test("release table matrix distinct counts, group comparison and user drilldown include unparsed records on request", async ({
  page,
}) => {
  await page.goto("/#session=browser-test-session");
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Release Roles", exact: true })
    .click();
  const release = page.getByRole("region", {
    name: "Release Roles",
    exact: true,
  });
  await expect(release).toContainText("2 users · 4 records");
  await page.getByRole("button", { name: "Matrix", exact: true }).click();
  await page
    .getByRole("button", { name: "Investigate PR SH N6: 2 users", exact: true })
    .click();
  const detail = page.getByRole("region", {
    name: "Release role details",
    exact: true,
  });
  await expect(detail).toContainText("2 distinct users · 4 assignment records");
  await detail.getByRole("button", { name: "DEMO_BETA", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "User details", exact: true }),
  ).toContainText("DEMO_BETA");
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Release Roles", exact: true })
    .click();
  await page.getByRole("button", { name: "Back to Release Roles", exact: true }).click();
  await page.getByRole("button", { name: "Matrix", exact: true }).click();
  await page.getByLabel("Compare SAP User Groups", { exact: true }).check();
  await expect(
    page.getByRole("button", {
      name: "Investigate GROUP_A PR SH N6: 2 users",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Investigate GROUP_B PR SH N6: 1 users",
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Table", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Release assignment status", exact: true })
    .selectOption("all");
  await page.getByRole("combobox", { name: "PR/PO", exact: true }).fill("Unparsed");
  await page.getByRole("option", { name: "Unparsed", exact: true }).click();
  await expect(release).toContainText("ZO:UNKNOWN");
  await expect(release).toContainText("Unparsed");
});

test("user CSV detection preview and independent custom preset create rename duplicate delete persist", async ({
  page,
  request,
}) => {
  await page.goto("/#session=browser-test-session");
  await page
    .getByRole("button", { name: "Open settings", exact: true })
    .click();
  await page
    .getByRole("tab", { name: "Data Source & Import", exact: true })
    .click();
  await page.getByRole("tab", { name: "User Access", exact: true }).click();
  const user = page.getByRole("region", {
    name: "User access CSV configuration",
    exact: true,
  });
  await expect(
    page.getByRole("tab", { name: "Domains & Classification", exact: true }),
  ).toHaveCount(0);
  await expect(
    user.getByRole("button", { name: "Delete preset", exact: true }),
  ).toBeDisabled();
  await user
    .getByRole("button", { name: "Create preset", exact: true })
    .click();
  await user
    .getByLabel("User import preset name", { exact: true })
    .fill("Synthetic user layout");
  await user
    .getByRole("button", { name: "Duplicate preset", exact: true })
    .click();
  await expect(
    user.getByLabel("User import preset name", { exact: true }),
  ).toHaveValue("Synthetic user layout copy");
  page.once("dialog", (dialog) => dialog.accept());
  await user
    .getByRole("button", { name: "Delete preset", exact: true })
    .click();
  await expect(
    user.getByLabel("User import preset name", { exact: true }),
  ).toBeDisabled();
  await user
    .getByRole("button", { name: "Preview user import", exact: true })
    .click();
  await expect(user).toContainText(
    "7 users · 13 assignments · 1 identical duplicate rows",
  );
  const before = (
    await (await request.get("/api/configuration", { headers })).json()
  ).settings;
  await page
    .getByRole("button", { name: "Save and load CSV", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "SAP Lens settings", exact: true }),
  ).toBeHidden();
  const after = (
    await (await request.get("/api/configuration", { headers })).json()
  ).settings;
  expect(after.data_csv_path).toBe(before.data_csv_path);
  expect(after.active_user_import).toBe("default");
  expect(
    after.user_import_profiles.some(
      (p: { name: string }) => p.name === "Synthetic user layout",
    ),
  ).toBeTruthy();
  expect(after.import_profiles).toEqual(before.import_profiles);
  await page.reload();
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "User Access", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "DEMO_EMPTY", exact: true }),
  ).toBeVisible();
});

for (const theme of ["light", "dark"] as const) {
  test(`access pages render with keyboard navigation in ${theme} at narrow desktop width`, async ({
    page,
    request,
  }, info) => {
    expect(
      (
        await request.post("/api/configuration/theme", {
          headers,
          data: { theme },
        })
      ).ok(),
    ).toBeTruthy();
    await page.setViewportSize({ width: 1024, height: 800 });
    await page.goto("/#session=browser-test-session");
    const nav = page.getByRole("navigation", { name: "Main navigation" });
    await nav.getByRole("button", { name: "User Access", exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByRole("heading", { name: "User Access", exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: info.outputPath(`user-access-${theme}.png`),
    });
    await nav
      .getByRole("button", { name: "Release Roles", exact: true })
      .click();
    await page.getByRole("button", { name: "Matrix", exact: true }).click();
    await expect(
      page.getByRole("table", { name: "PR release matrix", exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: info.outputPath(`release-matrix-${theme}.png`),
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  });
}

test("a partial matrix never presents off-page cells as zero users", async ({
  page,
}) => {
  await page.route(
    (url) => url.pathname === "/api/access/releases",
    (route) =>
      route.fulfill({
        json: {
          items: [],
          total: 0,
          offset: 0,
          limit: 50,
          loaded: true,
          groups: [],
          matrix_total: 3,
          matrix_offset: 0,
          matrix: [
            {
              user_group: "",
              document_type: "PR",
              release_group: "SH",
              release_strategy: "N6",
              user_count: 2,
            },
            {
              user_group: "",
              document_type: "PR",
              release_group: "SI",
              release_strategy: "N7",
              user_count: 1,
            },
          ],
        },
      }),
  );
  await page.goto("/#session=browser-test-session");
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Release Roles", exact: true })
    .click();
  await page.getByRole("button", { name: "Matrix", exact: true }).click();
  const matrix = page.getByRole("table", {
    name: "PR release matrix",
    exact: true,
  });
  await expect(
    matrix.getByRole("cell", { name: "—", exact: true }),
  ).toHaveCount(2);
  await expect(
    matrix.getByRole("cell", { name: "0", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText(/A dash means no cell is shown on this page/),
  ).toBeVisible();
});

for (const theme of ['light', 'dark'] as const) for (const width of [1280, 600]) {
  test(`copyable users and compact role transactions in ${theme} at ${width}px`, async ({ page, request }, info) => {
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
    expect((await request.post('/api/configuration/theme', { headers, data: { theme } })).ok()).toBeTruthy()
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/#session=browser-test-session')
    const nav = page.getByRole('navigation', { name: 'Main navigation' })
    for (const name of ['Release Roles', 'Role Lookup', 'User Access']) {
      const button = nav.getByRole('button', { name, exact: true })
      await button.click()
      await expect(button).toHaveAttribute('aria-current', 'page')
      await expect(button).toHaveCSS('box-shadow', 'none')
      await expect(button).toHaveCSS('border-bottom-width', '0px')
      await expect(button).toHaveCSS('text-decoration-line', 'none')
      expect(await button.evaluate(element => ['::before', '::after'].map(pseudo => getComputedStyle(element, pseudo).content))).toEqual(['none', 'none'])
      await button.focus(); await button.press('Tab'); await page.keyboard.press('Shift+Tab')
      await expect(button).toHaveCSS('outline-style', 'solid')
    }
    const row = page.getByRole('row').filter({ has: page.getByRole('button', { name: 'DEMO_ALFA', exact: true }) })
    const identifier = row.locator('.role-identifier')
    await expect(identifier.locator('code')).toHaveText('DEMO_ALFA')
    const copy = identifier.getByRole('button', { name: 'Copy username DEMO_ALFA', exact: true })
    await expect(copy.locator('svg.lucide-copy')).toBeVisible()
    await copy.focus(); await copy.press('Enter')
    await expect(identifier.getByRole('status')).toHaveText('Copied')
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('DEMO_ALFA')
    await expect(page.getByRole('region', { name: 'User details', exact: true })).toHaveCount(0)
    await page.screenshot({ path: info.outputPath('user-directory.png'), fullPage: true })
    await row.getByRole('button', { name: 'DEMO_ALFA', exact: true }).press('Enter')
    const detail = page.getByRole('region', { name: 'User details', exact: true })
    await expect(detail.getByRole('button', { name: 'Copy username DEMO_ALFA', exact: true })).toBeVisible()
    await expect(detail.getByText('wildcard', { exact: true })).toHaveCount(0)
    const match = detail.locator('.catalogue-match').filter({ hasText: 'ZC:MM:BUY:EN*' })
    await expect(match.locator('.evidence-badge')).toHaveCount(0)
    await expect(match.locator('.role-identifier')).toHaveCSS('margin-bottom', '0px')
    await expect(match.getByRole('button', { name: 'Copy role identifier ZC:MM:BUY:EN*', exact: true })).toBeVisible()
    await match.getByRole('button', { name: 'Copy role identifier ZC:MM:BUY:EN*', exact: true }).click()
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('ZC:MM:BUY:EN*')
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: info.outputPath('catalogue-matches.png'), fullPage: true })
    await page.getByRole('button', { name: 'Back to users', exact: true }).click()
    await expect(page.getByRole('button', { name: 'DEMO_ALFA', exact: true })).toBeFocused()
    for (const code of ['FB03', 'ME23N']) {
      await nav.getByRole('button', { name: 'Role Lookup', exact: true }).click()
      await page.getByRole('button', { name: 'View details for ZC:FI:VIEW:*', exact: true }).click()
      const dialog = page.getByRole('dialog')
      const entry = dialog.locator('.single-role-entry')
      const expand = entry.getByRole('button', { name: 'Expand single role ZS:VIEW', exact: true })
      await expand.press('Enter')
      await expect(expand).toHaveAttribute('aria-expanded', 'true')
      const description = entry.locator('.single-role-description'), identifier = entry.locator('.single-role-heading-main .role-identifier')
      expect((await description.boundingBox())!.x).toBeCloseTo((await identifier.boundingBox())!.x, 0)
      await expect(description).not.toHaveCSS('text-overflow', 'ellipsis')
      const table = entry.getByRole('table')
      await expect(table.getByRole('columnheader')).toHaveText(['T-Code', 'Description', 'Action'])
      const actions = table.getByRole('button', { name: /^Investigate users with / })
      await expect(actions).toHaveCount(2)
      const widths: number[] = []
      for (const current of ['FB03', 'ME23N']) {
        const action = table.getByRole('button', { name: `Investigate users with ${current}`, exact: true })
        await expect(action).toHaveText('Investigate users')
        const cells = action.locator('xpath=ancestor::tr').getByRole('cell')
        await expect(cells).toHaveCount(3)
        await expect(cells.nth(2).getByRole('button')).toHaveAttribute('aria-label', `Investigate users with ${current}`)
        await expect(cells.nth(0).getByRole('button')).toHaveCount(0)
        await expect(cells.nth(2)).toHaveCSS('text-align', 'right')
        widths.push((await action.boundingBox())!.width)
      }
      expect(widths[0]).toBeCloseTo(widths[1], 0)
      const investigate = table.getByRole('button', { name: `Investigate users with ${code}`, exact: true })
      await investigate.focus(); await investigate.press('Tab'); await page.keyboard.press('Shift+Tab')
      await expect(investigate).toHaveCSS('outline-style', 'solid')
      await page.screenshot({ path: info.outputPath(`transactions-${code}.png`), fullPage: true })
      await table.getByRole('button', { name: `Investigate users with ${code}`, exact: true }).press('Enter')
      await expect(page.getByRole('region', { name: 'User Access', exact: true })).toContainText(`Evidence filter: Transaction ${code}`)
      await expect(page.getByRole('button', { name: 'DEMO_ALFA', exact: true })).toBeVisible()
    }
  })
}

test('long username code wraps within its cell and copies without navigation', async ({ page }) => {
  const username = 'DEMO_' + 'LONG_USERNAME_'.repeat(8)
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.route('**/api/access/users?*', async route => {
    const response = await route.fetch(), body = await response.json()
    await route.fulfill({ json: { ...body, items: [{ ...body.items[0], username }], total: 1 } })
  })
  await page.setViewportSize({ width: 600, height: 900 })
  await page.goto('/#session=browser-test-session')
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'User Access', exact: true }).click()
  const identifier = page.getByRole('button', { name: username, exact: true }).locator('..')
  await expect(identifier.locator('code')).toHaveText(username)
  expect(await identifier.evaluate(element => element.scrollWidth <= element.clientWidth)).toBeTruthy()
  await identifier.getByRole('button', { name: `Copy username ${username}`, exact: true }).click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(username)
  await expect(page.getByRole('region', { name: 'User details', exact: true })).toHaveCount(0)
})
