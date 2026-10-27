"""Private SoD business annotations, separate from immutable imported definitions.

Names, explanations and controls are operator-authored metadata, never inferred
from historical documents. Disabling a risk changes current analysis scope only.
"""
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import threading
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, field_validator
from config import atomic_write, config_dir, get_settings
from config_models import StrictModel

lock = threading.RLock()
MAX_BYTES = 20 * 1024 * 1024
MAX_RISKS = 5000
ReviewStatus = Literal['Needs description review', 'Reviewed']


class LocalMetadata(StrictModel):
    enabled: bool = True
    display_name: str = Field(default='', max_length=200)
    business_category: str = Field(default='', max_length=120)
    explanation_en: str = Field(default='', max_length=12000)
    explanation_no: str = Field(default='', max_length=12000)
    consequence_en: str = Field(default='', max_length=8000)
    consequence_no: str = Field(default='', max_length=8000)
    mitigating_controls_en: str = Field(default='', max_length=12000)
    mitigating_controls_no: str = Field(default='', max_length=12000)
    review_guidance_en: str = Field(default='', max_length=8000)
    review_guidance_no: str = Field(default='', max_length=8000)
    notes: str = Field(default='', max_length=8000)
    description_review_status: ReviewStatus = 'Needs description review'

    @field_validator('*')
    @classmethod
    def safe_text(cls, value):
        if isinstance(value, str):
            if any(ord(char) < 32 and char not in '\n\r\t' for char in value):
                raise ValueError('Metadata contains unsupported control characters.')
            return value.strip()
        return value


class StoredEntry(StrictModel):
    metadata: LocalMetadata
    observed_definition: str = Field(pattern=r'^[a-f0-9]{64}$')
    reviewed_definition: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    modified: str = Field(max_length=40)

    @field_validator('modified')
    @classmethod
    def valid_timestamp(cls, value):
        datetime.fromisoformat(value)
        return value


class CatalogueStorage(StrictModel):
    version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    entries: dict[str, StoredEntry] = Field(default_factory=dict, max_length=MAX_RISKS)

    @field_validator('entries')
    @classmethod
    def bounded_keys(cls, values):
        if any(not key or len(key) > 512 or any(ord(c) < 32 for c in key) for key in values):
            raise ValueError('Invalid risk identifier.')
        return values


