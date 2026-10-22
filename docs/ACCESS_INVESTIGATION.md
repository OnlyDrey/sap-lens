# Local access investigation

## Baseline and dependencies reviewed

Work begins on `work` at `3331e52f5124b805b6935c79b68aaed1c5dbb252`, with a clean
working tree. The preceding CI and UI commits are preserved. No workflow or
Windows packaging redesign belongs to this task; no remote validation is authorized.

The role catalogue uses FUNCTION_KEY, AGR_NAME, TEXT, CHILD_AGR, CHILD_AGR_TEXT,
PARENT_AGR, Effective_Role, TCODE and TTEXT. AGR_NAME is required. Existing
`CsvImport` header/row validation feeds `cache.build_cache`; composite, child,
parent, effective-role and transaction relationships are constructed before
classification. Role Lookup, role detail, comparison, module filters and T-code
search consume these relationships. They must remain intact when classification
is removed. Import presets map columns; they do not classify role names.

The removed classification engine used profiles, domains, name rules, overrides
and fallback assignments. Its consumers were Settings, previews, domain filters,
role labels and analysis provenance. None owns transaction membership or hierarchy.
SAP Modules remains the canonical visual registry, including aliases, standard
labels, user colors/icons and filter availability. The new policy uses explicit
CSV FUNCTION_KEY evidence only: recognized aliases normalize to their stable SAP
area; missing, unknown or contradictory areas become Unclassified. Child names
and description fragments never invent SAP areas. Child/T-code relationships are
retained even when their own area label is unknown.

## Two independent local CSV sources

Settings → Data Source & Import provides separate User Access and Role Catalogue tabs.
Each source has its own path, active CSV Import Format and preset collection.
They may be used separately. Without a catalogue, user assignments remain
Unmapped and provide no inferred transaction evidence. No third CSV is needed.

Both files are read locally. Preview does not publish data or save settings.
Save/refresh constructs a complete candidate generation and commits both sources
atomically. A failure retains the previous generation and settings. Clearing a
source path is explicit; deleting a preset does not delete a CSV or its records.
Refresh currently reparses configured sources together to keep cross-source
evidence coherent; it does not partially apply a successful file if the other fails.

The role catalogue schema and relationship provenance are preserved. The user
source supports these canonical fields, with mappings for differently named headers:

| Field | Meaning |
| --- | --- |
| USERNAME | Required SAP user identifier; independent of name/email |
| ROLE_NAME | Exact assigned role; blank explicitly supports a directory-only row |
| USER_GROUP | SAP source user group, retained per assignment/account record |
| FIRST_NAME, LAST_NAME, EMAIL | Optional directory metadata; conflicting variants retained |
| USER_VALID_FROM, USER_VALID_TO | Account validity, separate from assignment validity |
| ROLE_VALID_FROM, ROLE_VALID_TO | Assignment interval |
| USER_LOCKED | X/true/yes/locked or nonzero SAP lock mask; 0/false/no/unlocked is unlocked; missing/unrecognized is unknown |
| USER_TYPE | Optional source value, without invented semantics |

UTF-8/BOM, UTF-16 BOM and Windows-1252 are supported. Auto detection uses a
bounded sample; delimiters include comma, semicolon, tab and pipe. Advanced
options override detection. Duplicate/empty headers, missing USERNAME, malformed
row widths, invalid dates and reversed intervals fail validation without publishing.
Files are bounded to 128 MiB and one million logical records and 100,000 distinct users; fields and role
identifiers are length-bounded. Full identical rows are deduplicated. Distinct
users are never joined by names/emails. Case-normalized SAP usernames identify a user (interior text is not removed);
assignment intervals, source groups and account evidence remain distinct.

Dates accept YYYY-MM-DD or YYYYMMDD, including 9999-12-31. Empty/00000000/0000-00-00
means unknown, not unrestricted access. Bounds are inclusive. An ended interval
is expired, a not-yet-started interval future, two enclosing bounds active;
otherwise unknown. Status is evaluated using the local backend calendar date.
Nested transaction previews show the first 100 codes with a full count and a link to the complete catalogue role; reverse lookup still uses all codes.
User Access hides expired assignments by default but identifies future/unknown
records. Release Roles defaults to active assignment intervals only. These are
assignment counts, not claims of usable access: account expiration and lock state
are displayed separately. Filters can recover expired/future/unknown records.

