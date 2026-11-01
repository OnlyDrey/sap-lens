"""Validation tracker tooling. The CSV under docs/validation is the source of truth; nothing here needs a service or a dependency.

    python scripts/validation_tracker.py check                  validate the CSV (exit 1 on problems)
    python scripts/validation_tracker.py summary                counts per status and per area
    python scripts/validation_tracker.py export [--output FILE] write an Excel workbook generated from the CSV
    python scripts/validation_tracker.py merge FILE             copy reviewer decisions edited in a workbook back into the CSV
    python scripts/validation_tracker.py migrate                convert a tracker in the earlier 15-column layout to the current one

``export`` is reproducible and ``merge`` only touches the reviewer-owned columns of items that already exist, so a workbook round trip never loses
a decision. Item definitions (ID, area, page, criterion) are edited in the CSV. Nothing here ever marks an item as manually approved.
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

COLUMNS = ['ID', 'Area', 'Page/component', 'Validation criterion', 'Priority', 'Status', 'Manual approval', 'Automated test evidence', 'Last validated date',
           'Build/commit', 'Notes', 'Linked issue or finding', 'Potential future improvement', 'Manual validation steps', 'Known limitations',
           'Implementation reference', 'Implementation status', 'Classification', 'Retest status']
DEFINITION = ['ID', 'Area', 'Page/component', 'Validation criterion', 'Automated test evidence', 'Manual validation steps', 'Known limitations', 'Implementation reference', 'Implementation status']
REVIEWER = ['Priority', 'Status', 'Manual approval', 'Last validated date', 'Build/commit', 'Notes', 'Linked issue or finding', 'Potential future improvement', 'Classification', 'Retest status']
AREAS = ['Dashboard', 'Role Lookup', 'Access Package', 'User Directory', 'Account Review', 'Compare Users', 'Release Roles', 'SoD Overview', 'Risk Matrix', 'Activity Matrix',
         'Access Explorer', 'SoD Reviews', 'Review Periods', 'SoD Reports', 'Settings and Data Sources', 'SAP Modules', 'SoD Risk Configuration', 'Component Library',
         'Desktop and Startup', 'Server and Deployment', 'Accessibility and Responsive Design', 'Security and Data Integrity']
STATUSES = ['Not tested', 'Passed', 'Failed', 'Needs improvement', 'Blocked', 'Not applicable']
APPROVALS = ['Pending', 'Approved', 'Rejected', 'Not applicable']
PRIORITIES = ['Not set', 'Critical', 'High', 'Medium', 'Low']
CLASSIFICATIONS = ['Unclassified', 'Current defect', 'Improvement opportunity', 'Not an issue']
RETEST = ['Not started', 'Pending retest', 'Retest passed', 'Retest failed']
# Implementation status says what the code does today; Status and Manual approval are decisions people record and no implementation sets them.
IMPLEMENTATION = ['Not assessed', 'Not implemented', 'Partially implemented', 'Implemented']
CHOICES = {'Priority': PRIORITIES, 'Status': STATUSES, 'Manual approval': APPROVALS, 'Implementation status': IMPLEMENTATION, 'Classification': CLASSIFICATIONS, 'Retest status': RETEST}
ID_PATTERN = re.compile(r'^[A-Z][A-Z0-9]{1,4}-\d{2,3}$')
DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')
NEEDS_NOTES = {'Passed', 'Failed', 'Needs improvement', 'Blocked'}

# The earlier layout (R4 to R7), converted by ``migrate``.
LEGACY_COLUMNS = ['ID', 'Area', 'Page', 'Component', 'Expected behavior', 'Status', 'Priority', 'Classification', 'Notes and evidence', 'Implementation reference', 'Implementation status',
                  'Test evidence', 'Manual validation required', 'Remaining issues', 'Retest status']
LEGACY_STATUS = {'Not reviewed': 'Not tested', 'Approved': 'Passed', 'Needs improvement': 'Needs improvement', 'Bug': 'Failed', 'Blocked': 'Blocked', 'Not applicable': 'Not applicable'}


def read(path=CSV_PATH):
    with open(path, newline='', encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def write(rows, path=CSV_PATH):
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def is_legacy(path=CSV_PATH):
    with open(path, newline='', encoding='utf-8') as handle:
        return next(csv.reader(handle), []) == LEGACY_COLUMNS


# ---- migration from the earlier layout ----

ACCESSIBILITY_WORDS = ('accessibility', 'keyboard', 'focus', 'responsive')
# Security controls that sat under "Deployment and Security" belong with the security items.
AREA_OVERRIDES = {'DEP-001': 'Security and Data Integrity', 'DEP-002': 'Security and Data Integrity'}


def map_area(old):
    """Place an item of the earlier 18-area layout into one of the 22 functional areas, by area, page and component."""
    area, page, component = old['Area'], old['Page'], old['Component']
    where = f'{page} {component}'.lower()
    direct = {'Dashboard': 'Dashboard', 'Role Lookup': 'Role Lookup', 'Access Package': 'Access Package', 'User Access': 'User Directory', 'Account Review': 'Account Review',
              'Compare Users': 'Compare Users', 'Release Roles': 'Release Roles', 'SoD Overview': 'SoD Overview', 'SoD Access Explorer': 'Access Explorer', 'SoD Reviews': 'SoD Reviews',
              'SoD Remediation': 'SoD Reviews', 'SoD Review Periods': 'Review Periods', 'SoD Reports': 'SoD Reports'}
    if old['ID'] in AREA_OVERRIDES:
        return AREA_OVERRIDES[old['ID']]
    if area in direct:
        return direct[area]
    if area == 'SoD Risk Matrix and Activity Matrix':
        return 'Activity Matrix' if 'activity' in where and 'risk' not in where else 'Risk Matrix'  # items that cover both matrices stay one record under Risk Matrix
    if area == 'Settings':
        return 'SoD Risk Configuration' if 'sod risk configuration' in where else 'SAP Modules' if 'sap modules' in where and 'data sources' not in where else 'Settings and Data Sources'
    if area == 'Data Management':
        return 'Settings and Data Sources'
    if area == 'Deployment and Security':
        if page == 'Privacy':
            return 'Security and Data Integrity'
        if page == 'Windows':
            return 'Desktop and Startup' if component in {'Desktop lifecycle (WebView2)', 'Installer'} else 'Server and Deployment'
        return 'Server and Deployment'
    # Global UI and shared components
    if page == 'Desktop loading screen':
        return 'Desktop and Startup'
    return 'Accessibility and Responsive Design' if any(word in where for word in ACCESSIBILITY_WORDS) else 'Component Library'


def migrate_legacy(rows):
    """Convert earlier-layout rows. Every decision is preserved; no result, approval or date is invented."""
    converted = []
    for old in rows:
        status = LEGACY_STATUS[old['Status']]
        converted.append({
            'ID': old['ID'], 'Area': map_area(old), 'Page/component': f'{old["Page"]} › {old["Component"]}', 'Validation criterion': old['Expected behavior'],
            'Priority': old['Priority'], 'Status': status, 'Manual approval': 'Approved' if old['Status'] == 'Approved' else 'Not applicable' if old['Status'] == 'Not applicable' else 'Pending',
            'Automated test evidence': old['Test evidence'], 'Last validated date': '', 'Build/commit': '', 'Notes': old['Notes and evidence'], 'Linked issue or finding': '',
            'Potential future improvement': '', 'Manual validation steps': old['Manual validation required'], 'Known limitations': old['Remaining issues'],
            'Implementation reference': old['Implementation reference'], 'Implementation status': old['Implementation status'], 'Classification': old['Classification'],
            'Retest status': old['Retest status']})
    return converted


# ---- consistency ----

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
        for name in ('Page/component', 'Validation criterion'):
            if not row[name].strip():
                found.append(f'{label}: {name} is empty')
        for name, allowed in CHOICES.items():
            if row[name] not in allowed:
                found.append(f'{label}: {name} "{row[name]}" is not one of {allowed}')
        if row['Last validated date'] and not DATE_PATTERN.match(row['Last validated date']):
            found.append(f'{label}: Last validated date must be YYYY-MM-DD')
        status, approval, classification = row['Status'], row['Manual approval'], row['Classification']
        if status == 'Not tested' and (row['Retest status'] != 'Not started' or row['Last validated date'] or approval in {'Approved', 'Rejected'}
                                        or classification not in {'Unclassified', 'Improvement opportunity'}):
            found.append(f'{label}: a Not tested item has no validation date, approval decision, retest or defect classification')
        if status == 'Passed' and not row['Last validated date']:
            found.append(f'{label}: a Passed item records its last validated date')
        if status == 'Failed' and classification != 'Current defect':
            found.append(f'{label}: a Failed item is a Current defect')
        if status == 'Needs improvement' and classification not in {'Improvement opportunity', 'Current defect'}:
            found.append(f'{label}: Needs improvement must be classified as an improvement opportunity or a current defect')
        if status in NEEDS_NOTES and not row['Notes'].strip():
            found.append(f'{label}: {status} needs notes or evidence')
        if approval == 'Approved' and (status != 'Passed' or not row['Last validated date'] or not row['Notes'].strip()):
            found.append(f'{label}: Manual approval needs a Passed status, a validation date and notes naming who approved')
        if approval == 'Approved' and (row['Implementation status'] in {'Not implemented', 'Partially implemented'} or row['Retest status'] == 'Retest failed'):
            found.append(f'{label}: an item that is not fully implemented or failed its retest cannot be approved')
        if row['Implementation status'] == 'Implemented' and not row['Automated test evidence'].strip():
            found.append(f'{label}: an Implemented item names its automated test evidence')
        if classification == 'Current defect' and status not in {'Failed', 'Needs improvement', 'Blocked'}:
            found.append(f'{label}: a Current defect is Failed, Needs improvement or Blocked')
    return found


def completion(items):
    """Share of applicable items that have a recorded result (Passed, Failed or Needs improvement), and the share manually approved."""
    applicable = [row for row in items if row['Status'] != 'Not applicable']
    if not applicable:
        return 0.0, 0.0
    decided = sum(row['Status'] in {'Passed', 'Failed', 'Needs improvement'} for row in applicable)
    return decided / len(applicable), sum(row['Manual approval'] == 'Approved' for row in applicable) / len(applicable)


def summary(rows):
    by_status = Counter(row['Status'] for row in rows)
    lines = [f'{len(rows)} items'] + [f'  {status}: {by_status.get(status, 0)}' for status in STATUSES]
    lines.append(f"  Manually approved: {sum(row['Manual approval'] == 'Approved' for row in rows)}; pending: {sum(row['Manual approval'] == 'Pending' for row in rows)}")
    lines.append(f"  Current defects: {sum(row['Classification'] == 'Current defect' for row in rows)}; improvement opportunities: {sum(row['Classification'] == 'Improvement opportunity' for row in rows)}")
    lines.append('By area (items, not tested, completion, approved):')
    for area in AREAS:
        items = [row for row in rows if row['Area'] == area]
        done, approved = completion(items)
        lines.append(f"  {area}: {len(items)}, {sum(row['Status'] == 'Not tested' for row in items)}, {done:.0%}, {approved:.0%}")
    return '\n'.join(lines)


# ---- a minimal workbook writer: inline strings, an Excel table, frozen headers, drop-downs, conditional formatting, live summary formulas ----

def _column(index):
    name = ''
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def _cell(ref, value, style, kind='string', formula=None):
    if kind == 'number':
        return f'<c r="{ref}" s="{style}">{f"<f>{escape(formula)}</f>" if formula else ""}<v>{value}</v></c>'
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'


def _formats(columns):
    """Conditional formats (dxf ids) for the status, priority and approval columns."""
    rules, priority = [], 1
    spec = {'Status': {'Passed': 0, 'Failed': 1, 'Needs improvement': 2, 'Blocked': 3, 'Not applicable': 4},
            'Priority': {'Critical': 1, 'High': 2, 'Medium': 3},
            'Manual approval': {'Approved': 0, 'Rejected': 1}}
    for name, values in spec.items():
        if name not in columns:
            continue
        letter = _column(columns.index(name))
        body = ''.join(f'<cfRule type="cellIs" dxfId="{dxf}" priority="{priority + offset}" operator="equal"><formula>"{value}"</formula></cfRule>' for offset, (value, dxf) in enumerate(values.items()))
        priority += len(values)
        rules.append(f'<conditionalFormatting sqref="{letter}2:{letter}2000">{body}</conditionalFormatting>')
    return ''.join(rules)


def _sheet(table, widths, validations=(), table_part=False, formats=False):
    rows = []
    for r, values in enumerate(table, start=1):
        cells = ''.join(_cell(f'{_column(c)}{r}', value, 1 if r == 1 else 2) for c, value in enumerate(values))
        rows.append(f'<row r="{r}">{cells}</row>')
    columns = ''.join(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>' for i, width in enumerate(widths, start=1))
    last = f'{_column(len(table[0]) - 1)}{len(table)}'
    checks = ''.join(f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" sqref="{column}2:{column}2000"><formula1>"{",".join(options)}"</formula1></dataValidation>' for column, options in validations)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheetViews><sheetView workbookViewId="0"><pane xSplit="1" ySplit="1" topLeftCell="B2" activePane="bottomRight" state="frozen"/></sheetView></sheetViews>'
            f'<cols>{columns}</cols><sheetData>{"".join(rows)}</sheetData>'
            + ('' if table_part else f'<autoFilter ref="A1:{last}"/>')
            + (_formats(table[0]) if formats else '')
            + (f'<dataValidations count="{len(validations)}">{checks}</dataValidations>' if validations else '')
            + ('<tableParts count="1"><tablePart r:id="rId1"/></tableParts>' if table_part else '') + '</worksheet>')


def _table_xml(columns, rows):
    last = f'{_column(len(columns) - 1)}{rows + 1}'
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><table xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" id="1" name="ValidationItems" displayName="ValidationItems" '
            f'ref="A1:{last}" totalsRowShown="0"><autoFilter ref="A1:{last}"/><tableColumns count="{len(columns)}">'
            + ''.join(f'<tableColumn id="{i}" name="{escape(name)}"/>' for i, name in enumerate(columns, start=1))
            + '</tableColumns><tableStyleInfo name="TableStyleLight1" showFirstColumn="0" showLastColumn="0" showRowStripes="1" showColumnStripes="0"/></table>')


def _summary_sheet(rows):
    """Live summary: COUNTIFS over the Items sheet, so edits in the workbook update it; cached values keep previews correct."""
    n = len(rows) + 1
    items = lambda column: f'Items!${_column(COLUMNS.index(column))}$2:${_column(COLUMNS.index(column))}${max(n, 2)}'
    header = ['Area', 'Items', *STATUSES, 'Manual approved', 'Manual pending', 'Completion', 'Approved']
    body = [f'<row r="1">{_cell("A1", "SAP Lens validation checklist", 3)}</row>',
            f'<row r="2">{_cell("A2", "Generated from docs/validation/validation-items.csv. Status and Manual approval are recorded by people; automated test evidence is listed separately on the Items sheet. Nothing is approved automatically.", 6)}</row>',
            f'<row r="3">{_cell("A3", "Completion = Passed, Failed and Needs improvement over applicable items. Approved = manually approved over applicable items. Defects and Future Improvements are snapshots taken when the workbook was generated.", 6)}</row>']
    table_rows = ['<row r="5">' + ''.join(_cell(f'{_column(c)}5', value, 1) for c, value in enumerate(header)) + '</row>']
    first = 6
    for offset, area in enumerate(AREAS + ['All areas']):
        r, total = first + offset, area == 'All areas'
        scope = rows if total else [row for row in rows if row['Area'] == area]
        style = 5 if total else 0
        cells = [_cell(f'A{r}', area, 5 if total else 0)]
        crit = '' if total else f'{items("Area")},$A{r},'
        sums = lambda col: f'SUM({col}{first}:{col}{first + len(AREAS) - 1})'
        values = []
        count = len(scope)
        values.append((count, f'SUM(B{first}:B{first + len(AREAS) - 1})' if total else f'COUNTIFS({items("Area")},$A{r})'))
        for c, status in enumerate(STATUSES, start=2):
            col = _column(c)
            values.append((sum(row['Status'] == status for row in scope), sums(col) if total else f'COUNTIFS({crit}{items("Status")},{col}$5)'))
        for c, approval in ((8, 'Approved'), (9, 'Pending')):
            col = _column(c)
            values.append((sum(row['Manual approval'] == approval for row in scope), sums(col) if total else f'COUNTIFS({crit}{items("Manual approval")},"{approval}")'))
        done, approved = completion(scope)
        values.append((round(done, 6), f'IF(B{r}-G{r}=0,0,(D{r}+E{r}+F{r})/(B{r}-G{r}))'))
        values.append((round(approved, 6), f'IF(B{r}-G{r}=0,0,H{r}/(B{r}-G{r}))'))
        for c, (value, formula) in enumerate(values, start=1):
            cells.append(_cell(f'{_column(c)}{r}', value, 4 if c >= 10 else style, 'number', formula))
        table_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    last = first + len(AREAS)
    outstanding = [('Failed items', 'Failed'), ('Items needing improvement', 'Needs improvement'), ('Blocked items', 'Blocked')]
    extra = [f'<row r="{last + 2}">{_cell(f"A{last + 2}", "Outstanding", 1)}{_cell(f"B{last + 2}", "Count", 1)}</row>']
    for k, (label, status) in enumerate(outstanding, start=3):
        r = last + k
        formula = 'COUNTIFS(' + items('Status') + ',"' + status + '")'
        extra.append(f'<row r="{r}">{_cell(f"A{r}", label, 0)}{_cell(f"B{r}", sum(row["Status"] == status for row in rows), 0, "number", formula)}</row>')
    r = last + 6
    open_findings = sum(bool(row['Linked issue or finding'].strip()) and row['Status'] != 'Passed' for row in rows)
    formula = 'COUNTIFS(' + items('Linked issue or finding') + ',"<>",' + items('Status') + ',"<>Passed")'
    extra.append(f'<row r="{r}">{_cell(f"A{r}", "Items linked to an open finding", 0)}{_cell(f"B{r}", open_findings, 0, "number", formula)}</row>')
    r = last + 7
    evidence = sum(bool(row['Automated test evidence'].strip()) for row in rows)
    formula = 'COUNTIFS(' + items('Automated test evidence') + ',"<>")'
    extra.append(f'<row r="{r}">{_cell(f"A{r}", "Items with automated test evidence", 0)}{_cell(f"B{r}", evidence, 0, "number", formula)}</row>')
    widths = [38, 10, 12, 10, 10, 18, 10, 14, 14, 14, 12, 12]
    columns = ''.join(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>' for i, width in enumerate(widths, start=1))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetViews><sheetView workbookViewId="0" showGridLines="0"/></sheetViews><cols>{columns}</cols><sheetData>{"".join(body + table_rows + extra)}</sheetData></worksheet>')


STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
          '<numFmts count="1"><numFmt numFmtId="164" formatCode="0.0%"/></numFmts>'
          '<fonts count="4"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font>'
          '<font><b/><sz val="14"/><name val="Calibri"/></font><font><i/><sz val="10"/><color rgb="FF595959"/><name val="Calibri"/></font></fonts>'
          '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
          '<fill><patternFill patternType="solid"><fgColor rgb="FFDCE3F5"/></patternFill></fill></fills>'
          '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
          '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
          '<cellXfs count="7"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
          '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
          '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
          '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
          '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
          '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
          '<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
          '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
          '<dxfs count="5">'
          '<dxf><font><color rgb="FF006100"/></font><fill><patternFill><bgColor rgb="FFC6EFCE"/></patternFill></fill></dxf>'
          '<dxf><font><color rgb="FF9C0006"/></font><fill><patternFill><bgColor rgb="FFFFC7CE"/></patternFill></fill></dxf>'
          '<dxf><font><color rgb="FF9C5700"/></font><fill><patternFill><bgColor rgb="FFFFEB9C"/></patternFill></fill></dxf>'
          '<dxf><font><color rgb="FF7F3F00"/></font><fill><patternFill><bgColor rgb="FFF8CBAD"/></patternFill></fill></dxf>'
          '<dxf><font><color rgb="FF595959"/></font><fill><patternFill><bgColor rgb="FFEDEDED"/></patternFill></fill></dxf>'
          '</dxfs></styleSheet>')

ITEM_WIDTHS = [10, 30, 34, 60, 11, 16, 14, 40, 14, 14, 44, 24, 36, 40, 36, 36, 18, 20, 14]
OUTSTANDING_COLUMNS = ['ID', 'Area', 'Page/component', 'Priority', 'Status', 'Linked issue or finding', 'Notes', 'Known limitations']
IMPROVEMENT_COLUMNS = ['ID', 'Area', 'Page/component', 'Priority', 'Status', 'Potential future improvement', 'Notes', 'Linked issue or finding']


def _subset(rows, columns, keep):
    return [columns] + [[row[name] for name in columns] for row in rows if keep(row)]


def workbook(rows):
    """Bytes of an .xlsx: Summary (live), Items (editable table with drop-downs), Defects and Findings, Future Improvements. Reproducible for the same rows."""
    table = [COLUMNS] + [[row[name] for name in COLUMNS] for row in rows]
    lists = [(_column(COLUMNS.index(name)), options) for name, options in CHOICES.items()]
    outstanding = _subset(rows, OUTSTANDING_COLUMNS, lambda row: row['Status'] in {'Failed', 'Needs improvement', 'Blocked'} or row['Classification'] == 'Current defect'
                          or (row['Linked issue or finding'].strip() and row['Status'] != 'Passed'))
    ideas = _subset(rows, IMPROVEMENT_COLUMNS, lambda row: row['Potential future improvement'].strip() or row['Classification'] == 'Improvement opportunity')
    sheets = [('Summary', _summary_sheet(rows), None), ('Items', _sheet(table, ITEM_WIDTHS, lists, table_part=True, formats=True), _table_xml(COLUMNS, len(rows))),
              ('Defects and Findings', _sheet(outstanding, [10, 30, 34, 11, 16, 24, 60, 40], formats=True), None), ('Future Improvements', _sheet(ideas, [10, 30, 34, 11, 16, 60, 50, 24], formats=True), None)]
    parts = ['<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>',
             '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
             '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
             '<Override PartName="/xl/tables/table1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>']
    parts += [f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets) + 1)]
    files = {
        '[Content_Types].xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' + ''.join(parts) + '</Types>',
        '_rels/.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                           + ''.join(f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _, _) in enumerate(sheets, start=1)) + '</sheets><calcPr fullCalcOnLoad="1"/></workbook>',
        'xl/_rels/workbook.xml.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                      + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
                                      + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        'xl/styles.xml': STYLES,
        'xl/worksheets/_rels/sheet2.xml.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/table" Target="../tables/table1.xml"/></Relationships>',
        'xl/tables/table1.xml': sheets[1][2],
    }
    for i, (_, xml, _extra) in enumerate(sheets, start=1):
        files[f'xl/worksheets/sheet{i}.xml'] = xml
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return buffer.getvalue()


def read_items_sheet(data):
    """Rows of the Items sheet of an .xlsx (inline or shared strings) as dictionaries keyed by the header row."""
    namespace = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main', 'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            for item in ElementTree.fromstring(archive.read('xl/sharedStrings.xml')).findall('m:si', namespace):
                shared.append(''.join(node.text or '' for node in item.iter('{%s}t' % namespace['m'])))
        book = ElementTree.fromstring(archive.read('xl/workbook.xml'))
        relations = {rel.get('Id'): rel.get('Target') for rel in ElementTree.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        target = next((relations[sheet.get('{%s}id' % namespace['r'])] for sheet in book.find('m:sheets', namespace) if sheet.get('name') == 'Items'), 'worksheets/sheet1.xml')
        sheet = ElementTree.fromstring(archive.read('xl/' + target.lstrip('/').replace('xl/', '')))
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
    commands.add_parser('migrate')
    export = commands.add_parser('export')
    export.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    merging = commands.add_parser('merge')
    merging.add_argument('workbook', type=Path)
    args = parser.parse_args(argv)
    if args.command == 'migrate':
        if not is_legacy(args.csv):
            print('The tracker already uses the current layout.')
            return 0
        rows = migrate_legacy(read(args.csv))
        write(rows, args.csv)
        print(f'Migrated {len(rows)} items to the current layout.')
        return 0
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
