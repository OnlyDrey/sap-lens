"""Validated SoD source definitions; policy v1 supports observed two-sided TYPE S only.

This source describes potential transaction-derived conflicts, not effective SAP
permissions. Other TYPE values remain importable but are never evaluated by v1.
"""
import hashlib
import json
from pathlib import Path
from typing import ClassVar

from analysis_errors import AnalysisValidationError
from config_models import SOD_FIELDS, SodImportProfile
from csv_import import CsvImport, MAX_ROWS

HEADERS = tuple(SOD_FIELDS)
FIELDS = HEADERS
EVALUATION_POLICY = 'sod-two-sided-v1'


class SodCsvImport(CsvImport):
    fields = HEADERS
    required = 'RISK'
    identifier_fields = ['RISK', 'ACTVT1', 'ACTVT2', 'ACTIVITY', 'TCODE']

    def records(self):
        for row in super().records():
            if any(not self.mapping.get(field) for field in HEADERS):
                raise AnalysisValidationError('SoD requires all documented headers, including TTEXT.')
            yield row
        if any(not self.mapping.get(field) for field in HEADERS):
            raise AnalysisValidationError('SoD requires all documented headers, including TTEXT.')


def build_sod(records, report=None):
    """Validate/rebuild canonical source records, including persisted snapshots.

    Identical rows are deduplicated; ordering does not affect content_hash.
    Empty TTEXT values are warnings; every other field is required. Identifiers
    remain case-sensitive and are never translated or normalized into labels.
    """
    canonical = {}
    risks = {}
    missing_text = 0
    duplicates = 0
    parsed_rows = 0
    for index, raw in enumerate(records):
        parsed_rows += 1
        if index >= MAX_ROWS:
            raise AnalysisValidationError('SoD exceeds the one-million-record safety limit.')
        if not isinstance(raw, dict) or set(raw) != set(HEADERS):
            raise AnalysisValidationError('SoD records must contain exactly the documented fields.')
        if any(not isinstance(raw[field], str) for field in HEADERS):
            raise AnalysisValidationError('SoD fields must be text.')
        row = {field: raw[field].strip() for field in HEADERS}
        if any(len(value) > 4096 or '\x00' in value for value in row.values()):
            raise AnalysisValidationError('SoD contains invalid or oversized fields.')
        if any(len(row[field]) > 512 for field in SodCsvImport.identifier_fields):
            raise AnalysisValidationError('A SoD identifier is too long.')
        if any(not row[field] for field in HEADERS if field != 'TTEXT'):
            raise AnalysisValidationError('A SoD record is missing a required value.')
        slot = row['ACTIVITY_SLOT']
        if slot not in ('ACTVT1', 'ACTVT2') or row['ACTIVITY'] != row.get(slot):
            raise AnalysisValidationError('SoD ACTIVITY_SLOT must be ACTVT1 or ACTVT2 and reference the matching ACTIVITY.')
        if row['ACTVT1'] == row['ACTVT2']:
            raise AnalysisValidationError('SoD requires two distinct activity definitions.')
        key = tuple(row[field] for field in HEADERS)
        if key in canonical:
            duplicates += 1
            continue
        canonical[key] = row
        definition = (row['CRITICITY'], row['TYPE'], row['TEXT'], row['ACTVT1'], row['ACTVT2'])
        entry = risks.setdefault(row['RISK'], {'definition': definition, 'ACTVT1': {}, 'ACTVT2': {}})
        if entry['definition'] != definition:
            raise AnalysisValidationError('SoD contains conflicting definitions for the same risk.')
        activity_key = (row['ACTIVITY'], row['TCODE'])
        previous = entry[slot].get(activity_key)
        if previous is not None and previous != row['TTEXT']:
            raise AnalysisValidationError('SoD contains conflicting descriptions for the same activity transaction.')
        entry[slot][activity_key] = row['TTEXT']
        missing_text += not bool(row['TTEXT'])
    if not canonical:
        raise AnalysisValidationError('An empty SoD dataset cannot replace the current source.')
    definitions = []
    for risk_id, entry in sorted(risks.items()):
        if not entry['ACTVT1'] or not entry['ACTVT2']:
            raise AnalysisValidationError('Every SoD risk requires transaction mappings for both activity sides.')
        criticality, risk_type, source_text, activity1, activity2 = entry['definition']
        supported = risk_type == 'S'
        definitions.append(dict(risk_id=risk_id, criticality=criticality, risk_type=risk_type,
                                source_text=source_text, activity1=activity1, activity2=activity2,
                                activities={slot: [dict(activity=a, tcode=t, ttext=text)
                                                  for (a, t), text in sorted(entry[slot].items())]
                                            for slot in ('ACTVT1', 'ACTVT2')},
                                supported=supported, evaluation_policy=EVALUATION_POLICY if supported else None))
    rows = [canonical[key] for key in sorted(canonical)]
    warnings = list((report or {}).get('warnings', []))
    if duplicates:
        warnings.append(f'{duplicates} identical duplicate SoD records were deduplicated.')
    if missing_text:
        warnings.append(f'{missing_text} SoD transaction mappings have no TTEXT description.')
    unsupported = sum(not risk['supported'] for risk in definitions)
    if unsupported:
        warnings.append(f'{unsupported} SoD risk definitions have unsupported TYPE values and will not be evaluated.')
    overlaps = sum(bool({item['tcode'] for item in risk['activities']['ACTVT1']}
                        & {item['tcode'] for item in risk['activities']['ACTVT2']})
                   for risk in definitions)
    if overlaps:
        warnings.append(f'{overlaps} SoD risk definitions contain overlapping transaction codes between activity sides; definition overlap needs review.')
    warnings = list(dict.fromkeys(warnings))
    final_report = dict(report or {})
    final_report.setdefault('parsed_rows', parsed_rows)
    final_report.setdefault('unique_records', len(rows))
    final_report.setdefault('duplicate_rows', duplicates)
    final_report['warnings'] = warnings.copy()
    digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode()).hexdigest()
    return dict(version=1, source='sod', records=rows, risks=definitions,
                content_hash=digest, warnings=warnings, report=final_report)


