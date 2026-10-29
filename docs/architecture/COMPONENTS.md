# Component Library and UI architecture inventory

Open **Settings → APPLICATION → Component Library**. The page is lazy-loaded and uses actual shared components with synthetic identities and local demo state. It has no source-import actions, production settings writes, review decisions or sensitive diagnostics. Saved-filter previews use an injected in-memory adapter with an instance-specific query key; real saved investigations remain untouched. No developer permissions, telemetry, external service, Storybook or UI framework was added.

## Architecture audit

React/TypeScript renders Vite production assets inside either a browser or WebView2. Application state uses React Query, application-scoped dataset loading and a small hash/history router. Existing Tailwind utilities and CSS variables already formed a partial design system. Existing selectors, datepicker, identifiers, status rules and pagination were reused.

Observed inconsistencies: repeated input/button strings in Access and Settings; two separate Settings control-size rules; table font/padding overrides; duplicated status badge rules; action-like segmented page navigation; inline saved-filter management; repeated comparison identities and prose metrics; independent import-tab keyboard handling; text-heavy navbar utilities and a redundant UI refresh clock. These were consolidated incrementally. Specialized role comparison, module registry, CSV editors, matrices and profile layouts remain specialized.

## Canonical component inventory

Paths below are relative to `frontend/src/components/`. The inventory covers reusable component families; full page components remain under their existing feature folders.

