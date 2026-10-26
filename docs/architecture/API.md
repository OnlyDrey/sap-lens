# Local API reference

Desktop: the owned `http://127.0.0.1:<selected-port>` origin, preferring `18743`. Development: Vite on `18743` proxies these routes to `127.0.0.1:18744`. Data/settings/health responses are `Cache-Control: no-store`.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/health` | App/version/instance identity, load status, role count, last successful load |
| GET | `/api/settings` | Current file location, latest safe load error and loading flag |
| POST | `/api/settings` | Validate/load an absolute CSV path and atomically save its location |
| GET | `/api/roles` | Role summaries; optional `function_key`, `search`, `tcode` parameters |
| GET | `/api/roles/{agr_name}` | Role details with single roles and transactions |
| GET | `/api/modules` | Distinct module labels |
| POST | `/api/compare` | Compare two to five distinct roles |
| POST | `/api/refresh` | Reload the configured CSV |

Desktop API reads and writes require `X-SAP-Lens: <per-launch-capability>`; the capability is managed by the native window and never written to logs, settings or runtime diagnostics. Source development requires `X-SAP-Lens: 1` for POST. OPTIONS preflight is validated against the exact allowed origin, not a wildcard. Hosts other than localhost/loopback are rejected; desktop binds exclusively to `127.0.0.1`. `/health` and bundled assets do not reveal the capability or source-file contents. The desktop-only root document has a narrow navigation bootstrap exception: exact loopback Host/port and peer, top-level non-cross-site Fetch Metadata, non-cacheable HTML and a fresh CSP nonce. It hands the capability into origin session storage; API endpoints remain guarded. See [Desktop connectivity](DESKTOP.md).

Settings request:

```json
{"data_csv_path":"C:/SAP/exports/sap_roles.csv"}
```

Comparison request:

```json
{"roles":["DEMO:A","DEMO:B"]}
```

Health `status` is `loading`, `ok`, or `needs_configuration`. CSV loading is independent of API readiness: the server stays usable before a dataset is available. `cached_roles` and `last_loaded` describe the retained cache, even after a later failed refresh.

Errors: invalid request shape 422; unreadable/invalid CSV 400 with safe details; unknown role 404; origin/capability failure 403; load already in progress 409; oversized POST body 413. The application remains accessible after file errors. Built-in CDN-backed Swagger/ReDoc pages are disabled; source schema is at `/openapi.json`.

The native JavaScript bridge exposes `choose_csv(capability)`, which opens a single-file CSV picker. A selection returns its path, cancellation returns null, and incorrect capabilities are rejected before opening a dialog. It does not directly load or save the selected file; the normal validated settings API performs that action.

## Enterprise configuration API

All routes below use the same capability/origin protection and no-store policy. GET configuration returns settings, recovery notice, loading/error and analysis provenance. POST configuration accepts the complete schema-2 AppConfig, including current revision. A stale revision returns 409. Imports and resets validate before atomic application.

| Method | Route | Purpose |
| --- | --- | --- |
| GET / POST | `/api/configuration` | Read/apply complete configuration |
| POST | `/api/configuration/theme` | Persist `{ "theme": "system" }` (also light/dark) |
| POST | `/api/configuration/export?include_private=false` | Redacted portable package; private content requires true |
| POST | `/api/configuration/import` | Validate/apply portable package; preserve local source path |
| POST | `/api/configuration/reset` | Restore generic defaults |
| POST | `/api/data/cancel` | Invalidate current CSV load/publication |
| GET | `/api/registry/modules` | Registry, approved icons and reference caveat |
| POST | `/api/classification/preview` | `{profile, test_role?}` against loaded roots |
| POST | `/api/import/headers` | `{data_csv_path, profile?}` header detection |
| POST | `/api/import/preview` | Same request; counts/warnings/samples without publication |
| POST | `/api/branding/preview` | `{path}`; sanitize/stage image and return data URL/hash |
| GET | `/api/branding/logo` | Active sanitized logo data URL or 404 fallback |

Default POST limit is 16,384 bytes; full configuration allows 1,000,000, portable import 4,000,000 and classification preview 128,000. Limits apply to streamed bodies too. Role details/comparisons include analysis metadata; role details also expose original relationships and alternate descriptions. Native bridge additions `choose_logo`, `export_configuration` and `open_configuration_folder` require the same capability and fixed validated operations; they provide no arbitrary command execution.

## UX and appearance additions (1.2)

GET `/api/diagnostics` exposes guarded local UI details, including source/application directory. GET `/api/diagnostics/export` exposes an allowlisted path-free, identity-free report with versions, platform, status and counts. Both use the existing API capability boundary and no-store responses.

Schema-2 configuration now includes independent `theme_colors.light` and `theme_colors.dark` palettes (primary, accent, background, surface, text) and up to 20 named custom presets. HEX colors and 4.5:1 primary-text contrast against both backgrounds are validated. Old schema-2 files backfill defaults without rewriting the file on read. Empty organization names are supported for product-branding fallback.

Native additions `close_application`, `open_logs` and `export_diagnostics` require the launch capability; log opening uses only the fixed owned log path. The trusted startup document is kept in memory, carries no CSV data, loads no remote resources and permits only its authored inline startup logic. The HTTP application allows bundled scripts, plus only the per-response nonce for its guarded desktop browser handoff; arbitrary inline scripts remain blocked.


## Global user/release record navigation

`GET /api/access/users` and `GET /api/access/releases` accept optional `anchor`
(maximum 512 characters). Supply the same filters, `sort` and `descending` as the
originating list, plus `limit=1&offset=0`. The authenticated navigation response
contains the bounded `items/total/offset/limit` page and:

```json
{"navigation":{"index":50,"total":125,"previous":"DEMO_049","next":"DEMO_051"}}
```

The index is zero-based; the UI displays 51 of 125. Anchor comparison uses existing
username/role normalization, while returned identities preserve source spelling.
Ordering, tie breaks, evidence matching, group/status filters and classification
are the same code path as the normal list. No separate frontend ordering exists.
Boundary neighbours are null. An absent or filtered-out anchor returns null index
and neighbours with the current filtered total; it never resolves to the first
row. Navigation mode omits source/group/matrix aggregates, and the UI requests
only one bounded sample row. Normal responses without `anchor` are unchanged.
Session/origin protections and no-store behavior apply as before. Navigation is
re-resolved on refresh; an in-flight/failed query cannot expose stale actions.

### GET /api/access/release-options

Authenticated, no-store release filter options from the current loaded User
Access generation. `field` is required: `group`, `document_type`, `release_group`,
`strategy`, `username` or `role`. Optional `search` and `selected` are bounded to
512 characters; `limit` defaults to 50 and cannot exceed 100. Context parameters
are `group`, `document_type`, `release_group`, `strategy` and assignment `status`
(default `active`, also `all`, `expired`, `future`, `unknown`).

Returns `items`, `total`, `has_more` and `selected_available`. The availability
check is independent of the option search window. Facets use the hierarchy
[documented with the investigation UI](../archive/implementation/ACCESS_INVESTIGATION.md#data-aware-release-filters-and-navigation).
No role, user or transaction relationships are modified.

Diagnostics now include a `sources` array for Role Catalogue and User Access:
configured/loaded flags, record/assignment counts, last successful load and
allowlisted error/availability categories. Only authenticated local diagnostics
include `configured_path`, `loaded_path` and `attempted_path`. The export omits
all three and includes no source contents or identities. Availability is evidence
from the last completed read, not a synchronous filesystem probe: an unavailable
UNC share cannot block a diagnostic request. `available_at_last_load` explicitly
does not claim the file is currently reachable.

### User assignment views and transaction evidence

`GET /api/access/users/{username}` accepts `scope=business|release|all` for the
User Details views. `all` is strictly the ZC/ZO union, filtered before pagination;
legacy `other` and empty scopes retain their existing API behavior. `status`,
`show_expired`, `offset` and `limit` (maximum 100) retain their meaning.

Optional `tcode` (maximum 128 characters) trims whitespace and performs an exact,
case-insensitive match against the import-time transaction index and resolved
catalogue assignments. Responses add `mapping_available`,
`unmapped_assignments` (assignments without resolved transaction mappings in the
selected user/view/status scope before the transaction filter), and `data_revision`
(an opaque import-generation identity). Each item adds `role_description` and
`transaction_roles`; these are catalogue evidence, not effective authorization.

CSV export uses these existing authenticated pages, checks generation/count/date
consistency and runs locally. There is no new HTTP export/upload endpoint. Native
CSV saving uses a separate capability-guarded Save dialog and does not enable
unrestricted WebView2 downloads. See [User access](../archive/implementation/ACCESS_INVESTIGATION.md#user-role-views-transaction-search-and-csv-export).

### Multiple exact transaction filters

The existing role-list and user-detail endpoints additionally accept repeated
`tcodes` parameters, for example `?tcodes=MIGO&tcodes=ME21N`. Values are trimmed,
uppercased and deduplicated. User-detail matching uses OR before assignment pagination. The catalogue defaults to AND across the full role, with `transaction_mode=or` available explicitly. Other filter categories still apply with AND. At most 21 values (20 chips plus one draft)
of 128 characters each are accepted; larger inputs return 422. Legacy `tcode`
behavior is preserved. API dates remain ISO; Norwegian formatting is UI-only.

### Optional Employee Directory

All `/api/employees` routes use existing local session/origin protection:

- `GET /api/employees/status`: feature/configuration/availability/health, aggregate
  matching and manager counts, plus private filename metadata for the local UI.
- `POST /api/employees/preview`: `{path, revision}` validates the fixed directory
  schema and returns a SHA-256 digest, counts and at most five preview records.
- `POST /api/employees/import`: `{path, revision, digest}` rereads and confirms
  the exact previewed bytes, then atomically publishes the source preference and
  memory snapshot. Changed input or stale settings returns 409.
- `POST /api/employees/clear`: `{path, revision}` clears directory configuration
  and memory after UI confirmation; the source file is never deleted.
- `GET /api/employees?search=&offset=0&limit=25`: bounded employee search, available
  only while the feature is enabled. Returns the dataset generation digest.
- `GET /api/employees/record/{id}?generation=...`: one-level employee/manager
  details; stale generations return 409 instead of reusing an old row index.
- `GET /api/employees/match/{username}`: exact SAP email enrichment; missing,
  duplicate, unmatched and unavailable states never modify SAP user responses.

Redacted `/api/diagnostics/export` includes directory aggregate status only.
See [Employee Directory contracts](../data/EMPLOYEE_DIRECTORY.md) for matching and privacy.

### Catalogue areas and assignment dates

Repeated `function_keys` combine with OR in `/api/roles`. Role text search matches only role name and description. User-detail/release endpoints share inclusive `valid_from_min/max`, `valid_to_min/max` and `open_ended` parameters before pagination. See [filter and navigation contracts](../features/FILTERS.md#api-additions).

### Authenticated user import preview samples

`POST /api/user-import/preview` validates without publication. Its bounded sample
response contains at most 20 rows of USERNAME, ROLE_NAME, USER_GROUP, FIRST_NAME,
LAST_NAME, EMAIL, ROLE_VALID_FROM and ROLE_VALID_TO. This enables local preview
search; the full CSV is not transferred to the DOM. Personal samples remain absent
from stored user reports and diagnostic exports. Existing session/origin, size,
row and validation guards still apply.

### Review annotations and assignment transaction matching

GET `/api/access/users/{username}` accepts `transaction_mode=and|or` (default `and`)
for `tcodes`; it reuses canonical aggregate role mapping sets before pagination.
User Details export supplies the same mode alongside date/status/scope filters.

GET `/api/account-review` supports `finding=reviewed|pending` in addition to existing
findings. POST `/api/account-review/decision/{username}` validates current evidence
before preserving the previous decision and atomically saving the new annotation.
GET `/api/account-review/history/{username}?offset=0&limit=25` returns bounded earlier
decisions (maximum page size 100). Authentication and mapping-feature guards apply;
this is private annotation history, not SAP modification history.

### Filtered assignment CSV downloads

`GET /api/access/exports/users` accepts the same validated directory query filters
as `/api/access/users` and exports all assignments for all matching users.
`GET /api/access/exports/releases` accepts the same release/date filters as
`/api/access/releases`, exporting only matching assignments independently of
Table/Matrix grouping. Both use the existing feature/session boundary; unavailable
validated mapping data returns 409. Pagination parameters do not limit exports.

Responses are no-store `text/csv; charset=utf-8` with safe attachment filenames,
UTF-8 BOM, quote-all semicolon rows and CRLF. Columns are USERNAME, FIRST_NAME,
LAST_NAME, EMAIL, USER_GROUP, ROLE_NAME, ROLE_VALID_FROM, ROLE_VALID_TO,
ASSIGNMENT_STATUS, PR_PO, RELEASE_GROUP, RELEASE_STRATEGY, MATCHED_FILTER. Dates are
DD.MM.YYYY; missing dates remain empty. Formula-like cells receive a leading
apostrophe in the file only. Snapshot and evaluation day are captured once.
`X-SAP-Lens-Data-Revision`, `X-SAP-Lens-As-Of` and
`X-SAP-Lens-Assignment-Count` permit client consistency checks. Normal users/releases
responses add `data_revision` and `export_assignments`; existing fields are retained.

`GET /api/access/releases?matrix_complete=true` returns every filtered matrix cell independently of role-table pagination. The legacy bounded matrix_offset API remains compatible for existing consumers. The UI uses complete mode with independently scrollable PR/PO matrices; incomplete responses retain a dash rather than falsely establishing zero users. Assignment filtering, distinct counts, drill-down and export scope are unchanged.
