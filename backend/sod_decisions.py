"""Private SoD 2.0 decisions: activity, role-assignment and risk-acceptance events, remediation actions.

Each kind is an append-only event history per (context, subject key). Events retain the evidence
they were made against in an immutable content-addressed snapshot and never change imported SAP
data. Reviewer, approver and actor names are self-reported, not authenticated identities.
Legacy risk decisions stay in ``sod_reviews`` and are never reinterpreted as these decisions.
"""
from datetime import date, datetime, timezone
import re
import threading
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ConfigDict, Field, field_validator, model_validator

from config import atomic_write, config_dir
from config_models import StrictModel
from csv_lifecycle import read_private, write_private
from sod_reviews import CONTEXT_PATTERN, IDENTITY_NOTICE

lock = threading.RLock()
MAX_BYTES = 64 * 1024 * 1024
MAX_EVENTS = 500
MAX_KEYS = 100000
MAX_ACTIONS = 20000
MAX_REPORTS = 5000
MAX_BATCH = 100
DECISIONS = {
    'activity': ('Pending', 'Approved', 'Conditional', 'Remove'),
    'assignment': ('Pending', 'Keep', 'Remove'),
    'acceptance': ('Pending', 'Accepted', 'Rejected'),
}
RECOMMENDED = ('Remove assignment', 'Investigate assignment', 'Maintain access', 'Apply compensating control', 'No action required')
ACTION_STATUS = ('Open', 'In progress', 'Completed', 'Cancelled')
Kind = Literal['activity', 'assignment', 'acceptance']
HEX64 = r'^[a-f0-9]{64}$'


def _clean(value):
    if isinstance(value, str):
        if any(ord(char) < 32 and char not in '\n\r\t' for char in value):
            raise ValueError('Text contains unsupported control characters.')
        return value.strip()
    return value


class Event(StrictModel):
    model_config = ConfigDict(extra='forbid', validate_default=True, frozen=True)
    event_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    kind: Kind
    context: str = Field(pattern=CONTEXT_PATTERN)
    timestamp: str = Field(max_length=40)
    key: str = Field(pattern=HEX64)
    user: str = Field(min_length=1, max_length=512)
    ref: str = Field(min_length=1, max_length=512)
    decision: str = Field(max_length=40)
    reviewer: str = Field(min_length=1, max_length=120)
    approver: str = Field(default='', max_length=120)
    justification: str = Field(max_length=4000)
    controls: str = Field(default='', max_length=8000)
    expires: date | None = None
    evidence_version: str = Field(pattern=HEX64)
    evidence_snapshot: str = Field(pattern=HEX64)
    source_versions: dict[str, str] = Field(default_factory=dict, max_length=4)

    @field_validator('*', mode='before')
    @classmethod
    def readable(cls, value):
        return _clean(value)

    @field_validator('timestamp')
    @classmethod
    def utc_timestamp(cls, value):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise ValueError('Decision timestamps must use UTC.')
        return value

    @model_validator(mode='after')
    def consistent(self):
        if self.decision not in DECISIONS[self.kind]:
            raise ValueError('Unsupported decision for this review type.')
        if not self.justification:
            raise ValueError('A justification is required.')
        if self.kind == 'activity' and self.decision == 'Conditional' and not self.controls:
            raise ValueError('Describe the conditions before approving this activity conditionally.')
        if self.kind == 'acceptance' and self.decision != 'Pending':
            if not self.approver:
                raise ValueError('Risk acceptance and rejection require a named approver.')
            if self.approver.casefold() == self.reviewer.casefold():
                raise ValueError('Reviewer and approver must be different people.')
        if self.kind != 'acceptance' and (self.approver or self.expires):
            raise ValueError('Approver and expiry apply to risk acceptance only.')
        return self


class ActionEvent(StrictModel):
    timestamp: str
    actor: str = Field(max_length=120)
    note: str = Field(max_length=2000)


class Action(StrictModel):
    id: str = Field(pattern=r'^[a-f0-9]{32}$')
    context: str = Field(pattern=CONTEXT_PATTERN)
    user: str = Field(min_length=1, max_length=512)
    activity: str = Field(default='', max_length=512)
    risk_id: str = Field(default='', max_length=512)
    assignment_id: str = Field(default='', max_length=64)
    role: str = Field(default='', max_length=512)
    recommended: Literal['Remove assignment', 'Investigate assignment', 'Maintain access', 'Apply compensating control', 'No action required']
    reason: str = Field(max_length=4000)
    owner: str = Field(default='', max_length=120)
    due_date: date | None = None
    status: Literal['Open', 'In progress', 'Completed', 'Cancelled'] = 'Open'
    completion_evidence: str = Field(default='', max_length=4000)
    created: str
    modified: str
    created_by: str = Field(min_length=1, max_length=120)
    history: list[ActionEvent] = Field(default_factory=list, max_length=500)

    @field_validator('*', mode='before')
    @classmethod
    def readable(cls, value):
        return _clean(value)

    @model_validator(mode='after')
    def completed(self):
        if self.status == 'Completed' and not self.completion_evidence:
            raise ValueError('Completion evidence is required to complete an action.')
        if not self.reason:
            raise ValueError('A reason is required.')
        if self.assignment_id and not re.fullmatch(HEX64[1:-1], self.assignment_id):
            raise ValueError('Invalid assignment identity.')
        return self