## Import preset management and compatibility

Built-in default formats cannot be deleted. Create starts an empty mapping;
Duplicate copies the current mapping. Custom formats can be renamed or deleted
with confirmation; deleting the active format selects the source's default.
Delimiter and encoding remain advanced options. Neither format deletion nor
column detection deletes a source file. Apply revalidates data with the selected
format; errors retain the last published generation.

Configuration schema 3 adds the user source and separate presets. Schema 2
classification fields are accepted and archived as inactive `legacy_classification`
data without interpreting old expressions or requiring valid old rule targets.
Existing source paths, import mappings and explicit module preferences survive.
The original saved JSON is not rewritten on read; saving creates the existing
local before-save backup. Schema-1 file settings still migrate with a backup.
No old rules execute, no profile switcher/editor/preview API remains, and no
classification regular-expression dependency is needed. Private local exports
can retain the inactive archive; sanitized exports use neutral defaults. Both
filesystem paths and all imported data are excluded from every configuration
export. Importing settings retains the two locally configured source paths.

This intentionally changes area labels formerly inferred by Legacy/Custom.
It preserves assignments and transaction relationships, not obsolete inferred
module/domain labels. Review unknown areas in the source export.

## Matching and navigation

Role Lookup preserves catalogue role and transaction investigation. User Access
lists users with search, sorting and pagination, separate ZC business and ZO
release sections, account evidence and exact identifier copying. Other roles
remain available for explicit source review without becoming primary access roles.
Release Roles supports table/matrix investigation and user drill-down.

`role_matching.RoleMatcher` strips whitespace and normalizes casing for matching
while keeping the original identifiers for display/copy. Match order is exact,
then longest literal prefix ending in a single `*`. Matching is anchored to the
whole role name. Thus `ZC:MM:BUY:EN*` covers ENP/ENO/ENK/ENS and other EN suffixes;
`ZC:MM:BUY:*` is broader. Exact catalogue entries beat both. Equal normalized
candidates at the winning specificity are Ambiguous, with no inferred transaction
access. Unmatched assignments are Unmapped. Wildcard catalogue entries are
patterns, never expanded into actual user assignments. A wildcard in an assigned-role field fails import rather than claiming an actual assignment. Interior/multiple `*`,
`?`, character classes and backslash patterns are unsupported/malformed and do
not participate; regex evaluation is not used.

Resolved role evidence uses catalogue child/effective/direct T-code links. Links
support user → exact assignment → matching catalogue role → transactions, and
role/T-code → distinct assigned users. A user appears once in user search even
when several assignments explain a T-code; all role/interval evidence is retained.
Role-derived transactions do not prove effective SAP authorization.

## Confirmed release naming contract

Only `ZO:MM:<opaque>:PR_REL_ST_<group>_<strategy>:<opaque>` and corresponding PO
forms are parsed. Group and strategy tokens are alphanumeric; opaque tokens may
also include underscore/hyphen. The parser is strict, case-normalized and anchored.
PR means Purchase Requisition; PO means Purchase Order. SH, SI, E1 and E2 are
example release groups; N6 and ND are example strategies, not hardcoded allowlists.
M and ALL are kept as opaque source tokens with no business interpretation.
Unknown/malformed ZO names remain visible as Unparsed in the table and detail.

Matrix rows are release groups, columns release strategies; PR and PO are kept
separate. Cells count distinct normalized usernames, not assignment rows.
Optional SAP User Group comparison uses the group from each source assignment.
A user with records in multiple groups can appear in each group comparison;
counts across groups are not additive. Matrix pages contain at most 200 populated cells; a dash on a partial page does not claim zero users. Cell drill-down retains all intervals and
user-group evidence. Unparsed names stay in the table, not fabricated matrix cells.

## Security and validation boundaries

