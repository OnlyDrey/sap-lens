# Functional equivalence: Python v1 versus .NET prototype

Method: the **production Python v1 functions** (`backend/`, unchanged) and the .NET domain run on the **same synthetic files** and write the same
neutral JSON. `tools/compare_equivalence.py` compares every field except the implementation name and timings and exits with code 1 on any
mismatch. Expected behaviour is, by definition, v1's behaviour: the "Python" column is the expected result.

| Run | Data | Result |
| --- | --- | --- |
| Small | 220 roles with edge cases (duplicates, wildcards, ambiguous names, release roles, blank and odd text), 300 users, 40 risks, 16 malformed files | **68 of 68 match** [M] |
| Large | 3,642 roles / 96,924 role rows, 20,000 users / 101,046 user rows, 300 risks / 1,801 SoD rows | **68 of 68 match** [M] |
| Negative control | Three deliberate changes injected into the .NET output | 3 mismatches detected (the comparer is not vacuous) [M] |

Scenario groups: catalogue import (every role, single role, transaction, source relationship, warnings, counts), user import (every user,
account, assignment, match status, indexes), SoD source hash, 15 Role Lookup queries (text search, AND/OR transaction groups, ANY/ALL
exclusion, reversed matching, multi-select SAP areas, leading/trailing `*` wildcards and partial T-code prefixes), 15 User Access queries (groups, roles, transactions, validity, sorting), 7 Compare Users pairs (incl.
same-user and unknown-user errors), 4 comparison listings (difference, SAP areas, search, sort), 3 SoD analyses (active, all, selected roles;
**finding IDs and evidence versions byte-identical**, 64,664 and 281,345 user findings on the large set), 5 import checks (suspicious-change
rules and diff counts against changed and shrunk revisions), 16 malformed or edge-case files (encodings, BOMs, quoting, width mismatch, missing
identifiers, invalid dates, reversed intervals, wildcard assignments).

Critical scenarios (all match): CSV import, normalization, Role Lookup, User Access, Compare Users, SoD findings, change detection.

## Known differences (not exercised by SAP identifiers)

| Difference | Effect | Assessment |
| --- | --- | --- |
| `str.upper()` vs `ToUpperInvariant` | Differ for some non-ASCII letters (for example `ß` becomes `SS` in Python) | SAP role and user names are ASCII; add a guard or exact port before production |
| Code-point vs UTF-16 ordinal ordering | Differ only for characters outside the Basic Multilingual Plane | Not present in SAP identifiers; document |
| User Access scope | Username lists, missing-role, functional-group, manager, band filters and directory fields not ported | Scope limit of the prototype, not a mismatch |
| Role suffix handling | Organizational suffix evidence (`GET /api/roles/naming`) and the Access Package preview (`access_package.py`) are not ported | Scope limit; requested for Role Lookup, must be ported and equivalence-tested before migration |

## Defect found by the benchmark, fixed and regression-tested

The first service benchmark rejected 52 of 587 review writes with HTTP 400. Root cause: the review assignment key used the role name as
exported (v1 keeps `role_name` unnormalized) instead of the normalized name, so mixed-case exports (`ZC:Finance:...`) could not be reviewed by
normalized key. Fixed in `Sources.AssignmentKey`, covered by
`Assignment_keys_use_the_normalized_role_name_whatever_the_export_spelling`; the rerun had 0 rejected writes. [T][M]

## Frontend compatibility

The production React UI (`frontend/`, unchanged) is served by the .NET host since Phase 1. It calls the v1 routes; a server-side compatibility
layer serves those that are migrated (boot and Role Lookup today) in the v1 shapes from the equivalence-tested C# domain, and answers the rest
with an explicit 501. See [UI_INTEGRATION.md](UI_INTEGRATION.md) and [FEATURE_PARITY.md](FEATURE_PARITY.md).

## Small dataset report

