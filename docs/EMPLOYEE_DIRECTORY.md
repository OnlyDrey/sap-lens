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
4. Select **Confirm directory replacement**. This action saves immediately;
   first save or cancel any pending edits to other settings. Confirmation verifies
   the preview's SHA-256 and current settings revision. Changed files must be
   previewed again. Invalid replacements retain the previous valid directory.
5. Use the employee search in this tab to search name, email, department, job
   title, site or manager. Results are paginated, with employee and manager details.
6. Open a SAP user in **User Access**. A unique, exact email match adds an Employee
   Directory section beneath the original SAP account information. Use **View
   manager** to inspect the uniquely resolved manager's employee record.

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

**Enabled** is a saved preference, **configured** means a source path exists, and
**loaded** means a valid dataset is available. These are independent states.
Disabling the feature preserves its path and already loaded data but hides employee
search/enrichment results. Re-enabling restores access. Existing SAP capabilities
are core investigation functions, not new artificial feature toggles.

**Application & Diagnostics** and the source/feature cards show disabled,
not configured, healthy, warning or error status, with record counts, duplicate
and missing emails, manager resolution counts, SAP match coverage and last
successful read time. Disabled/unconfigured optional sources do not fail application
health. Enabled/configured read or validation failures are errors, even if an older
valid snapshot is retained. Incomplete identity/manager information is a warning.

Timestamps describe the last successful read in this process, including after a
restart; they do not prove the share is currently reachable or the export is recent.
The app reads on first enabled use and after explicit confirmed replacement rather
than continuously polling the filesystem. To refresh or retry the same path, preview
and confirm it again. Source contents must remain accessible after restart.

## Persistence, privacy and recovery

Settings use the existing per-user application directory (`%LOCALAPPDATA%\SAP Lens`
on Windows). Additive schema-3 settings default safely for existing installations;
SAP import presets, module preferences and archived legacy classification remain
intact. No directory migration rewrites existing user data. Settings backups contain
configuration paths/preferences, never copied directory records.

The application keeps one accepted dataset in memory and retains the selected
source path. It does not persist a second directory database or copy the CSV into
application storage. Consequently an unavailable source after restarting cannot
restore an in-memory snapshot from the previous process. Reconnect the share and
preview/confirm again. During the same process, a failed replacement retains the
last valid snapshot.

Portable settings exports omit directory paths and all imported records; private
configuration exports can include the feature preference. Import preserves the
installation's local directory path. Redacted diagnostic exports include aggregate
counts/status only, excluding filenames, paths, employee identities and CSV contents.
The local UI necessarily shows personal data to the signed-in user. Treat screenshots
and local exports accordingly. Existing session/origin checks apply to directory APIs;
no data is cached in a service worker or bundled into Windows artifacts.

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
build. Python runtime/development/desktop/build requirement audits found no known
vulnerabilities, and the JavaScript production audit found none. Seven unchanged
JavaScript development-tool advisories remain (five high, two moderate).

Workflow contracts, actionlint, PowerShell syntax/static guards, repository
integrity/privacy and the 1,447-entry Lucide catalog check passed. Synthetic
light/dark Features and Data Sources screenshots were reviewed at 800 and 1280
pixels. Native Windows packaging, WebView2, UNC access and the actual file picker
remain pending; no remote builds or workflow dispatches were performed.