The local loopback, per-launch capability, origin, CSP and no-store protections
remain unchanged. No SAP connection, credentials, cloud upload, telemetry or
network source is added. CSV/user data stays outside Git and executable assets.
Routine logging contains no usernames, emails, role names, records or file paths.
APIs return bounded pages (up to 100 assignments/users, 50 account records and 200 matrix cells per page); preview summaries omit personal record samples. Group suggestions are capped at 1,000, with typed exact group filters still available. Name/email variants are paginated in groups of 100; all source evidence remains available.
Tests and screenshots use synthetic users and example.invalid addresses only.
Native Windows/WebView2 and packaged EXE validation require later approval; local
Linux tests are not equivalent. Do not push or dispatch workflows in this task.

## Implementation file inventory

Paths are relative to the repository root. Retired classification tests are
removed intentionally; import, graph, color, configuration and privacy coverage
is retained and extended. The prior profile assessment remains a historical
record, superseded by this explicitly approved architecture change.

| File | Purpose |
| --- | --- |
| `backend/cache.py` | One atomic catalogue/user generation; CSV-only SAP area labels; original relationship aggregation retained |
| `backend/classification.py` | Remove obsolete profile/rule/preview engine |
| `backend/config.py` | Read schema-2 settings without rewriting; explain inactive archived classification |
| `backend/config_models.py` | Schema 3, separate user presets/path and legacy archival; remove classification models |
| `backend/configuration_routes.py` | Retire classification API; add independent user header/preview APIs and coherent settings apply |
| `backend/csv_import.py` | Reuse bounded streaming validation across source schemas and detect Windows-1252 safely |
| `backend/data_loader.py` | Update validation wording after classification removal |
| `backend/main.py` | Register local access APIs and support user-only startup |
| `backend/models.py` | Retire domain/profile output; retain CSV module conflict metadata |
| `backend/portable_config.py` | Exclude both paths; preserve locally configured sources on import |
| `backend/requirements.txt` | Remove unused classification-only regex dependency |
| `backend/role_matching.py` | Reusable exact / most-specific literal-prefix matching with ambiguity |
| `backend/routers/access.py` | Paged users, evidence lookup, release tables/matrices and drill-down |
| `backend/routers/roles.py` | Allow literal slashes in linked catalogue identifiers |
| `backend/tests/fixtures/user-access.csv` | Synthetic two-source investigation scenarios; never a packaging input |
| `backend/tests/test_classification_review.py` | Retire obsolete profile preview/mode tests; preserve relevant coverage in CSV area/access tests |
| `backend/tests/test_configuration.py` | Retain configuration/registry tests; remove retired rule-engine scenarios and update schema expectations |
| `backend/tests/test_csv_area_labels.py` | CSV-only labels, unchanged relationships, deterministic defaults and explicit preferences |
| `backend/tests/test_csv_profiles.py` | Retain graph/import tests with CSV-only provenance expectations |
| `backend/tests/test_user_access.py` | Synthetic matching, import/status, identity, pagination, compatibility, privacy and release regressions |
| `backend/user_access.py` | Bounded user parsing, dates/account evidence, release parser and shared indexes |
| `docs/ACCESS_INVESTIGATION.md` | Update current documentation or mark prior classification assessment as historical |
| `docs/ARCHITECTURE.md` | Update current documentation or mark prior classification assessment as historical |
| `docs/CLASSIFICATION.md` | Update current documentation or mark prior classification assessment as historical |
| `docs/CLASSIFICATION_ARCHITECTURE.md` | Update current documentation or mark prior classification assessment as historical |
| `docs/CONFIGURATION.md` | Update current documentation or mark prior classification assessment as historical |
| `docs/CSV_IMPORT.md` | Update current documentation or mark prior classification assessment as historical |
| `docs/DESKTOP.md` | Update current documentation or mark prior classification assessment as historical |
| `docs/PRIVACY.md` | Update current documentation or mark prior classification assessment as historical |
| `docs/UI_REFINEMENT.md` | Update current documentation or mark prior classification assessment as historical |
| `docs/VALIDATION.md` | Update current documentation or mark prior classification assessment as historical |
| `examples/README.md` | Update current documentation or mark prior classification assessment as historical |
| `frontend/src/App.tsx` | Three primary views and cross-page investigation state |
| `frontend/src/api/access.ts` | Typed user/release API contracts |
| `frontend/src/api/configuration.ts` | Separate user source formats; remove retired classification client contracts |
| `frontend/src/api/types.ts` | CSV module conflict metadata without domain/profile fields |
| `frontend/src/components/Access/ReleaseRoles.tsx` | Filtered table/matrix, group comparison and evidence drill-down |
| `frontend/src/components/Access/Shared.tsx` | Shared filters, dates, paging and authorization-evidence notice |
| `frontend/src/components/Access/UserAccess.tsx` | Search/sort/paging, account evidence, scoped assignments and links |
| `frontend/src/components/Modules/ModuleRegistry.tsx` | Remove obsolete domain-label context; preserve module visuals |
| `frontend/src/components/RoleDetail/RoleDetailPanel.tsx` | Assigned-user / transaction investigation links and CSV provenance |
| `frontend/src/components/RoleList/RoleCard.tsx` | Remove domain display; retain module labels and conflicts |
| `frontend/src/components/RoleList/RoleList.tsx` | Remove customer-domain filters; preserve role/T-code/comparison behavior |
| `frontend/src/components/Settings/ClassificationExample.tsx` | Remove obsolete classification preview component |
| `frontend/src/components/Settings/ImportPresets.tsx` | Preset create/rename/duplicate/delete and independent user source editor/preview |
| `frontend/src/components/Settings/SettingsView.tsx` | Remove classification section and add two-source CSV Import Format management |
| `frontend/src/components/Shared/RoleIdentifier.tsx` | Reuse exact-copy control with appropriate username labels |
| `frontend/src/index.css` | Responsive investigation tables using existing tokens |
| `frontend/tests/access-investigation.spec.ts` | New synthetic cross-page, release, import-management, theme and partial-matrix tests |
| `frontend/tests/desktop.spec.ts` | Make first-launch checks independent of test-file order by resetting synthetic configuration explicitly |
| `frontend/tests/enterprise.spec.ts` | Replace retired classification setup with explicit CSV area evidence; preserve graph/preferences tests |
| `frontend/tests/navigation-classification.spec.ts` | Rename retained navigation/module coverage; retire only classification preview scenarios |
| `frontend/tests/navigation-modules.spec.ts` | Preserved navigation, module palette and filter persistence regressions for five settings sections |
| `frontend/tests/ux.spec.ts` | Update section list after the approved removal |