| Scenario | Python | .NET | Result |
| --- | --- | --- | --- |
| catalogue | duplicate_rows=1, parsed_rows=1820, relationship_count=498, transaction_assignments=1816, unique_records=1818, unique_ro | unique_roles=227, unique_transactions=403, transaction_assignments=1816, relationship_count=498, parsed_rows=1820, uniqu | MATCH |
| users | assignments=1495, directory_only_users=0, duplicate_rows=3, group_count=5, invalid_catalogue_patterns=1, parsed_rows=151 | unique_users=302, assignments=1495, relevant_assignments=1495, directory_only_users=0, invalid_catalogue_patterns=1, gro | MATCH |
| sod_source | edc315651fbbd22d | edc315651fbbd22d | MATCH |
| role_lookup[0] | 227 items | 227 items | MATCH |
| role_lookup[1] | 112 items | 112 items | MATCH |
| role_lookup[2] | 31 items | 31 items | MATCH |
| role_lookup[3] | 9 items | 9 items | MATCH |
| role_lookup[4] | 61 items | 61 items | MATCH |
| role_lookup[5] | 1 items | 1 items | MATCH |
| role_lookup[6] | 0 items | 0 items | MATCH |
| role_lookup[7] | 7 items | 7 items | MATCH |
| role_lookup[8] | 199 items | 199 items | MATCH |
| role_lookup[9] | 223 items | 223 items | MATCH |
| role_lookup[10] | 226 items | 226 items | MATCH |
| role_lookup[11] | 1 items | 1 items | MATCH |
| role_lookup[12] | 43 items | 43 items | MATCH |
| role_lookup[13] | 16 items | 16 items | MATCH |
| role_lookup[14] | 3 items | 3 items | MATCH |
| user_lookup[0] | 302 items | 302 items | MATCH |
| user_lookup[1] | 2 items | 2 items | MATCH |
| user_lookup[2] | 226 items | 226 items | MATCH |
| user_lookup[3] | 102 items | 102 items | MATCH |
| user_lookup[4] | 50 items | 50 items | MATCH |
| user_lookup[5] | 16 items | 16 items | MATCH |
| user_lookup[6] | 6 items | 6 items | MATCH |
| user_lookup[7] | 34 items | 34 items | MATCH |
| user_lookup[8] | 1 items | 1 items | MATCH |
| user_lookup[9] | 264 items | 264 items | MATCH |
| user_lookup[10] | 154 items | 154 items | MATCH |
| user_lookup[11] | 161 items | 161 items | MATCH |
| user_lookup[12] | 302 items | 302 items | MATCH |
| user_lookup[13] | 302 items | 302 items | MATCH |
| user_lookup[14] | 302 items | 302 items | MATCH |
| comparison[0] | 2 users / 5 roles | 2 users / 5 roles | MATCH |
| comparison[1] | 2 users / 5 roles | 2 users / 5 roles | MATCH |
| comparison[2] | 2 users / 1 roles | 2 users / 1 roles | MATCH |
| comparison[3] | 2 users / 11 roles | 2 users / 11 roles | MATCH |
| comparison[4] | 2 users / 7 roles | 2 users / 7 roles | MATCH |
| comparison[5] | error: Choose two different SAP users. | error: Choose two different SAP users. | MATCH |
| comparison[6] | error: A selected SAP user is not in the current export. | error: A selected SAP user is not in the current export. | MATCH |
| comparison_listing[0] | 5 items | 5 items | MATCH |
| comparison_listing[1] | 2 items | 2 items | MATCH |
| comparison_listing[2] | 4 items | 4 items | MATCH |
| comparison_listing[3] | 0 items | 0 items | MATCH |
| sod[0] | 146 users / 30 roles | 146 users / 30 roles | MATCH |
| sod[1] | 796 users / 30 roles | 796 users / 30 roles | MATCH |
| sod[2] | 48 users / 30 roles | 48 users / 30 roles | MATCH |
| import_checks[0] | not held, diff {'added': 1, 'ambiguous': 0, 'modified': 0, 'removed': 180, 'unchanged': 1638} | not held, diff {'added': 1, 'removed': 180, 'modified': 0, 'unchanged': 1638, 'ambiguous': 0} | MATCH |
| import_checks[1] | not held, diff {'added': 0, 'ambiguous': 0, 'modified': 31, 'removed': 0, 'unchanged': 1481} | not held, diff {'added': 0, 'removed': 0, 'modified': 31, 'unchanged': 1481, 'ambiguous': 0} | MATCH |
| import_checks[2] | held, diff {'added': 0, 'ambiguous': 0, 'modified': 0, 'removed': 908, 'unchanged': 910} | held, diff {'added': 0, 'removed': 908, 'modified': 0, 'unchanged': 910, 'ambiguous': 0} | MATCH |
| import_checks[3] | held, diff {'added': 0, 'ambiguous': 0, 'modified': 0, 'removed': 1007, 'unchanged': 505} | held, diff {'added': 0, 'removed': 1007, 'modified': 0, 'unchanged': 505, 'ambiguous': 0} | MATCH |
| import_checks[4] | not held, diff {'added': 0, 'ambiguous': 0, 'modified': 0, 'removed': 0, 'unchanged': 240} | not held, diff {'added': 0, 'removed': 0, 'modified': 0, 'unchanged': 240, 'ambiguous': 0} | MATCH |
| malformed/roles_bad_quote | error: csv-format-error | error: csv-format-error | MATCH |
| malformed/roles_blank_and_duplicate | error: The required AGR_NAME field is not mapped. | error: The required AGR_NAME field is not mapped. | MATCH |
| malformed/roles_cp1252 | ok | ok | MATCH |
| malformed/roles_duplicate_headers | error: CSV headers contain duplicate, ambiguous or empty column nam | error: CSV headers contain duplicate, ambiguous or empty column nam | MATCH |
| malformed/roles_empty_header | error: CSV headers contain duplicate, ambiguous or empty column nam | error: CSV headers contain duplicate, ambiguous or empty column nam | MATCH |
| malformed/roles_identifier_too_long | error: A role identifier is too long. | error: A role identifier is too long. | MATCH |
| malformed/roles_missing_agr | error: A nonempty record has no AGR_NAME; no data was applied. | error: A nonempty record has no AGR_NAME; no data was applied. | MATCH |
| malformed/roles_ok_quoted | ok | ok | MATCH |
| malformed/roles_unterminated_quote | error: csv-format-error | error: csv-format-error | MATCH |
| malformed/roles_utf16 | ok | ok | MATCH |
| malformed/roles_utf8_bom | ok | ok | MATCH |
| malformed/roles_width_mismatch | error: The required AGR_NAME field is not mapped. | error: The required AGR_NAME field is not mapped. | MATCH |
| malformed/users_invalid_date | error: Invalid SAP date. Use YYYY-MM-DD or YYYYMMDD; no data was ap | error: Invalid SAP date. Use YYYY-MM-DD or YYYYMMDD; no data was ap | MATCH |
| malformed/users_ok | ok | ok | MATCH |
| malformed/users_reversed_interval | error: A validity interval ends before it starts; no data was appli | error: A validity interval ends before it starts; no data was appli | MATCH |
| malformed/users_wildcard_assignment | error: User exports require exact assigned role names, not catalogu | error: User exports require exact assigned role names, not catalogu | MATCH |