| Component / canonical implementation | Real usage and variants | Styling / accessibility / migration decision |
| --- | --- | --- |
| `Shared/Button.tsx`: Button | Access exports/review, pagination, detail actions, library; primary/secondary/outline/ghost/destructive, default/compact/icon, loading/disabled | Central tokens; native button/default type=button, forwarded ref, disabled/aria-busy. Replaces duplicated routine action markup incrementally |
| IconButton / Tooltip, same file | Navbar utilities, comparison user links, library | Required label; focus/hover tooltip, Escape, disabled/loading states. No hidden text-only dependency |
| ButtonGroup, same file | Release Table/Matrix, transaction AND/OR, library | Native pressed buttons, named group; this is a presentation/filter control, not page navigation |
| `Shared/Controls.tsx`: Input / SearchInput | Library and shared form contract; legacy Settings/Access inputs use `controlClass` | IDs/ARIA forwarded; search icon space, invalid/disabled states; no copied theme color literals |
| FormField | Access Filter alias, Settings Field alias, SAP selector and library | Label/control association; optional description, retained described-by links. Replaces duplicate label wrappers |
| Checkbox / Toggle, same file | Checkbox preview; real Feature Settings toggles and library | Native checkbox; switch uses native Button with checked state and existing StatusPill, no automatic persistence |
| `Shared/Select.tsx`; SettingsSelect adapter | Settings, Access filters, dates, library | Native selection semantics, one chevron, shared dimensions. Keep the Settings adapter for compatible styling |
| `Shared/Combobox.tsx` | User/group/area/source selectors and library | Portal listbox, arrows/Enter/Escape/Tab, outside dismissal; string values, optional option labels, local/server filtering. Preserved and extended in place |
| `Shared/SAPUserSelector.tsx` | Comparison's authenticated search adapter and isolated library options | Pure presentation of username plus distinguishing name/email options. Does not fetch, merge or mutate identities |
| `Shared/NorwegianDateInput.tsx` | Assignment date controls, library | Existing localized portal calendar/manual entry, focus/keyboard behavior and maximum-date safety preserved |
| `Shared/AssignmentDateFilters.tsx` | User/role/release assignment tables | Existing apply/cancel/date-bound semantics retained; chips now canonical |
| `Shared/TransactionFilter.tsx` / useTransactionFilter | Role Lookup, User Directory/Details, library | Existing multi-code live/deferred state and AND/OR; operator group/chip reuse replaces repeated UI. This is the real multi-value selector showcased |
| `Shared/MultiSelectFilter.tsx` | Release Area and Release Group filters, library | Searchable multi-select: a Combobox adds values, removable FilterChips show them; "All" clears. Values combine with OR, the caller combines filters with AND |
| `Shared/PackageToggle.tsx`, `Shared/AccessPackageBar.tsx` | Role Lookup cards, Release Roles rows and Matrix cells, floating access package action | One round Plus/Check toggle and one floating package action for catalogue and release roles; the package store is shared and unlimited |
| `Shared/WindowsIcon.tsx` | Windows Desktop settings heading, library | Generic four-pane inline mark in currentColor; no third-party artwork or dependency |
| `Shared/FilterChip.tsx` | Transactions and assignment date filters | One removable-chip implementation, explicit removal label, existing focus restoration supplied by caller |
| `Shared/ClearFilterButton.tsx` | Investigation pages/date controls | Canonical Button + filter-x icon; neutral reset styling, explicit accessible text |
| `Shared/SavedFilters.tsx` | Users, roles, releases, review, comparison; memory-only library | Same versioned persistence/CRUD/compatibility logic, compact Popover. Existing page-level clears remain singular; menu-only clear available when needed |
| `Shared/Popover.tsx` | Saved-filter menus and library demonstration | Anchored nonmodal portal, viewport bounds, scroll/resize placement, outside/Escape/Back dismissal and focus restoration. Forms remain forms, not falsely labeled ARIA menus |
| `Shared/Navigation.tsx`: MainNavigation / MainNavigationItem | Application navbar and library | Named landmark, current page, native keyboard operation, visible responsive labels |
| SecondaryNavigation, same file | User Access and library | Real anchors, bottom-border active state, native modified-click support, history-backed routes |
| ContentTabs / ContentTabList, same file | User Details, Data Source tabs and library | Single roving-keyboard implementation, tab/panel IDs, arrows/Home/End, optional counts/icons; existing source IDs preserved |
| `Shared/InvestigationNavigation.tsx`: DetailNavigation / DetailButton | User/role/release investigations | Existing breadcrumb/record position/focus and global filtered navigation. Routine buttons now canonical; domain routing preserved |
| `Access/Shared.tsx`: Filter / Pagination / QueryState | Access, review, comparison and library | Filter aliases FormField; pagination uses compact Button; shared LoadingState and existing error semantics. Server pagination unchanged |
| `Shared/Presentation.tsx`: Card / Toolbar / PageHeader | Comparison and library | Lightweight layout wrappers with explicit children/classes, no data responsibilities |
| DataTable, same file | Comparison and library; existing tables share CSS | Caption, focusable bounded overflow; columns remain caller-owned rather than a complex table framework |
| StatusBadge / EmptyState / LoadingState, same file | Domain status wrappers, query state and library | Generic presentation only; labels and source interpretation remain in domain components |
| EvidenceDisclosure, same file | Comparison and library | Discoverable information summary, keyboard-operable disclosure; evidence limitations retained |
| `Shared/AccountStatus.tsx` | User Directory/Details, comparison, review, library | Existing SAP validity/lock/AD classifications and friendly type labels unchanged; generic badge rendering reused |
| EvidenceBadge / LockStatus / AccountEvidence / AssignmentStatus in InvestigationNavigation | Access investigation and library | Existing account-versus-assignment semantics retained; generic badge reused |
| `Shared/StatusPill.tsx` / SourceBadge / Notification | Feature controls, source status, app feedback and library | Preserve semantic enabled/source/loading/error states and dismissal behavior; use shared tokens |
| `Shared/RoleIdentifier.tsx` | Roles/users/T-codes and library | Exact code, optional open action, clipboard feedback overlay. Larger copy hit target preserves text-only overlay and two-second timing |
| `Shared/RoleMetadata.tsx` | Role cards/details/assignments | Preserve registry-derived descriptions and classification rules; no generic name inference |
| `Shared/EmployeeInformation.tsx`, Access/EmployeeEnrichment and UserProfile | User Details | Specialized enrichment/manager/status presentation retained; no second profile model |
| `Modules/ModuleRegistry.tsx`, ModuleIcon, CatalogIcon, IconCatalog | All module/role views, Settings icon picker | Existing Lucide catalog, module preferences and theme-aware classification colors retained; no duplicate icon library |
| Settings Controls/ColorControl, ImportSection, ImportPresets, SourceStatus | Settings data/branding workflows | Specialized mapping/preset/color contracts retained; common dimensions and tab behavior consolidated |
| RoleList/RoleCard, RoleDetail panels and RoleComparison subcomponents | Existing role investigations | Specialized selection/overlap/hierarchy presentation retained. No duplicate Role Comparison or generalized data model |
| Settings navigation/sidebar, diagnostics and health source cards | Existing Settings workspace | Existing section IDs preserved, Component Library ordered immediately before About. Detailed source/diagnostic responsibilities retained |

