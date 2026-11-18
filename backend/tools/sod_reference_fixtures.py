"""Generates synthetic SoD reference workbooks and Python v1 sod_reference.parse results for the .NET golden tests.
Usage: python -I tools/sod_reference_fixtures.py BACKEND_DIR OUT_DIR
Writes OUT_DIR/<case>.xlsx (or .bin) and OUT_DIR/expected.python.json: {case: {ok, library | error, pydantic}}."""
import io, json, os, sys, tempfile, zipfile
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
sys.path.insert(0, sys.argv[1])
from pydantic import ValidationError
import sod_reference as reference

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
RISK_HEAD = ['Risk', *reference.RISK]
ACT_HEAD = ['Activity', *reference.ACTIVITY]


def esc(v):
    return v.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def sheet(rows, shared=None, formula_at=None, raw_rows=None):
    out = ['<worksheet xmlns="' + NS + '"><sheetData>']
    for n, values in enumerate(rows, 1):
        out.append(f'<row r="{n}">')
        for c, value in enumerate(values):
            ref = f'{chr(65 + c)}{n}'
            if value is None:
                continue
            f = '<f>1+1</f>' if formula_at == ref else ''
            if shared is not None:
                if value not in shared: shared.append(value)
                out.append(f'<c r="{ref}" t="s">{f}<v>{shared.index(value)}</v></c>')
            else:
                out.append(f'<c r="{ref}" t="inlineStr">{f}<is><t>{esc(value)}</t></is></c>')
        out.append('</row>')
    out.append(raw_rows or '')
    out.append('</sheetData></worksheet>')
    return ''.join(out)


def book(risks, activities, definitions=None, shared=False, formula_at=None, extra_files=None, doctype=False, rels_target=None, risk_raw=None, rich=False):
    buffer = io.BytesIO()
    strings = [] if shared else None
    names = [('Risks', risks), ('Activities', activities)] + ([('Definitions', definitions)] if definitions is not None else [])
    with zipfile.ZipFile(buffer, 'w') as z:
        z.writestr('xl/workbook.xml', '<workbook xmlns="' + NS + '" xmlns:r="' + R + '"><sheets>' + ''.join(
            f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>' for i, (n, _) in enumerate(names, 1)) + '<sheet name="Notes" sheetId="9" r:id="rId9"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(
            f'<Relationship Id="rId{i}" Type="x" Target="{rels_target if (rels_target and i == 1) else f"worksheets/sheet{i}.xml"}"/>' for i in range(1, len(names) + 1)) + '<Relationship Id="rId9" Type="x" Target="worksheets/notes.xml"/></Relationships>')
        for i, (name, rows) in enumerate(names, 1):
            xml = sheet(rows, strings, formula_at if name == 'Risks' else None, risk_raw if name == 'Risks' else None)
            if doctype and i == 1:
                xml = '<!DOCTYPE x [<!ENTITY e "x">]>' + xml
            z.writestr(f'xl/worksheets/sheet{i}.xml', xml)
        z.writestr('xl/worksheets/notes.xml', '<worksheet xmlns="' + NS + '"><sheetData/></worksheet>')
        if strings is not None:
            items = ''.join(f'<si><r><t>{esc(s[:3])}</t></r><r><t>{esc(s[3:])}</t></r></si>' if rich and len(s) > 3 else f'<si><t>{esc(s)}</t></si>' for s in strings)
            z.writestr('xl/sharedStrings.xml', '<sst xmlns="' + NS + '">' + items + '</sst>')
        for path, data in (extra_files or {}).items():
            z.writestr(path, data)
    return buffer.getvalue()


def risk(i, name='Risk name', color=''):
    return [i, name, 'Finance', 'Explanation', 'Consequence', 'Controls', 'Guidance', color]


def act(i, name='Activity name'):
    return [i, name, 'Finance', 'Explanation', 'Guidance', '']


good_r = [RISK_HEAD, risk('F001', '  Payment fraud  ', '#AABBCC'), risk('F002', 'Second', ''), ['F003', '', '', '', '', '', '', '']]
good_a = [ACT_HEAD, act('AP01'), act('AP_02:x', 'Second activity')]
cases = {
    'inline_valid': book(good_r, good_a),
    'shared_strings_definitions': book(good_r, good_a, definitions=[['Term', 'Definition'], ['SoD', 'Segregation of duties'], ['Risk', 'A pair of activities']], shared=True),
    'rich_text_shared': book(good_r, good_a, shared=True, rich=True),
    'header_order_and_blank_rows': book([[RISK_HEAD[0], *reversed(RISK_HEAD[1:])], ['F001', '', 'Notes', 'Guide', 'Ctl', 'Cons', 'Expl', 'Area', 'Name'][:8], ['', '', '', '', '', '', '', '']], good_a),
    'formula': book(good_r, good_a, formula_at='B2'),
    'duplicate_id': book([RISK_HEAD, risk('F001'), risk('F001')], good_a),
    'invalid_id': book([RISK_HEAD, risk('F 001')], good_a),
    'bad_header': book([['Risk', 'Name'], risk('F001')], good_a),
    'missing_activities': book(good_r, [ACT_HEAD]),
    'unheaded_column': book([RISK_HEAD, risk('F001') + ['extra']], good_a),
    'bad_color': book([RISK_HEAD, risk('F001', 'x', 'red')], good_a),
    'control_character': book([RISK_HEAD, risk('F001', 'bad\x01name')], good_a),
    'long_name': book([RISK_HEAD, risk('F001', 'n' * 201)], good_a),
    'oversized_field': book([RISK_HEAD, risk('F001', 'x' * 12001)], good_a),
    'bad_definitions_header': book(good_r, good_a, definitions=[['Name', 'Text'], ['a', 'b']]),
    'duplicate_term': book(good_r, good_a, definitions=[['Term', 'Definition'], ['a', 'b'], ['a', 'c']]),
    'doctype': book(good_r, good_a, doctype=True),
    'macro': book(good_r, good_a, extra_files={'xl/vbaProject.bin': b'\0'}),
    'external_link': book(good_r, good_a, extra_files={'xl/externalLinks/externalLink1.xml': '<x/>'}),
    'path_traversal': book(good_r, good_a, rels_target='../../evil.xml'),
    'invalid_cell_reference': book(good_r, good_a, risk_raw='<row><c r="1A" t="inlineStr"><is><t>x</t></is></c></row>'),
    'not_a_zip': b'PK\x03\x04 this is not a workbook',
    'empty': b'',
}
out = sys.argv[2]
os.makedirs(out, exist_ok=True)
expected = {}
for name, raw in cases.items():
    with open(os.path.join(out, name + '.xlsx.bin'), 'wb') as f:
        f.write(raw)
    try:
        library = reference.parse(raw)
        expected[name] = dict(ok=True, library=library.model_dump(exclude={'imported_at', 'revision'}))
    except ValidationError as error:
        expected[name] = dict(ok=False, pydantic=True, error=str(error).splitlines()[0])
    except ValueError as error:
        expected[name] = dict(ok=False, pydantic=False, error=str(error))
with open(os.path.join(out, 'expected.python.json'), 'w') as f:
    json.dump(expected, f, indent=1, sort_keys=True, ensure_ascii=False)
print(json.dumps({k: (v['ok'], v.get('error', '')[:70]) for k, v in expected.items()}, indent=0))
