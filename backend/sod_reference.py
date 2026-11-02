"""Versioned private business reference library; never an active SoD source."""
import hashlib
import io
import re
import zipfile
from datetime import datetime, timezone
from functools import lru_cache
from typing import Literal

from fastapi import HTTPException
from lxml import etree
from pydantic import Field, field_validator
from config import atomic_write, config_dir
from config_models import StrictModel
from sod_catalogue import ActivityMetadata, LocalMetadata, lock

MAX_BYTES = 2 * 1024 * 1024
MAX_EXPANDED = 12 * 1024 * 1024
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
RISK = {'Display name': 'display_name', 'Business area': 'business_category', 'Business explanation': 'explanation_en',
        'Risk consequence': 'consequence_en', 'Mitigating controls': 'mitigating_controls_en', 'Review Guidance': 'review_guidance_en', 'Local notes': 'notes'}
ACTIVITY = {key: value for key, value in RISK.items() if key not in ('Risk consequence', 'Mitigating controls')}


class Library(StrictModel):
    version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    digest: str = Field(default='', pattern=r'^(?:[a-f0-9]{64})?$')
    imported_at: str = ''
    risks: dict[str, dict[str, str]] = Field(default_factory=dict, max_length=5000)
    activities: dict[str, dict[str, str]] = Field(default_factory=dict, max_length=5000)
    terms: dict[str, str] = Field(default_factory=dict, max_length=100)

    @field_validator('terms')
    @classmethod
    def validate_terms(cls, values):
        if any(not key or len(key) > 200 or not value or len(value) > 12000 for key, value in values.items()):
            raise ValueError('Invalid reference terminology.')
        return values

    @field_validator('risks', 'activities')
    @classmethod
    def validate_records(cls, values, info):
        model, allowed = (LocalMetadata, set(RISK.values())) if info.field_name == 'risks' else (ActivityMetadata, set(ACTIVITY.values()))
        for identifier, metadata in values.items():
            if not re.fullmatch(r'[A-Za-z0-9_:-]{1,128}', identifier) or set(metadata) - allowed:
                raise ValueError('Invalid reference record.')
            model.model_validate(metadata)
        return values


@lru_cache(maxsize=2)
def _decode(raw):
    return Library.model_validate_json(raw)


def read():
    path = config_dir() / 'sod-reference.json'
    if not path.exists():
        return Library()
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_EXPANDED + 1)
        if len(raw) > MAX_EXPANDED:
            raise ValueError('Oversized library')
        return _decode(raw).model_copy(deep=True)
    except (OSError, ValueError, TypeError, RecursionError):
        raise HTTPException(409, 'SoD reference library is unreadable. Original data is preserved; restore a backup before replacing it.') from None


