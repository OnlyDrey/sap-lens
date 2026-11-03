"""Field-level local overrides, imported metadata, then curated reference guidance.

Detection never reads this resolver; review snapshots retain resolved values and provenance.
"""
from types import SimpleNamespace

from sod_catalogue import read as read_local

# Resolved field -> (key in the imported metadata, attribute of the local annotation).
RISK_FIELDS = {'name': ('name', 'display_name'), 'description': ('description', 'explanation_en'),
               'impact': ('impact', 'consequence_en'), 'business_process': ('business_process', 'business_category'),
               'controls': ('controls', 'mitigating_controls_en'), 'guidance': ('guidance', 'review_guidance_en'), 'notes': ('notes', 'notes')}
ACTIVITY_FIELDS = {'name': ('name', 'display_name'), 'description': ('description', 'explanation_en'),
                   'business_process': ('business_process', 'business_category'), 'guidance': ('guidance', 'review_guidance_en'), 'notes': ('notes', 'notes')}
IMPORTED_ONLY_ACTIVITY = ('type',)


def resolve(imported, local, reference=''):
    """Non-empty local overrides win; retain the next differing source as an alternate."""
    values = [(origin, (value or '').strip()) for origin, value in (('local', local), ('imported', imported), ('reference', reference))]
    values = [(origin, value) for origin, value in values if value]
    if not values:
        return dict(value='', origin=None, alternate='', alternate_origin=None)
    origin, value = values[0]
    alternate = next(((other_origin, other) for other_origin, other in values[1:] if other != value), (None, ''))
    return dict(value=value, origin=origin, alternate=alternate[1], alternate_origin=alternate[0])


def _imported(snapshot):
    report = (snapshot.sod or {}).get('report') or {}
    metadata = report.get('metadata') or {}
    return metadata.get('risks') or {}, metadata.get('activities') or {}, metadata.get('source') or {}, report.get('optional_columns') or {}


def _entry(fields, imported, local, reference=None):
    resolved = {name: resolve(imported.get(source), getattr(local, attribute, '') if local is not None else '', (reference or {}).get(attribute, '')) for name, (source, attribute) in fields.items()}
    entry = {name: item['value'] for name, item in resolved.items() if item['value']}
    entry['origin'] = {name: item['origin'] for name, item in resolved.items() if item['value']}
    inherited = {name: resolve(imported.get(source), '', (reference or {}).get(attribute, '')) for name, (source, attribute) in fields.items()}
    if any(item['value'] for item in inherited.values()):
        entry['inherited'] = {name: item['value'] for name, item in inherited.items() if item['value']}
        entry['inherited_origin'] = {name: item['origin'] for name, item in inherited.items() if item['value']}
    if reference:
        entry['reference'] = {name: reference[attribute] for name, (_, attribute) in fields.items() if reference.get(attribute)}

    differing = {name: dict(value=item['alternate'], origin=item['alternate_origin']) for name, item in resolved.items() if item['alternate']}
    if differing:
        entry['alternate'] = differing
    return entry


