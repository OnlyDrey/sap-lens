# SAP Lens design system

## Principles and scope

Build new screens from existing shared components. Navigation changes location, tabs change associated content, filters constrain evidence, and buttons perform operations. Keep SAP identity/account/directory evidence distinct. Preserve exact technical identifiers, local-only handling and readable light/dark themes.

This consolidates the existing React/TypeScript/Vite/Tailwind application rather than introducing another framework. Color customization, saved theme presets, module classifications, source parsing, review decisions and comparison evidence sets are unchanged. The integrated reference is **Settings → APPLICATION → Component Library**.

## Token ownership

`frontend/src/styles/tokens.css` owns default palette values and shared dimensions. `frontend/src/lib/theme.ts` remains authoritative for validated user palettes, derived colors, readable foregrounds and System appearance. Its existing CSS property contract is preserved; aliases resolve live values rather than copying a preset. `styles/components.css` owns canonical component styles and compatibility classes. `index.css` retains domain layouts, calendar/combobox placement, module/editor presentation and responsive source arrangements.

| Purpose | Tokens |
| --- | --- |
| App, surface, elevated background | `--bg`, `--surface`, `--surface2`; aliases `--color-background`, `--color-surface`, `--color-elevated` |
| Text, secondary, muted, borders | `--text`, `--text2`, `--muted`, `--border`; corresponding `--color-*` aliases |
| Branding and action | `--primary` / `--on-primary` for navbar; accessible action `--accent2` / `--on-accent2`; `--color-action` alias |
| Hover/focus | `--hover`, `--focus`; `--color-hover`, `--color-focus` aliases |
| Semantic states | `--success`, `--warning`, `--error`, `--info`, `--error-bg`, `--info-bg`; danger alias `--color-danger` |
| Spacing | `--space-1/2/3/4/5/6/8`: 4/8/12/16/20/24/32 px |
| Typography | `--font-ui`, `--font-code`; title 20 px, section 16 px, body 14 px, label/table header 13 px, metadata 12 px |
| Radius | Control 8 px, card 12 px, popover 10 px, badge 4 px |
| Controls | `--control-height`: 42 px; compact: 34 px; icon default: 42 px square; copy target: 32 px, 42 px on coarse pointers |
| Floating surfaces | `--elevation`; popover borders/background use surface/text tokens |

Tailwind's font families reference the same CSS font tokens. Existing scale utilities remain useful for layout; new components should prefer the shared dimensions. Specialty choices such as icon-picker tiles, matrices and long evidence tables have deliberate domain-specific geometry.

SAP module colors remain independent of general theme colors. Do not substitute a success/warning color for a classification color, or interpret a module color as risk.

## Actions and interaction states

Canonical `Button` supports primary, secondary, outline, ghost and destructive variants; default, compact and icon sizes; loading and disabled states. Loading disables the operation and exposes `aria-busy`. Every icon-only action uses `IconButton` with a required accessible label. Tooltips also work on keyboard focus and dismiss on Escape; they are supplemental labels, not the only accessible name.

Primary actions use the derived accessible action foreground. Secondary/outline are routine operations, ghost reduces chrome, and destructive is reserved for deletion. Clearing filters is neutral. Hover uses theme tokens; active action feedback is a small press translation; selection uses explicit bottom-border/pressed state rather than relying solely on color. Focus-visible is a two-pixel ring with spacing. Reduced-motion preferences remain honored.

`settings-secondary-button`, `settings-control` and `settings-icon-button` are compatibility aliases in the canonical stylesheet, not independent designs. Remaining Settings actions use the shared default size; compact buttons explicitly override that default. Do not copy long utility strings into new screens.

## Forms, tables and feedback

`FormField` associates the actual control ID with its label and keeps help/error descriptions out of the accessible name. `Input`, `SearchInput`, `Select` and `Combobox` share dimensions. Select owns its chevron; callers must not add another. Searchable controls use the existing portal combobox, not native datalists. Multi-value transaction entry remains the existing `TransactionFilter` with shared chips and operator buttons; no redundant generic MultiSelect was introduced.

Date entry remains `NorwegianDateInput`, with Norwegian labels, Monday-first floating calendar, keyboard navigation and DD.MM.YYYY entry. ISO date-only comparison and SAP maximum-date semantics remain unchanged.

`DataTable` provides a focusable overflow region, caption and shared table styling; specialized existing tables retain their domain JSX and inherit the same header, spacing, hover and row-divider rules. Role identifiers remain single-line, copyable and horizontally scrollable within their own control. Horizontal scrolling is confined to the table region, never required for the whole page.

`StatusBadge` owns generic tone presentation. `AccountStatus`, `AssignmentStatus`, `StatusPill` and `SourceBadge` keep their domain-specific labels and rules. Lock indicators preserve their established neutral unlocked/unknown and red locked appearance. AD status is not SAP validity. Loading, empty, notification and evidence-disclosure components use semantic text and icons.

## Choosing the right summary component

