# Saved Filters

Supported: User Directory, Role Lookup, Release Roles, Account Review and User Comparison. This is one compact shared Saved filters popover and private persistence API, not separate page-specific stores.

1. Set the current filters/sorting and open **Saved filters**.
2. Enter a name and choose **Save as new**.
3. Choose a saved definition and **Load** to re-evaluate it against current data.
4. Changed controls show **Modified**. **Update saved filter** explicitly replaces the saved configuration; it never autosaves.
5. **Rename** changes only the name; **Delete** asks for confirmation. Names are unique case-insensitively within a view.
6. **Clear applied filter** resets that page's filters/sorting and selection of the saved definition. It does not delete the definition or source data.

Stored state excludes pagination, open menus, details dialogs, results and comparison user identities. Release dates and sorting, role area selections/multiple T-codes, directory evidence filters, and Account Review finding/license/review-state controls are supported. Existing list filter semantics are unchanged.

Storage: the existing per-user settings directory, `%LOCALAPPDATA%\SAP Lens\saved-filters.json` on Windows. Each entry has stable ID, name, target view, filter schema version, bounded scalar/list state and UTC creation/modification timestamps. Atomic writes preserve the previous file on failure. Maximum 250 entries / 1 MB file; definitions max 16 KB. Concurrent edits require the expected last-modified value, preventing silent overwrite. API writes retain the existing launch-session/origin protection.

Restarting or replacing the EXE preserves definitions. Definitions are re-evaluated after refresh; they are not frozen result snapshots. Filter text may contain local investigation identifiers: the file remains private, Git-ignored and outside packaging inputs. It is not included in portable configuration or diagnostic exports.

Unsupported whole-file formats/corrupt files are retained and produce a recoverable message, never silently reset. Future per-filter schemas cannot be loaded; the original definition remains. Unsupported fields/types/options in schema 1 are skipped with a warning. Rename preserves the original schema/configuration. Explicit Update is the only operation that replaces an old definition with current supported fields. A disappearing valid group/area value remains an explicit filter and can legitimately return no results; it does not silently broaden the investigation.

No cloud synchronization, result caching, credentials or SAP data uploads are introduced.

Search saved names in the popover. Save/Clear share a compact row; Clear resets
applied filters without deleting a definition. Escape closes the popover and
returns focus to its trigger; outside click dismisses without stealing focus.

Save as new and Clear filters occupy equal halves of their shared action row,
excluding its gap. Selector/name fields stay aligned and the popover remains
viewport-bounded. Clear is non-destructive; disabled save and compatibility guards
remain unchanged.
