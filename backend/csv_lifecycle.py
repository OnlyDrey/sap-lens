"""Private CSV generations and refresh evidence. No incremental upserts or email identities.

Immutable staged files precede a single settings-pointer commit. Readers continue
using the previous generation until all successful independent sources are ready.
"""
from collections import Counter, defaultdict
from copy import copy
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import logging
import re

import cache
import import_checks
import source_store
from config import config_dir, get_settings, save_configuration
from config_models import FIELDS, USER_FIELDS, SourceSnapshot, RefreshMetadata, ImportConfirmation as ConfirmationRecord
from employee_directory import store, persist_directory

logger = logging.getLogger('sap-lens')
NAMES = {'roles': 'Role Catalogue', 'users': 'User–Role Mapping', 'employees': 'Employee Directory', 'sod': 'SoD Matrix'}
MAX_PRIVATE_BYTES = 256 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


def private_path(kind, identity):
    if kind not in {'snapshots', 'reports'} or not re.fullmatch(r'[a-f0-9]{64}', identity):
        raise ValueError('Invalid private data reference.')
    return config_dir() / 'csv-data' / kind / f'{identity}.json'


def _canonical_chunks(value, rows=2000):
    """The exact text of json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True), produced in pieces so a large snapshot is never held
    as one string next to its encoded bytes. A long list is encoded `rows` items at a time (the C encoder), which is byte-identical to encoding it whole."""
    options = dict(ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    if not isinstance(value, dict):
        yield json.dumps(value, **options)
        return
    yield '{'
    for position, key in enumerate(sorted(value)):
        yield ('' if position == 0 else ',') + json.dumps(key, ensure_ascii=False) + ':'
        item = value[key]
        if isinstance(item, list) and len(item) > rows:
            yield '['
            for start in range(0, len(item), rows):
                yield ('' if start == 0 else ',') + json.dumps(item[start:start + rows], **options)[1:-1]
            yield ']'
        else:
            yield json.dumps(item, **options)
    yield '}'


def write_private(kind, value):
    """Store a value as immutable content-addressed JSON. Streams to a temporary file while hashing (memory stays flat for 100 MB+ snapshots), then
    publishes it under its digest. The bytes are identical to those of the former in-memory encoding, so existing snapshots keep their identities."""
    import os
    import tempfile
    parent = private_path(kind, '0' * 64).parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    digest, size = hashlib.sha256(), 0
    descriptor, temporary = tempfile.mkstemp(dir=parent, suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            for piece in _canonical_chunks(value):
                raw = piece.encode('utf-8')
                size += len(raw)
                if size > MAX_PRIVATE_BYTES:
                    raise ValueError('Private snapshot or report exceeds its storage limit.')
                digest.update(raw)
                stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        identity = digest.hexdigest()
        target = private_path(kind, identity)
        if target.exists():
            existing = hashlib.sha256()
            with target.open('rb') as stream:
                while block := stream.read(1024 * 1024):
                    existing.update(block)
            if existing.hexdigest() == identity:
                return identity                                 # already stored and verified: reuse
        os.replace(temporary, target)
        temporary = None
        return identity
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def read_private(kind, identity):
    with private_path(kind, identity).open('rb') as stream:
        raw = stream.read(MAX_PRIVATE_BYTES + 1)
    if len(raw) > MAX_PRIVATE_BYTES or hashlib.sha256(raw).hexdigest() != identity:
        raise ValueError('Private data failed its integrity check.')
    result = json.loads(raw)
    if not isinstance(result, dict) or result.get('version') != 1:
        raise ValueError('Unsupported private data format.')
    return result


def read_source(source, reference):
    return validate_source(source,read_private('snapshots', reference.snapshot))


def validate_source(source,saved):
    """Pure durable-record contract, shared with stopped restore staging."""
    if source == 'sod':
        from sod_import import HEADERS
        fields = set(HEADERS)
    else:
        fields = set(FIELDS if source == 'roles' else USER_FIELDS)
    rows = saved.get('records')
    if saved.get('source') != source or not isinstance(rows, list) or len(rows) > 1_000_000:
        raise ValueError('Invalid source snapshot.')
    for row in rows:
        if not isinstance(row, dict) or set(row) != fields or any(not isinstance(v, str) or len(v) > 4096 for v in row.values()):
            raise ValueError('Invalid snapshot records.')
    if not isinstance(saved.get('report'), dict):
        raise ValueError('Invalid snapshot report.')
    return rows, saved['report']


def record_key(source, row):
    if source == 'employees':
        # Email is deliberately not a record identity. Missing identities are
        # reported as add/remove evidence rather than guessed modifications.
        value = row.get('DistinguishedName') or row.get('SamAccountName')
        return ('dn' if row.get('DistinguishedName') else 'sam', value.strip().casefold()) if value else None
    if source == 'sod':
        return tuple(row.get(k, '') for k in ('RISK', 'ACTIVITY_SLOT', 'ACTIVITY', 'TCODE'))
    keys = ['AGR_NAME', 'CHILD_AGR', 'PARENT_AGR', 'Effective_Role', 'TCODE'] if source == 'roles' else ['USERNAME', 'ROLE_NAME', 'USER_GROUP']
    return tuple(row.get(k, '').strip().upper() for k in keys)


def diff_records(source, before, after, include_changes=True):
    """Multiset comparison, stable under reordering and distinct validity intervals.

    Exact observations cancel first. Only one remaining old/new observation for
    a stable identifier is called modified; ambiguous groups stay add/remove.
    """
    order = {}
    def identity(row):
        # Equal records have equal values under equal key names (the `id` bookkeeping field of directory rows is not part of a record): a tuple of references, no
        # per-row JSON text and no copy. Rows of one source share their key set, so the sort is done once; the key tuple keeps differently shaped rows apart.
        names = order.get(len(row))
        if names is None or any(name not in row for name in names) or 'id' in names:
            names = order[len(row)] = tuple(sorted(name for name in row if name != 'id'))
        return names, tuple(row[name] for name in names)
    # Exact observations cancel first, across the whole source: a re-import that changes a handful of rows only has to group those rows by identifier.
    counted = [Counter(identity(row) for row in rows) for rows in (before, after)]
    common = counted[0] & counted[1]
    leftovers = [counted[0] - common, counted[1] - common]
    counts = dict(added=0, removed=0, modified=0, unchanged=sum(common.values()))
    changes = []
    ambiguous = 0
    missing = sum(record_key(source, row) is None for rows in (before, after) for row in rows)
    groups = [defaultdict(list), defaultdict(list)]
    for target, rows, remaining in zip(groups, (before, after), leftovers):
        if not remaining:
            continue
        remaining = Counter(remaining)
        for row in rows:
            fingerprint = identity(row)
            if remaining.get(fingerprint):
                remaining[fingerprint] -= 1
                clean = {k: v for k, v in row.items() if k != 'id'} if 'id' in row else row
                target[record_key(source, clean) or ('missing',)].append(clean)
    for key in sorted(set(groups[0]) | set(groups[1])):
        old, new = groups[0].get(key, []), groups[1].get(key, [])
        representative = (new or old)[0]
        display_fields = (['DistinguishedName'] if representative.get('DistinguishedName') else ['SamAccountName']) if source == 'employees' else (['AGR_NAME','CHILD_AGR','PARENT_AGR','Effective_Role','TCODE'] if source == 'roles' else ['USERNAME','ROLE_NAME','USER_GROUP'])
        identifier = ' / '.join(representative.get(field, '') for field in display_fields if representative.get(field)) or 'Unidentified record'
        if len(old) == len(new) == 1 and key != ('missing',):
            left, right = old[0], new[0]
            fields = [dict(field=f, before=left.get(f, ''), after=right.get(f, ''))
                      for f in sorted(set(left) | set(right)) if left.get(f) != right.get(f)]
            counts['modified'] += 1
            if include_changes: changes.append(dict(type='modified', identifier=identifier, fields=fields, before=left, after=right))
        else:
            if old and new: ambiguous += 1
            for kind, values in [('removed', old), ('added', new)]:
                counts[kind] += len(values)
                if include_changes: changes.extend(dict(type=kind, identifier=identifier, fields=[], **{'before' if kind == 'removed' else 'after': value}) for value in values)
    return dict(**counts, changes=changes, ambiguous_identifiers=ambiguous, missing_identifiers=missing,
                identity_note='Exact records are compared as multisets. Ambiguous or missing identifiers are not paired into invented modifications.')


def sod_risk_changes(before, after):
    """Definition-level changes; bounded identifiers supplement complete row evidence."""
    old = {risk['risk_id']: risk for risk in before}
    new = {risk['risk_id']: risk for risk in after}
    common = sorted(old.keys() & new.keys())
    changes = {
        'added_risks': sorted(new.keys() - old.keys()),
        'removed_risks': sorted(old.keys() - new.keys()),
        'changed_risks': [key for key in common if old[key] != new[key]],
        'changed_criticality': [key for key in common if old[key]['criticality'] != new[key]['criticality']],
        'changed_source_descriptions': [key for key in common if old[key]['source_text'] != new[key]['source_text']],
        'changed_activities': [key for key in common if any(old[key][field] != new[key][field] for field in ('activity1', 'activity2'))],
        'changed_transaction_mappings': [key for key in common if old[key]['activities'] != new[key]['activities']],
    }
    return {key: {'total':len(values), 'risk_ids':values[:100], 'truncated':len(values)>100} for key,values in changes.items()}


def error_result(error):
    if isinstance(error, FileNotFoundError):
        category, message = 'missing', 'The configured CSV is missing. Reconnect the share or choose an existing file.'
    elif isinstance(error, PermissionError):
        category, message = 'access_denied', 'The CSV could not be read. Check file and network-share permissions.'
    elif isinstance(error, UnicodeError):
        category, message = 'encoding', 'The CSV encoding is invalid. Review the source encoding and import format.'
    elif isinstance(error, csv.Error):
        category, message = 'malformed_csv', 'The CSV has malformed quoting or records. Correct the export and validate it again.'
    elif isinstance(error, ValueError):
        text = str(error).casefold()
        if 'changed while being read' in text:
            category, message = 'source_changed', 'The CSV changed during validation. Wait for the external export to finish, then retry.'
        elif 'row width' in text or 'malformed' in text:
            category, message = 'malformed_csv', 'CSV records do not match the expected structure. Review quoting, delimiters and row widths.'
        elif any(v in text for v in ('header', 'mapped', 'column')):
            category, message = 'headers', 'Required headers or column mappings are invalid. Review this source’s CSV import format.'
        elif 'utf' in text or 'encoding' in text:
            category, message = 'encoding', 'The CSV encoding is invalid. Review the source encoding and import format.'
        elif 'date' in text or 'validity' in text:
            category, message = 'dates', 'Assignment or account dates are invalid. Review date formats and reversed validity intervals.'
        else:
            category, message = 'validation', 'The CSV failed validation. Review identifiers, field lengths and import settings before retrying.'
    else:
        category, message = 'read_failed', 'The source could not be prepared. Check source access and retry.'
    return dict(status='failed', category=category, message=message, previous_preserved=True,
                recovery='Review this source under Settings → Data Sources. Previous validated records remain available.')


def summary(report):
    # Keep neither complete changed datasets in the UI response nor removed
    # personal records in a long-lived DataLoader result after publication.
    return {**report, 'sources': [{key:value for key,value in row.items() if key != 'changes'} for row in report['sources']]}


def source_fingerprint(source, path, settings):
    """Identity of the input that produced a source's records: the file content plus the settings and the parser code that shape the parse.

    Equal fingerprint means parsing would reproduce the active snapshot exactly, so a dynamic source can skip parsing, diffing and rebuilding."""
    import persistent_cache
    if source == 'roles':
        shaping = next(p for p in settings.import_profiles if p.id == settings.active_import).model_dump_json()
    elif source == 'users':
        shaping = next(p for p in settings.user_import_profiles if p.id == settings.active_user_import).model_dump_json()
    else:
        shaping = settings.sod_import.model_dump_json()
    digest = hashlib.sha256()
    for part in (source, shaping, persistent_cache.code_digest('csv_import.py', 'user_access.py', 'sod_import.py', 'cache.py')):
        digest.update(part.encode() + b'\0')
    digest.update(persistent_cache.file_digest(path).encode())
    return digest.hexdigest()


def verify_snapshot(reference):
    """The authoritative snapshot file still matches its content address. Checked on every restore, even when the records come from the store or the
    derived cache, so damaged evidence is reported exactly as before instead of being masked by a copy."""
    path = private_path('snapshots', reference.snapshot)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        if path.stat().st_size > MAX_PRIVATE_BYTES:
            raise ValueError('Private data failed its integrity check.')
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != reference.snapshot:
        raise ValueError('Private data failed its integrity check.')


def stored_source(source, reference):
    """(records, report) of a snapshot: from its verified SQLite revision when present, otherwise from the immutable JSON snapshot, which then
    repopulates the store. The JSON snapshot stays the authority; the store only makes the same records cheaper to read and to query."""
    found = source_store.read(source, reference.snapshot)
    if found:
        return found
    rows, report = read_source(source, reference)
    try:
        source_store.ingest(source, reference.snapshot, rows, report)
    except Exception:  # noqa: BLE001 - the store is optional
        pass
    return rows, report


def restore(settings):
    """Rebuild derived mappings from durable canonical observations. Serialized derived values are used only when authenticated and keyed to this
    exact snapshot, catalogue, settings and code; otherwise the records are read and the model is derived again."""
    state = cache._CacheState()
    imported = []
    errors = set()
    for source in ('roles', 'users', 'sod'):
        ref = settings.data_lifecycle.sources.get(source)
        path = {'roles':settings.data_csv_path, 'users':settings.user_csv_path, 'sod':settings.sod_csv_path}[source]
        if not ref or ref.path != path:
            continue
        try:
            verify_snapshot(ref)
            def records(source=source, ref=ref):
                return stored_source(source, ref)[0]
            def revision(source=source, ref=ref):
                found = source_store.revision_id(source, ref.snapshot)
                return (found,) if found else ()
            if source == 'sod':
                from sod_import import build_sod
                rows, report = stored_source(source, ref)
                state.sod = build_sod(rows, report)
            elif source == 'roles':
                def derive(ref=ref, path=path):
                    rows, report = stored_source('roles', ref)
                    return cache._build_catalog(path, settings, records=rows, report=report)
                state = cache._persisted('roles', path, cache.roles_dependencies(settings), derive, identity=ref.snapshot, revisions=lambda r=revision: r(), rows=records, revision=settings.revision)
            else:
                profile = next(p for p in settings.user_import_profiles if p.id == settings.active_user_import)
                def derive(ref=ref, catalogue=state.roles, profile=profile, path=path):
                    rows, report = stored_source('users', ref)
                    return cache.build_users(path, profile, catalogue, records=rows, report=report)
                state.users = cache._persisted('users', path, cache.users_dependencies(settings), derive, state, identity=ref.snapshot, revisions=lambda r=revision: r(), rows=records)
            state.loaded_sources[source] = path
            if source != 'sod': imported.append(datetime.fromisoformat(ref.imported_at))
        except (OSError, ValueError, KeyError, TypeError):
            # Refresh records a safe source-specific failure if its live source
            # cannot recover. An invalid snapshot is never activated.
            errors.add(source)
    state.last_loaded = max(imported) if imported else None
    state.restore_errors = errors
    return state


def load(settings=None, operation='refresh', before_commit=None, strict=False, force=(), progress=None, confirm=()):
    settings = (settings or get_settings()).model_copy(deep=True)
    expected = settings.revision
    settings.revision = expected + 1
    old = cache.get_snapshot()
    if operation == 'startup' and not old.last_loaded:
        old = restore(settings)
    previous_directory = (old.directory if old.directory_bound else store.get(settings.employee_csv_path, settings.employee_snapshot_id) if settings.employee_snapshot_id
                          else store.directory if store.path == settings.employee_csv_path else None)
    state = copy(old)
    state.loaded_sources = dict(old.loaded_sources)
    directory = previous_directory
    results = []
    changed = False
    sap_cleared = False
    stamp = now()
    successful = []
    checked_files = []
    fresh = {}
    pending_fingerprints = {}
    catalogue_new = users_fresh = False
    def announce(stage, source=None):
        if progress: progress(stage,source)
    def signature(path):
        stat=Path(path).stat()
        return (stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns)
    forced = set(force)
    if operation == 'startup' and settings.features.employee_directory and settings.employee_csv_path and not settings.employee_snapshot_id:
        # One-time recovery of legacy path-only installations. Once confirmed,
        # a static source always restores the durable snapshot instead.
        forced.add('employees')
    if operation == 'import':
        current = get_settings()
        for source, fields in [('roles', ('data_csv_path', 'import_profiles', 'active_import')),
                               ('users', ('user_csv_path', 'user_import_profiles', 'active_user_import')),
                               ('employees', ('employee_csv_path',)),
                               ('sod', ('sod_csv_path', 'sod_import'))]:
            if any(getattr(settings, key) != getattr(current, key) for key in fields): forced.add(source)
        if old.source_records and settings.module_overrides != current.module_overrides:
            state = cache._build_catalog(settings.data_csv_path, settings, records=old.source_records, report=old.import_report)
            state.users, state.loaded_sources, state.sod = old.users, dict(old.loaded_sources), old.sod
            changed = catalogue_new = True
    sources = ['roles', 'users', 'employees']
    if settings.sod_csv_path or old.sod or 'sod' in settings.data_lifecycle.sources or 'sod' in forced:
        sources.append('sod')
    for source in sources:
        path = {'roles': settings.data_csv_path, 'users': settings.user_csv_path, 'employees': settings.employee_csv_path, 'sod': settings.sod_csv_path}[source]
        enabled = source == 'roles' or getattr(settings.features, {'users': 'user_role_mapping', 'sod': 'sod'}.get(source, 'employee_directory'))
        mode = getattr(settings.source_modes, source)
        result = dict(source=source, name=NAMES[source], mode=mode, checked_at=stamp)
        if mode == 'static' and source in getattr(old, 'restore_errors', set()) and source not in forced:
            result.update(status='failed', category='snapshot', previous_preserved=False,
                          message='The durable snapshot failed validation or could not be read.',
                          recovery='Re-import this source in Data Sources or restore a valid local backup.')
            results.append(result)
            continue
        if not path or source not in forced and (not enabled or mode == 'static' or operation == 'import'):
            reason = 'unconfigured' if not path else 'disabled' if not enabled else 'static' if mode == 'static' else 'not_selected'
            result.update(status='skipped', reason=reason, message=f'Source skipped: {reason}.')
            results.append(result)
            continue
        try:
            phase = 'read'
            announce('Reading file',source)
            initial_signature=signature(path)
            if source == 'employees':
                from employee_directory import directory_fingerprint
                fingerprint = directory_fingerprint(path)
                if (previous_directory is not None and settings.employee_snapshot_id and source not in forced and state.loaded_sources.get('employees', path) == path
                        and source_store.directory_fingerprint(settings.employee_snapshot_id) == fingerprint and signature(path) == initial_signature):
                    # Same CSV content and parser code as the stored directory: no parse, no comparison, no position-change pass, no re-matching.
                    total = len(previous_directory.rows)
                    result.update(status='unchanged', **{**diff_records(source, [], []), 'unchanged': total}, records=total, fast_path=True)
                    announce('Unchanged', source)
                    successful.append(source)
                    results.append(result)
                    continue
            else:
                fingerprint = source_fingerprint(source, path, settings)
            existing_ref = settings.data_lifecycle.sources.get(source)
            if (fingerprint and existing_ref and existing_ref.path == path and source not in forced and state.loaded_sources.get(source) == path
                    and source_store.fingerprint(source, existing_ref.snapshot) == fingerprint and signature(path) == initial_signature):
                # Same file, same parsing settings and code as the active revision: nothing to parse, compare, rebuild or stage.
                total = len(old.source_records if source == 'roles' else old.users.source_records if source == 'users' else old.sod.get('records', []))
                if total:
                    existing_ref.checked_at = stamp
                    result.update(status='unchanged', **{**diff_records(source, [], []), 'unchanged': total}, records=total, fast_path=True)
                    announce('Unchanged',source)
                    successful.append(source)
                    results.append(result)
                    continue
            if source == 'roles':
                candidate = cache._build_catalog(path, settings)
                before, after = old.source_records, candidate.source_records
            elif source == 'users':
                profile = next(p for p in settings.user_import_profiles if p.id == settings.active_user_import)
                candidate = cache.build_users(path, profile, state.roles)
                before, after = old.users.source_records, candidate.source_records
            elif source == 'sod':
                from sod_import import parse_sod
                candidate = parse_sod(path, settings.sod_import)
                before, after = old.sod.get('records', []), candidate['records']
            else:
                from employee_directory import parse_directory
                candidate = parse_directory(path)
                before, after = previous_directory.rows if previous_directory else [], candidate.rows
            announce('Validating',source)
            if not after:
                from analysis_errors import AnalysisValidationError
                raise AnalysisValidationError('The CSV contains no usable records. Previous data is retained; use Clear source data to remove it intentionally.')
            if signature(path)!=initial_signature:
                raise ValueError('The CSV changed during validation. Select it again after the export finishes.')
            checked_files.append((source,path,initial_signature))
            delta = diff_records(source, before, after)
            # Compare only with the active revision of this same source. Invalid files were rejected above and are never confirmable;
            # a valid but suspicious replacement waits for explicit confirmation and leaves everything active untouched.
            check = import_checks.evaluate(source, before, after, settings.import_checks) if before else None
            if check and check['suspicious']:
                if source not in confirm:
                    raise import_checks.ImportHeld(source, check)
                from server_access import actor
                settings.data_lifecycle.confirmations = [*settings.data_lifecycle.confirmations, ConfirmationRecord(
                    source=source, confirmed_at=stamp, actor=actor(), anomalies=[item['message'] for item in check['anomalies']][:20],
                    old_records=check['old']['records'], new_records=check['new']['records'])][-100:]
            has_changes = bool(delta['added'] or delta['removed'] or delta['modified'])
            if source == 'sod' and ((old.sod.get('report') or {}).get('metadata') or None) != (candidate['report'].get('metadata') or None):
                has_changes = True  # descriptive metadata changed without any record changing: stage it, so the new descriptions are not silently ignored
            result.update(status='updated' if has_changes else 'unchanged', records=len(after), **delta)
            if source == 'sod':
                result['risk_change_summary'] = sod_risk_changes(old.sod.get('risks', []), candidate['risks'])
            phase = 'stage'
            announce('Importing',source)
            if source != 'employees':
                existing = settings.data_lifecycle.sources.get(source)
                if has_changes or source in forced or not existing or existing.path != path:
                    snapshot_report = candidate.import_report if source == 'roles' else candidate['report'] if source == 'sod' else candidate.report
                    identity = write_private('snapshots', dict(version=1, source=source, records=after, report=snapshot_report))
                    fresh[source] = (identity, after, snapshot_report, fingerprint)
                    new_sod_version = source == 'sod' and (has_changes or not old.sod) and not any(item.snapshot == identity for item in settings.data_lifecycle.sod_history)
                    if new_sod_version and len(settings.data_lifecycle.sod_history) >= 1000:
                        raise ValueError('SoD source history is full. Preserve a backup and review storage before importing another version.')
                    settings.data_lifecycle.sources[source] = SourceSnapshot(snapshot=identity, path=path, imported_at=stamp, checked_at=stamp)
                    if new_sod_version:
                        settings.data_lifecycle.sod_history.append(settings.data_lifecycle.sources[source].model_copy(deep=True))
                else:
                    existing.checked_at = stamp
                    if fingerprint: pending_fingerprints[source] = (existing.snapshot, fingerprint)
            elif has_changes or source in forced or not settings.employee_snapshot_id:
                candidate.imported_at = stamp
                settings.employee_snapshot_id = persist_directory(candidate)
                if fingerprint: pending_fingerprints[source] = (settings.employee_snapshot_id, fingerprint)
            elif fingerprint:
                pending_fingerprints[source] = (settings.employee_snapshot_id, fingerprint)
            # A source becomes a publication candidate only after all of its
            # immutable durable inputs have been staged successfully.
            if source == 'roles':
                catalogue_new |= bool(has_changes or source in forced or not old.roles)
                candidate.users = state.users
                candidate.sod = state.sod
                candidate.loaded_sources = dict(state.loaded_sources)
                if not has_changes and old.last_loaded: candidate.last_loaded = old.last_loaded
                state = candidate
            elif source == 'users':
                users_fresh = True
                state.users = candidate
            elif source == 'sod':
                state.sod = candidate
            else:
                directory = candidate if has_changes or source in forced or not previous_directory else previous_directory
            if source != 'employees': state.loaded_sources[source] = path
            changed |= has_changes or operation == 'import' and source in forced
            successful.append(source)
        except Exception as error:
            logger.warning('Source initialization/import failed (source=%s phase=%s exception=%s errno=%s winerror=%s).',
                           source, phase, type(error).__name__, getattr(error, 'errno', None), getattr(error, 'winerror', None))
            if strict:
                error.sap_lens_source = source
                raise
            if isinstance(error, import_checks.ImportHeld):
                result.update(status='failed', category='needs_confirmation', severity='suspicious', confirmable=True, previous_preserved=True,
                              anomalies=error.evaluation['anomalies'], old=error.evaluation['old'], new=error.evaluation['new'], message=str(error),
                              recovery='Review the change report. If the smaller file is correct, import it again and confirm; otherwise export the complete source again.')
                results.append(result)
                continue
            result.update(error_result(error))
            result.update(severity='invalid', confirmable=False)
            result['previous_preserved'] = bool(old.import_report if source == 'roles' else old.users.report if source == 'users' else old.sod if source == 'sod' else previous_directory)
            if phase == 'stage':
                result.update(category='storage', message='The validated source could not be staged in private local storage.',
                              recovery='Check free space and permissions on the SAP Lens application-data directory, then retry.')
        results.append(result)
    # Source removal is explicit configuration, never inferred from a failed read.
    if operation == 'import' or not settings.data_csv_path or not settings.user_csv_path:
        if not settings.data_csv_path and (state.loaded_sources.get('roles') or 'roles' in settings.data_lifecycle.sources):
            state = cache._CacheState(users=state.users, sod=state.sod, loaded_sources={k:v for k,v in state.loaded_sources.items() if k != 'roles'})
            settings.data_lifecycle.sources.pop('roles', None)
            sap_cleared = catalogue_new = True
            changed = True
        if not settings.user_csv_path and (state.loaded_sources.get('users') or 'users' in settings.data_lifecycle.sources):
            from user_access import UserState
            state.users = UserState()
            state.loaded_sources.pop('users', None)
            settings.data_lifecycle.sources.pop('users', None)
            sap_cleared = True
            changed = True
    if not settings.sod_csv_path and (state.sod or 'sod' in settings.data_lifecycle.sources):
        state.sod = {}
        state.loaded_sources.pop('sod', None)
        settings.data_lifecycle.sources.pop('sod', None)
        changed = True
    announce('Updating dependent views')
    # User-derived indexes must match the final catalogue: replacing the catalogue can remove mappings, wildcard matches and transaction links.
    # Users parsed in this call were already mapped against the final catalogue; only users carried over from before need re-mapping.
    if state.users.source_records and catalogue_new and not users_fresh:
        from user_access import build_users as rebuild_users
        profile = next(p for p in settings.user_import_profiles if p.id == settings.active_user_import)
        state.users = rebuild_users(settings.user_csv_path, profile, state.roles,
                                        records=state.users.source_records, report=state.users.report)
    failed = sum(r['status'] == 'failed' for r in results)
    updated = sum(r['status'] == 'updated' for r in results)
    report = dict(version=1, timestamp=stamp, operation=operation, sources=results,
                  checked=sum(r['status'] != 'skipped' for r in results), updated=updated,
                  unchanged=sum(r['status'] == 'unchanged' for r in results), failed=failed,
                  skipped=sum(r['status'] == 'skipped' for r in results),
                  status='partial' if failed and successful else 'failed' if failed else 'changed' if updated else 'unchanged')
    report_id = None
    store_operation = None
    try:
        if operation == 'refresh' and report['checked']:
            if failed: settings.data_lifecycle.last_failed_refresh = stamp
            else: settings.data_lifecycle.last_successful_refresh = stamp
        report_id = write_private('reports', report)
        old_reports = list(settings.data_lifecycle.history)
        settings.data_lifecycle.history = [report_id, *old_reports][:5]
        metadata = {key: report[key] for key in RefreshMetadata.model_fields}
        settings.data_lifecycle.history_metadata = {
            key:value for key,value in settings.data_lifecycle.history_metadata.items() if key in settings.data_lifecycle.history}
        settings.data_lifecycle.history_metadata[report_id] = RefreshMetadata(**metadata)
        # Slow network stats remain outside the publication lock. Snapshot records
        # are immutable; a changed original can never turn into a mixed generation.
        for checked_source,checked_path,expected_signature in checked_files:
            if signature(checked_path)!=expected_signature:
                from analysis_errors import AnalysisValidationError
                error=AnalysisValidationError('The CSV changed before activation. Previous data is retained; select it again after the export finishes.')
                error.sap_lens_source=checked_source
                raise error
        # Slow store work happens before the pointer commit, outside every lock: rows are staged invisibly, activation afterwards is one short flip.
        if fresh:
            source_store.recover_orphans()  # staged by operations that no longer exist (older than an hour, not live here)
            store_operation = source_store.begin()
        for staged_source, (staged_id, staged_rows, staged_report, staged_fp) in fresh.items():
            try: source_store.stage(staged_source, staged_id, staged_rows, staged_report, staged_fp, owner=store_operation)
            except Exception: pass  # noqa: BLE001 - the store is optional; reconcile retries after the commit
        with cache._load_lock, store.lock:
            if before_commit: before_commit()
            # CAS covers settings edits, competing imports and concurrent loaders.
            save_configuration(settings, expected)
            state = cache.with_directory(state, directory, settings.employee_csv_path, settings.employee_snapshot_id)
            if changed or not cache.get_snapshot().directory_bound or not cache.get_snapshot().last_loaded and state.last_loaded:
                # Directory enrichment has its own durable import metadata; it must
                # not change the independent SAP dataset generation.
                sap_changed=sap_cleared or any(row['source'] in {'roles','users'} and row['status']=='updated' for row in results)
                state.last_loaded = datetime.fromisoformat(stamp) if changed and sap_changed else state.last_loaded
                cache._cache = state
            if directory is not None:
                store.generation += 1
                store.directory, store.path = directory, settings.employee_csv_path
                store.attempted_path = ('snapshot', settings.employee_snapshot_id) if settings.employee_snapshot_id else settings.employee_csv_path
            directory_result = next(row for row in results if row['source']=='employees')
            if directory_result['status']=='failed':
                store.import_error = directory_result['message']
            elif directory_result['status'] in {'updated','unchanged'}:
                store.error = store.import_error = None
        # The store follows the committed pointer (never the other way round); a failure only means the JSON snapshots are read next time.
        source_store.reconcile(settings, fresh)
        try:
            import assignment_lifecycle
            assignment_lifecycle.observe()  # verified absence / reappearance of decided assignments, from the revision that was just committed
        except Exception:  # noqa: BLE001 - lifecycle memory must never fail an import; the next load observes again
            logger.warning('Assignment lifecycle observation failed and will be retried at the next load.')
        for pending_source, (pending_snapshot, pending_value) in pending_fingerprints.items():
            if pending_source == 'employees': source_store.set_directory_fingerprint(pending_snapshot, pending_value)
            else: source_store.set_fingerprint(pending_source, pending_snapshot, pending_value)
        from account_review import record_missing_users
        record_missing_users(state)
        if previous_directory is not None and directory is not None and directory is not previous_directory:
            from position_changes import record_safely
            record_safely(previous_directory, directory)
        for identity in old_reports:
            if identity not in settings.data_lifecycle.history:
                try: private_path('reports', identity).unlink(missing_ok=True)
                except OSError: pass
        report['id'] = report_id
        return summary(report)
    except Exception as activation_error:
        # Type only: the message can carry a path or source values.
        logger.warning('Source activation did not commit (operation=%s exception=%s); previous data retained.', operation, type(activation_error).__name__)
        if report_id and report_id not in get_settings().data_lifecycle.history:
            try: private_path('reports', report_id).unlink(missing_ok=True)
            except OSError: pass
        if strict: raise
        # No pointer commit means no dataset publication. Do not claim that any
        # staged successful source was activated when local storage/CAS failed.
        for result in results:
            if result['status'] in {'updated', 'unchanged'}:
                result.update(status='failed', category='activation', previous_preserved=True,
                              message='Local storage or settings changed before activation. Previous data was retained.',
                              recovery='Check local storage permissions, reload Settings and retry.')
        report.update(status='failed', updated=0, unchanged=0,
                      failed=sum(r['status'] == 'failed' for r in results), id=None)
        return summary(report)
    finally:
        source_store.end(store_operation)  # only this operation's staged-but-never-activated revisions; other loaders' are untouched


def history():
    reports = []
    for identity in get_settings().data_lifecycle.history:
        metadata = get_settings().data_lifecycle.history_metadata.get(identity)
        if metadata:
            reports.append(dict(id=identity, **metadata.model_dump()))
            continue
        try:
            report = read_private('reports', identity)
            reports.append(dict(id=identity, **{key: report[key] for key in ('timestamp', 'operation', 'status', 'checked', 'updated', 'unchanged', 'failed', 'skipped')}))
        except (OSError, ValueError, KeyError):
            reports.append(dict(id=identity, status='unavailable'))
    return reports
