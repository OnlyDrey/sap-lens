# Settings and role visual refinement

> Historical evidence: applies to the source/phase recorded below, not later
> commits. Use the [current documentation index](../../README.md) for instructions.

Work branch: `work`. The protected README and canonical application assets are
unchanged. No new dependencies, schema changes or SAP analysis/classification
semantics were introduced. Existing configuration migrations remain in place.

## Pages and shared controls

| Area | Changes |
|---|---|
| Navigation | One subtle active background and left indicator; independent keyboard focus; consistent spacing and icons; section changes scroll to the top without losing edits |
| Dropdowns | Shared `SettingsSelect`: token colors, aligned Lucide chevron, reserved right padding, consistent height and radius; native keyboard/menu semantics retained for WebView2 |
| SAP Modules | Full installed Lucide catalog, searchable names and common aliases, paginated responsive grid, selected icon preview, shared validated color controls |
| Domains & Classification | Plain-English profile guidance; Legacy clearly marked as compatibility; advanced custom domains/rules collapsed; preview explanations and technical fingerprint disclosure |
| CSV import | Debounced header inspection and preview after file selection/path change; required and ambiguous header guidance; contextual mapping labels and Automatic/Manual states |
| Appearance & Branding | Selected preset states and palette samples, shared rounded swatch/HEX/reset controls, reusable-preset guidance, explicit active/pending logo status and consistent action icons |
| Diagnostics | Application status, Data & storage, Troubleshooting and Backup & recovery; schema/revision/platform in Technical details; redacted export behavior retained |
| Save/Cancel | Apply disabled without changes or with invalid colors; unsaved edits preserved across pages; stale previews cleared after save; Cancel restores the saved draft and resets temporary theme-editor state |

The shared controls are in `frontend/src/components/Settings/Controls.tsx`.
Native select menus deliberately retain operating-system semantics and can escape
scroll containers; replacing them with a new popup library was unnecessary.
Custom colors continue to use semantic theme tokens and existing contrast guards.
SAP module colors remain independent of application theme colors.

## Icon catalog and compatibility

The locked Lucide package supplies 1,447 catalog names. The backend accepts 1,448
identifiers including retained legacy aliases; all previous 21 identifiers remain
supported. `scripts/sync-lucide-catalog.mjs` generates the backend allowlist from
the installed package and verifies synchronization with `--check`. It does not
fetch code or change dependencies. Run it after a Lucide lockfile update.

The complete loader/catalog and picker are separate lazy chunks. SVG modules load
only when rendered; the first picker page contains 48 choices, with search and
Show more. Missing SVG modules safely render the existing Hash fallback. The
production entry remains approximately 337 kB raw / 100 kB gzip, compared with
approximately 334 kB / 99 kB before; the entire SVG catalog is not loaded initially.
All required icon chunks are local build assets, not runtime CDN requests.

## CSV safety and configuration compatibility

Header inspection returns supported-column proposals and missing/ambiguous-header
messages without loading a dataset. The parser's relationship, transaction and
classification rules are unchanged. Standard fields continue to auto-detect;
manual selections remain explicit overrides rather than redundant stored defaults.

Refreshing the same path retains valid manual overrides and explains removed
mappings to missing columns. Selecting another file clears previous manual
mappings and explains that change. Cancel restores the original saved path and
mapping. Async results from an older selection cannot replace a newer draft or
preview. Previews do not replace the active dataset; Save and load CSV remains the
explicit confirmation boundary. Existing two-task daemon limits and loopback,
origin, host and session-capability protections remain unchanged.

All three classification modes remain necessary for different data:
Generic SAP uses recognized module evidence, Legacy preserves earlier child-label
hints and results, and Custom adds user domains/rules. Guidance recommends Generic
SAP for neutral new setups without changing any existing selected/default profile.

## Role identifiers, module icons and status

`RoleIdentifier` presents the original identifier in wrapping monospace text,
with a labeled keyboard-operable Copy button and a short live confirmation.
Clipboard denial reports an accessible error and leaves the exact identifier
selectable. Copy controls do not open cards or expand rows. Card, detail,
single-role, comparison and classification-preview identifiers use the same
component; human-readable descriptions retain their existing presentation.
Single-role expansion uses a separate button, avoiding nested interactive controls.
Relationship identifiers are also copyable. No imported value is modified.

`ModuleIcon` supplies circular 24/32/40 px containers throughout cards, filter
chips, detail panels, single-role lists, comparisons and SAP Modules settings.
Its background blends 10% configured module color with the saved theme surface.
The configured foreground is retained when its actual contrast is at least 3:1;
otherwise it uses readable theme text or a black/white fallback. Invalid or absent
module colors fall back safely. Selection, hover and disabled outlines preserve
readability without gradients, shadows or opacity reduction. One shared provider
tracks system appearance, rather than installing a listener per icon.

`StatusPill` is informational. Module row pills reflect the saved enabled state;
the expanded editor explicitly labels the draft state as Preview. The checkbox
continues to edit only the draft. Cancel discards it; Apply persists it. No schema,
classification, relationship or settings-location changes were required.

## Validation record

Final results are recorded after the complete local suite below. No Windows build
or GitHub workflow was started. Windows packaging, actual WebView2 clipboard and
menus/focus, native dialogs, Explorer launch and Windows DPI behavior remain
unverified in this Linux environment.

