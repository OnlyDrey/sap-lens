# Navigation patterns

## Four distinct interactions

| Pattern | Purpose | SAP Lens implementation |
| --- | --- | --- |
| Main navigation | Major application destinations | Dashboard, Role Lookup, User Access, Release Roles; Settings is a compact utility opening the existing workspace |
| Secondary navigation | Related pages within a major area | User directory, Account Review, Compare users; real anchor destinations and underline current-page indicator |
| Content tabs | Associated content in one investigation | User Details role sections and Settings import sources; roving focus and an associated tabpanel |
| Actions / filter controls | Perform an operation or constrain results | Canonical buttons, neutral Clear filters, pressed button groups for Table/Matrix and AND/OR |

Do not make secondary routes look like primary operation buttons. Do not label a form-containing popover as an ARIA menu. Do not force tabs onto a page without associated content.

## Routing contract

The existing `useViewHistory` hash/history architecture is extended, not replaced:

- `#/dashboard`
- `#/role-lookup`
- `#/user-access` (directory)
- `#/user-access/account-review`
- `#/user-access/compare`
- `#/release-roles`

Legacy primary paths continue to work. Secondary links preserve hash query parameters. Normal primary clicks use application history; modified secondary clicks keep native anchor behavior. Direct secondary URLs and page reload restore the correct view. Back/Forward use the same state reader and bootstrap boundary; startup screens do not reappear as investigation history.

Existing identities, record navigation, role comparison, selected transaction codes, source settings and release drilldowns retain their current state contracts. Comparison controls and Account Review search/sort/review controls are bounded history metadata; result datasets and credentials are never stored there. Saved-filter definitions remain in their existing private store rather than URL query strings.

## Content tabs

`ContentTabs` owns a tablist and selected panel. `ContentTabList` is the same keyboard implementation for existing independently rendered panels, such as the three Data Source forms. Arrow Left/Right, Home and End select/focus a tab; Tab proceeds into the content. Import-source tab/panel IDs remain stable for recovery and direct source actions.

Role sections retain the actual existing ZC/ZO investigation scopes; these naming conventions are not presented as universal SAP standards. Changing tabs does not change parsing, transaction resolution or date filters' scope.

## Compact navbar and metadata

Theme, Settings and Refresh are icon actions with independent accessible names, focus tooltips and shared hit targets. Refresh retains application-scoped loading, request suppression and atomic publication; completion/error feedback is explicit. Destination text remains visible at narrow widths on a wrapped navigation row.

The navbar no longer displays the full updated timestamp. Dashboard and Data Sources already show the backend's actual successful publication/import metadata. A redundant frontend `new Date()` refresh clock was removed rather than relabeled as source time.

## Investigation actions

Keep exact identifier copy, manager-to-SAP-user navigation, record Previous/Next and browser Back behavior. Popovers close on outside click, Escape and history traversal, restoring trigger focus for keyboard dismissal. Tables may scroll within their named focusable region; controls and page-level navigation must remain within the viewport.

See [Component Library](COMPONENT_LIBRARY.md) for APIs and [UI validation](UI_CONSOLIDATION_VALIDATION.md) for actual checks and platform limits.
