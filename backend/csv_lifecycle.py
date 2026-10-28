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
import re

import cache
from config import ensure_content_file, config_dir, get_settings, save_configuration
from config_models import FIELDS, USER_FIELDS, SourceSnapshot, RefreshMetadata
from employee_directory import HEADERS, Directory, store, persist_directory

NAMES = {'roles': 'Role Catalogue', 'users': 'User–Role Mapping', 'employees': 'Employee Directory', 'sod': 'SoD Matrix'}
MAX_PRIVATE_BYTES = 256 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


def private_path(kind, identity):
    if kind not in {'snapshots', 'reports'} or not re.fullmatch(r'[a-f0-9]{64}', identity):
        raise ValueError('Invalid private data reference.')
    return config_dir() / 'csv-data' / kind / f'{identity}.json'


def write_private(kind, value):
    raw = json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode('utf-8')
    if len(raw) > MAX_PRIVATE_BYTES:
        raise ValueError('Private snapshot or report exceeds its storage limit.')
    identity = hashlib.sha256(raw).hexdigest()
    target = private_path(kind, identity)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    ensure_content_file(target, raw, identity, MAX_PRIVATE_BYTES)
    return identity


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
    saved = read_private('snapshots', reference.snapshot)
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
    groups = [defaultdict(list), defaultdict(list)]
    missing = 0
    for target, rows in zip(groups, (before, after)):
        for row in rows:
            clean = {k: v for k, v in row.items() if k != 'id'} if 'id' in row else row
            key = record_key(source, clean)
            if key is None:
                missing += 1
                key = ('missing',)
            target[key].append(clean)
    counts = dict(added=0, removed=0, modified=0, unchanged=0)
    changes = []
    ambiguous = 0
    for key in sorted(set(groups[0]) | set(groups[1])):
        originals = {}
        buckets = []
        for group in groups:
            bucket = Counter()
            for row in group.get(key, []):
                fingerprint = json.dumps(row, sort_keys=True, ensure_ascii=False)
                bucket[fingerprint] += 1
                originals[fingerprint] = row
            buckets.append(bucket)
        common = buckets[0] & buckets[1]
        counts['unchanged'] += sum(common.values())
        old = list((buckets[0] - common).elements())
        new = list((buckets[1] - common).elements())
        representative = (groups[1].get(key) or groups[0].get(key))[0]
        display_fields = (['DistinguishedName'] if representative.get('DistinguishedName') else ['SamAccountName']) if source == 'employees' else (['AGR_NAME','CHILD_AGR','PARENT_AGR','Effective_Role','TCODE'] if source == 'roles' else ['USERNAME','ROLE_NAME','USER_GROUP'])
        identifier = ' / '.join(representative.get(field, '') for field in display_fields if representative.get(field)) or 'Unidentified record'
        if len(old) == len(new) == 1 and key != ('missing',):
            left, right = originals[old[0]], originals[new[0]]
            fields = [dict(field=f, before=left.get(f, ''), after=right.get(f, ''))
                      for f in sorted(set(left) | set(right)) if left.get(f) != right.get(f)]
            counts['modified'] += 1
            if include_changes: changes.append(dict(type='modified', identifier=identifier, fields=fields, before=left, after=right))
        else:
            if old and new: ambiguous += 1
            for kind, values in [('removed', old), ('added', new)]:
                counts[kind] += len(values)
                if include_changes: changes.extend(dict(type=kind, identifier=identifier, fields=[], **{'before' if kind == 'removed' else 'after': originals[value]}) for value in values)
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


def restore(settings):
    """Rebuild derived mappings from durable canonical observations, never pickles."""
    state = cache._CacheState()
    imported = []
    errors = set()
    for source in ('roles', 'users', 'sod'):
        ref = settings.data_lifecycle.sources.get(source)
        path = {'roles':settings.data_csv_path, 'users':settings.user_csv_path, 'sod':settings.sod_csv_path}[source]
        if not ref or ref.path != path:
            continue
        try:
            rows, report = read_source(source, ref)
            if source == 'sod':
                from sod_import import build_sod
                state.sod = build_sod(rows, report)
            elif source == 'roles':
                state = cache._build_catalog(path, settings, records=rows, report=report)
            else:
                profile = next(p for p in settings.user_import_profiles if p.id == settings.active_user_import)
                state.users = cache.build_users(path, profile, state.roles, records=rows, report=report)
            state.loaded_sources[source] = path
            if source != 'sod': imported.append(datetime.fromisoformat(ref.imported_at))
        except (OSError, ValueError, KeyError, TypeError):
            # Refresh records a safe source-specific failure if its live source
            # cannot recover. An invalid snapshot is never activated.
            errors.add(source)
    state.last_loaded = max(imported) if imported else None
    state.restore_errors = errors
    return state


