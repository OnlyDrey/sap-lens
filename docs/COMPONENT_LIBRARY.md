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
| `Shared/FilterChip.tsx` | Transactions and assignment date filters | One removable-chip implementation, explicit removal label, existing focus restoration supplied by caller |
| `Shared/ClearFilterButton.tsx` | Investigation pages/date controls | Canonical Button + filter-x icon; neutral reset styling, explicit accessible text |
| `Shared/SavedFilters.tsx` | Users, roles, releases, review, comparison; memory-only library | Same versioned persistence/CRUD/compatibility logic, compact Popover. Existing page-level clears remain singular; menu-only clear available when needed |
| `Shared/Popover.tsx` | Saved-filter menus and library demonstration | Anchored nonmodal portal, viewport bounds, scroll/resize placement, outside/Escape/Back dismissal and focus restoration. Forms remain forms, not falsely labeled ARIA menus |
| `Shared/Navigation.tsx`: MainNavigation / MainNavigationItem | Application navbar and library | Named landmark, current page, native keyboard operation, visible responsive labels |
| SecondaryNavigation, same file | User Access and library | Real anchors, underline active state, native modified-click support, history-backed routes |
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
| Settings navigation/sidebar, diagnostics and health source cards | Existing Settings workspace | Existing section IDs preserved, Component Library appended. Detailed source/diagnostic responsibilities retained |

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

See [Design system](DESIGN_SYSTEM.md), [Navigation patterns](NAVIGATION_PATTERNS.md) and [validation report](UI_CONSOLIDATION_VALIDATION.md).

## CSV lifecycle additions

`Shared/Dialog.tsx` is the canonical modal used by refresh change/error viewers and the isolated Component Library preview. It portals outside overflow boundaries, makes the app root inert, traps Tab focus, supports Escape, and restores the originating control. `Shared/RefreshReport.tsx` shares the result banner, bounded report viewer and history presentation between Data Sources and Diagnostics. `Settings/DirectoryPreview.tsx` reuses the shared fields, table, status and pagination controls. These components introduce no external service or UI dependency.
