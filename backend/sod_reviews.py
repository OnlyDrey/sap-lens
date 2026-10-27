"""Private justified SoD review annotations; never changes imported SAP evidence.

Reviewer names are self-reported, not authenticated identities. Each edit appends
an immutable evidence-bearing event; source absence is historical, not resolution.
"""
from datetime import date, datetime, timezone
import json
import re
import threading
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ConfigDict, Field, field_validator, model_validator
from config import atomic_write, config_dir
from config_models import StrictModel
from csv_lifecycle import read_private, write_private

lock = threading.RLock()
MAX_BYTES = 20 * 1024 * 1024
MAX_FINDING_BYTES = 4 * 1024 * 1024
MAX_REVIEWS = 10000
MAX_EVENTS = 1000
CONTEXT_PATTERN = r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'
IDENTITY_NOTICE = 'Self-reported reviewer; not an authenticated or verified identity.'
Decision = Literal['Pending review', 'Accepted with mitigating controls', 'Access removal required',
                   'Not applicable / false positive', 'Further investigation required']
ActionStatus = Literal['Not started', 'In progress', 'Completed', 'Not applicable']


class Annotation(StrictModel):
    decision: Decision
    reviewer: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=1, max_length=4000)
    comments: str = Field(default='', max_length=4000)
    mitigating_controls: str = Field(default='', max_length=8000)
    action_owner: str = Field(default='', max_length=120)
    target_date: date | None = None
    action_status: ActionStatus = 'Not started'
    completion_notes: str = Field(default='', max_length=4000)

    @field_validator('*', mode='before')
    @classmethod
    def readable_text(cls, value):
        if isinstance(value, str):
            if any(ord(char) < 32 and char not in '\n\r\t' for char in value):
                raise ValueError('Review text contains unsupported control characters.')
            return value.strip()
        return value

    @field_validator('reviewer', 'rationale')
    @classmethod
    def required_text(cls, value):
        if not value:
            raise ValueError('Reviewer and justification are required.')
        return value

    @model_validator(mode='after')
    def completed_notes(self):
        if self.decision == 'Accepted with mitigating controls' and not self.mitigating_controls:
            raise ValueError('Describe the mitigating controls before accepting this finding.')
        if self.action_status == 'Completed' and not self.completion_notes:
            raise ValueError('Completion notes are required for a completed action.')
        return self


class SourceProvenance(StrictModel):
    child_agr: str | None = Field(default=None, max_length=512)
    parent_agr: str | None = Field(default=None, max_length=512)
    effective_role: str | None = Field(default=None, max_length=512)


class EvidencePath(StrictModel):
    matched_catalogue_pattern: str = Field(min_length=1, max_length=512)
    single_role: str = Field(min_length=1, max_length=512)
    assignment_kind: str = Field(min_length=1, max_length=64)
    tcode: str = Field(min_length=1, max_length=512)
    source_provenance: list[SourceProvenance] = Field(default_factory=list, max_length=10000)
    activity_slot: Literal['ACTVT1', 'ACTVT2']
    activity: str = Field(min_length=1, max_length=512)
    matrix_transaction: str = Field(min_length=1, max_length=512)
    actual_assigned_role: str = Field(min_length=1, max_length=512)
    matching_status: Literal['exact', 'wildcard']
    role_valid_from: date | None = None
    role_valid_to: date | None = None
    interval_status: Literal['active', 'expired', 'future', 'unknown']
    user_group: str = Field(default='', max_length=4096)


class AccountRecord(StrictModel):
    valid_from: date | None = None
    valid_to: date | None = None
    locked: bool | None = None
    user_type: str = Field(default='', max_length=4096)
    user_group: str = Field(default='', max_length=4096)


class AccountEvidence(StrictModel):
    accounts: list[AccountRecord] = Field(default_factory=list, max_length=10000)
    directory_match: str = Field(max_length=120)
    ad_status: Literal['Enabled', 'Disabled', 'Unknown']


class RiskMetadata(StrictModel):
    display_name: str = Field(default='', max_length=200)
    source_text: str = Field(default='', max_length=4096)
    business_category: str = Field(default='', max_length=120)
    risk_type: str = Field(default='', max_length=4096)


