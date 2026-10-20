# Configuration and recovery

Settings has six sections: System & Organization, Data Source & Import, SAP Modules, Domains & Classification, Appearance & Branding, and Application & Diagnostics. Defaults are generic and configure one current dataset/system; there is no multi-system infrastructure.

Organization name, platform (S/4HANA, ECC or Other/Custom), system ID, client, description and footer are editable. The configured organization name is the primary header heading; an empty name uses SAP Lens. Windows and repository branding remain SAP Lens. Module display overrides and custom business domains are separate from SAP area IDs. Theme supports System, Light and Dark, defaults to Dark, and persists independent color palettes and custom presets. See [desktop workspace and theme colors](UX_AND_THEMES.md).

## Storage and upgrades

Schema version 2 settings live at `%LOCALAPPDATA%/SAP Lens/settings.json` on Windows, or `$XDG_CONFIG_HOME/sap-lens` / `~/.config/sap-lens` on Linux. They survive moving/upgrading the EXE. `SAP_LENS_CONFIG_DIR` can override this with an absolute path. `DATA_CSV_PATH` bootstraps an initial path only; saved settings take precedence. Environment variables override `backend/.env` bootstrap values. Neither is needed for normal desktop use.

Desktop binds exclusively to `127.0.0.1`, preferring 18743 with an OS-assigned fallback. Desktop CORS is the actual origin. Source-only `CORS_ORIGINS` defaults to `http://127.0.0.1:18743` and `http://localhost:18743`; HTTP loopback origins only, no wildcard. Restart development after changing bootstrap variables.

Settings are validated, revision checked and atomically replaced. Concurrent stale edits receive 409. Analysis-affecting changes build a complete new graph before settings/cache publication; metadata-only edits avoid rereading CSV. Profile content edits increase their versions. Migration from the previous path-only format makes an exact-byte backup first. Unknown, malformed or future-schema files remain untouched until an explicit recovery save/reset; a notice explains fallback defaults. Before-save backups are under `configuration-backups/`. Keep private backups secure; retention is user-managed and they can grow.

## Branding and portability

Choose PNG, JPEG or WebP up to 2 MB and 4096 pixels per side. SVG and animated images are rejected. Decoded pixels are resized to at most 1024 per side, stripped of metadata and reencoded as PNG in the private `branding/` directory. Moving/deleting the original does not affect the saved image. Missing/invalid copied images fall back to SAP Lens. Replace, remove or restore the default in Appearance & Branding. Retained assets/backups permit recovery and are not automatically erased by reset.

Export defaults to a redacted portable `.sap-lens.json` package. Including private organization details, profiles, rules, mappings, module overrides and the logo requires the explicit private export option. Both modes include theme colors/custom preset names and exclude CSV paths and records, session capabilities and runtime state. Review private packages before sharing. Import validates the package/version/logo and preserves the local CSV path; it never trusts an embedded source path. Reset restores generic defaults after confirmation. Desktop export uses a native Save dialog; browser development downloads JSON. Open configuration folder is a guarded Windows native action.

Logs rotate at 2 MB with two backups, contain safe stages/counts and omit source paths, SAP values and capabilities. `runtime.json` contains only process/origin/instance diagnostics and is removed on normal exit. A stale record cannot authorize a connection. Settings, assets and backups use normal per-user filesystem protection, not encryption.

See [CSV import](CSV_IMPORT.md), [classification](CLASSIFICATION.md) and [privacy](PRIVACY.md).

The removed frontend environment template was unused: no VITE_API_URL setting exists. Browser requests are same-origin and development uses the Vite proxy. Keep local data paths in application settings; backend/.env.example documents optional bootstrap variables only.