def parse_sod(path, profile=None):
    if profile is None:
        profile = SodImportProfile(id='sod', name='SoD source')
    elif isinstance(profile, dict):
        profile = SodImportProfile.model_validate(profile)
    else:
        profile = SodImportProfile.model_validate(profile.model_dump())
    importer = SodCsvImport(Path(path), profile)
    records = list(importer.records())
    return build_sod(records, importer.report())


# Read-only description of the fixed SoD schema: what each documented column means to the parser. A mapping only chooses the source header that carries a column.
COLUMN_MEANING = {
    'RISK': 'Risk identifier (case-sensitive); groups the rows of one risk definition',
    'CRITICITY': 'Source criticality label, kept and shown literally as evidence',
    'TYPE': 'Risk type; only S risks are evaluated, others are kept but not evaluated',
    'TEXT': 'Source description of the risk',
    'ACTVT1': 'Name of the first required activity of the risk',
    'ACTVT2': 'Name of the second required activity of the risk',
    'ACTIVITY_SLOT': 'ACTVT1 or ACTVT2: the activity side this transaction mapping belongs to',
    'ACTIVITY': 'Activity that the transaction supplies on that side',
    'TCODE': 'Transaction code that supplies the activity',
    'TTEXT': 'Transaction description (optional; an empty value is only a warning)',
}