class Finding(StrictModel):
    finding_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    subject: str = Field(min_length=1, max_length=512)
    kind: Literal['user']
    risk_id: str = Field(min_length=1, max_length=512)
    criticality: str = Field(min_length=1, max_length=4096)
    evaluation_policy: str = Field(min_length=1, max_length=120)
    evidence: dict[Literal['ACTVT1', 'ACTVT2'], list[EvidencePath]] = Field(max_length=2)
    current_potential: bool
    account: AccountEvidence | None = None
    evidence_version: str = Field(pattern=r'^[a-f0-9]{64}$')
    risk: RiskMetadata | None = None
    source_versions: dict[str, str] = Field(default_factory=dict, max_length=4)
    evaluation_as_of: date | None = None

    @field_validator('source_versions')
    @classmethod
    def source_hashes(cls, value):
        if set(value) - {'roles', 'users', 'sod', 'employees'} or any(not re.fullmatch(r'[a-f0-9]{64}', identity) for identity in value.values()):
            raise ValueError('Source versions must reference supported immutable snapshots.')
        return value

    @model_validator(mode='after')
    def valid_sides(self):
        if set(self.evidence) != {'ACTVT1', 'ACTVT2'} or any(not paths for paths in self.evidence.values()):
            raise ValueError('A review requires complete evidence for both SoD activity sides.')
        for side, paths in self.evidence.items():
            if len(paths) > 100000 or any(path.activity_slot != side for path in paths):
                raise ValueError('Invalid SoD evidence-side structure.')
        if len(self.model_dump_json().encode('utf-8')) > MAX_FINDING_BYTES:
            raise ValueError('The finding exceeds the review evidence storage limit.')
        return self


class ReviewEvent(StrictModel):
    model_config = ConfigDict(extra='forbid', validate_default=True, frozen=True)
    event_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    context: str = Field(pattern=CONTEXT_PATTERN)
    timestamp: str = Field(max_length=40)
    finding_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    evidence_version: str = Field(pattern=r'^[a-f0-9]{64}$')
    annotation: Annotation
    finding_snapshot: str = Field(pattern=r'^[a-f0-9]{64}$')
    subject: str = Field(min_length=1, max_length=512)
    risk_id: str = Field(min_length=1, max_length=512)

    @field_validator('timestamp')
    @classmethod
    def utc_timestamp(cls, value):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise ValueError('Review timestamps must use UTC.')
        return value

class ReviewStorage(StrictModel):
    version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    contexts: dict[str, dict[str, list[ReviewEvent]]] = Field(default_factory=dict, max_length=1000)

    @model_validator(mode='after')
    def consistent_history(self):
        count, event_ids = 0, set()
        for context, reviews in self.contexts.items():
            if not re.fullmatch(CONTEXT_PATTERN, context):
                raise ValueError('Invalid review context.')
            count += len(reviews)
            for finding_id, events in reviews.items():
                if not re.fullmatch(r'[a-f0-9]{64}', finding_id) or not events or len(events) > MAX_EVENTS:
                    raise ValueError('Invalid review history.')
                for event in events:
                    if event.context != context or event.finding_id != finding_id or event.event_id in event_ids:
                        raise ValueError('Inconsistent review history.')
                    event_ids.add(event.event_id)
        if count > MAX_REVIEWS:
            raise ValueError('Review storage capacity is reached.')
        return self


def _context(value):
    if not isinstance(value, str) or not re.fullmatch(CONTEXT_PATTERN, value):
        raise HTTPException(422, 'Choose a supported review context identifier.')
    return value


def read():
    path = config_dir() / 'sod-reviews.json'
    if not path.exists():
        return ReviewStorage()
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('Oversized review data')
        return ReviewStorage.model_validate_json(raw)
    except (OSError, ValueError, TypeError, RecursionError):
        raise HTTPException(409, 'SoD review history is unreadable or unsupported. Original data is retained; restore a private backup before editing.') from None


def _write(data):
    try:
        validated = ReviewStorage.model_validate(data.model_dump())
        raw = validated.model_dump_json().encode('utf-8')
        if len(raw) > MAX_BYTES:
            raise ValueError('Oversized review data')
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(409, 'SoD review storage capacity or format is invalid. Existing history is retained.') from None
    try:
        atomic_write(config_dir() / 'sod-reviews.json', raw)
    except OSError:
        raise HTTPException(409, 'SoD review history could not be saved. Previous events are retained.') from None