def lookup(snapshot=None, saved=None, reference=None):
    """Resolved descriptions for every risk and activity that has any: `{risks: {id: {...}}, activities: {id: {...}}}`. Empty entries are omitted."""
    import cache
    snapshot = snapshot if snapshot is not None else cache.get_snapshot()
    saved = saved if saved is not None else read_local()
    from sod_reference import read as read_reference
    reference = reference if reference is not None else read_reference()
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
        entry = _entry(RISK_FIELDS, imported_risks.get(risk_id, {}), stored.metadata if stored else None, reference.risks.get(risk_id) if risk_id in definitions else None)
        definition = definitions.get(risk_id)
        if definition:
            entry.update(criticality=definition['criticality'], type=definition['risk_type'], activities=sorted({mapping['activity'] for slot in ('ACTVT1','ACTVT2') for mapping in definition['activities'][slot]}))
        if definition or any(key in entry for key in ('name', 'description', 'impact', 'business_process')):
            risks_out[risk_id] = entry
    for name in sorted(set(activities) | set(saved.activities) | set(imported_activities)):
        stored = saved.activities.get(name)
        entry = _entry(ACTIVITY_FIELDS, imported_activities.get(name, {}), stored.metadata if stored else None, reference.activities.get(name) if name in activities else None)
        for key in IMPORTED_ONLY_ACTIVITY:
            if imported_activities.get(name, {}).get(key):
                entry[key] = imported_activities[name][key]
                entry['origin'][key] = 'imported'
        if name in activities:
            entry['risks'] = len(activities[name])
            entry['risk_ids'] = sorted(activities[name])
        if name in activities or any(key in entry for key in ('name', 'description', 'business_process', 'type')):
            activities_out[name] = entry
    return dict(risks=risks_out, activities=activities_out, active_activities=sorted(activities))


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

    from sod_reference import read as read_reference, summary
    reference = read_reference()
    resolved = lookup(snapshot, saved, reference)

    def over(ids, imported, stored, source_key, local_attribute, column):
        library = reference.risks if stored is saved.entries else reference.activities
        origins = [resolve((imported.get(key) or {}).get(source_key), getattr(stored[key].metadata, local_attribute, '') if key in stored else '', library.get(key, {}).get(local_attribute, ''))['origin'] for key in ids]
        imported_count, local_count, reference_count = (origins.count(origin) for origin in ('imported', 'local', 'reference'))
        differing = sum(bool(key in stored and getattr(stored[key].metadata, local_attribute, '') and imported.get(key, {}).get(source_key) and getattr(stored[key].metadata, local_attribute) != imported[key][source_key]) for key in ids)
        result = _indicator('', len(ids), imported_count, local_count + reference_count, column in detected, differing)
        result.update(local_fallback=local_count, reference=reference_count)
        return result

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
        reference={**summary(reference), 'matched_risks': len(risk_ids & reference.risks.keys()), 'matched_activities': len(activity_ids & reference.activities.keys()),
                   'unmatched_risks': sorted(reference.risks.keys() - risk_ids), 'unmatched_activities': sorted(reference.activities.keys() - activity_ids)},
        optional_columns=dict(detected=[field for field in OPTIONAL_FIELDS if field in detected], missing=[field for field in OPTIONAL_FIELDS if field not in detected]),
        source_facts=[dict(field=column, detected=column in detected, values=source.get(key, [])) for column, key in SOURCE_METADATA.items()],
        sample=[dict(id=key, kind='risk', **{name: entry[name] for name in ('name', 'description') if name in entry}, origin=entry['origin'])
                for key, entry in list(resolved['risks'].items()) if 'name' in entry or 'description' in entry][:5],
        note='Counts use distinct risks, activities and transaction codes. Priority: non-empty local overrides, imported metadata, then curated reference definitions. Reference records never activate risks or activities; no description is generated.')


# ----------------------------------------------------------------------------------------------- review snapshots and reports

SNAPSHOT_VERSION = 1


def frozen(snapshot, saved, risk_ids):
    """The resolved descriptions of the given risks and of their activities, as they are when a review snapshot is captured.

    The copy is stored inside the immutable snapshot, so a period's report never reads descriptions that were imported or edited later.
    Origins and differing alternates are kept; nothing is generated, and detection never reads this.
    """
    from sod_reference import read as read_reference, summary
    reference = read_reference()
    resolved = lookup(snapshot, saved, reference)
    wanted = set(risk_ids)
    activity_ids = {mapping['activity'] for risk in (snapshot.sod or {}).get('risks', []) if risk['risk_id'] in wanted for slot in ('ACTVT1', 'ACTVT2') for mapping in risk['activities'][slot]}
    risks = {key: {name: value for name, value in entry.items() if name not in ('criticality', 'type', 'risks')} for key, entry in resolved['risks'].items() if key in wanted}
    activities = {key: {name: value for name, value in entry.items() if name != 'risks'} for key, entry in resolved['activities'].items() if key in activity_ids}
    return dict(version=SNAPSHOT_VERSION, risks={key: entry for key, entry in risks.items() if len(entry) > 1}, activities={key: entry for key, entry in activities.items() if len(entry) > 1},
                source={**_imported(snapshot)[2], 'reference': summary(reference)})


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
