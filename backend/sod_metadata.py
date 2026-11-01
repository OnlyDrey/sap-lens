"""One resolution of SoD descriptions for pills, investigations, Settings and diagnostics.

Priority: (1) the value imported with the SoD CSV, when populated; (2) the locally maintained business value as a clearly identified fallback;
(3) a neutral missing state. The two stores stay separate: imports never overwrite local text and local text never edits an import. When both
exist and differ, both are kept and the origin of each is reported. Nothing here is generated from identifiers, and nothing here is read by detection.
"""
from types import SimpleNamespace

from sod_catalogue import read as read_local

# Resolved field -> (key in the imported metadata, attribute of the local annotation).
RISK_FIELDS = {'name': ('name', 'display_name'), 'description': ('description', 'explanation_en'),
               'impact': ('impact', 'consequence_en'), 'business_process': ('business_process', 'business_category')}
ACTIVITY_FIELDS = {'name': ('name', 'display_name'), 'description': ('description', 'explanation_en'),
                   'business_process': ('business_process', 'business_category')}
IMPORTED_ONLY_ACTIVITY = ('type',)


def resolve(imported, local):
    """Return value, its origin ('imported', 'local' or None) and, when the other store differs, that alternate value and its origin."""
    imported, local = (imported or '').strip(), (local or '').strip()
    if imported:
        return dict(value=imported, origin='imported', alternate=local if local and local != imported else '', alternate_origin='local' if local and local != imported else None)
    if local:
        return dict(value=local, origin='local', alternate='', alternate_origin=None)
    return dict(value='', origin=None, alternate='', alternate_origin=None)


def _imported(snapshot):
    report = (snapshot.sod or {}).get('report') or {}
    metadata = report.get('metadata') or {}
    return metadata.get('risks') or {}, metadata.get('activities') or {}, metadata.get('source') or {}, report.get('optional_columns') or {}


def _entry(fields, imported, local):
    resolved = {name: resolve(imported.get(source), getattr(local, attribute, '') if local is not None else '') for name, (source, attribute) in fields.items()}
    entry = {name: item['value'] for name, item in resolved.items() if item['value']}
    entry['origin'] = {name: item['origin'] for name, item in resolved.items() if item['value']}
    differing = {name: dict(value=item['alternate'], origin=item['alternate_origin']) for name, item in resolved.items() if item['alternate']}
    if differing:
        entry['alternate'] = differing
    return entry


def lookup(snapshot=None, saved=None):
    """Resolved descriptions for every risk and activity that has any: `{risks: {id: {...}}, activities: {id: {...}}}`. Empty entries are omitted."""
    import cache
    snapshot = snapshot if snapshot is not None else cache.get_snapshot()
    saved = saved if saved is not None else read_local()
    imported_risks, imported_activities, _, _ = _imported(snapshot)
    definitions = {risk['risk_id']: risk for risk in (snapshot.sod or {}).get('risks', [])}
    activities = {}
    for risk in definitions.values():
        for slot in ('ACTVT1', 'ACTVT2'):
            for mapping in risk['activities'][slot]:
                activities.setdefault(mapping['activity'], set()).add(risk['risk_id'])
    risks_out, activities_out = {}, {}
    for risk_id in sorted(set(definitions) | set(saved.entries) | set(imported_risks)):
        stored = saved.entries.get(risk_id)
        entry = _entry(RISK_FIELDS, imported_risks.get(risk_id, {}), stored.metadata if stored else None)
        definition = definitions.get(risk_id)
        if definition:
            entry.update(criticality=definition['criticality'], type=definition['risk_type'])
        if definition or any(key in entry for key in ('name', 'description', 'impact', 'business_process')):
            risks_out[risk_id] = entry
    for name in sorted(set(activities) | set(saved.activities) | set(imported_activities)):
        stored = saved.activities.get(name)
        entry = _entry(ACTIVITY_FIELDS, imported_activities.get(name, {}), stored.metadata if stored else None)
        for key in IMPORTED_ONLY_ACTIVITY:
            if imported_activities.get(name, {}).get(key):
                entry[key] = imported_activities[name][key]
                entry['origin'][key] = 'imported'
        if name in activities:
            entry['risks'] = len(activities[name])
        if any(key in entry for key in ('name', 'description', 'business_process', 'type')):
            activities_out[name] = entry
    return dict(risks=risks_out, activities=activities_out)


def _indicator(label, total, imported_count, local_count, column_present, differing=0):
    """Distinct entities only. `local_count` counts entities that have no imported value but do have a local one."""
    missing = total - imported_count - local_count
    available = imported_count + local_count
    state = 'complete' if total and not missing else 'column_absent' if not column_present and not imported_count else 'values_missing' if total else 'empty'
    return dict(label=label, total=total, imported=imported_count, local_fallback=local_count, available=available, missing=missing,
                percent=round(100 * available / total, 1) if total else 0.0, column_present=column_present, state=state, differing=differing)