def definition_version(definition):
    return hashlib.sha256(json.dumps(definition, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def read():
    path = config_dir() / 'sod-catalogue.json'
    if not path.exists():
        return CatalogueStorage()
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('Oversized catalogue')
        return CatalogueStorage.model_validate_json(raw)
    except (OSError, ValueError, TypeError, RecursionError):
        raise HTTPException(409, 'SoD catalogue annotations are unreadable or unsupported. Original storage is preserved; restore a local backup before editing.') from None


def write(data):
    # Revalidate even when an internal caller constructs a model via model_copy.
    data = CatalogueStorage.model_validate(data.model_dump())
    raw = data.model_dump_json().encode('utf-8')
    if len(raw) > MAX_BYTES:
        raise HTTPException(409, 'SoD catalogue storage is full. Existing annotations are preserved.')
    try:
        atomic_write(config_dir() / 'sod-catalogue.json', raw)
    except OSError:
        raise HTTPException(409, 'SoD catalogue could not be saved. Previous annotations are retained.') from None


@lru_cache(maxsize=2)
def _historical_definitions(directory, identities):
    """Content-addressed inputs only; refresh invalidates by immutable identities."""
    from csv_lifecycle import MAX_PRIVATE_BYTES
    from sod_import import build_sod
    definitions = {}
    try:
        for identity in identities:
            path = Path(directory) / 'csv-data' / 'snapshots' / f'{identity}.json'
            with path.open('rb') as stream:
                raw = stream.read(MAX_PRIVATE_BYTES + 1)
            if len(raw) > MAX_PRIVATE_BYTES or hashlib.sha256(raw).hexdigest() != identity:
                raise ValueError('Invalid source integrity')
            saved = json.loads(raw)
            if saved.get('version') != 1 or saved.get('source') != 'sod':
                raise ValueError('Invalid source version')
            parsed = build_sod(saved['records'], saved.get('report'))
            for risk in parsed['risks']:
                definitions[risk['risk_id']] = risk
        return definitions
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise HTTPException(409, 'A historical SoD source version is unavailable or invalid. Current imported data is retained; restore the missing source snapshot from a private backup.') from None


def catalogue(snapshot=None, settings=None, saved=None):
    import cache
    snapshot = snapshot if snapshot is not None else cache.get_snapshot()
    settings = settings if settings is not None else get_settings()
    saved = saved if saved is not None else read()
    identities = tuple(ref.snapshot for ref in settings.data_lifecycle.sod_history)
    definitions = dict(_historical_definitions(str(config_dir()), identities))
    current = {risk['risk_id']: risk for risk in snapshot.sod.get('risks', [])}
    definitions.update(current)
    items = []
    for risk_id, source in sorted(definitions.items()):
        stored = saved.entries.get(risk_id)
        metadata = stored.metadata.model_dump() if stored else LocalMetadata().model_dump()
        version = definition_version(source)
        changed = bool(stored and stored.observed_definition != version)
        reviewed = bool(stored and stored.reviewed_definition == version and metadata['description_review_status'] == 'Reviewed')
        review_status = 'Reviewed' if reviewed else 'Needs description review'
        items.append(dict(risk_id=risk_id, source=source, local=metadata,
                          current=risk_id in current, new=risk_id in current and stored is None,
                          source_changed=changed, description_review_status=review_status,
                          definition_version=version, modified=stored.modified if stored else None))
    reference = settings.data_lifecycle.sources.get('sod')
    return dict(items=items, revision=saved.revision,
                summary=dict(total=len(items), current=len(current),
                             enabled=sum(item['current'] and item['local']['enabled'] for item in items),
                             new=sum(item['new'] for item in items),
                             needs_description_review=sum(item['current'] and item['description_review_status'] != 'Reviewed' for item in items),
                             unsupported=sum(item['current'] and not item['source']['supported'] for item in items)),
                source=dict(loaded=bool(snapshot.sod), records=len(snapshot.sod.get('records', [])),
                            risks=len(current), version=snapshot.sod.get('content_hash'),
                            imported_at=reference.imported_at if reference else None,
                            checked_at=reference.checked_at if reference else None))


def _expect(saved, expected):
    if saved.revision != expected:
        raise HTTPException(409, 'SoD catalogue changed. Reload before saving your edits.')


def save(risk_id, metadata, expected_revision, expected_definition):
    import cache
    with lock, cache._load_lock:
        saved = read()
        _expect(saved, expected_revision)
        current = catalogue(saved=saved)
        item = next((row for row in current['items'] if row['risk_id'] == risk_id), None)
        if item is None:
            raise HTTPException(404, 'SoD risk is not present in the current or retained source history.')
        if item['definition_version'] != expected_definition:
            raise HTTPException(409, 'The SoD source definition changed. Reload before saving metadata.')
        if risk_id not in saved.entries and len(saved.entries) >= MAX_RISKS:
            raise HTTPException(409, 'SoD catalogue capacity is reached. Existing annotations are retained.')
        metadata = LocalMetadata.model_validate(metadata.model_dump() if isinstance(metadata, LocalMetadata) else metadata)
        saved.entries[risk_id] = StoredEntry(metadata=metadata, observed_definition=expected_definition,
                                             reviewed_definition=expected_definition if metadata.description_review_status == 'Reviewed' else None,
                                             modified=datetime.now(timezone.utc).isoformat())
        saved.revision += 1
        write(saved)
        result = next(row for row in catalogue(saved=saved)['items'] if row['risk_id'] == risk_id)
        return dict(item=result, revision=saved.revision)


def bulk(enabled, expected_revision, confirm=False):
    if not enabled and not confirm:
        raise HTTPException(422, 'Confirm disabling all current SoD risks. Historical findings and reviews will be retained.')
    import cache
    with lock, cache._load_lock:
        saved = read()
        _expect(saved, expected_revision)
        current = catalogue(saved=saved)
        identifiers = {item['risk_id'] for item in current['items'] if item['current']}
        if len(set(saved.entries) | identifiers) > MAX_RISKS:
            raise HTTPException(409, 'SoD catalogue capacity is reached. Existing annotations are retained.')
        stamp = datetime.now(timezone.utc).isoformat()
        for item in current['items']:
            if not item['current']:
                continue
            previous = saved.entries.get(item['risk_id'])
            metadata = LocalMetadata.model_validate(item['local'])
            metadata.enabled = enabled
            saved.entries[item['risk_id']] = StoredEntry(metadata=metadata,
                observed_definition=previous.observed_definition if previous else item['definition_version'],
                reviewed_definition=previous.reviewed_definition if previous else None, modified=stamp)
        saved.revision += 1
        write(saved)
        return dict(revision=saved.revision, updated=current['summary']['current'], enabled=enabled)
