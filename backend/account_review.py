"""Local evidence-based review. Decisions are annotations, never SAP account actions."""
import hashlib
import json
import threading
import re
from datetime import date, datetime
from fastapi import HTTPException
from config import atomic_write, config_dir
from user_access import interval_status, sap_date
from employee_directory import sap_email_owners, match_sap_identity

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
    path = config_dir() / 'account-review.json'
    if not path.exists(): return {}
    try:
        with path.open('rb') as stream: raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES: raise ValueError()
        data = json.loads(raw)
        if not isinstance(data, dict): raise ValueError()
        if data.get('format') != 1 or not isinstance(data['decisions'], dict): raise ValueError()
        for key, item in data['decisions'].items():
            if not re.fullmatch(r'[a-f0-9]{64}', key) or not isinstance(item, dict) or item['state'] not in STATES: raise ValueError()
            if any(not isinstance(item[field], str) for field in ('reviewer', 'rationale', 'evidence_version', 'timestamp')): raise ValueError()
            if not re.fullmatch(r'[a-f0-9]{64}', item['evidence_version']) or len(item['reviewer']) > 120 or len(item['rationale']) > 2000: raise ValueError()
            datetime.fromisoformat(item['timestamp'])
        return data['decisions']
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(409, 'Review annotations could not be read. Original storage is retained; review local application storage before recovery.') from None


def rows(state, directory, saved, groups, today=None):
    today = today or date.today()
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
        version = digest([user, employee, match['status'], groups, valid, findings])
        decision = saved.get(digest(user['username'].strip().upper()))
        stale = bool(decision and decision['evidence_version'] != version)
        result.append(dict(username=user['username'], name=' / '.join(' '.join(n).strip() for n in user['names'] if any(n)),
                           groups=user['groups'], sap_validity=valid, lock_status=locked, ad_status=ad,
                           match_status=match['status'], findings=findings, unlicensed=unlicensed,
                           evidence_version=version, decision=decision, stale=stale,
                           review_state='Needs review' if not decision or stale else decision['state'],
                           needs_review=bool(findings or stale)))
    return result


def save_decision(username, decision):
    with lock:
        data = decisions()
        data[digest(username.strip().upper())] = decision
        raw = json.dumps({'format': 1, 'decisions': data}, ensure_ascii=False).encode()
        if len(raw) > MAX_BYTES: raise HTTPException(409, 'Review annotation storage is full.')
        try: atomic_write(config_dir() / 'account-review.json', raw)
        except OSError: raise HTTPException(409, 'Review decision could not be saved. Previous decisions are retained.') from None


_cached = None


def cached_rows(state, directory, saved, groups, today):
    """One bounded publication cache; page/export reads do not re-hash every assignment."""
    global _cached
    key = (state.last_loaded, directory.digest if directory else None, digest(saved), tuple(groups), today)
    with lock:
        if _cached is None or _cached[0] != key:
            # Cache derived rows only; do not retain a second full SAP snapshot.
            _cached = (key, rows(state, directory, saved, groups, today))
        return _cached[1]