The [pre-push policy](../../../AGENTS.md) requires explicit approval before pushing
when required Windows validation is unavailable. Linux browser/unit tests are
not equivalent to packaged Windows validation. No partially tested version is
pushed as a way to debug the Windows pipeline.

## Visual review and limits

The local review uses screenshots captured before these changes and the same
settings pages afterward, plus light/dark module editors and role details with a
synthetic 389-character identifier. The browser regressions cover the existing
1280×720, 1366×768 and 1920×1080 settings matrix in both default dark and light
presets. Identifier copy buttons must not create page overflow or nested buttons.
Copy confirmation must fit inside its component, including clipped single-role
containers. Module icon tests measure computed foreground/background contrast,
including white, black, near-surface, invalid and reset colors.

The theme preview regression decodes screenshot pixels: editing a primary color
must change more than 10% of the preview; Cancel must restore all pixels within a
one-channel-level tolerance for rasterization. This is a comparison of the same
preview state, rather than a new screenshot silently accepted as its own baseline.
The eight external reference screenshots mentioned in the settings request were
not attached to the supplied text, so no pixel match against those images is
claimed. Linux Chromium screenshots do not establish Windows DPI or screen-reader
compatibility.

## Dependency and security scope

No dependency manifest or lockfile changed. The full npm audit still reports seven
existing development advisories in the Tailwind 3 build-tool dependency tree
(five high and two moderate); the separate production-only audit is recorded
below. Those tools run during frontend builds and are not bundled into the desktop
Python runtime. Updating that tree may require a Tailwind major-version migration,
which is outside this UI refinement. No advisory was suppressed.

Windows-only dependency checks and executable verification remain part of the
canonical Windows workflow; a Linux installed-package audit does not replace them.
Application host/origin/session guards, privacy boundaries, data import semantics,
configuration schema and migrations are preserved. The tracked-change review also
checks for private-key/token signatures without printing candidate values.

## Commands executed locally

These are validation records from the prepared Linux checkout, not Windows setup
instructions. Commands using `/workspace/sap-lens-dev` refer to isolated audit and
screenshot tooling outside the repository. Browser tests use installed Chromium;
no additional executable or dependency is committed.

| Command (repository root) | Result |
|---|---|
| `git diff --check` and `git diff --cached --check` | Passed |
| `npm --prefix frontend ci --cache /workspace/.npm-cache` | Passed; locked dependencies installed |
| `node scripts/sync-lucide-catalog.mjs --check` | Passed; 1,447 catalog icons, legacy identifiers retained |
| `npm --prefix frontend run check:types` | Passed |
| `npm --prefix frontend run build` | Passed; main entry approximately 337.33 kB / 100.17 kB gzip |
| `.venv/bin/python -m unittest discover -s backend/tests -v` | Passed: 68 tests, including import, classification, persistence, migration, launcher, repository integrity and privacy coverage |
| `.venv/bin/python -m pip check` | Passed |
| `/workspace/sap-lens-dev/audit-venv/bin/python -m pip_audit --path /workspace/sap-lens/.venv/lib/python3.12/site-packages --cache-dir /workspace/.pip-audit-cache --progress-spinner off` | Passed; no known vulnerabilities in audited installed Python dependencies |
| `npm --prefix frontend audit --omit=dev` | Passed; zero production advisories |
| `npm --prefix frontend audit --json` | Seven existing development advisories, reported above |
| `/workspace/sap-lens-dev/actionlint/actionlint` | Passed |
| `PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium PATH=/workspace/sap-lens/.venv/bin:$PATH npm --prefix frontend run test:browser -- role-visuals.spec.ts --reporter=line` | Passed: six affected behavior tests after corrections |

The initial combined browser run found a test race around asynchronous theme-save
closure. It was corrected by waiting for the settings region to close, rather than
increasing timeouts or enabling retries. Visual inspection also found clipped copy
feedback; it now stays inside the identifier and has a bounds regression assertion.
An empty confirmation retains a screen-reader live region; its expiry assertion
inspects the element directly rather than requiring visible text. The complete
suite is rerun after affected checks, with a source-diff fingerprint compared
before and after to detect edits during validation.

The checkout started at local commit `6053c610ef8ce034084f65db0fb5e7f00ed2a9c7`.
A fresh fetch of remote `work` returned
`3defa1b479108784ffc2d6bab55a2b1b7f82129f`; the previous local-only commit was
preserved. README, PNG and ICO bytes were compared directly with the starting
commit, and no dependency manifest or lockfile changed. No push, remote build or
GitHub Actions dispatch was performed for these refinements.

Final complete browser command:

```sh
PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium PATH=/workspace/sap-lens/.venv/bin:$PATH npm --prefix frontend run test:browser -- --reporter=line,github
```

Result: **28 passed (3.0 minutes)**, with one worker and no retries. All commands in
the final full local sequence succeeded. The before/after source-diff comparison
matched; SHA-256 of the validated runtime/test patch:
`a74bb10c67eae4bee628e7506d43740d7557a3ced168593391f2e9c081e6bdd1`.

The final screenshot capture was also executed with
`python /workspace/sap-lens-dev/settings-refinement/capture-with-server.py` and
reviewed alongside the baseline and light/dark role/module screenshots. The full
README file and canonical PNG/ICO remained byte-for-byte unchanged. Windows
packaging/EXE/WebView2 validation is **pending**, not passed. Push and GitHub Actions
remain **not started**, awaiting the required Windows-validation exception approval.
