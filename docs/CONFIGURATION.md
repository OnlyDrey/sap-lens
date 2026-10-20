# Configuration

Use **Settings → Browse for CSV…** to open the Windows file picker, or enter a complete path, then choose **Save and load CSV**. The currently configured file is displayed. Canceling the picker leaves the path unchanged. The picker is available in the desktop window; source/browser development supports typed paths. No `.env` file is required.

| Setting | Default / behavior |
| --- | --- |
| CSV path | Empty on first launch; UI asks for a file |
| Desktop address | Exclusively `127.0.0.1`; prefers `18743`, falls back to an OS-assigned port on conflict |
| Desktop CORS | Only the actual selected origin, including its port |
| `CORS_ORIGINS` | Source-mode override only. Defaults to `http://127.0.0.1:18743` and `http://localhost:18743`; explicit HTTP loopback origins only, never wildcards |
| `DATA_CSV_PATH` | Optional initial path before a user saves one in the app |
| `SAP_LENS_CONFIG_DIR` | Optional override for the per-user settings/log directory |

Saved `settings.json` takes precedence over `DATA_CSV_PATH`. Environment variables take precedence over `backend/.env` for initial settings. The desktop always derives its own CORS origin from its reserved socket, ignoring a source-mode CORS override. Restart source-mode development after changing environment settings.

Windows stores settings and logs at `%LOCALAPPDATA%/SAP Lens/`; Linux uses `$XDG_CONFIG_HOME/sap-lens` or `~/.config/sap-lens`. Moving/upgrading the EXE preserves settings. Settings are atomically replaced after a successful CSV load. Corrupt saved settings fall back to bootstrap defaults and can be replaced from the app. Logs rotate at 2 MB with two backups. They record stages/counts and generic failure categories, without CSV contents, file locations, full tracebacks or launch tokens.

An ephemeral `runtime.json` records the owned process ID, selected origin and random instance identity for diagnostics. It never contains the session capability and is removed on normal exit. A stale record after forced termination does not authorize connecting to a listener; the next owned desktop launch replaces it after acquiring the Windows instance lock.

Only absolute filesystem CSV paths are accepted by Settings. HTTP/file URLs are rejected. UNC shares are supported by Windows; other platforms require a mount. The signed-in user must have read access to the file. The app reads but never writes SAP data.

Required CSV headers: `FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT`. UTF-8 with or without BOM is accepted. Additional columns are ignored. Empty role names are ignored; transaction codes without a child role are ignored. Duplicate T-codes within a single role are deduplicated. Quoted commas/newlines in descriptions are supported. The file is streamed into a new cache generation before publication.

A missing/unreadable/invalid CSV produces an understandable error without replacing the saved location or previous cache. Initial loading runs in the background; the UI shows **Loading role data…**. Loads are serialized. A stalled network filesystem can delay completion; the app remains closable, and daemon loader threads cannot keep it running after exit. Once the filesystem responds, choose a local export if necessary. Do not treat a CSV from an untrusted source as authoritative SAP data.
