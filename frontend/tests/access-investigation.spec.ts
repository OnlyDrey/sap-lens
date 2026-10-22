import { test, expect } from "@playwright/test";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";

const headers = { "X-SAP-Lens": "browser-test-session" };
const fixture = path.resolve("../backend/tests/fixtures/user-access.csv");
const catalogue =
  "FUNCTION_KEY,AGR_NAME,CHILD_AGR,TCODE\nMM,ZC:MM:BUY:EN*,ZS:BUY,ME23N\nFI,ZC:FI:VIEW:*,ZS:VIEW,ME23N\nFI,ZC:FI:VIEW:*,ZS:VIEW,FB03\n";
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
