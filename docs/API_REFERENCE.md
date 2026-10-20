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

Errors: invalid request shape 422; unreadable/invalid CSV 400 with safe details; unknown role 404; origin/capability failure 403; load already in progress 409; POST body exceeding 16 KiB 413. The application remains accessible after file errors. Built-in CDN-backed Swagger/ReDoc pages are disabled; source schema is at `/openapi.json`.

The native JavaScript bridge exposes `choose_csv(capability)`, which opens a single-file CSV picker. A selection returns its path, cancellation returns null, and incorrect capabilities are rejected before opening a dialog. It does not directly load or save the selected file; the normal validated settings API performs that action.