## Large dataset report

| Scenario | Python | .NET | Result |
| --- | --- | --- | --- |
| catalogue | duplicate_rows=0, parsed_rows=96924, relationship_count=8168, transaction_assignments=96761, unique_records=96924, uniqu | unique_roles=3642, unique_transactions=3000, transaction_assignments=96761, relationship_count=8168, parsed_rows=96924,  | MATCH |
| users | assignments=99967, directory_only_users=0, duplicate_rows=19, group_count=5, invalid_catalogue_patterns=0, parsed_rows=1 | unique_users=20000, assignments=99967, relevant_assignments=99967, directory_only_users=0, invalid_catalogue_patterns=0, | MATCH |
| sod_source | 6a39e1622854196d | 6a39e1622854196d | MATCH |
| role_lookup[0] | 3642 items | 3642 items | MATCH |
| role_lookup[1] | 1011 items | 1011 items | MATCH |
| role_lookup[2] | 533 items | 533 items | MATCH |
| role_lookup[3] | 9 items | 9 items | MATCH |
| role_lookup[4] | 882 items | 882 items | MATCH |
| role_lookup[5] | 0 items | 0 items | MATCH |
| role_lookup[6] | 2 items | 2 items | MATCH |
| role_lookup[7] | 77 items | 77 items | MATCH |
| role_lookup[8] | 1926 items | 1926 items | MATCH |
| role_lookup[9] | 3642 items | 3642 items | MATCH |
| role_lookup[10] | 3640 items | 3640 items | MATCH |
| role_lookup[11] | 33 items | 33 items | MATCH |
| role_lookup[12] | 291 items | 291 items | MATCH |
| role_lookup[13] | 792 items | 792 items | MATCH |
| role_lookup[14] | 0 items | 0 items | MATCH |
| user_lookup[0] | 20000 items | 20000 items | MATCH |
| user_lookup[1] | 0 items | 0 items | MATCH |
| user_lookup[2] | 15000 items | 15000 items | MATCH |
| user_lookup[3] | 6667 items | 6667 items | MATCH |
| user_lookup[4] | 3333 items | 3333 items | MATCH |
| user_lookup[5] | 0 items | 0 items | MATCH |
| user_lookup[6] | 0 items | 0 items | MATCH |
| user_lookup[7] | 2075 items | 2075 items | MATCH |
| user_lookup[8] | 110 items | 110 items | MATCH |
| user_lookup[9] | 18197 items | 18197 items | MATCH |
| user_lookup[10] | 11120 items | 11120 items | MATCH |
| user_lookup[11] | 11027 items | 11027 items | MATCH |
| user_lookup[12] | 20000 items | 20000 items | MATCH |
| user_lookup[13] | 20000 items | 20000 items | MATCH |
| user_lookup[14] | 20000 items | 20000 items | MATCH |
| comparison[0] | 2 users / 5 roles | 2 users / 5 roles | MATCH |
| comparison[1] | 2 users / 11 roles | 2 users / 11 roles | MATCH |
| comparison[2] | 2 users / 4 roles | 2 users / 4 roles | MATCH |
| comparison[3] | 2 users / 11 roles | 2 users / 11 roles | MATCH |
| comparison[4] | 2 users / 6 roles | 2 users / 6 roles | MATCH |
| comparison[5] | error: Choose two different SAP users. | error: Choose two different SAP users. | MATCH |
| comparison[6] | error: A selected SAP user is not in the current export. | error: A selected SAP user is not in the current export. | MATCH |
| comparison_listing[0] | 11 items | 11 items | MATCH |
| comparison_listing[1] | 0 items | 0 items | MATCH |
| comparison_listing[2] | 0 items | 0 items | MATCH |
| comparison_listing[3] | 11 items | 11 items | MATCH |
| sod[0] | 64664 users / 1130 roles | 64664 users / 1130 roles | MATCH |
| sod[1] | 281345 users / 1130 roles | 281345 users / 1130 roles | MATCH |
| sod[2] | error: A selected catalogue role is unavailable in the current data | error: A selected catalogue role is unavailable in the current data | MATCH |
| import_checks[0] | not held, diff {'added': 1, 'ambiguous': 0, 'modified': 0, 'removed': 9693, 'unchanged': 87231} | not held, diff {'added': 1, 'removed': 9693, 'modified': 0, 'unchanged': 87231, 'ambiguous': 0} | MATCH |
| import_checks[1] | not held, diff {'added': 2, 'ambiguous': 0, 'modified': 2019, 'removed': 0, 'unchanged': 99008} | not held, diff {'added': 2, 'removed': 0, 'modified': 2019, 'unchanged': 99008, 'ambiguous': 0} | MATCH |
| import_checks[2] | held, diff {'added': 0, 'ambiguous': 0, 'modified': 0, 'removed': 48462, 'unchanged': 48462} | held, diff {'added': 0, 'removed': 48462, 'modified': 0, 'unchanged': 48462, 'ambiguous': 0} | MATCH |
| import_checks[3] | held, diff {'added': 0, 'ambiguous': 0, 'modified': 0, 'removed': 67353, 'unchanged': 33674} | held, diff {'added': 0, 'removed': 67353, 'modified': 0, 'unchanged': 33674, 'ambiguous': 0} | MATCH |
| import_checks[4] | not held, diff {'added': 0, 'ambiguous': 0, 'modified': 0, 'removed': 0, 'unchanged': 1800} | not held, diff {'added': 0, 'removed': 0, 'modified': 0, 'unchanged': 1800, 'ambiguous': 0} | MATCH |
| malformed/roles_bad_quote | error: csv-format-error | error: csv-format-error | MATCH |
| malformed/roles_blank_and_duplicate | error: The required AGR_NAME field is not mapped. | error: The required AGR_NAME field is not mapped. | MATCH |
| malformed/roles_cp1252 | ok | ok | MATCH |
| malformed/roles_duplicate_headers | error: CSV headers contain duplicate, ambiguous or empty column nam | error: CSV headers contain duplicate, ambiguous or empty column nam | MATCH |
| malformed/roles_empty_header | error: CSV headers contain duplicate, ambiguous or empty column nam | error: CSV headers contain duplicate, ambiguous or empty column nam | MATCH |
| malformed/roles_identifier_too_long | error: A role identifier is too long. | error: A role identifier is too long. | MATCH |
| malformed/roles_missing_agr | error: A nonempty record has no AGR_NAME; no data was applied. | error: A nonempty record has no AGR_NAME; no data was applied. | MATCH |
| malformed/roles_ok_quoted | ok | ok | MATCH |
| malformed/roles_unterminated_quote | error: csv-format-error | error: csv-format-error | MATCH |
| malformed/roles_utf16 | ok | ok | MATCH |
| malformed/roles_utf8_bom | ok | ok | MATCH |
| malformed/roles_width_mismatch | error: The required AGR_NAME field is not mapped. | error: The required AGR_NAME field is not mapped. | MATCH |
| malformed/users_invalid_date | error: Invalid SAP date. Use YYYY-MM-DD or YYYYMMDD; no data was ap | error: Invalid SAP date. Use YYYY-MM-DD or YYYYMMDD; no data was ap | MATCH |
| malformed/users_ok | ok | ok | MATCH |
| malformed/users_reversed_interval | error: A validity interval ends before it starts; no data was appli | error: A validity interval ends before it starts; no data was appli | MATCH |
| malformed/users_wildcard_assignment | error: User exports require exact assigned role names, not catalogu | error: User exports require exact assigned role names, not catalogu | MATCH |