def load(settings=None, operation='refresh', before_commit=None, strict=False, force=(), progress=None):
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
                               ('sod', ('sod_csv_path',))]:
            if any(getattr(settings, key) != getattr(current, key) for key in fields): forced.add(source)
        if old.source_records and settings.module_overrides != current.module_overrides:
            state = cache._build_catalog(settings.data_csv_path, settings, records=old.source_records, report=old.import_report)
            state.users, state.loaded_sources, state.sod = old.users, dict(old.loaded_sources), old.sod
            changed = True
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
            if source == 'roles':
                candidate = cache._build_catalog(path, settings)
                before, after = old.source_records, candidate.source_records
            elif source == 'users':
                profile = next(p for p in settings.user_import_profiles if p.id == settings.active_user_import)
                candidate = cache.build_users(path, profile, state.roles)
                before, after = old.users.source_records, candidate.source_records
            elif source == 'sod':
                from sod_import import parse_sod
                candidate = parse_sod(path)
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
            has_changes = bool(delta['added'] or delta['removed'] or delta['modified'])
            result.update(status='updated' if has_changes else 'unchanged', records=len(after), **delta)
            if source == 'sod':
                result['risk_change_summary'] = sod_risk_changes(old.sod.get('risks', []), candidate['risks'])
            phase = 'stage'
            announce('Importing',source)
            if source != 'employees':
                existing = settings.data_lifecycle.sources.get(source)
                if has_changes or source in forced or not existing or existing.path != path:
                    identity = write_private('snapshots', dict(version=1, source=source, records=after,
                                                               report=candidate.import_report if source == 'roles' else candidate['report'] if source == 'sod' else candidate.report))
                    new_sod_version = source == 'sod' and (has_changes or not old.sod) and not any(item.snapshot == identity for item in settings.data_lifecycle.sod_history)
                    if new_sod_version and len(settings.data_lifecycle.sod_history) >= 1000:
                        raise ValueError('SoD source history is full. Preserve a backup and review storage before importing another version.')
                    settings.data_lifecycle.sources[source] = SourceSnapshot(snapshot=identity, path=path, imported_at=stamp, checked_at=stamp)
                    if new_sod_version:
                        settings.data_lifecycle.sod_history.append(settings.data_lifecycle.sources[source].model_copy(deep=True))
                else:
                    existing.checked_at = stamp
            elif has_changes or source in forced or not settings.employee_snapshot_id:
                candidate.imported_at = stamp
                settings.employee_snapshot_id = persist_directory(candidate)
            # A source becomes a publication candidate only after all of its
            # immutable durable inputs have been staged successfully.
            if source == 'roles':
                candidate.users = state.users
                candidate.sod = state.sod
                candidate.loaded_sources = dict(state.loaded_sources)
                if not has_changes and old.last_loaded: candidate.last_loaded = old.last_loaded
                state = candidate
            elif source == 'users':
                state.users = candidate
            elif source == 'sod':
                state.sod = candidate
            else:
                directory = candidate if has_changes or source in forced or not previous_directory else previous_directory
            if source != 'employees': state.loaded_sources[source] = path
            changed |= has_changes or operation == 'import' and source in forced
            successful.append(source)
        except Exception as error:
            if strict:
                error.sap_lens_source = source
                raise
            result.update(error_result(error))
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
            sap_cleared = True
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
    # Always rebuild user-derived indexes against the final catalogue. Replacing
    # either dataset can remove mappings, wildcard matches and transaction links.
    if state.users.source_records:
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
        from account_review import record_missing_users
        record_missing_users(state)
        for identity in old_reports:
            if identity not in settings.data_lifecycle.history:
                try: private_path('reports', identity).unlink(missing_ok=True)
                except OSError: pass
        report['id'] = report_id
        return summary(report)
    except Exception:
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