Native confirmation dialogs remain the existing deletion safeguard. There is no separate custom ConfirmationDialog or new toast service to showcase. Do not create a second abstraction simply to populate the library.

## APIs and examples

```tsx
<Button variant="primary" loading={saving} onClick={save}>Save</Button>
<IconButton label="Open user" variant="ghost" onClick={open}><ArrowUpRight /></IconButton>
<FormField label="Search users" description="Username, name or email">
  <SearchInput value={search} onChange={event => setSearch(event.target.value)} />
</FormField>
<ContentTabs label="Role sections" value={scope} items={items} onChange={setScope}>
  <RoleTable />
</ContentTabs>
<Popover label="Investigation options" trigger="Options">
  <Button onClick={apply}>Apply</Button>
</Popover>
```

`DataTable` accepts caption, optional regionLabel/tableClassName and native table children. `SavedFilters` retains view/state/apply/clear and supports optional `storage` and `showClear`. Production callers use the default local API; only isolated previews inject storage. The five production views and backend schemas are unchanged.

## Adding a component

Search Shared, Access/Shared and Settings/Controls first. Add a variant when behavior is the same. Keep domain calculations outside presentation. Choose tokens instead of copying color/radius strings; preserve native form semantics and accessible names. Add a library example only after the actual shared component exists. Test keyboard/focus, loading/disabled/invalid states and both themes. Validate real callers as well as the showcase. Do not connect previews to production data APIs or settings mutations.

See [Design system](DESIGN_SYSTEM.md), [Navigation patterns](NAVIGATION.md) and [validation report](../archive/validation/UI_CONSOLIDATION_VALIDATION.md).

## CSV lifecycle additions

`Shared/Dialog.tsx` is the canonical modal used by refresh change/error viewers and the isolated Component Library preview. It portals outside overflow boundaries, makes the app root inert, traps Tab focus, supports Escape, and restores the originating control. `Shared/RefreshReport.tsx` shares the result banner, bounded report viewer and history presentation between Data Sources and Diagnostics. `Settings/DirectoryPreview.tsx` reuses the shared fields, table, status and pagination controls. These components introduce no external service or UI dependency.

## Import and evidence refinement

`Settings/ImportControls.tsx` owns SourceFileField, MappingField and ImportPreview.
Their callers retain all selection, parsing and activation decisions. Mapping labels
retain technical accessible names where existing workflows rely on them. Previews
are bounded and explicitly separate from loaded datasets. `SourceHealthSummary`
is shared between Diagnostics and source settings. `InvestigationPatterns.tsx`
provides compact StatusCard, FilterPanel and ResultsToolbar wrappers.

Assignment dates use the shared Popover. Combobox/calendar portals register their
popover ownership so an inner selection does not dismiss its parent. Escape closes
the inner popup first; the next Escape restores focus to the outer trigger. The
Component Library uses these actual components with isolated synthetic state.
See [the current refinement report](../archive/validation/UI_REFINEMENT_PHASE1.md) for scope and validation.


Navigation containers share the internal `NavigationStrip` in
`frontend/src/components/Shared/Navigation.tsx`. Main/secondary routes retain
navigation landmarks; content tabs retain roving focus and associated panels.
Do not substitute tab semantics for a route. The Settings showcase uses these
same exported components and isolated state.

`SourceBadge` displays Loaded in success styling when a valid dataset remains
available. A failed replacement attempt is reported separately by source health;
it does not erase the distinction between available data and the last attempt.

`Combobox` accepts `openOnFocus` (default `true`). Saved Filters sets it to `false`
so programmatic popover focus does not open a second overlay over Load/Save.
Click, typing and Arrow keys still open the list; Escape closes the list before
its parent popover and restores the expected focus.

## Shared page and investigation refinements

