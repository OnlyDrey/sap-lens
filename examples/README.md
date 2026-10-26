# Synthetic investigation examples

These three linked CSVs are generated entirely from invented identifiers and
reserved `example.org` email addresses. They are not anonymized company exports.
Do not infer production naming rules or authorization from these examples.
Nothing is imported automatically or included in deployment packages.

| Source | File | Encoding / delimiter | Volume |
| --- | --- | --- | --- |
| Role Catalogue | [role-catalogue.example.csv](role-catalogue.example.csv) | UTF-8 BOM / comma | 371 rows, 130 catalogue identifiers |
| User–Role Mapping | [user-access.example.csv](user-access.example.csv) | UTF-8 BOM / comma | 273 rows, 70 users |
| Employee Directory | [employee-directory.example.csv](employee-directory.example.csv) | UTF-8 BOM / semicolon | 75 directory records |

## Try an investigation

Use an isolated test configuration, not an existing production installation.
Under Settings → Data Sources, select and validate each corresponding CSV, inspect
its preview and explicitly confirm import. Enable User–Role Mapping and Employee
Directory under Features. Static mode retains validated snapshots independently of
the original file; Dynamic mode refreshes the configured server-visible path.
See [CSV lifecycle](../docs/data/IMPORT_AND_REFRESH.md) and
[Employee Directory](../docs/data/EMPLOYEE_DIRECTORY.md) for the actual import controls.

1. Compare `SYN_U001` and `SYN_U002`. They share two business roles, have different
   additional roles, and User 1 has two distinct validity intervals for role 001.
2. Investigate the role-derived transactions, then open Release Roles. Both PR
   and PO examples use invented groups Q7/Q8 and strategies R2/R3. Matrix cells
   count distinct users, not assignment rows.
3. Inspect Data Health and Account Review. Intentional cases include expired,
   future and unknown dates, locked and unknown lock states, disabled AD accounts,
   missing/ambiguous email matches, unknown user type, unmapped roles and unparsed
   release roles. These are investigation scenarios, not proof of effective access.
4. Inspect manager navigation: unique, missing, ambiguous and directory-only
   manager identities are represented. SAP identity remains distinct from AD.

Dates 2000/2001 and 2999 provide historical/future cases; 31.12.9999 is an explicit
SAP maximum date, not a missing date. Identical duplicate rows and distinct
intervals deliberately exercise importer deduplication and evidence preservation.
The optional three-character suffixes ABC/ABD/XYZ/SYN are invented, not mandatory.
Catalogue patterns use anchored literal-prefix wildcards. Broad/narrow overlap
and case-normalized equal-specificity ambiguity are intentional.

## Schemas and regeneration

Headers follow the current built-in schemas exactly; optional fields may be blank.
See [access schema](../docs/data/CSV_SCHEMAS.md) and
[directory schema](../docs/data/EMPLOYEE_DIRECTORY.md). Regenerate deterministically
from the repository root with `python scripts/generate-examples.py`. The generator
never reads local configuration or source exports. Automated regression tests
import all three sources through the real APIs and verify snapshot restoration in
a fresh process after removing the source files.

## Compatibility examples

[synthetic.csv](synthetic.csv) retains the small historical role-catalogue example.
Its DEMO transactions are invented. The optional PARENT_AGR and Effective_Role
columns demonstrate relationship provenance.
[synthetic-profile.sap-lens.json](synthetic-profile.sap-lens.json) is a schema-2
compatibility example, not an active classification preset. Legacy rules are
archived without execution; it contains no source paths or raw records.
