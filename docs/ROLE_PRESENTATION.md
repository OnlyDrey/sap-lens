# Role presentation and transaction investigation

This guide describes the consolidated User Details and Role Details UI. It does
not change CSV formats, role matching, account validity, lock interpretation,
configuration, SQL exports or Windows packaging.

## User Details

The default view is **All roles**, followed by **Business Roles — ZC:\*** and
**Release Roles — ZO:\***. All roles remains strictly the union of supported ZC
and ZO assignments. ZD, ZZ and other families remain in source data/relationships
but do not become primary assignments or CSV export rows. Moving between detail
records preserves the selected role-family/status filters; opening details from
the directory starts with All roles.

Assignment status, submitted transaction search and CSV export share one toolbar.
On desktop, the input grows and Export CSV aligns right; controls wrap on narrow
windows. Enter submits the exact transaction search. Clear removes both the
submitted code and draft input. CSV export still includes every filtered page,
uses the existing source-generation checks and native save capability, and
preserves distinct assignment evidence. See [access investigation](ACCESS_INVESTIGATION.md#user-role-views-transaction-search-and-csv-export).

Catalogue match cells show copyable catalogue identifiers or **Unmapped**, without
Exact/Wildcard/other strategy badges or tooltips. Internal match strategy,
precedence and candidate evidence remain unchanged. Release classification is
shown in the Release Roles view rather than underneath a Catalogue match heading.
Existing role-detail actions keep their icons and original destinations.

Lock indicators are shared rounded pills: red-tinted Locked, neutral Unlocked or
neutral unknown/mixed evidence. Validity pills retain the existing state names,
semantic colors and CircleCheck/Clock/CircleX/CircleHelp icons. Missing or
conflicting lock evidence is never converted to Unlocked.

## Single-role metadata

Single-role headers have two main rows:

1. Existing circular module icon, module badge where supported, and source title.
2. The existing copyable role identifier.

The source description is no longer repeated underneath the identifier. Expansion,
transaction counts and direct/effective-assignment provenance remain available.

`RoleMetadata` is shared with composite headers. It uses the existing SAP module
registry, aliases, icon mapping and saved visual overrides. Explicit single-role
module metadata takes precedence. Otherwise, a leading, delimited module token in
the imported **description** can supply a display label only when it resolves
unambiguously through that registry. No role identifier fragments are parsed.

Examples:

| Imported description | Header badge | Header title |
|---|---|---|
| `CA - Master Data - Materials Display & Reporting` | CA | Master Data · Materials Display & Reporting |
| `CA - Master Data - Batch Display` | CA | Master Data · Batch Display |
| `SD - Master Data - InfoRecord` | SD | Master Data · InfoRecord |
| Meaningful text without a recognized prefix | None; neutral icon | Full source description |
| No description and no module metadata | None; neutral icon | Unclassified |

Whitespace-delimited hyphens, en dashes and em dashes are supported. Unknown or
ambiguous prefixes remain literal source text. A conflicting description prefix
does not override explicit module metadata. This is presentation of source text,
not another classification engine: backend module IDs, module filters, catalogue
matching and transaction relationships are unchanged. A child can therefore retain
a backend Unclassified ID while its header displays a recognized description
prefix. This distinction is explained in the existing provenance disclosure.

## Role Details: Find transaction code

The sidebar search sits below **Relationships & analysis provenance**, immediately
above **Single Roles**. Search trims surrounding whitespace and uses an exact,
case-insensitive comparison. It searches all imported single-role transaction
mappings, including collapsed sections; it does not contact SAP.

Submitting a code hides nonmatching sections, expands every matching section and
shows the matching count. Matching transaction rows have a theme-token background
and underlined, heavier code text. Transaction descriptions and Investigate users
buttons remain intact. Other transaction rows in each matching section remain
available as context. Users can collapse sections during search. Clear restores
the full list and its previous normal expansion state. Changing the opened role
resets the search and its temporary expansion state.

Matching is memoized on submitted code and role data; typing alone does not scan
transaction mappings. Memoized single-role rows avoid rerendering their full
transaction tables for every input keystroke. Hidden sections retain their normal
expansion state and are excluded from keyboard navigation by the HTML hidden
attribute.

## Catalogue diagnostics and source limitations

These conditions are independent:

| Imported evidence | Interpretation / UI |
|---|---|
| No resolved catalogue record for the assignment | Unmapped/unavailable catalogue evidence; no transaction access is invented |
| Matching catalogue record with an empty description | Match remains valid; provenance reports the missing description |
| Catalogue record without explicit child/parent/effective fields | Provenance reports absent relationship fields; existing direct source mappings are preserved |
| Role or single role without transaction rows | Mapping evidence is unavailable, not proof of no SAP permissions |
| Some transaction mappings are supplied | Matches are confirmed within those mappings; completeness of the external export cannot be established |

An exact match depends on the catalogue identifier, not on whether description,
relationship or transaction fields are populated. If the catalogue export later
contains a previously absent role, refresh can legitimately change an Unmapped
assignment into a confirmed match. The application cannot determine why an SQL
export omitted a record. No SQL query or missing role record is created here.

Search reports no match **in the imported mappings** separately from a role with
no mappings. Zero-mapping single roles trigger a completeness warning. Imported
mapping evidence never proves effective SAP authorization or the absence of
permissions. Review the upstream export separately when evidence is incomplete.

## Validation

Regression coverage is in `frontend/tests/consolidated-role-ui.spec.ts`, alongside
the existing access/export/browser tests. It covers header parsing and unchanged
backend classification, fallback text, collapsed/multiple/exact/custom-code search,
row highlighting, expansion restoration, role changes, missing evidence, All roles,
match-code presentation, export, shared toolbar layout and both themes at 800 and
1280 pixels. Existing lock tests now require a pill background while retaining
icon, label, alignment and unknown-state assertions.

From the repository root, with the prepared Python environment active:

```powershell
python -W error::DeprecationWarning -m unittest discover -s backend/tests -v
python -m pip check
python scripts/check-workflows.py
pwsh -NoProfile -File scripts/check-powershell.ps1
node scripts/sync-lucide-catalog.mjs --check
cd frontend
npm ci
npm run check:types
npm run build
npm run test:browser
npm audit --omit=dev
```

Run the project's Python dependency audit and actionlint as documented in the CI
architecture as well. Browser and mocked native-save tests are not native Windows
WebView2, UNC-path or packaged-EXE validation. This frontend task does not alter or
run the Windows packaging pipeline.

### Local results (2026-10-23)

- Backend suite with deprecations treated as errors: **214 passed**, no skips.
- Full browser suite: **95 passed**. The eight consolidated regression cases also
  passed separately after strengthening the active five-control toolbar check.
- npm clean installation, TypeScript checking and production frontend build: passed.
- pip consistency, workflow contracts, actionlint, PowerShell parser/static guards,
  Lucide catalogue verification and Git whitespace checks: passed.
- Python requirements audit and production npm audit: no known vulnerabilities.
  Full npm audit retains seven existing development-only tooling advisories
  (five high, two moderate); dependencies and lockfiles were not changed.
- Light/dark screenshots were inspected at 800/1280 pixels for the toolbar,
  catalogue match cells, metadata headers, search highlighting and lock pills.
- Native Windows/WebView2, UNC paths and a packaged executable were not tested.
  No Windows package, GitHub workflow, release or remote push was performed.

Changed files:

| Responsibility | Files |
|---|---|
| User views and toolbar | `frontend/src/components/Access/UserAccess.tsx` |
| Shared metadata | `frontend/src/components/Shared/RoleMetadata.tsx`, `frontend/src/components/Modules/ModuleRegistry.tsx` |
| Sidebar search and provenance | `frontend/src/components/RoleDetail/RoleDetailPanel.tsx` |
| Presentation tokens/layout | `frontend/src/index.css` |
| Browser regression coverage | `frontend/tests/consolidated-role-ui.spec.ts`, `frontend/tests/access-investigation.spec.ts`, `frontend/tests/user-role-export.spec.ts` |
| Documentation | `docs/ROLE_PRESENTATION.md`, `docs/ACCESS_INVESTIGATION.md` |
