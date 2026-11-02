# Validation tracker

A repository-maintained checklist of what SAP Lens should do on every page, and what a reviewer found when checking it. The source of truth is plain CSV; an
Excel workbook generated from it is provided for manual review. Nothing is approved until a person validates it and records the evidence: automated test
results are listed separately and never approve an item.

- Source of truth: [`validation-items.csv`](validation-items.csv): one row per item in 22 functional areas.
- Workbook for reviewers: [`validation-tracker.xlsx`](validation-tracker.xlsx), generated from the CSV (a test fails if it is stale).
- CI/CD workflows: [workflow validation matrix](WORKFLOW_MATRIX.md), with GitHub run evidence per scenario.
- Tooling: `python scripts/validation_tracker.py` with `check`, `summary`, `export`, `merge` and `migrate`.

## Functional areas

Dashboard, Role Lookup, Access Package, User Directory, Account Review, Compare Users, Release Roles, SoD Overview, Risk Matrix, Activity Matrix, Access Explorer,
SoD Reviews (work queue and remediation), Review Periods, SoD Reports, Settings and Data Sources, SAP Modules, SoD Risk Configuration, Component Library
(shared components), Desktop and Startup, Server and Deployment, Accessibility and Responsive Design, Security and Data Integrity. An item that covers both matrices
is one record under Risk Matrix, so no record is duplicated.

## Columns

| Column | Meaning |
| --- | --- |
| ID | Stable identifier such as `SODM-003` or `R8-01`. Never reuse or renumber an ID; a new item takes the next number of its prefix. |
| Area | One of the 22 areas above. |
| Page/component | Where the behavior lives (`Page › Component`). |
| Validation criterion | What a reviewer should observe, written as a testable statement. |
| Priority | `Not set`, `Critical`, `High`, `Medium`, `Low`. |
| Status | The recorded validation result: `Not tested` (default), `Passed`, `Failed`, `Needs improvement`, `Blocked`, `Not applicable`. Recorded by a person. |
| Manual approval | `Pending` (default), `Approved`, `Rejected`, `Not applicable`. **Never set by tooling or by a passing test.** `Approved` needs Status `Passed`, a validation date and notes naming who approved. |
| Automated test evidence | The specs and tests that exercise the behavior (required for `Implemented`). Passing tests are evidence of implementation, not approval. |
| Last validated date | `YYYY-MM-DD`, set when a person validates. Required for `Passed`; empty while not tested. |
| Build/commit | The build or commit that was validated. |
| Notes | What was seen, how, in which theme and viewport, with screenshots or test names. Required for every result status. |
| Linked issue or finding | A finding or issue identifier, for example `SEC-02` from the [security review](../development/SECURITY_REVIEW_R8.md). |
| Potential future improvement | A possible improvement that is not a defect. Collected in the workbook's Future Improvements sheet. |
| Manual validation steps | What a person must look at or try before approving (visual and subjective checks are never approved by a test run). |
| Known limitations | Known gaps, limits and anything not covered by the automated validation. |
| Implementation reference | Guide and code files for the behavior, then fix commits once an item has one. |
| Implementation status | What the code does today: `Not assessed`, `Not implemented`, `Partially implemented`, `Implemented`. Implementing an item never changes its Status. |
| Classification | `Unclassified`, `Current defect`, `Improvement opportunity`, `Not an issue`. |
| Retest status | `Not started`, `Pending retest`, `Retest passed`, `Retest failed`. |

Consistency rules (enforced by `check`, which the repository tests also run): a `Not tested` item has no date, approval decision, retest or defect classification; `Passed` records its date;
`Failed` is a current defect and a current defect is `Failed`, `Needs improvement` or `Blocked`; every result status needs notes; `Approved` needs a `Passed` status, a date and notes and
cannot apply to an item that is not fully implemented or failed its retest; an `Implemented` item names existing automated evidence.

## Workflow

1. **Validate an area.** Follow the guide named in Implementation reference, in light and dark, at 375, 800, 1280 and 1600 px, with synthetic data. Record the result in Status, the date in Last validated date, the commit in Build/commit and what you saw in Notes.
2. **Record an issue.** Status `Failed` (behavior is wrong; Classification `Current defect`) or `Needs improvement` (works but could be better; Classification `Improvement opportunity`). Write what was seen, where and how to reproduce it; link a finding if one exists.
3. **Prioritize.** `Critical` (data integrity, security or a blocked workflow), `High` (wrong result or unusable on a supported screen), `Medium` (confusing or inconsistent), `Low` (polish).
4. **Link a fix.** Add the commit to Implementation reference (`fix: abc1234`) and set Retest status to `Pending retest`. Keep the original notes and append what changed.
5. **Retest.** Repeat the steps. Right now: `Retest passed` with the new evidence; not yet right: `Retest failed` with the difference.
6. **Approve.** Only a person: Status `Passed`, Manual approval `Approved`, the date, and notes naming who approved and with which theme, viewport and data.

## Excel workbook

```
python scripts/validation_tracker.py export --output docs/validation/validation-tracker.xlsx   # regenerate after editing the CSV
python scripts/validation_tracker.py export                                                    # writes build/validation-tracker.xlsx (not committed)
python scripts/validation_tracker.py merge review.xlsx                                         # copy decisions edited in the workbook back into the CSV
```

Sheets: **Summary** (items, status counts, manual approvals and completion per area, with live formulas over the Items sheet; outstanding counts), **Items** (a filterable
Excel table with a frozen header, drop-downs for Priority, Status, Manual approval, Implementation status, Classification and Retest status, and conditional formatting),
**Defects and Findings** (failed, needs-improvement, blocked, defect and finding-linked items) and **Future Improvements** (the backlog). The two list sheets are snapshots taken when the
workbook is generated. `merge` copies only the reviewer-owned columns (Priority, Status, Manual approval, Last validated date, Build/commit, Notes, Linked issue or finding, Potential future improvement,
Classification, Retest status) of items that already exist and rejects values that are not allowed; item definitions are edited in the CSV. `migrate` converts a tracker in the earlier
15-column layout (R4 to R7) to the current one without losing a field; running it on a current file does nothing.

## Keeping it useful

- Add a row when a feature adds a page, control or rule, in the same change, with its guide and test as references.
- Reset an item to `Not tested` (Manual approval `Pending`, Retest `Not started`, no date) when its behavior changes materially, keeping the old evidence in Notes.
- Use the tracker for regression planning: every `Passed` item names the specs that protect it.
- Platform checks that Linux CI cannot run (Windows desktop, service, installer, systemd) stay `Blocked` or `Not tested` with the reason until someone runs them on the target platform.