def coverage(snapshot=None, saved=None):
    """Metadata completeness over distinct risks, activities and transaction codes (never raw CSV rows), plus the optional columns found."""
    import cache
    snapshot = snapshot if snapshot is not None else cache.get_snapshot()
    saved = saved if saved is not None else read_local()
    risks = (snapshot.sod or {}).get('risks', [])
    imported_risks, imported_activities, source, columns = _imported(snapshot)
    detected = set(columns.get('detected') or [])
    risk_ids = {risk['risk_id'] for risk in risks}
    activity_ids, transactions = set(), {}
    for risk in risks:
        for slot in ('ACTVT1', 'ACTVT2'):
            for mapping in risk['activities'][slot]:
                activity_ids.add(mapping['activity'])
                transactions[mapping['tcode']] = transactions.get(mapping['tcode'], False) or bool(mapping.get('ttext'))

    def over(ids, imported, stored, source_key, local_attribute, column):
        have = {key for key in ids if (imported.get(key) or {}).get(source_key)}
        local = {key for key in ids - have if key in stored and getattr(stored[key].metadata, local_attribute, '').strip()}
        differ = sum(1 for key in have if key in stored and getattr(stored[key].metadata, local_attribute, '').strip() not in ('', imported[key][source_key]))
        return _indicator('', len(ids), len(have), len(local), column in detected, differ)

    rows = [
        dict(over(risk_ids, imported_risks, saved.entries, 'name', 'display_name', 'RISK_NAME'), id='risk_names', label='Risk display names', column='RISK_NAME'),
        dict(over(risk_ids, imported_risks, saved.entries, 'description', 'explanation_en', 'RISK_DESCRIPTION'), id='risk_descriptions', label='Risk descriptions', column='RISK_DESCRIPTION'),
        dict(over(activity_ids, imported_activities, saved.activities, 'name', 'display_name', 'ACTIVITY_NAME'), id='activity_names', label='Activity display names', column='ACTIVITY_NAME'),
        dict(over(activity_ids, imported_activities, saved.activities, 'description', 'explanation_en', 'ACTIVITY_DESCRIPTION'), id='activity_descriptions', label='Activity descriptions', column='ACTIVITY_DESCRIPTION'),
        dict(_indicator('', len(transactions), sum(transactions.values()), 0, True), id='transaction_descriptions', label='Transaction descriptions', column='TTEXT'),
    ]
    from sod_import import OPTIONAL_FIELDS, SOURCE_METADATA
    return dict(
        indicators=rows,
        optional_columns=dict(detected=[field for field in OPTIONAL_FIELDS if field in detected], missing=[field for field in OPTIONAL_FIELDS if field not in detected]),
        source_facts=[dict(field=column, detected=column in detected, values=source.get(key, [])) for column, key in SOURCE_METADATA.items()],
        sample=[dict(id=key, kind='risk', **{name: entry[name] for name in ('name', 'description') if name in entry}, origin=entry['origin'])
                for key, entry in list(lookup(snapshot, saved)['risks'].items()) if 'name' in entry or 'description' in entry][:5],
        note='Counts use distinct risks, activities and transaction codes. Local descriptions only fill gaps; no description is generated.')


# ----------------------------------------------------------------------------------------------- review snapshots and reports

SNAPSHOT_VERSION = 1


def frozen(snapshot, saved, risk_ids):
    """The resolved descriptions of the given risks and of their activities, as they are when a review snapshot is captured.

    The copy is stored inside the immutable snapshot, so a period's report never reads descriptions that were imported or edited later.
    Origins and differing alternates are kept; nothing is generated, and detection never reads this.
    """
    resolved = lookup(snapshot, saved)
    wanted = set(risk_ids)
    activity_ids = {mapping['activity'] for risk in (snapshot.sod or {}).get('risks', []) if risk['risk_id'] in wanted for slot in ('ACTVT1', 'ACTVT2') for mapping in risk['activities'][slot]}
    risks = {key: {name: value for name, value in entry.items() if name not in ('criticality', 'type', 'risks')} for key, entry in resolved['risks'].items() if key in wanted}
    activities = {key: {name: value for name, value in entry.items() if name != 'risks'} for key, entry in resolved['activities'].items() if key in activity_ids}
    return dict(version=SNAPSHOT_VERSION, risks={key: entry for key, entry in risks.items() if len(entry) > 1}, activities={key: entry for key, entry in activities.items() if len(entry) > 1},
                source=_imported(snapshot)[2])


def for_period(saved):
    """Descriptions for a stored review snapshot. `basis` is 'captured' when the snapshot carries its own copy; a snapshot from before descriptions were
    retained ('legacy') offers only the local business text that was frozen with its risk records, never imported text and never today's values."""
    copy = saved.get('metadata')
    if isinstance(copy, dict) and copy.get('version') == SNAPSHOT_VERSION:
        return dict(basis='captured', risks=copy.get('risks') or {}, activities=copy.get('activities') or {}, source=copy.get('source') or {})
    risks = {}
    for item in saved.get('risks', []):
        local = item.get('local') or {}
        entry = _entry(RISK_FIELDS, {}, SimpleNamespace(**{attribute: local.get(attribute, '') for _, attribute in RISK_FIELDS.values()}))
        if len(entry) > 1:
            risks[item['risk_id']] = entry
    return dict(basis='legacy', risks=risks, activities={}, source={})