`PageHeader` accepts an optional leading `icon` and adjacent `titleAction`, keeping
route titles, utility actions and labels in one responsive heading pattern.
`MetadataList` accepts `{label, value}` items and renders full-width semantic
key/value rows, stacking on narrow screens. SourceHealthSummary uses it without
substituting import timestamps for source-check evidence.

`SearchInput` accepts an optional `onClear`; callers retain search state and scope.
ImportPreview filters only the bounded validated response rows, reports visible
versus preview counts separately from full CSV totals, and never mutates imports.
The authenticated User Access preview includes at most 20 identity/assignment
samples; these response-only samples remain absent from persistent reports and
sanitized diagnostics. RoleMetadata accepts a leading evidence slot for the
single-role transaction count without changing source classification.

## Compact role evidence

`Shared/RoleIdentifier.tsx` is the canonical exact role identifier and copy action.
It stays on one line, with contained horizontal scrolling and Arrow Left/Right
support when focused; the title and accessible name retain the complete value.
Optional `moduleId` colors use canonical backend module evidence.
`Shared/RoleMetadata.tsx` never classifies from a description prefix: unknown single
roles stay unclassified when the source has no independent module evidence.
`Shared/TransactionCount.tsx` renders the same compact count badge in catalogue,
single-role, comparison and Component Library views. Single-role zebra backgrounds
remain invariant on hover; only the expand/collapse action has hover feedback.

Saved Filters uses the shared Popover, which measures dynamic content and applies
viewport-constrained scrolling only when needed. Adjacent Save/Clear actions use
an explicit spacing token. User Directory and Account Review use five primary
filter columns at desktop widths; smaller widths retain the existing reflow.
Release PR/PO matrices size to their contents, sharing a row where possible and
stacking at tablet widths, with independent scroll regions.

## Modal investigation and source status

The existing Dialog owns portal placement, focus isolation/restoration, Escape and
bounded body scrolling; textarea controls participate in its focus loop. Title
changes refocus the modal when switching between the change list and record details.
DirectoryMatchDetails, source technical details, ReviewFindings and ChangeRecordDetails
reuse that owner instead of large inline editors. Their private evidence remains in
authenticated application responses; it is not copied into diagnostics exports.

SourceHealthSummary is canonical for all four sources, including Employee Directory and the SoD Matrix;
SourceStatusSummary reads the shared diagnostics query to keep persisted mode, loaded
state, activation, snapshot and validation evidence aligned. Source configuration
navigation is separate from the technical details modal.

Toggle renders an interactive StatusPill directly. The pill describes the draft
Enabled/Disabled preference; pending feedback persists until Apply succeeds. Data
availability and operational status describe saved server evidence separately.
SectionHeader and the real ReviewFindings/ChangeRecordDetails previews are included
in Component Library with isolated synthetic data and no production mutations.

## Anchored layout lifecycle

`lib/observeAnchorLayout.ts` keeps Popover, Combobox and NorwegianDateInput portals
attached while open. It observes real anchor/ancestor size, surrounding content
and ancestor positioning-style changes, plus captured scroll and window resize.
Cleanup disconnects every observer/listener. No delay, remount or frame polling is
used for placement. First-open stale coordinates were reproducible when asynchronous
employee enrichment increased the profile height after the first measurement.
Observing only the popup size missed that movement; reopening happened to remeasure.
Popup coordinates are viewport-clamped and initial focus does not scroll the page.

### Assignment export actions

`Shared/ExportCSVButton.tsx` wraps the canonical outline Button and Lucide Download
icon. User Directory and Release Roles use it beside their result counts; the
Component Library renders an isolated disabled preview.
`hooks/useAssignmentCSVExport.ts` shares authenticated streaming downloads, strict
UTF-8 decoding, a 32 MiB limit, generation/day guards and filter-change cancellation.
It delegates filtering to the existing backend selection functions, never a
second frontend interpretation. The existing native `save_user_access_csv` bridge
accepts the exact new semicolon header only for its two assignment-export filename
prefixes; capability, size and destination protections remain intact.

Component Library uses eight category tabs (actions, navigation, forms, filters, feedback, dialogs, data display and SAP controls); All components is an explicit expanded QA view. Previews use real shared controls and isolated in-memory state. ModuleEditor uses the shared Dialog with a local draft and explicit parent-draft Apply. SourceDetailsDialog groups status, storage and diagnostics, with complete copyable paths. SourceHealthSummary supports a compact dashboard variant from the same diagnostic evidence. Anchored portals stay hidden until measured; event-driven anchor observation continues tracking subsequent layout changes.