## Local validation record

The Linux validation uses Python 3.12, Node 24 and system Chromium. Commands run
from the repository root unless a working directory is shown:

```sh
git diff --check
.venv/bin/python scripts/ci.py lint
.venv/bin/python scripts/check-workflows.py
pwsh -NoProfile -File scripts/check-powershell.ps1
npm --prefix frontend ci
node scripts/sync-lucide-catalog.mjs --check
npm --prefix frontend run check:types
npm --prefix frontend run build
.venv/bin/python -W error::DeprecationWarning -m unittest discover -s backend/tests -v
.venv/bin/python -m pip check
# pip-audit is installed in a separate tooling environment:
python -m pip_audit --path /workspace/sap-lens/.venv/lib/python3.12/site-packages --progress-spinner off
npm --prefix frontend audit --omit=dev
PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium PATH="$PWD/.venv/bin:$PATH" npm --prefix frontend run test:browser
```

The tooling audit environment, writable package caches, PowerShell XDG directories,
logs and screenshots live outside the repository. No new application dependency
was added. The retired rule engine's sole dependency, `regex`, was removed from
runtime requirements. Production JavaScript manifests and lockfiles are unchanged.
A separate full npm audit reports seven existing development-only advisories
(five high, two moderate); production auditing reports none. These findings remain
visible; no exclusions or warning suppression were added.

