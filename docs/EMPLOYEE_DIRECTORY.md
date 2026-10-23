# Employee Directory and optional features

Employee Directory enriches SAP user identities using an optional, local Active
Directory export. It does not grant access, change SAP account status, or modify
role/transaction evidence. Role Catalogue and User Access remain independent
sources. No direct AD connection, cloud upload or credentials are required.

## Setup and daily use

1. Open **Settings → Features**. Enable **Employee Directory**, then **Apply settings**.
   This switch is off by default on existing and new installations.
2. Open **Settings → Data Sources → Employee Directory**. Browse to a CSV or enter
   its absolute path. UNC paths are supported by the underlying Windows filesystem,
   subject to the signed-in user's share permissions.
3. Select **Validate & preview directory**. Review the filename, record count,
   duplicate/missing-email counts and first five employee samples.
4. Select **Import directory**. This action saves immediately;
   first save or cancel any pending edits to other settings. Confirmation verifies
   the preview's SHA-256 and current settings revision. Changed files must be
   previewed again. Invalid replacements retain the previous valid directory.
5. Use the employee search in this tab to search name, email, department, job
   title, site or manager. Results are paginated, with employee and manager details.
6. Open a SAP user in **User Access**. A unique, exact email match adds an Employee
   Directory section beneath the original SAP account information. Use **View SAP user** in **Reports to** to open the manager’s existing SAP User Details, when exactly one SAP username matches `ManagerMail`. Browser Back returns to the employee.

Use the independent Role Catalogue and User Access tabs for their existing CSV
formats, presets, mappings, delimiters and encodings. Their preview and save
behavior is unchanged. Clearing a source requires confirmation and never deletes
the original file. For these two SAP sources, **Save and load CSV** applies the
pending clear operation. Directory confirmation/clear applies immediately.

## Exact directory format

Use these 16 headers, separated by semicolons (header order may vary):

```text
Site;Name;SamAccountName;UserPrincipalName;Mail;Department;Title;Enabled;DistinguishedName;ManagerDN;ManagerName;ManagerSamAccountName;ManagerMail;ManagerDepartment;ManagerTitle;ManagerLookupStatus
```

All headers are required, case-insensitively and without duplicates. Individual
values may be blank. Use UTF-8, optionally with a BOM. Quoted fields support
semicolons, quotes and line breaks. Leading/trailing whitespace is trimmed.
Blank rows are ignored; a header-only/empty file is rejected. Malformed rows,
invalid UTF-8 and missing/extra headers are rejected atomically. Limits: 50 MB,
100,000 records and 4,096 characters per field. No real employee fixtures belong
in the repository.

`Enabled` accepts `true`/`false` or `1`/`0`, case-insensitively. Other/missing values
remain **Unknown**, never implicitly enabled. AD account state is shown separately
from SAP lock and validity evidence. `UserPrincipalName` is not an email fallback;
`ManagerLookupStatus` is source information, not proof that SAP Lens resolved a
manager.

## Identity and manager rules

- SAP email and directory `Mail` are trimmed and compared case-insensitively.
- Names, usernames, partial addresses and UPNs are never used to guess a SAP match.
- Outcomes: matched, unmatched, missing email, duplicate directory email,
  ambiguous SAP email, or directory unavailable. Conflicting SAP email values
  deliberately prevent automatic enrichment, even if only one matches.
- Duplicate directory email keys are retained for review; no duplicate wins.
- Manager relationships prefer `ManagerMail` → `Mail`. If that preferred key is
  absent, use `ManagerDN` → `DistinguishedName`, then `ManagerSamAccountName` →
  `SamAccountName`, requiring exactly one match. A supplied but unresolved or
  ambiguous preferred key stops resolution; weaker keys never override it.
- Missing, unresolved, ambiguous and self-referencing managers remain distinct.
  Manager relationships are rendered one step at a time, without recursive tree
  expansion, so cycles cannot cause recursive failures.
- Record links include a directory generation digest. A replaced dataset cannot
  silently reinterpret an old row ID as a different employee.

## Feature state, availability and health

**Features** contains two compact switches, saved together using the existing
**Apply settings** action. Employee Directory defaults off; User–Role Mapping
defaults on to preserve existing installations. Disabling either preserves its
source configuration. User–Role Mapping guards every `/api/access/*` endpoint,
including paginated export reads, returning an explicit disabled response (409).
Assignment views are unmounted while disabled so cached evidence cannot appear
current. Role Lookup remains independent. An unavailable disabled mapping CSV
cannot prevent the catalogue from loading.

