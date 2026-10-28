"""Local evidence-based review. Decisions are annotations, never SAP account actions."""
import hashlib
import json
import threading
import re
from datetime import date, datetime, timezone
import logging
from fastapi import HTTPException
from config import atomic_write, config_dir
from user_access import interval_status, sap_date
from employee_directory import sap_email_owners, match_sap_identity
from position_changes import normalize_text

lock = threading.RLock()
MAX_BYTES = 20 * 1024 * 1024
STATES = ['Needs review', 'Investigating', 'Approved for deactivation', 'No action required']
FINDINGS = {'ad_disabled_open': 'AD disabled / SAP valid and unlocked',
            'ad_disabled_locked': 'AD disabled / SAP locked', 'directory_match': 'Missing or ambiguous directory match',
            'expired': 'Expired SAP account', 'technical': 'Technical or service account'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validity(accounts, today=None):
    statuses = {interval_status(sap_date(a['valid_from']), sap_date(a['valid_to']), today) for a in accounts}
    return 'Valid' if statuses == {'active'} else 'Invalid' if statuses and statuses <= {'expired', 'future'} else 'Unknown'


def decisions():
    try:
        path = config_dir() / 'account-review.json'
        if not path.exists(): return {}
        with path.open('rb') as stream: raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES: raise ValueError()
        data = json.loads(raw)
        if not isinstance(data, dict): raise ValueError()
        if data.get('format') not in {1,2} or not isinstance(data['decisions'], dict): raise ValueError()
        def validate(item):
            if not isinstance(item,dict) or item['state'] not in STATES: raise ValueError()
            if any(not isinstance(item[field],str) for field in ('reviewer','rationale','evidence_version','timestamp')): raise ValueError()
            if not re.fullmatch(r'[a-f0-9]{64}',item['evidence_version']) or len(item['reviewer'])>120 or len(item['rationale'])>2000: raise ValueError()
            datetime.fromisoformat(item['timestamp'])
            if item.get('evidence_schema',1) not in {1,2}: raise ValueError()
            if 'identity_version' in item and not re.fullmatch(r'[a-f0-9]{64}',item['identity_version']): raise ValueError()
            if 'absent_since' in item: datetime.fromisoformat(item['absent_since'])
        for key,item in data['decisions'].items():
            if not re.fullmatch(r'[a-f0-9]{64}',key): raise ValueError()
            validate(item)
            history=item.get('history',[])
            if not isinstance(history,list) or len(history)>1000: raise ValueError()
            for event in history:
                validate(event)
                if 'history' in event: raise ValueError()
        return data['decisions']
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise HTTPException(409, 'Review annotations could not be read. Original storage is retained; review local application storage before recovery.') from None


def rows(state, directory, saved, groups, today=None, position=None):
    today = today or date.today()
    position = position or {}
    configured = {g.strip().casefold() for g in groups}
    result = []
    owners = sap_email_owners(state.users.users.values())
    for user in state.users.users.values():
        match = match_sap_identity(directory, user, owners) if directory else {'status': 'directory_unavailable', 'employee': None}
        employee = match['employee']
        ad = employee['account_status'] if employee else 'Unknown'
        valid = validity(user['accounts'], today)
        locks = {a['locked'] for a in user['accounts']}
        locked = 'Locked' if locks == {True} else 'Unlocked' if locks == {False} else 'Unknown'
        findings = []
        if ad == 'Disabled' and valid == 'Valid' and locked == 'Unlocked': findings.append('ad_disabled_open')
        if ad == 'Disabled' and locked == 'Locked': findings.append('ad_disabled_locked')
        if directory and match['status'] != 'matched': findings.append('directory_match')
        if any(interval_status(sap_date(a['valid_from']), sap_date(a['valid_to']), today) == 'expired' for a in user['accounts']): findings.append('expired')
        if any(a['user_type'].strip().upper() in {'B', 'C', 'S', 'L'} for a in user['accounts']): findings.append('technical')
        unlicensed = any(g.strip().casefold() in configured for g in user['groups'])
        legacy_version = digest([user, employee, match['status'], groups, valid, findings])
        identity = digest([user['username'].strip().upper(), sorted({e.strip().casefold() for e in user['emails']}), sorted(user['names'])])
        # Ignore CSV row IDs/order, snapshot row IDs and unrelated directory fields.
        assignments = [{k:a.get(k) for k in ('role_name','user_group','valid_from','valid_to','scope','match_status','catalogue_roles','tcodes')} for a in user['assignments']]
        canonical = lambda values: sorted((json.dumps(v,sort_keys=True) for v in values))
        version = digest([identity,canonical(user['accounts']),canonical(assignments),sorted(user['groups']),
                          {k:employee.get(k) for k in ('email','username','account_status')} if employee else None,
                          match['status'],sorted(g.casefold().strip() for g in groups),valid,findings])
        stored = saved.get(digest(user['username'].strip().upper()))
        stale = bool(stored and (stored.get('absent_since') or stored['evidence_version'] != (version if stored.get('evidence_schema')==2 else legacy_version)))
        decision = {k:v for k,v in stored.items() if k!='history'} if stored else None
        change = position.get(normalize_text(employee['email'])) if employee and match['status'] == 'matched' and employee.get('email') else None
        # A decision recorded after the change reviews it; reusing the Account Review decision avoids a second record.
        open_change = bool(change and (not stored or datetime.fromisoformat(stored['timestamp']) < datetime.fromisoformat(change['detected_at'])))
        needs = bool(findings or stale or open_change)
        result.append(dict(username=user['username'], name=' / '.join(' '.join(n).strip() for n in user['names'] if any(n)),
                           groups=user['groups'], sap_validity=valid, lock_status=locked, ad_status=ad,
                           match_status=match['status'], findings=findings, unlicensed=unlicensed,
                           evidence_version=version, identity_version=identity, evidence=dict(accounts=user['accounts'][:25],account_total=len(user['accounts']),assignment_records=len(user['assignments']),sap_emails=user['emails'][:5],directory_email=employee.get('email') if employee else None), decision=decision, history_count=len(stored.get('history',[])) if stored else 0, stale=stale,
                           review_state='Needs review' if not decision or stale or open_change else decision['state'],
                           needs_review=needs,
                           position_change=dict(id=change['id'], open=open_change, fields=change['fields'], previous_department=change['previous_department'],
                                                current_department=change['current_department'], previous_title=change['previous_title'], current_title=change['current_title'],
                                                detected_at=change['detected_at'], source_generation=change['source_generation']) if change else None,
                           priority='High' if open_change else 'Normal' if needs else 'None', priority_order=0 if open_change else 1 if needs else 2))
    return result


def write_decisions(data):
    raw = json.dumps({'format':2,'decisions':data},ensure_ascii=False).encode()
    if len(raw)>MAX_BYTES: raise HTTPException(409,'Review annotation storage is full.')
    try: atomic_write(config_dir()/'account-review.json',raw)
    except OSError: raise HTTPException(409,'Review decision could not be saved. Previous decisions are retained.') from None


def save_decision(username, decision):
    with lock:
        data=decisions();key=digest(username.strip().upper());previous=data.get(key)
        history=[*previous.get('history',[]),{k:v for k,v in previous.items() if k!='history'}] if previous else []
        if len(history)>1000: raise HTTPException(409,'Review history is full. Existing decisions are retained.')
        data[key]={**decision,'history':history}
        write_decisions(data)


def record_missing_users(state):
    """A published valid replacement can retire users; unavailable sources cannot.

    Called outside cache/directory locks to avoid lock-order inversion with review reads.
    Failure never erases annotations or blocks independent SAP source publication.
    """
    if not state.users.report: return
    try:
        if not (config_dir()/'account-review.json').exists(): return
        with lock:
            data=decisions();present={digest(name.strip().upper()) for name in state.users.users}
            changed=False
            for key,item in data.items():
                if key not in present and not item.get('absent_since'):
                    item['absent_since']=datetime.now(timezone.utc).isoformat();changed=True
            if changed: write_decisions(data)
    except (HTTPException,OSError):
        logging.getLogger('sap-lens').warning('Review presence metadata unavailable; previous annotations retained.')


_cached = None


def cached_rows(state, directory, saved, groups, today, position=None):
    """One bounded publication cache; page/export reads do not re-hash every assignment."""
    global _cached
    key = (state.last_loaded, directory.digest if directory else None, digest(saved), tuple(groups), today, tuple(sorted(position or {})) , tuple(event['id'] for event in (position or {}).values()))
    with lock:
        if _cached is None or _cached[0] != key:
            # Cache derived rows only; do not retain a second full SAP snapshot.
            _cached = (key, rows(state, directory, saved, groups, today, position))
        return _cached[1]


def current_rows(state, directory, saved, groups, today):
    """Review rows including recent employee position changes; the one place that combines them."""
    from position_changes import latest_recent, read
    position = latest_recent(read()['events'], today) if directory else {}
    return cached_rows(state, directory, saved, groups, today, position), position
