"""Malformed and edge-case CSV files shared by the Python and .NET equivalence runs (synthetic). Writes OUT/<name>.csv and OUT/cases.json."""
import json
import sys
from pathlib import Path

ROLE = 'FUNCTION_KEY;AGR_NAME;TEXT;CHILD_AGR;CHILD_AGR_TEXT;PARENT_AGR;Effective_Role;TCODE;TTEXT\r\n'
USER = 'USERNAME;ROLE_NAME;USER_GROUP;FIRST_NAME;LAST_NAME;EMAIL;USER_VALID_FROM;USER_VALID_TO;ROLE_VALID_FROM;ROLE_VALID_TO;USER_LOCKED;USER_TYPE\r\n'
CASES = {
    'roles_ok_quoted': ('roles', (ROLE + 'FI;"ZC:FI:A";"Text; with ""quotes""";C;;;;FB01;"multi\r\nline"\r\n').encode()),
    'roles_bad_quote': ('roles', (ROLE + 'FI;"ZC:FI:A"x;T;C;;;;FB01;t\r\n').encode()),
    'roles_unterminated_quote': ('roles', (ROLE + 'FI;"ZC:FI:A;T;C;;;;FB01;t\r\n').encode()),
    'roles_width_mismatch': ('roles', (ROLE + 'FI;ZC:FI:A;T;C;;;;FB01\r\n').encode()),
    'roles_missing_agr': ('roles', (ROLE + 'FI;;T;C;;;;FB01;t\r\n').encode()),
    'roles_duplicate_headers': ('roles', ('AGR_NAME;agr name;TCODE\r\nA;B;C\r\n').encode()),
    'roles_empty_header': ('roles', ('AGR_NAME;;TCODE\r\nA;B;C\r\n').encode()),
    'roles_identifier_too_long': ('roles', (ROLE + 'FI;' + 'Z' * 513 + ';T;C;;;;FB01;t\r\n').encode()),
    'roles_cp1252': ('roles', (ROLE + 'FI;ZC:FI:CAFÉ;Café rôle;C;;;;FB01;Buchung\r\n').encode('cp1252')),
    'roles_utf16': ('roles', (ROLE + 'FI;ZC:FI:UTF16;Ünïcödé;C;;;;FB01;t\r\n').encode('utf-16')),
    'roles_utf8_bom': ('roles', (ROLE + 'FI;ZC:FI:BOM;Text;C;;;;FB01;t\r\n').encode('utf-8-sig')),
    'roles_blank_and_duplicate': ('roles', (ROLE + ';;;;;;;;\r\nFI;ZC:FI:A;T;C;;;;FB01;t\r\nFI;ZC:FI:A;T;C;;;;FB01;t\r\n\r\n').encode()),
    'users_invalid_date': ('users', (USER + 'U1;ZC:A;G;F;L;;2020-13-01;;;;;A\r\n').encode()),
    'users_reversed_interval': ('users', (USER + 'U1;ZC:A;G;F;L;;20201231;20200101;;;;A\r\n').encode()),
    'users_wildcard_assignment': ('users', (USER + 'U1;ZC:A*;G;F;L;;;;;;;A\r\n').encode()),
    'users_ok': ('users', (USER + 'U1;ZC:FI:A;G;F;L;u1@example.invalid;20000101;20981231;;;X;A\r\nu1;ZC:FI:A;G2;F;L;;;;;;;A\r\n').encode()),
}

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for name, (source, data) in CASES.items():
    (out / f'{name}.csv').write_bytes(data)
(out / 'cases.json').write_text(json.dumps({name: source for name, (source, _) in CASES.items()}, indent=1))
print(f'{len(CASES)} cases in {out}')