Employee Directory remains independently enabled when User–Role Mapping is off.
Directory browsing remains available, but SAP enrichment and match coverage require
enabled User–Role Mapping with a loaded SAP user CSV. This is the only currently
supported SAP email source, not an inherent requirement for storing AD records.
Coverage counts SAP identities, including missing/unmatched/ambiguous email states,
not assignment rows; zero users and unavailable dependencies have explanations.

The Data Sources tab owns import history, filename, data quality and manager counts.
Features shows only compact availability and configuration links. Application &
Diagnostics owns technical storage/dependency/operational health and recovery links.
Enabled preference, configured path, available records, satisfied dependency and
operational health are separate states. Disabled optional capabilities do not fail
core health. Missing emails are warnings: records remain imported and searchable.

## Persistence, privacy and recovery

Confirmation atomically stages one validated, content-addressed UTF-8 JSON snapshot
in `%LOCALAPPDATA%\SAP Lens\employee-directory\`, then saves its ID and the selected
source path in settings. Only after both succeed is the new in-memory dataset
published. Failed validation, changed preview digests, stale revisions, storage or
settings failures retain the previous accepted import. Successful replacement removes
the previous snapshot; cleanup failures are reported without exposing local paths.
The original CSV is never copied, changed or deleted. Imported records now survive
restart even when that CSV/share is unavailable. Last successful import remains the
confirmation timestamp, not the latest process start/read time.

The source path describes where a replacement can be selected; it does **not** prove
the file exists or substitute for persisted records. Old path-only settings remain
readable. Re-import once to create a durable snapshot; a missing legacy source with
no snapshot cannot be recovered. Corrupt snapshots produce an optional error and
require re-import; SAP lookup stays independent. Bounds: 50 MB input, 100,000 rows,
4,096 characters per value and 128 MiB serialized storage. Snapshot reads revalidate
schema, limits and SHA-256. This detects corruption, not malicious local tampering.

Confirmed records contain personal data. They remain inside the signed-in user’s
private application directory; POSIX writes use restrictive file permissions and
Windows relies on the per-user directory’s ACL. Settings backups retain references,
not records; replacing/clearing can make older references unavailable. Resetting
settings does not erase orphaned private snapshots: review local storage when
performing a deliberate personal-data cleanup. **Clear directory data** removes the
active snapshot and reference, preserving the original file and feature preference.
Neither records, paths nor snapshot IDs enter portable settings exports. Importing
portable settings preserves the current local snapshot. `.gitignore` and Windows
package verification exclude `employee-directory` directories. No network uploads,
credentials, personal-data logs, external profile images or service-worker data caches
are introduced. Keep local screenshots and exports private.

## Employee profile and manager SAP navigation

SAP User Details shows a compact employee card: name, title and email, then
department, site, AD username and **AD account status**. These never overwrite SAP
source fields or establish SAP validity. Reports to shows only manager name/title.
The button resolves the employee’s **ManagerMail** against normalized exact SAP
emails, requiring exactly one SAP username. AD usernames, manager names and directory
row IDs are never used as SAP route identities. No/multiple SAP matches or missing
manager email have neutral explanations and no active link. Disabled/unavailable
mapping prevents identity enrichment; a disabled directory has no enrichment card.
The underlying directory relationship resolver still supports its existing unique
AD keys for data-quality reporting and settings browsing; that is separate from
SAP manager navigation. No organization chart or new manager route is introduced.

## Validation boundaries

Automated synthetic tests cover parsing, email/manager matching, duplicates, optional
states, revision/digest guards, atomic replacement, feature persistence, restart
loading, search, privacy, manager navigation and light/dark layouts. Existing SAP
CSV and package integrity tests remain required.

Before distribution, run the canonical Windows build and packaged EXE smoke tests,
then manually test WebView2, the native file dialog, Unicode paths and a real
permitted UNC share. Linux browser and unit tests do not validate those native
Windows behaviors. No real employee data should enter test logs or build inputs.

## Local implementation validation (2026-10-23)

The Employee Directory implementation was completed on `work` before starting
subsequent role-filter refinements. The Linux baseline passed 236 backend tests
(with deprecations treated as errors), TypeScript checking and the production
build, followed by all 113 browser tests. Python runtime/development/desktop/build requirement audits found no known
vulnerabilities, and the JavaScript production audit found none. Seven unchanged
JavaScript development-tool advisories remain (five high, two moderate).

Workflow contracts, actionlint, PowerShell syntax/static guards, repository
integrity/privacy and the 1,447-entry Lucide catalog check passed. Synthetic
light/dark Features and Data Sources screenshots were reviewed at 800 and 1280
pixels. Native Windows packaging, WebView2, UNC access and the actual file picker
remain pending; no remote builds or workflow dispatches were performed.
