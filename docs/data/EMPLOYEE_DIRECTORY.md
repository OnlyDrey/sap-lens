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
3. Selection automatically validates and imports the entire file. Wait for Completed
   and the committed record/change counts. Invalid or empty replacements preserve
   the previous directory; no confirmation/import button is required.
4. Use **Preview data** for searchable, paginated snapshot inspection and quality
   filters, **View changes** for replacement evidence and **Technical source details**
   for storage information. Source diagnostics and employee search remain below the
   source controls. Unrelated unsaved Settings edits are preserved.
5. Open a SAP user in **User Access**. A unique exact email match enriches the
   unified profile without replacing SAP identity. A uniquely resolved manager opens
   the existing SAP User Details page; Browser Back returns to the employee.

All four sources use the same automatic-selection workflow. Static snapshots remain
available without the original CSV; Dynamic sources revalidate on Global Refresh.
Importing does not enable Employee Directory automatically. Use its direct Feature
Settings action when imported records are retained but enrichment is disabled.
Clear source data is an explicit confirmed operation and never deletes the CSV.
See [Import and refresh](IMPORT_AND_REFRESH.md) for atomic replacement and failure
recovery. Legacy loaded records without a durable snapshot can still use **Save
durable directory snapshot**, without rereading a missing original file.

## Source format

The fixed 16-column UTF-8 semicolon format, limits and Enabled values are defined
once in [CSV schemas](CSV_SCHEMAS.md#employee-directory).

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
settings failures retain the previous accepted import. Prior immutable snapshot retention follows the [CSV lifecycle](IMPORT_AND_REFRESH.md);
cleanup failures are reported without exposing local paths.
The original CSV is never copied, changed or deleted. Imported records now survive
restart even when that CSV/share is unavailable. Last successful import remains the
confirmation timestamp, not the latest process start/read time.

The source path describes where a replacement can be selected; it does **not** prove
the file exists or substitute for persisted records. Old path-only settings remain
readable. Readable enabled legacy sources are captured durably at startup. Validated
in-memory records also support Save durable directory snapshot without rereading
the source. With neither records nor a readable source, reimport is required. Corrupt snapshots produce an optional error and
require re-import; SAP lookup stays independent. Bounds: 50 MB input, 100,000 rows,
4,096 characters per value and 128 MiB serialized storage. Snapshot reads revalidate
schema, limits and SHA-256. This detects corruption, not malicious local tampering.

Confirmed records contain personal data. They remain inside the signed-in user’s
private application directory; POSIX writes use restrictive file permissions and
Windows relies on the per-user directory’s ACL. Settings backups retain references,
not records; preserve the complete data directory for recovery. Resetting
settings does not erase orphaned private snapshots: review local storage when
performing a deliberate personal-data cleanup. **Clear directory data** removes the
active snapshot and reference, preserving the original file and feature preference.
Neither records, paths nor snapshot IDs enter portable settings exports. Importing
portable settings preserves the current local snapshot. `.gitignore` and Windows
package verification exclude `employee-directory` directories. Server browser uploads go only to the configured SAP Lens server; no third-party
upload service, credentials, personal-data logs, external profile images or service-worker
data caches are introduced. Keep local screenshots and exports private.

## Validation boundaries

Automated synthetic tests cover parsing, email/manager matching, duplicates, optional
states, revision/digest guards, atomic replacement, feature persistence, restart
loading, search, privacy, manager navigation and light/dark layouts. Existing SAP
CSV and package integrity tests remain required.

Before distribution, run the canonical Windows build and packaged EXE smoke tests,
then manually test WebView2, the native file dialog, Unicode paths and a real
permitted UNC share. Linux browser and unit tests do not validate those native
Windows behaviors. No real employee data should enter test logs or build inputs.

## SAP User Details profile

The profile has three responsive groups: **SAP Identity**, **Account Status**,
and **Organization**. SAP CSV names/emails remain authoritative. Directory job
title and department enrich Organization; AD account status appears
separately from SAP validity/lock status in Account Status. Site remains in the
source model and source investigation, not the primary SAP profile. Exact matching
outcomes remain available in Data Sources and technical diagnostics rather than a
repeated “Exact email match” label beside the profile.

The SAP profile header never substitutes AD names or emails for missing SAP values.
Display-only normalization in directory/manager displays recognizes letter-only
comma-separated `Surname, Given names` or an uppercase surname prefix followed
by mixed-case given names. Compound parts are retained; initials, annotations,
all-uppercase and ambiguous structures remain unchanged. This never changes
imported values, SAP names, matching keys or manager resolution.

Reports to keeps the manager's name/title without repeated technical attributes.
A unique normalized exact `ManagerMail` → SAP email match enables **View SAP user**
using the actual SAP username. Missing/ambiguous/unmatched identities use a neutral
status pill and no broken link. Browser Back returns to the employee. No AD
username/name-only fallback or organization chart is introduced. Disabled or
unavailable optional sources leave an explanatory Organization group while core
SAP profile/assignment evidence stays available.

## Profile and recovery refinements

The compact profile header contains SAP name/email only. SAP Identity contains
username, group and user type; Account Status separates SAP validity/lock, AD state
and SAP validity dates; Organization contains job title, department and the manager
identity card. AD username and Site remain source attributes, not primary profile
fields. A unique manager SAP identity makes that card navigable using the SAP name
where unambiguous; unresolved identities remain non-clickable.

A shared SAP email is ambiguous enrichment evidence even when the directory has one
row for it. Coverage, profile matching and Account Review now apply this boundary
consistently. A mismatch warning requires reliably matched AD Disabled plus SAP
Valid and Unlocked; absent/ambiguous directory data cannot produce it.

For legacy path-only imports, validated in-memory records can be committed through
**Save durable directory snapshot** without rereading the original CSV. It preserves
the original import timestamp and validates the current settings revision/digest.
See [Settings and persistence recovery](../getting-started/CONFIGURATION.md) and
[Account Review](../features/ACCOUNT_REVIEW.md) for current behavior and privacy boundaries.

## Shared status and technical evidence

All sources use the same mode, loaded-state, record count, import/activation,
snapshot and last-validated-check summary. Employee Directory reads this from the
shared diagnostics query rather than substituting a draft mode or import time for
a current check. A missing check timestamp stays unavailable; a static snapshot can
remain loaded when the original CSV is absent. Technical paths, matching and quality
diagnostics are available through a separate source-details modal. Source configuration
navigation remains a separate action.

Features uses an interactive Enabled/Disabled preference pill. A pending edit is
not saved until Apply settings succeeds. Imported data availability and current
operational/dependency status describe persisted server state independently of that
draft. Directory matching in SAP User Details opens its own compact evidence modal;
no identity matching rule or source replacement semantics are changed.
