"""Validation tracker tooling. The CSV under docs/validation is the source of truth; nothing here needs a service or a dependency.

    python scripts/validation_tracker.py check                  validate the CSV (exit 1 on problems)
    python scripts/validation_tracker.py summary                counts per status and per area
    python scripts/validation_tracker.py export [--output FILE] write an Excel-compatible workbook generated from the CSV
    python scripts/validation_tracker.py merge FILE             copy reviewer decisions edited in a workbook back into the CSV

``export`` is reproducible and ``merge`` only touches the reviewer-owned columns of items that already exist, so a workbook round trip never
loses a decision. Item definitions (ID, area, page, component, expected behavior) are edited in the CSV.
"""
import argparse
import csv
import io
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / 'docs' / 'validation' / 'validation-items.csv'
DEFAULT_OUTPUT = ROOT / 'build' / 'validation-tracker.xlsx'

COLUMNS = ['ID', 'Area', 'Page', 'Component', 'Expected behavior', 'Status', 'Priority', 'Classification', 'Notes and evidence', 'Implementation reference', 'Implementation status', 'Test evidence', 'Manual validation required', 'Remaining issues', 'Retest status']
DEFINITION = COLUMNS[:5]
REVIEWER = COLUMNS[5:]  # the columns a reviewer or implementer edits; merge never touches the others
AREAS = ['Global UI and shared components', 'Dashboard', 'Role Lookup', 'Access Package', 'User Access', 'Account Review', 'Compare Users', 'Release Roles', 'SoD Overview',
         'SoD Risk Matrix and Activity Matrix', 'SoD Access Explorer', 'SoD Reviews', 'SoD Remediation', 'SoD Review Periods', 'SoD Reports', 'Settings', 'Data Management',
         'Deployment and Security']
STATUSES = ['Not reviewed', 'Approved', 'Needs improvement', 'Bug', 'Blocked', 'Not applicable']
PRIORITIES = ['Not set', 'Critical', 'High', 'Medium', 'Low']
CLASSIFICATIONS = ['Unclassified', 'Current defect', 'Improvement opportunity', 'Not an issue']
RETEST = ['Not started', 'Pending retest', 'Retest passed', 'Retest failed']
# Implementation status says what the code does today; Status is the manual acceptance decision and is never set by an implementation.
IMPLEMENTATION = ['Not assessed', 'Not implemented', 'Partially implemented', 'Implemented']
CHOICES = {'Status': STATUSES, 'Priority': PRIORITIES, 'Classification': CLASSIFICATIONS, 'Implementation status': IMPLEMENTATION, 'Retest status': RETEST}
ID_PATTERN = re.compile(r'^[A-Z][A-Z0-9]{1,4}-\d{2,3}$')  # AREA-001, or a round tag such as R7-01
NEEDS_NOTES = {'Approved', 'Needs improvement', 'Bug', 'Blocked'}