The retired classification test cases exercised the removed rule editor, profile
preview and name-rule engine. Their removal is intentional. Catalogue graph,
transaction relationships, import mapping, module preferences, configuration
migration/privacy and navigation coverage are retained or extended. Browser
first-launch tests explicitly reset synthetic settings so test ordering cannot
supply stale CSV paths.

Final full local run: **131 backend tests passed** (15.794 seconds), with
DeprecationWarning treated as an error; **41 browser tests passed** (4.9 minutes).
Workflow/actionlint and trigger/security contracts, PowerShell syntax/static
guards, clean npm installation, Lucide catalog consistency, TypeScript checking,
production build, Python dependency consistency, Python vulnerability audit and
production JavaScript audit all passed. Python and production JavaScript audits
found no known vulnerabilities. Environment-only pip cache ownership and
NO_COLOR/FORCE_COLOR notices remain visible.

The implementation diff was frozen before this full run and compared byte for
byte afterward. Its SHA-256, excluding documentation, was
`40c68c0fa2088c078e5fa88462d484770a55a9c9a15652f5ebd1ef5b135ae120`.
The protected README, canonical PNG/ICO, module registry defaults, Windows
packaging/verification scripts, workflow files and frontend lockfile were
compared with the baseline and are unchanged. The original catalogue relationship
aggregation loop was also compared structurally and is unchanged.

Visual QA inspected synthetic User Access directory/detail, Release Roles table,
and PR/PO matrix screenshots in both light and dark modes at 1440×1000, plus the
matrix at 768×900. Filters reflow, identifiers remain copyable, tables remain
readable and the matrix drill-down controls remain visible. Screenshots are
stored outside Git in the task's local validation directory. Browser tests also
cover keyboard access, partial-matrix paging and existing settings/theme layouts.

Pending: native Windows/WebView2 runtime, real native file picker interaction,
new packaged-EXE startup/shutdown and artifact privacy/integrity checks. No Windows
artifact was built, no workflow was dispatched and no changes were pushed.
Production-sized exports were not available; bounds/indexing are tested with
synthetic data, without claiming a production-scale performance benchmark.


## Investigation navigation and controls

The application header owns Role Lookup, User Access and Release Roles navigation.
Narrow windows show the same destinations as accessible icon buttons. Settings
remains separate. Already visited views retain search, filter, sorting, pagination
and detail state; explicit cross-page evidence investigations start the requested
query. Breadcrumbs return to the originating list. Previous/Next uses the entire filtered, sorted result set, including page
boundaries, with a global position such as 51 of 125. The server resolves the
current identity against the same list ordering and returns only its position and
neighbour identities; the frontend does not download all matches. First/last
boundaries are disabled. Returning to the list retains its originating page,
filters, sorting and scroll position; a page made obsolete by a refreshed dataset
is clamped to the last valid page. Direct cross-page investigations resolve their
position independently of the loaded table page. Removed or no-longer-matching
records show an explanation and disable traversal instead of substituting another
record. Navigation errors never enable stale neighbour actions.

User details has one assignment-status selector: All non-expired (the previous
default), Currently valid, Expired, Future, Unknown validity, or All assignments.
The last option requests all statuses; it does not redefine missing-date validity.
The directory's Show expired assignments option still controls directory role
counts/evidence filtering separately. Account status and account lock remain
independent of role validity. Single account evidence is collapsed behind a
summary; multiple/conflicting account intervals remain expanded and paginated.

User-group filters and CSV column mappings use the shared local combobox. Type
to search, use Arrow Up/Down and Enter to select, Escape to cancel the popup, or
Tab to continue. The All/Automatic option clears the filter/override. Group filters
also accept typed group values; mapping selectors commit only an available option.
Popup panels use the active theme and float within the viewport outside scroll
containers. Small static selectors remain native; Role Lookup retains its
existing module buttons, and the existing searchable icon dialog is unchanged.

Source previews establish readability/validation at inspection time, not proof
of which file produced the loaded dataset. Settings distinguishes the edited
location, saved location and the last successful atomic dataset load. The current
API does not expose an independently trustworthy loaded path per source, so the
UI does not invent one. User preview retains its existing aggregate report;
backend contracts, source data and saved preset schema are unchanged.