class ReportEntry(StrictModel):
    id: str = Field(pattern=r'^[a-f0-9]{32}$')
    period_id: str = Field(pattern=CONTEXT_PATTERN)
    kind: str = Field(max_length=40)
    title: str = Field(max_length=160)
    status: str = Field(max_length=40)
    document_version: str = Field(max_length=80)
    model_checksum: str = Field(pattern=HEX64)
    previous_period_id: str | None = None
    timestamp: str
    prepared_by: str = Field(default='', max_length=120)


class Storage(StrictModel):
    version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    contexts: dict[str, dict[str, dict[str, list[Event]]]] = Field(default_factory=dict, max_length=1000)
    actions: dict[str, Action] = Field(default_factory=dict)
    reports: list[ReportEntry] = Field(default_factory=list)

    @model_validator(mode='after')
    def bounded(self):
        keys, ids = 0, set()
        for context, kinds in self.contexts.items():
            if not re.fullmatch(CONTEXT_PATTERN, context) or set(kinds) - set(DECISIONS):
                raise ValueError('Invalid decision context.')
            for kind, subjects in kinds.items():
                keys += len(subjects)
                for key, events in subjects.items():
                    if not events or len(events) > MAX_EVENTS:
                        raise ValueError('Invalid decision history.')
                    for event in events:
                        if event.context != context or event.kind != kind or event.key != key or event.event_id in ids:
                            raise ValueError('Inconsistent decision history.')
                        ids.add(event.event_id)
        if keys > MAX_KEYS or len(self.actions) > MAX_ACTIONS or len(self.reports) > MAX_REPORTS:
            raise ValueError('Decision storage capacity is reached.')
        return self


def _path():
    return config_dir() / 'sod-decisions.json'


def read():
    path = _path()
    if not path.exists():
        return Storage()
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError()
        return Storage.model_validate_json(raw)
    except (OSError, ValueError, TypeError, RecursionError):
        raise HTTPException(409, 'SoD decision history is unreadable or unsupported. Original data is retained; restore a private backup before editing.') from None


def _write(data):
    try:
        raw = Storage.model_validate(data.model_dump()).model_dump_json().encode('utf-8')
        if len(raw) > MAX_BYTES:
            raise ValueError()
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(409, 'SoD decision storage capacity or format is invalid. Existing history is retained.') from None
    try:
        atomic_write(_path(), raw)
    except OSError:
        raise HTTPException(409, 'SoD decisions could not be saved. Previous decisions are retained.') from None


def check_context(value):
    if not isinstance(value, str) or not re.fullmatch(CONTEXT_PATTERN, value):
        raise HTTPException(422, 'Choose a supported review context identifier.')
    return value


def record(kind, context, items, decision, reviewer, justification, expected_revision,
           approver='', controls='', expires=None, source_versions=None):
    """Append one event per item atomically; all items share one decision and justification."""
    context = check_context(context)
    if not items or len(items) > MAX_BATCH or len({item['key'] for item in items}) != len(items):
        raise HTTPException(422, f'Choose between 1 and {MAX_BATCH} distinct items.')
    if expires is not None and expires < date.today():
        raise HTTPException(422, 'The expiration date cannot be in the past.')
    with lock:
        data = read()
        if data.revision != expected_revision:
            raise HTTPException(409, 'SoD decisions changed. Reload before saving.')
        subjects = data.contexts.setdefault(context, {}).setdefault(kind, {})
        stamp = datetime.now(timezone.utc).isoformat()
        events = []
        for item in items:
            try:
                identity = write_private('snapshots', dict(version=1, source='sod-decision-evidence', kind=kind, evidence=item['evidence']))
            except (OSError, ValueError):
                raise HTTPException(409, 'SoD decision evidence could not be staged. Previous decisions are retained.') from None
            event = Event(event_id=uuid4().hex, kind=kind, context=context, timestamp=stamp, key=item['key'], user=item['user'], ref=item['ref'],
                          decision=decision, reviewer=reviewer, approver=approver, justification=justification, controls=controls,
                          expires=expires, evidence_version=item['evidence_version'], evidence_snapshot=identity,
                          source_versions=source_versions or {})
            history = subjects.get(item['key'], [])
            if len(history) >= MAX_EVENTS:
                raise HTTPException(409, 'SoD decision history capacity is reached for an item. Existing events are retained.')
            subjects[item['key']] = [*history, event]
            events.append(event)
        data.revision += 1
        _write(data)
        return dict(events=[event.model_dump(mode='json') for event in events], revision=data.revision, reviewer_identity=IDENTITY_NOTICE)