def read(path=CSV_PATH):
    with open(path, newline='', encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def write(rows, path=CSV_PATH):
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def problems(rows):
    """Human-readable problems; an empty list means the tracker is consistent."""
    found, seen = [], set()
    for number, row in enumerate(rows, start=2):
        label = f"line {number} ({row.get('ID') or 'no ID'})"
        if set(row) != set(COLUMNS) or None in row:
            found.append(f'{label}: columns do not match {COLUMNS}')
            continue
        if not ID_PATTERN.match(row['ID']):
            found.append(f'{label}: ID must look like AREA-001 or R7-01')
        elif row['ID'] in seen:
            found.append(f'{label}: duplicate ID')
        seen.add(row['ID'])
        if row['Area'] not in AREAS:
            found.append(f'{label}: unknown area "{row["Area"]}"')
        for name in DEFINITION[2:]:
            if not row[name].strip():
                found.append(f'{label}: {name} is empty')
        for name, allowed in CHOICES.items():
            if row[name] not in allowed:
                found.append(f'{label}: {name} "{row[name]}" is not one of {allowed}')
        status, classification = row['Status'], row['Classification']
        if status == 'Not reviewed' and (row['Retest status'] != 'Not started' or classification not in {'Unclassified', 'Improvement opportunity'}):
            found.append(f'{label}: a Not reviewed item has no retest and no defect classification')
        if status == 'Bug' and classification != 'Current defect':
            found.append(f'{label}: a Bug is a Current defect')
        if status == 'Needs improvement' and classification not in {'Improvement opportunity', 'Current defect'}:
            found.append(f'{label}: Needs improvement must be classified as an improvement opportunity or a current defect')
        if status in NEEDS_NOTES and not row['Notes and evidence'].strip():
            found.append(f'{label}: {status} needs notes or evidence')
        if row['Implementation status'] == 'Implemented' and not row['Test evidence'].strip():
            found.append(f'{label}: an Implemented item names its test evidence')
        if status == 'Approved' and row['Implementation status'] in {'Not implemented', 'Partially implemented'}:
            found.append(f'{label}: an item that is not fully implemented cannot be Approved')
        if status == 'Approved' and row['Retest status'] == 'Retest failed':
            found.append(f'{label}: an item whose retest failed cannot be Approved')
        if classification == 'Current defect' and status not in {'Bug', 'Needs improvement', 'Blocked'}:
            found.append(f'{label}: a Current defect is a Bug, Needs improvement or Blocked')
    return found


def summary(rows):
    by_status = Counter(row['Status'] for row in rows)
    lines = [f'{len(rows)} items'] + [f'  {status}: {by_status.get(status, 0)}' for status in STATUSES]
    lines.append(f"  Current defects: {sum(row['Classification'] == 'Current defect' for row in rows)}; improvement opportunities: {sum(row['Classification'] == 'Improvement opportunity' for row in rows)}")
    lines.append('By area (items, not reviewed, approved):')
    for area in AREAS:
        items = [row for row in rows if row['Area'] == area]
        lines.append(f"  {area}: {len(items)}, {sum(row['Status'] == 'Not reviewed' for row in items)}, {sum(row['Status'] == 'Approved' for row in items)}")
    return '\n'.join(lines)


# ---- a minimal workbook writer: inline strings, a header style, filters, frozen header, list validation ----

def _column(index):
    name = ''
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def _sheet(table, widths, validations=()):
    rows = []
    for r, values in enumerate(table, start=1):
        cells = ''.join(f'<c r="{_column(c)}{r}" t="inlineStr"{" s=\"1\"" if r == 1 else " s=\"2\""}><is><t xml:space="preserve">{escape(str(value))}</t></is></c>' for c, value in enumerate(values))
        rows.append(f'<row r="{r}">{cells}</row>')
    columns = ''.join(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>' for i, width in enumerate(widths, start=1))
    last = f'{_column(len(table[0]) - 1)}{len(table)}'
    checks = ''.join(f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" sqref="{column}2:{column}{max(len(table), 2) + 500}"><formula1>"{",".join(options)}"</formula1></dataValidation>' for column, options in validations)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            f'<cols>{columns}</cols><sheetData>{"".join(rows)}</sheetData><autoFilter ref="A1:{last}"/>'
            + (f'<dataValidations count="{len(validations)}">{checks}</dataValidations>' if validations else '') + '</worksheet>')


STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
          '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
          '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFDCE3F5"/></patternFill></fill></fills>'
          '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
          '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
          '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
          '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
          '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


def workbook(rows):
    """Bytes of an .xlsx: Items (editable), Summary, Defects and Improvements. Reproducible for the same rows."""
    table = [COLUMNS] + [[row[name] for name in COLUMNS] for row in rows]
    widths = [10, 30, 22, 28, 60, 16, 12, 22, 50, 44, 20, 44, 44, 44, 16]
    lists = [(_column(COLUMNS.index(name)), options) for name, options in CHOICES.items()]
    total = [['Area', 'Items', *STATUSES, 'Current defects', 'Improvement opportunities']]
    for area in AREAS:
        items = [row for row in rows if row['Area'] == area]
        total.append([area, len(items), *[sum(row['Status'] == status for row in items) for status in STATUSES],
                      sum(row['Classification'] == 'Current defect' for row in items), sum(row['Classification'] == 'Improvement opportunity' for row in items)])
    total.append(['All areas', len(rows), *[sum(row['Status'] == status for row in rows) for status in STATUSES],
                  sum(row['Classification'] == 'Current defect' for row in rows), sum(row['Classification'] == 'Improvement opportunity' for row in rows)])
    defects = [COLUMNS] + [[row[name] for name in COLUMNS] for row in rows if row['Classification'] == 'Current defect']
    ideas = [COLUMNS] + [[row[name] for name in COLUMNS] for row in rows if row['Classification'] == 'Improvement opportunity']
    sheets = [('Items', _sheet(table, widths, lists)), ('Summary', _sheet(total, [36] + [14] * 9)), ('Defects', _sheet(defects, widths)), ('Improvements', _sheet(ideas, widths))]
    files = {
        '[Content_Types].xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                              + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets) + 1)) + '</Types>',
        '_rels/.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                           + ''.join(f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _) in enumerate(sheets, start=1)) + '</sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                      + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
                                      + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        'xl/styles.xml': STYLES,
    }
    for i, (_, xml) in enumerate(sheets, start=1):
        files[f'xl/worksheets/sheet{i}.xml'] = xml
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return buffer.getvalue()


def read_items_sheet(data):
    """Rows of the first sheet of an .xlsx (inline or shared strings) as dictionaries keyed by the header row."""
    namespace = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            for item in ElementTree.fromstring(archive.read('xl/sharedStrings.xml')).findall('m:si', namespace):
                shared.append(''.join(node.text or '' for node in item.iter('{%s}t' % namespace['m'])))
        sheet = ElementTree.fromstring(archive.read('xl/worksheets/sheet1.xml'))
    table = []
    for row in sheet.iter('{%s}row' % namespace['m']):
        values = {}
        for cell in row.findall('m:c', namespace):
            column = re.match(r'[A-Z]+', cell.get('r')).group(0)
            kind = cell.get('t')
            if kind == 'inlineStr':
                text = ''.join(node.text or '' for node in cell.iter('{%s}t' % namespace['m']))
            else:
                node = cell.find('m:v', namespace)
                text = '' if node is None or node.text is None else (shared[int(node.text)] if kind == 's' else node.text)
            values[column] = text
        table.append(values)
    if not table:
        return []
    header = {column: name for column, name in table[0].items() if name}
    return [{name: row.get(column, '') for column, name in header.items()} for row in table[1:] if any(row.values())]


def merge(rows, edited):
    """Copy reviewer-owned values from workbook rows into ``rows`` (matched by ID). Returns (changed IDs, messages about rejected values)."""
    index, changed, rejected = {row['ID']: row for row in rows}, [], []
    for item in edited:
        row = index.get(item.get('ID', ''))
        if row is None:
            rejected.append(f"{item.get('ID', '(no ID)')}: not in the repository tracker; add it to the CSV first")
            continue
        for name in REVIEWER:
            value = item.get(name)
            if value is None or value == row[name]:
                continue
            if name in CHOICES and value not in CHOICES[name]:
                rejected.append(f'{row["ID"]}: {name} "{value}" is not allowed')
                continue
            row[name] = value
            if row['ID'] not in changed:
                changed.append(row['ID'])
    return changed, rejected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--csv', type=Path, default=CSV_PATH, help='tracker CSV (default docs/validation/validation-items.csv)')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('check')
    commands.add_parser('summary')
    export = commands.add_parser('export')
    export.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    merging = commands.add_parser('merge')
    merging.add_argument('workbook', type=Path)
    args = parser.parse_args(argv)
    rows = read(args.csv)
    issues = problems(rows)
    if args.command == 'check' or issues and args.command != 'summary':
        for issue in issues:
            print(issue, file=sys.stderr)
        if args.command == 'check' and not issues:
            print(f'{len(rows)} validation items are consistent.')
        return 1 if issues else 0
    if args.command == 'summary':
        print(summary(rows))
    elif args.command == 'export':
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(workbook(rows))
        print(f'Wrote {args.output} from {len(rows)} items.')
    elif args.command == 'merge':
        changed, rejected = merge(rows, read_items_sheet(args.workbook.read_bytes()))
        for message in rejected:
            print(message, file=sys.stderr)
        after = problems(rows)
        if after:
            for issue in after:
                print(issue, file=sys.stderr)
            print('Nothing was written: the merged tracker would be inconsistent.', file=sys.stderr)
            return 1
        write(rows, args.csv)
        print(f'Updated {len(changed)} items: {", ".join(changed) or "none"}.')
        return 1 if rejected else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