def inspection(sod):
    """Counts, column interpretation, validation checks and quality warnings of a parsed SoD dataset. Pure and read-only."""
    from collections import Counter
    report, risks, records = sod.get('report') or {}, sod.get('risks') or [], sod.get('records') or []
    detected, mapping = report.get('detected_columns') or [], report.get('resolved_mapping') or {}
    columns = [dict(column=field, detected=mapping.get(field) or (field if field in detected else ''), meaning=COLUMN_MEANING[field], required=field != 'TTEXT') for field in HEADERS]
    activities = {item['activity'] for risk in risks for slot in risk['activities'].values() for item in slot}
    transactions = {item['tcode'] for risk in risks for slot in risk['activities'].values() for item in slot}
    unsupported = [risk for risk in risks if not risk['supported']]
    overlapping = [risk['risk_id'] for risk in risks if {item['tcode'] for item in risk['activities']['ACTVT1']} & {item['tcode'] for item in risk['activities']['ACTVT2']}]
    missing_text = sum(not row['TTEXT'] for row in records)
    duplicates = int(report.get('duplicate_rows') or 0)
    present = sum(bool(item['detected']) for item in columns)
    checks = [
        dict(name='Documented columns', status='passed', detail=f'{present} of {len(HEADERS)} documented columns were found; the schema is fixed; a mapping only chooses the source header of each column.'),
        dict(name='Required values', status='passed', detail='Every row has RISK, CRITICITY, TYPE, TEXT, ACTVT1, ACTVT2, ACTIVITY_SLOT, ACTIVITY and TCODE.'),
        dict(name='Activity sides', status='passed', detail='Every risk has transaction mappings for both activity sides.'),
        dict(name='Evaluated risk types', status='warning' if unsupported else 'passed', detail=f'{len(unsupported)} risks have a TYPE other than S and are kept but not evaluated.' if unsupported else 'Every risk has an evaluated TYPE (S).'),
        dict(name='Duplicate rows', status='warning' if duplicates else 'passed', detail=f'{duplicates} identical rows were deduplicated.' if duplicates else 'No duplicate rows.'),
        dict(name='Transaction descriptions', status='warning' if missing_text else 'passed', detail=f'{missing_text} mappings have no TTEXT.' if missing_text else 'Every mapping has a TTEXT.'),
        dict(name='Overlapping transactions', status='warning' if overlapping else 'passed', detail=f'{len(overlapping)} risks share a transaction code between their two activity sides; the definition needs review.' if overlapping else 'No risk shares a transaction code between its activity sides.'),
    ]
    return dict(
        columns=columns,
        counts=dict(parsed_rows=int(report.get('parsed_rows') or len(records)), records=len(records), duplicate_rows=duplicates, risks=len(risks), evaluated_risks=len(risks) - len(unsupported),
                    unsupported_risks=len(unsupported), activities=len(activities), transactions=len(transactions)),
        criticality=dict(sorted(Counter(risk['criticality'] for risk in risks).items())), types=dict(sorted(Counter(risk['risk_type'] for risk in risks).items())),
        checks=checks, warnings=list(sod.get('warnings') or []), file_name=report.get('file_name') or '',
        samples=[{field: str(row.get(field, '')) for field in HEADERS} for row in (report.get('samples') or records)[:20]])


def inspect_file(path, profile):
    """Read-only inspection of a candidate SoD CSV with the given format and mapping: detected header, per-column mapping state, parser errors,
    counts, validation checks and sample rows. Parses the file exactly as an import would but never stores anything. Raises
    AnalysisValidationError only for an unusable path; unreadable or invalid content is reported in ``errors``."""
    importer = SodCsvImport(Path(path), profile)
    result = dict(valid=False, errors=[], format=dict(delimiter=profile.delimiter, encoding=profile.encoding), headers=[], issues=[], file_name=Path(path).name)
    try:
        head = importer.inspect_header()
    except AnalysisValidationError as exc:
        result['errors'].append(str(exc))
        head = None
    except Exception:
        result['errors'].append('The CSV header could not be read. Check the path, encoding and delimiter.')
        head = None
    proposed = head['proposed_mapping'] if head else {}
    if head:
        result.update(headers=head['detected_columns'], issues=head['issues'], format=dict(delimiter=head['delimiter'], encoding=head['encoding']))
    columns = []
    for field in HEADERS:
        manual = profile.mapping.get(field, '')
        found = manual or proposed.get(field, '')
        columns.append(dict(column=field, detected=found, state='manual' if manual else 'detected' if found else 'missing',
                            meaning=COLUMN_MEANING[field], required=field != 'TTEXT'))
    result.update(columns=columns, proposed_mapping=proposed)
    if not head:
        return result
    try:
        sod = parse_sod(path, profile)
    except AnalysisValidationError as exc:
        result['errors'].append(str(exc))
        return result
    except Exception:
        result['errors'].append('The CSV could not be parsed. Check the delimiter, encoding, mapping and that every row has the header width.')
        return result
    detail = inspection(sod)
    result.update(valid=True, **{key: detail[key] for key in ('counts', 'criticality', 'types', 'checks', 'warnings', 'samples')})
    return result