def parse(raw):
    """Bounded XLSX reading, no formulas, external entities, links, macros or inferred IDs."""
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError('Choose a non-empty XLSX workbook up to 2 MB.')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files = archive.infolist()
            if len(files) > 100 or len({item.filename for item in files}) != len(files) or sum(item.file_size for item in files) > MAX_EXPANDED:
                raise ValueError('Workbook exceeds safe archive limits.')
            if any('externallinks/' in item.filename.lower() or 'vbaproject' in item.filename.lower() for item in files):
                raise ValueError('External links and macros are not supported.')

            def xml(name):
                data = archive.read(name)
                if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                    raise ValueError('XML declarations are not supported.')
                return etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))

            strings = [''.join(item.itertext()) for item in xml('xl/sharedStrings.xml').findall('s:si', NS)] if 'xl/sharedStrings.xml' in archive.namelist() else []
            rels = {item.get('Id'): item.get('Target') for item in xml('xl/_rels/workbook.xml.rels')}
            sheets = {}
            text_budget = 0
            for sheet in xml('xl/workbook.xml').findall('s:sheets/s:sheet', NS):
                name = sheet.get('name')
                if name not in ('Risks', 'Activities', 'Definitions'):
                    continue
                target = rels[sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')]
                path = target.lstrip('/') if target.startswith('/') else 'xl/' + target
                if '..' in path.split('/'):
                    raise ValueError('Invalid workbook reference.')
                if name in sheets:
                    raise ValueError('Duplicate reference sheet.')
                rows = []
                for row in xml(path).findall('s:sheetData/s:row', NS):
                    cells = {}
                    for cell in row:
                        if cell.find('s:f', NS) is not None:
                            raise ValueError('Formula cells are not supported in reference definitions.')
                        coordinate = cell.get('r', '')
                        match = re.fullmatch(r'([A-Z]{1,2})[0-9]+', coordinate)
                        if not match:
                            raise ValueError('Invalid cell reference.')
                        value = cell.find('s:v', NS)
                        text = value.text or '' if value is not None else ''
                        if cell.get('t') == 's':
                            text = strings[int(text)]
                        elif cell.get('t') == 'inlineStr':
                            text = ''.join(cell.find('s:is', NS).itertext())
                        text_budget += len(text)
                        if text_budget > MAX_EXPANDED:
                            raise ValueError('Workbook expanded text exceeds its safe limit.')
                        if len(text) > 12000:
                            raise ValueError('A reference field exceeds its size limit.')
                        cells[match[1]] = text.strip()
                    if any(cells.values()):
                        rows.append(cells)
                if len(rows) > 5001:
                    raise ValueError('Too many reference records.')
                sheets[name] = rows
            result = Library(digest=hashlib.sha256(raw).hexdigest())
            for title, id_header, mapping, model, destination in (
                ('Risks', 'Risk', RISK, LocalMetadata, result.risks),
                ('Activities', 'Activity', ACTIVITY, ActivityMetadata, result.activities),
            ):
                rows = sheets.get(title, [])
                if len(rows) < 2:
                    raise ValueError(f'{title} must contain a header and definitions.')
                header = rows[0]
                if len(set(header.values())) != len(header) or set(header.values()) != {id_header, *mapping}:
                    raise ValueError(f'{title} headers do not match the supported reference workbook.')
                for row in rows[1:]:
                    if set(row) - set(header):
                        raise ValueError('Reference row contains an unheaded column.')
                    values = {header.get(column, ''): value for column, value in row.items()}
                    identifier = values.get(id_header, '')
                    if not re.fullmatch(r'[A-Za-z0-9_:-]{1,128}', identifier) or identifier in destination:
                        raise ValueError(f'{title} contains a missing, invalid or duplicate exact identifier.')
                    metadata = model.model_validate({field: values.get(column, '') for column, field in mapping.items()})
                    destination[identifier] = {field: getattr(metadata, field) for field in mapping.values() if getattr(metadata, field)}
            terms = sheets.get('Definitions', [])
            if terms:
                if terms[0] != {'A': 'Term', 'B': 'Definition'}:
                    raise ValueError('Definitions headers must be Term and Definition.')
                for row in terms[1:]:
                    if not row.get('A') or not row.get('B') or row['A'] in result.terms:
                        raise ValueError('Definitions contain missing or duplicate terms.')
                    result.terms[row['A']] = row['B']
            return Library.model_validate(result.model_dump())
    except (zipfile.BadZipFile, KeyError, IndexError, TypeError, RuntimeError, NotImplementedError, OSError, etree.XMLSyntaxError) as error:
        raise ValueError('The file is not a supported reference XLSX workbook.') from error


def install(raw, expected_revision):
    try:
        candidate = parse(raw)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    with lock:
        previous = read()
        if previous.revision != expected_revision:
            raise HTTPException(409, 'Reference library changed. Reload before replacing it.')
        if previous.digest == candidate.digest:
            return previous
        candidate.revision = previous.revision + 1
        candidate.imported_at = datetime.now(timezone.utc).isoformat()
        encoded = candidate.model_dump_json().encode()
        if len(encoded) > MAX_EXPANDED:
            raise HTTPException(422, 'Reference library exceeds its storage limit.')
        try:
            atomic_write(config_dir() / 'sod-reference.json', encoded)
        except OSError:
            raise HTTPException(409, 'Reference library could not be saved. Previous definitions are retained.') from None
        return candidate


def summary(library=None):
    value = library if library is not None else read()
    return dict(version=value.version, revision=value.revision, digest=value.digest, imported_at=value.imported_at,
                risks=len(value.risks), activities=len(value.activities), terms=len(value.terms))


def status(library=None, snapshot=None):
    import cache
    library = library if library is not None else read()
    snapshot = snapshot if snapshot is not None else cache.get_snapshot()
    risks = (snapshot.sod or {}).get('risks', [])
    risk_ids = {item['risk_id'] for item in risks}
    activity_ids = {row['activity'] for item in risks for slot in ('ACTVT1', 'ACTVT2') for row in item['activities'][slot]}
    return {**summary(library), 'installed': bool(library.digest),
            'matched_risks': len(risk_ids & library.risks.keys()), 'matched_activities': len(activity_ids & library.activities.keys()),
            'unmatched_risks': sorted(library.risks.keys() - risk_ids), 'unmatched_activities': sorted(library.activities.keys() - activity_ids),
            'missing_risks': sorted(risk_ids - library.risks.keys()), 'missing_activities': sorted(activity_ids - library.activities.keys())}
