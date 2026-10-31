# Validation tracker

A repository-maintained list of what SAP Lens should do on every page, and what a reviewer found when checking it. It is plain CSV, edited by hand or through an Excel workbook generated from it. There is no service, backend or extra dependency.

- Source of truth: [`validation-items.csv`](validation-items.csv) (one row per item, 18 functional areas).
- Tooling: `python scripts/validation_tracker.py` (`check`, `summary`, `export`, `merge`).
- Every item starts as **Not reviewed**. Nothing is approved until a person validates it and records the evidence. Automated tests are listed as implementation references; they do not approve an item.

## Columns

| Column | Meaning |
| --- | --- |
| ID | Stable identifier such as `SODM-003`. Never reuse or renumber an ID; new items take the next number of their area prefix. |
| Area, Page, Component | Where the behavior lives (area is one of the 18 fixed areas). |
| Expected behavior | What a reviewer should observe. Written as a testable statement. |
| Status | The **manual acceptance** status: `Not reviewed`, `Approved`, `Needs improvement`, `Bug`, `Blocked`, `Not applicable`. Only a person validating the behavior changes it. |
| Priority | `Not set`, `Critical`, `High`, `Medium`, `Low`. |
| Classification | `Unclassified`, `Current defect` (behavior is wrong today), `Improvement opportunity` (works, could be better), `Not an issue`. |
| Notes and evidence | What was seen, how, in which theme and viewport, with screenshots or test names. Required for every status except Not reviewed and Not applicable. |
| Implementation reference | Guide and code files for the behavior, then fix commits or pull requests once an item has one. |
| Implementation status | What the code does today: `Not assessed` (default), `Not implemented`, `Partially implemented`, `Implemented`. Implementing an item never changes its Status. |
| Test evidence | The specs and tests that exercise the behavior (required for `Implemented`): the automated validation. Passing tests are evidence of implementation, not acceptance. |
| Manual validation required | What a person must look at or try before the item can be Approved (visual and subjective checks are never approved by a test run). |
| Remaining issues | Known gaps, limits and anything not covered by the automated validation. |
| Retest status | `Not started`, `Pending retest`, `Retest passed`, `Retest failed`. |

Consistency rules (enforced by `check`): an Implemented item names its test evidence; an item that is not fully implemented cannot be Approved; a Bug is a Current defect; a Current defect is a Bug, Needs improvement or Blocked; Needs improvement is an improvement opportunity or a current defect; Approved, Needs improvement, Bug and Blocked need notes; a Not reviewed item has no retest; an item whose retest failed cannot be Approved. Defects and improvement opportunities are kept apart so the backlog can be read as two lists (the workbook has a sheet for each).

## Workflow

1. **Validate an area.** Run the guide steps for the area (the Implementation reference names its guide), in light and dark, at 375, 800, 1280 and 1600 px, with synthetic data. Work through its rows and set Status for each: `Approved` only with evidence in Notes; `Not applicable` when the behavior does not exist in the current configuration.
2. **Record an issue.** Set Status to `Bug` (behavior is wrong; Classification `Current defect`) or `Needs improvement` (works but could be better; Classification `Improvement opportunity`). Write what happened, where, and how to reproduce it in Notes. If the problem is a new behavior not covered by a row, add a row with the next ID of the area's prefix (the letters before the number in the existing IDs of that area).
3. **Prioritize improvements.** Set Priority: `Critical` (data integrity, security or a blocked workflow), `High` (wrong result or unusable on a supported screen), `Medium` (confusing or inconsistent), `Low` (polish). Review `python scripts/validation_tracker.py summary` or the Defects and Improvements sheets to order the work. Defects come before improvements of the same priority.
4. **Link a fix to an issue.** Add the commit or pull request to Implementation reference (`fix: abc1234`) and set Retest status to `Pending retest`. Keep the original notes; append what changed.
5. **Retest.** Repeat the original steps. If the behavior is now right, set Retest status to `Retest passed` and add the new evidence; if not, `Retest failed` and describe the difference (a failed retest keeps the item a Bug or Needs improvement).
6. **Mark an item approved.** Set Status to `Approved` with evidence in Notes (who, when, theme and viewport, data used) and Retest status `Retest passed` where there was a fix. Approval is a person's decision; do not set it from a green test run alone.

Run `python scripts/validation_tracker.py check` before committing a change to the CSV; the repository tests run the same check.

## Excel workbook

```
python scripts/validation_tracker.py export                    # writes build/validation-tracker.xlsx (not committed)
python scripts/validation_tracker.py export --output review.xlsx
python scripts/validation_tracker.py merge review.xlsx         # copy decisions edited in the workbook back into the CSV
```

The workbook has sheets Items (drop-down lists for Status, Priority, Classification and Retest status, filters and a frozen header), Summary (counts per area and status), Defects and Improvements. `export` is reproducible. `merge` updates only Status, Priority, Classification, Notes and evidence, Implementation reference and Retest status of rows that already exist (matched by ID), rejects values that are not allowed, refuses to write when the merged tracker would be inconsistent, and never removes a row, so regenerating the workbook and merging it back cannot lose a decision. Edit definitions (Area, Page, Component, Expected behavior) and add rows in the CSV. The workbook is a working copy: commit the CSV, not the `.xlsx`.

## Keeping it useful

- Add a row when a feature adds a page, control or rule, in the same change, with its guide and test as references.
- Reset an item to `Not reviewed` (and Retest status `Not started`) when its behavior changes materially, keeping the old evidence in Notes.
- Use the tracker for regression planning: every `Approved` item names the specs that protect it, and every `Bug` names what is missing.
- Platform checks that Linux CI cannot run (Windows desktop, service, installer) stay `Blocked` with the reason until someone runs them on the target platform.