def latest(context, data=None):
    """kind -> key -> most recent event for one context."""
    data = data or read()
    kinds = data.contexts.get(context, {})
    return {kind: {key: events[-1] for key, events in kinds.get(kind, {}).items()} for kind in DECISIONS}


def history(kind, context, key):
    if kind not in DECISIONS or not re.fullmatch(HEX64[1:-1], key):
        raise HTTPException(422, 'Choose a valid review item.')
    with lock:
        events = read().contexts.get(check_context(context), {}).get(kind, {}).get(key, [])
    return [event.model_dump(mode='json') for event in reversed(events)]


def evidence_for(event):
    try:
        saved = read_private('snapshots', event['evidence_snapshot'])
        if saved.get('source') != 'sod-decision-evidence' or saved.get('kind') != event['kind']:
            raise ValueError()
        return saved['evidence']
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(409, 'Retained decision evidence is unavailable or invalid. History is preserved; restore its snapshot from a private backup.') from None


def lifecycle(kind, event, current_version, today=None):
    """Lifecycle of one item. ``current_version`` is None when evidence no longer supports the item.

    Returns Pending, the decision itself (Approved, Keep, Accepted, Conditional, Rejected), Removal required,
    Outdated (evidence changed or acceptance expired) or Historical.
    """
    if event is None:
        return 'Pending'
    if current_version is None:
        return 'Historical'
    if event.evidence_version != current_version or kind == 'acceptance' and event.expires and event.expires < (today or date.today()):
        return 'Outdated'
    return 'Removal required' if event.decision == 'Remove' else event.decision


def save_action(context, payload, actor, expected_revision, action_id=''):
    """Create or update a remediation action; every change is appended to its history."""
    context = check_context(context)
    with lock:
        data = read()
        if data.revision != expected_revision:
            raise HTTPException(409, 'SoD decisions changed. Reload before saving.')
        stamp = datetime.now(timezone.utc).isoformat()
        previous = data.actions.get(action_id) if action_id else None
        if action_id and previous is None:
            raise HTTPException(404, 'Remediation action not found.')
        if previous and previous.context != context:
            raise HTTPException(422, 'An action cannot move to another review context.')
        if not previous and len(data.actions) >= MAX_ACTIONS:
            raise HTTPException(409, 'Remediation action capacity is reached. Existing actions are retained.')
        values = dict(payload)
        if previous:
            changes = [f'{name}: {getattr(previous, name) or "-"} → {values[name] or "-"}' for name in values
                       if name in {'recommended', 'reason', 'owner', 'due_date', 'status', 'completion_evidence'} and str(getattr(previous, name) or '') != str(values[name] or '')]
            entry = previous.model_copy(update={**values, 'modified': stamp, 'history': [*previous.history, ActionEvent(timestamp=stamp, actor=actor, note='; '.join(changes) or 'Reviewed')]})
        else:
            entry = Action(id=uuid4().hex, context=context, created=stamp, modified=stamp, created_by=actor,
                           history=[ActionEvent(timestamp=stamp, actor=actor, note='Created')], **values)
        entry = Action.model_validate(entry.model_dump())
        data.actions[entry.id] = entry
        data.revision += 1
        _write(data)
        return dict(action=entry.model_dump(mode='json'), revision=data.revision)


def actions_for(context, data=None):
    data = data or read()
    return [item for item in data.actions.values() if item.context == context]


def log_report(period_id, kind, title, status, document_version, model_checksum, previous_period_id=None, prepared_by=''):
    with lock:
        data = read()
        if len(data.reports) >= MAX_REPORTS:
            raise HTTPException(409, 'Report log capacity is reached. Existing entries are retained.')
        entry = ReportEntry(id=uuid4().hex, period_id=period_id, kind=kind, title=title, status=status, document_version=document_version,
                            model_checksum=model_checksum, previous_period_id=previous_period_id,
                            timestamp=datetime.now(timezone.utc).isoformat(), prepared_by=prepared_by)
        data.reports.append(entry)
        _write(data)
        return entry.model_dump(mode='json')


def context_summary(context):
    """Counts used for period deletion impact; includes reports that issued or compare this period."""
    data = read()
    kinds = data.contexts.get(context, {})
    reports = [item for item in data.reports if item.period_id == context]
    dependents = [item for item in data.reports if item.previous_period_id == context and item.period_id != context]
    return dict(activity=len(kinds.get('activity', {})), assignment=len(kinds.get('assignment', {})), acceptance=len(kinds.get('acceptance', {})),
                events=sum(len(events) for subjects in kinds.values() for events in subjects.values()),
                actions=len(actions_for(context, data)), reports=[item.model_dump(mode='json') for item in reports],
                dependents=[item.model_dump(mode='json') for item in dependents])


def freeze(context):
    """Complete copy of one context for an immutable period snapshot."""
    data = read()
    kinds = data.contexts.get(context, {})
    return dict(events={kind: {key: [event.model_dump(mode='json') for event in events] for key, events in kinds.get(kind, {}).items()} for kind in DECISIONS},
                actions=[item.model_dump(mode='json') for item in actions_for(context, data)])
