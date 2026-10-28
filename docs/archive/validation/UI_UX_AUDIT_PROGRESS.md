# UI/UX quality audit: progress and recovery record

Dated working record for the seven-phase UI/UX audit (28 October 2026). A new
session resumes from this file and `git log origin/work`; do not repeat completed
phases. Results apply to the recorded commits and the Linux build environment only.

## Status

| Field | Value |
|---|---|
| Completed phases | 1 Settings navigation, 2 Role card actions, 3 Shared components, 4 Screen audit, 5 Accessibility, 6 Responsive and theme validation, 7 Component Library and regression tests |
| Current phase | Full Validation (after Phase 7) |
| Remaining | Complete backend and browser suites, types, build, static and security checks, representative visual QA, final report |
| Last verified pushed commit | Phase 5: `441e65f`; Phase 6 and 7 commits are in `git log origin/work` |
| Validation | Fast Validation per phase passed locally; Full Validation pending |
| Known blockers | None |
| Next executable action | Run Full Validation per AGENTS.md; fix any failure, retest only the affected checks, push |

## Fixed so far

- **Settings navigation:** selected item is one filled rounded surface (no underline); content tabs inside Settings keep a square indicator (`.settings-workspace button` no longer rounds tabs); section descriptions added for SoD Risk Configuration and Runtime & Scheduling.
- **Role cards:** Compare (Scale) then Add to access package (Plus, rightmost); labels, titles and `aria-pressed` carry the state; "cart" wording replaced by "access package".
- **Shared components:** 24 px minimum targets for SoD tile, matrix row and evidence toggles; identifier `code` is not a tab stop; Review Periods empty state; SoD page icon size.
- **Accessibility:** focus is revealed inside horizontally scrolling strips and tables (`lib/focusVisibility.ts`, `scroll-padding`), skip link ring no longer clipped, selected Settings item text meets 4.5:1 in both themes.

- **Responsive (Phase 6):** 16 theme and width combinations (375, 800, 1280, 1600 px, light and dark) over the main screens, SoD views and all Settings sections show no page overflow or off-screen controls. Settings Cancel/Apply no longer split across two rows at 375 px. Reported overlaps were closed `<details>` content and combobox toggles, not defects.
- **Component Library (Phase 7):** production `RoleCard` and the Settings navigation item are previewed.

## Regression tests added

`frontend/tests/ui-polish-actions.spec.ts`: role card action order and icon semantics, Settings active state and keyboard, border scan (rounded underline and double border) over main screens and every Settings section in both themes, identifier and target-size checks, focus reveal in strips, skip link, access package panel focus, contrast.

## Not tested natively

Windows WebView2 desktop, Windows Service, installer, UNC and Linux systemd are outside this audit; see the deployment matrix.
