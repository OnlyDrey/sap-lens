"""Bounded employee preview: filter raw rows, render only the requested page."""
from collections import OrderedDict
from threading import Lock
from csv_lifecycle import diff_records
from employee_directory import sap_email_owners

_lock = Lock()
_deltas = OrderedDict()


def preview_page(directory, previous, snapshot, settings, request):
    key = (directory.digest, previous.digest if previous else None)
    with _lock:
        delta = _deltas.get(key)
    if delta is None:
        delta = diff_records('employees', previous.rows if previous else [], directory.rows, include_changes=False)
        delta = {name:value for name,value in delta.items() if name != 'changes'}
        with _lock:
            _deltas[key] = delta
            while len(_deltas) > 2: _deltas.popitem(last=False)
    matching_available = settings.features.user_role_mapping and bool(snapshot.users.report)
    owners = sap_email_owners(snapshot.users.users.values()) if matching_available else {}
    def quality(row):
        email = row['Mail'].strip().casefold()
        duplicate = bool(email and len(directory.indexes['Mail'][email]) > 1)
        match = ('unavailable' if not matching_available else 'ambiguous' if duplicate or owners.get(email,0)>1
                 else 'matched' if email and owners.get(email)==1 else 'unmatched')
        manager, _ = directory.manager(row)
        warnings = [name for name, applies in [('missing_email',not email),('duplicate_email',duplicate),
                    ('missing_identifier',not row['DistinguishedName'] and not row['SamAccountName']),
                    ('duplicate_identifier',any(row[field] and len(directory.indexes[field].get(row[field].strip().casefold(),[]))>1 for field in ['DistinguishedName','SamAccountName'])),
                    ('missing_manager',manager in {'missing','unresolved'}),('ambiguous_manager',manager=='ambiguous')] if applies]
        return match, warnings
    term = request.search.strip().casefold()
    rows = []
    for row in directory.rows:
        if term and term not in ' '.join(row[field] for field in ['Name','Mail','Department','ManagerName']).casefold(): continue
        if request.filter:
            match, warnings = quality(row)
            if request.filter not in warnings and request.filter != match: continue
        rows.append(row)
    field = {'name':'Name','email':'Mail','department':'Department','manager':'ManagerName'}[request.sort]
    rows.sort(key=lambda row:(row[field].casefold(),int(row['id'])),reverse=request.descending)
    items = []
    for row in rows[request.offset:request.offset+request.limit]:
        match, warnings = quality(row)
        items.append(dict(**directory.view(row),sap_match=match,validation=warnings))
    return dict(**directory.report(),digest=directory.digest,samples=[directory.view(r) for r in directory.rows[:5]],
                items=items,total=len(rows),offset=request.offset,limit=request.limit,
                replacement=delta,current_records=len(previous.rows) if previous else 0)
