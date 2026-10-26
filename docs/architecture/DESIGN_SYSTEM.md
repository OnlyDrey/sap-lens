# SAP Lens design system

## Principles and scope

Build new screens from existing shared components. Navigation changes location, tabs change associated content, filters constrain evidence, and buttons perform operations. Keep SAP identity/account/directory evidence distinct. Preserve exact technical identifiers, local-only handling and readable light/dark themes.

This consolidates the existing React/TypeScript/Vite/Tailwind application rather than introducing another framework. Color customization, saved theme presets, module classifications, source parsing, review decisions and comparison calculations are unchanged. The integrated reference is **Settings → APPLICATION → Component Library**.

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

Primary actions use the derived accessible action foreground. Secondary/outline are routine operations, ghost reduces chrome, and destructive is reserved for deletion. Clearing filters is neutral. Hover uses theme tokens; active action feedback is a small press translation; selection uses explicit underline/pressed state rather than relying solely on color. Focus-visible is a two-pixel ring with spacing. Reduced-motion preferences remain honored.

`settings-secondary-button`, `settings-control` and `settings-icon-button` are compatibility aliases in the canonical stylesheet, not independent designs. Remaining Settings actions use the shared default size; compact buttons explicitly override that default. Do not copy long utility strings into new screens.

## Forms, tables and feedback

`FormField` associates the actual control ID with its label and keeps help/error descriptions out of the accessible name. `Input`, `SearchInput`, `Select` and `Combobox` share dimensions. Select owns its chevron; callers must not add another. Searchable controls use the existing portal combobox, not native datalists. Multi-value transaction entry remains the existing `TransactionFilter` with shared chips and operator buttons; no redundant generic MultiSelect was introduced.

Date entry remains `NorwegianDateInput`, with Norwegian labels, Monday-first floating calendar, keyboard navigation and DD.MM.YYYY entry. ISO date-only comparison and SAP maximum-date semantics remain unchanged.

`DataTable` provides a focusable overflow region, caption and shared table styling; specialized existing tables retain their domain JSX and inherit the same header, spacing, hover and row-divider rules. Long identifiers wrap and remain copyable. Horizontal scrolling is confined to the table region, never required for the whole page.

`StatusBadge` owns generic tone presentation. `AccountStatus`, `AssignmentStatus`, `StatusPill` and `SourceBadge` keep their domain-specific labels and rules. Lock indicators preserve their established neutral unlocked/unknown and red locked appearance. AD status is not SAP validity. Loading, empty, notification and evidence-disclosure components use semantic text and icons.

## Responsive rules

Desktop navbar utilities are compact icons on one row where space permits. At narrower widths, primary navigation gets its own row with visible destination labels. Utility accessible names remain available to touch assistive technology. User panels become one column; comparison filters go from five to three/two/one; compact summary counts wrap without becoming large KPI cards. Existing settings-sidebar behavior and source/table breakpoints are retained.

Prefer shared responsive classes before adding another page-specific breakpoint. Validate labels, chevrons, focus rings, floating panels and table scrolling at 375, 800 and 1280 px in both themes.

See [Component Library](COMPONENTS.md), [Navigation patterns](NAVIGATION.md) and [validation report](../archive/validation/UI_CONSOLIDATION_VALIDATION.md).

## Refresh evidence surfaces

Refresh banners use semantic success/error backgrounds and a neutral unchanged state. Error styling describes failed operations, not intentionally disabled modules. Modal surfaces use the same elevation, surface, border, spacing and radius tokens as anchored popovers. Source cards keep technical information expandable within the relevant source; record-level evidence stays inside private report dialogs.


## Clean interaction states

Shared controls use background changes, borders and crisp two-pixel focus outlines.
Blurred elevation and colored glow are removed in both themes; autofill masking is
an inset fill, not a focus effect. Popovers remain portal-positioned with opaque
surfaces and visible borders. Navigation uses a shared strip implementation while
preserving distinct link and tab semantics. Secondary navigation has a subtle
underline hover state rather than a large background treatment.

Page titles use the shared icon-led header. Saved Filter Save/Clear actions share
an equal-width two-column row. Source metadata uses full-width facts rather than
nested two-column cards. Comparison's B-only category has a theme-specific
`--comparison-b` token; shared and A-only reuse success/information. Single-role
zebra backgrounds cover the whole contiguous row with outer-list rounding only;
hover reverses the two surface tokens. Identifiers remain exact and copyable,
wrapping or stacking without page overflow. Focus remains a visible outline.