`Settings/DesktopOptions.tsx` reuses Toggle/Checkbox and the parent settings draft.
It renders only after a Windows native capability response; hosted/Linux/browser
clients do not expose Windows options. No new reusable control or demo-only analogue
was introduced. Sign-in startup is disabled for source-mode activation; an existing
preference can still be switched off. Tray Settings navigation queues until App's
native-readiness handshake and preserves the current route/history underneath.

### Refined controls and search

`Shared/Select` supplies the default canonical control class; native menus retain
platform rendering. Use `FormField` for explicit label association. Navigation
strips reserve transparent bottom borders for stable hover and active geometry; focus remains an
outline. `Access/Shared.Pagination` and employee pagination use equal compact
Previous/Next controls with directional icons.

Module settings use the existing `ModuleEditor` dialog with responsive tiles and
All/Enabled/Disabled filtering, not a second editor. Appearance/logo controls retain
the existing managed-file and contrast validation with a full-width draft preview.
Employee source diagnostics expose a compact summary and expandable full details.
The Component Library uses these same navigation/select primitives automatically.

Text search lives in `backend/search_matching.py` and
`frontend/src/lib/searchMatching.ts`. Both match literal chunks, never execute user
regular expressions. Transaction pattern expansion lives in the existing
`transaction_filters.py`; internal identity and assignment joins remain unchanged.

## Current refinement behavior

`NavigationStrip` remains the canonical geometry for secondary navigation and
content tabs, using semantic Tailwind utilities. The Component Library starts with
All components and contains wide tables locally. `RoleIdentifier` keeps exact text
and copy behavior with a neutral border independent of SAP area color.

Role Comparison retains high-level similarity metrics and uses responsive
shared-by-all and exclusive-per-composite single-role tiles. Expanded shared tiles
span the available grid width. Exact/wildcard transaction filtering uses the same
matcher as Role Details and retains original totals and parent mapping provenance.
The duplicate detailed pair-overlap section is removed. User Details exposes View role details without duplicating
catalogue-matching disclosures. Release Roles requests the complete filtered list
from one snapshot; assignment-detail and other table pagination remain unchanged.

Appearance & Branding previews draft organization, system, logo and palette at full
content width without saving them. Native Windows Desktop preferences are under
Runtime & Scheduling (with the scheduled refresh) and still use the parent settings draft/Apply/Cancel lifecycle.

## SoD matrix and side panel

`MatrixGrid` (`Shared/MatrixGrid.tsx`) renders a sticky-header matrix with a fixed first
column. Cells are real buttons in a roving-focus grid: arrow keys move between detected cells
(to the nearest one in sparse rows), Home/End jump along a row, Enter opens. Status is shown
by icon, text and tone together, never color alone. Above 48 columns only a window of columns
renders, with scrolling and keyboard focus kept consistent. The scroll region is its own
containing block so wide matrices never widen the page.

`SidePanel` (`Shared/SidePanel.tsx`) is a docked, non-modal detail panel: the list or matrix
behind it keeps its scroll position and filters, Escape closes it and focus returns to the
trigger, and it is full width below 800 px. Use `Dialog` for modal confirmations. Both
components have isolated Component Library previews and are used by the SoD views.

## SoD filter layout (Phase 2)

- `Shared/FilterLayout`: `FilterLayout` (collapsible left sidebar from 1024 px, overlay drawer below; sidebar open state is a per-viewer convenience in `localStorage`, filter values stay in view history), `FilterSection`, `PageToolbar`, `SortControl`.
- `Sod/SodShared.SodFilters` replaces the old `FilterBar`: each page passes only the filter fields it can act on. Saved Filters sit at the top of the sidebar; applying one clears values for fields the page does not show so hidden filters never narrow results. Search, sort, view options, CSV export and Reset share one toolbar.
- `Shared/IdPill`: compact risk/activity identifier pill. The identifier text always carries the meaning; the optional `color` (validated `#rrggbb`) only tints it.
