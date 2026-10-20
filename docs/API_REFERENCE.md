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

Desktop API reads and writes require `X-SAP-Lens: <per-launch-capability>`; the capability is managed by the native window and never written to logs, settings or runtime diagnostics. Source development requires `X-SAP-Lens: 1` for POST. OPTIONS preflight is validated against the exact allowed origin, not a wildcard. Hosts other than localhost/loopback are rejected; desktop binds exclusively to `127.0.0.1`. `/health` and static assets do not reveal the capability or source-file contents.

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

Native additions `close_application`, `open_logs` and `export_diagnostics` require the launch capability; log opening uses only the fixed owned log path. The trusted startup document is kept in memory, carries no CSV data, loads no remote resources and permits only its authored inline startup logic. The HTTP application's strict script policy is unchanged.