def save(finding, annotation, expected_revision, expected_evidence_version, context='current'):
    context = _context(context)
    # Model validation errors intentionally remain Pydantic errors for API 422 handling.
    finding = Finding.model_validate(finding.model_dump() if isinstance(finding, Finding) else finding)
    annotation = Annotation.model_validate(annotation.model_dump() if isinstance(annotation, Annotation) else annotation)
    if expected_evidence_version != finding.evidence_version:
        raise HTTPException(409, 'SoD finding evidence changed. Reload before recording a decision.')
    with lock:
        data = read()
        if data.revision != expected_revision:
            raise HTTPException(409, 'SoD reviews changed. Reload before saving a decision.')
        reviews = data.contexts.get(context, {})
        events = reviews.get(finding.finding_id, [])
        count = sum(len(items) for items in data.contexts.values())
        if not events and count >= MAX_REVIEWS or len(events) >= MAX_EVENTS:
            raise HTTPException(409, 'SoD review history capacity is reached. Existing events are retained; preserve a private backup before recovery.')
        if events:
            finding_for_event(events[-1])
        try:
            identity = write_private('snapshots', dict(version=1, source='sod-review-finding', finding=finding.model_dump(mode='json')))
        except (OSError, ValueError):
            raise HTTPException(409, 'SoD review evidence could not be staged. Previous review events are retained.') from None
        event = ReviewEvent(event_id=uuid4().hex, context=context,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            finding_id=finding.finding_id, evidence_version=finding.evidence_version,
                            annotation=annotation, finding_snapshot=identity,
                            subject=finding.subject, risk_id=finding.risk_id)
        data.contexts[context] = {**reviews, finding.finding_id: [*events, event]}
        data.revision += 1
        _write(data)
        return dict(event=event.model_dump(mode='json'), revision=data.revision,
                    reviewer_identity=IDENTITY_NOTICE)


def listing(current_findings, context='current', coverage=None):
    context = _context(context)
    # Snapshot copies prevent caller mutation from changing retained review evidence.
    current = {item['finding_id']: item for item in json.loads(json.dumps(current_findings))}
    with lock:
        data = read()
    saved = data.contexts.get(context, {})
    result = []
    for finding_id in sorted(set(current) | set(saved)):
        events = saved.get(finding_id, [])
        event = events[-1] if events else None
        present = finding_id in current
        finding = current.get(finding_id) if present else finding_for_event(event)
        stale = bool(event and (not present or event.evidence_version != finding['evidence_version']))
        decision = event.annotation.decision if event else 'Pending review'
        lifecycle = ('Historical' if not present else 'Outdated' if stale else 'Pending' if decision == 'Pending review'
                     else 'Reviewed' if decision in {'Accepted with mitigating controls', 'Not applicable / false positive'}
                     else 'Action required')
        result.append(dict(finding_id=finding_id, finding=finding,
                           decision=decision, event=event.model_dump(mode='json') if event else None,
                           history_count=len(events), stale=stale, lifecycle=lifecycle,
                           presence='current' if present else 'historical'))
    return dict(items=result, revision=data.revision, context=context, coverage=coverage,
                reviewer_identity=IDENTITY_NOTICE,
                summary={name: sum(item['lifecycle'] == name for item in result)
                         for name in ('Pending', 'Reviewed', 'Action required', 'Outdated', 'Historical')})


def finding_for_event(event):
    """Hydrate one requested immutable observation, never entire review histories."""
    try:
        event = ReviewEvent.model_validate(event.model_dump() if isinstance(event, ReviewEvent) else event)
        saved = read_private('snapshots', event.finding_snapshot)
        if saved.get('source') != 'sod-review-finding':
            raise ValueError('Unexpected review snapshot type')
        finding = Finding.model_validate(saved['finding'])
        if (finding.finding_id != event.finding_id or finding.evidence_version != event.evidence_version
                or finding.subject != event.subject or finding.risk_id != event.risk_id):
            raise ValueError('Review snapshot metadata differs')
        return finding.model_dump(mode='json')
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise HTTPException(409, 'Retained SoD review evidence is unavailable or invalid. Review history is preserved; restore its snapshot from a private backup.') from None


def history(finding_id, context='current'):
    context = _context(context)
    if not re.fullmatch(r'[a-f0-9]{64}', finding_id):
        raise HTTPException(422, 'Choose a valid finding identifier.')
    with lock:
        events = read().contexts.get(context, {}).get(finding_id, [])
    return [event.model_dump(mode='json') for event in reversed(events)]
