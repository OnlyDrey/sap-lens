"""Validated SoD source definitions; policy v1 supports observed two-sided TYPE S only.

This source describes potential transaction-derived conflicts, not effective SAP
permissions. Other TYPE values remain importable but are never evaluated by v1.
"""
import hashlib
import json
from pathlib import Path
from typing import ClassVar

from analysis_errors import AnalysisValidationError
from config_models import ImportProfile
from csv_import import CsvImport, MAX_ROWS

HEADERS = ('RISK', 'CRITICITY', 'TYPE', 'TEXT', 'ACTVT1', 'ACTVT2',
           'ACTIVITY_SLOT', 'ACTIVITY', 'TCODE', 'TTEXT')
FIELDS = HEADERS
EVALUATION_POLICY = 'sod-two-sided-v1'


class SodImportProfile(ImportProfile):
    fields: ClassVar[list[str]] = list(HEADERS)


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