| Need | Use |
| --- | --- |
| One prominent figure to scan or drill into | `Kpi` (a few per view, never a wall of tiles) |
| Secondary metrics and operational facts | `InfoList` and `InfoRow`: plain rows, a full-row button when they filter or navigate |
| A distribution or proportion backed by data | A chart with readable labels and tooltips; no invented trends. Secondary explanations go in an `InfoTip` popover; neutral parts are gray, never the accent color; share-based health uses the central `lib/health.ts` thresholds with semantic tokens and always shows the number |
| A progress bar (`StackedBar`, `InfoRow` progress) | Always visible: the track has a border and a neutral fill so 0% reads as an empty bar; segments carry semantic tones and the percentage is also shown as text |
| Detailed, comparable records | A table (zebra, hover and selected states) |
| Compact status or classification | A badge or pill |
| An exact technical identifier | A codeblock (`RoleIdentifier`): the complete name on one line, never wrapped, scrolled, truncated or ellipsized; the copy control stays beside it and copies the exact value. In a narrow layout the font scales down (not below 9 px) and layouts such as the role card grid adapt their column count; a name that still does not fit stays whole and its surrounding region, never the codeblock, scrolls |

Identifiers are never given soft-wrap opportunities. Module icons carry no hover ring; only real controls get hover and focus treatments. Expand and collapse controls use one glyph: right when collapsed, down when expanded (`DisclosureChevron`, and the same control for native `details`), with the 34 px compact hit area shared with icon buttons.

## Disclosure and selection states

Every `details/summary` uses one compact chevron control (24 px box, its own hover background, rotates when open); the summary text has no hover fill. Selected rows and active tiles use a subtle full border or primary tint, so selection never shifts layout, and zebra rows, hover and selection stay distinguishable. The multi-select toolbar shows Select all, Clear and Close as three bordered buttons.

## Capitalization and terminology

Product names stay in Title Case: main navigation, page and section titles, SoD workspace views and the decision names (Activity Review, Role Assignment Review, Risk Acceptance). Table headers, buttons, field labels, filter labels, helper text and chips use sentence case. Official SAP terms keep their SAP spelling, for example **SAP User Group**, **Release Group**, **Release Strategy**, T-code and Risk ID. Use the same label for the same concept on every page.

## Responsive rules

Desktop navbar utilities are compact icons on one row where space permits. At narrower widths, primary navigation gets its own row with visible destination labels. Utility accessible names remain available to touch assistive technology. User panels become one column; comparison filters go from five to three/two/one; compact summary counts wrap without becoming large KPI cards. Existing settings-sidebar behavior and source/table breakpoints are retained.

Prefer shared responsive classes before adding another page-specific breakpoint. Validate labels, chevrons, focus rings, floating panels and table scrolling at 375, 800, 1280 and 1600 px in both themes.

See [Component Library](COMPONENTS.md), [Navigation patterns](NAVIGATION.md) and [validation report](../archive/validation/UI_CONSOLIDATION_VALIDATION.md).

## Refresh evidence surfaces

Refresh banners use semantic success/error backgrounds and a neutral unchanged state. Error styling describes failed operations, not intentionally disabled modules. Modal surfaces use the same elevation, surface, border, spacing and radius tokens as anchored popovers. Source cards keep technical information expandable within the relevant source; record-level evidence stays inside private report dialogs.


## Clean interaction states

Shared controls use background changes, borders and crisp two-pixel focus outlines.
Blurred elevation and colored glow are removed in both themes; autofill masking is
an inset fill, not a focus effect. Popovers remain portal-positioned with opaque
surfaces and visible borders. Navigation uses a shared strip implementation while
preserving distinct link and tab semantics. Secondary navigation has a subtle
bottom-border hover state rather than a large background treatment.

Page titles use the shared icon-led header. Saved Filter Save/Clear actions share
an equal-width two-column row. Source metadata uses full-width facts rather than
nested two-column cards. Comparison's B-only category uses `--comparison-b`, an alias of the theme's
error/red color; shared and A-only reuse success/information. Category colors do
not imply a security finding. Single-role
zebra backgrounds cover the whole contiguous row with outer-list rounding only;
hover leaves those surfaces unchanged. Identifiers remain exact, single-line and
copyable, with contained horizontal scrolling instead of arbitrary wrapping. Focus
remains a visible outline.

Dialogs share --dialog-backdrop with stronger theme-aware dimming and no blur. Spinners share --spinner-duration (1.4 seconds); reduced-motion mode removes their rotation without delaying operations. Navigation reserves bottom-border hover/active indicators; a separate focus-visible outline remains for keyboard users. Structural table separators remain.

## Tailwind-first styling contract

Tailwind 3.4 is the primary choice for new and migrated presentation. The runtime
pipeline remains configuration → CSS variables → semantic Tailwind utilities →
shared React components. `canvas`, `surface`, `elevated`, `content`, `secondary`,
`muted`, `line`, `action`, `hover` and `focus` map to the existing theme variables;
`rounded-control`, `rounded-card` and `min-h-control` map to shared dimensions.
These values update with runtime themes and custom branding.

Order utilities as layout, size, spacing, typography, colors, interaction and
responsive variants. Prefer standard spacing scales. Shared component contracts,
complex evidence tables, browser-specific rules and measured portal positioning
remain legitimate CSS. Validated runtime colors and isolated draft theme tokens
remain legitimate inline styles. Remove migrated selectors rather than stacking
new overrides on top of them; no new styling dependency is required.

Secondary navigation and content tabs reserve a transparent bottom border, coloring
it with the primary action color on selection and contrasting text color on hover
without changing geometry. Focus uses a separate visible
outline. Technical identifiers always retain a neutral code border; module colors
belong to module metadata, not identifier status. Comparison selection uses a full
outline rather than a bottom-only shadow.
