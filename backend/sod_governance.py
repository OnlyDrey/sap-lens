"""Pure SoD 2.0 derivations over user findings: assignments, activities, matrices and what-if impact.

Inputs are the user findings produced by ``sod_analysis`` (live, or frozen in a period
snapshot). Nothing here reads or writes storage, and nothing mutates the evidence it is
given: the technical conflict calculation stays independent of every review decision.
Review population = activities and assignments that contribute to a detected conflict.
"""
from collections import defaultdict

from sod_analysis import _digest
from sod_decisions import lifecycle


def assignment_id(user, path):
    """Stable identity of one actual assignment: user, assigned role, validity and group."""
    return _digest(['sod-assignment', 1, user, path.get('actual_assigned_role', ''), path.get('role_valid_from') or '',
                    path.get('role_valid_to') or '', path.get('user_group', '')])


def activity_key(user, activity):
    return _digest(['sod-activity', 1, user, activity])


def derive(findings, only_current=True):
    """Index findings by user into activities, assignments and per-risk side providers."""
    users = {}
    for finding in findings:
        if finding['kind'] != 'user' or only_current and not finding['current_potential']:
            continue
        user = finding['subject']
        entry = users.setdefault(user, dict(user=user, findings={}, activities={}, assignments={}, groups=set(), account=finding.get('account')))
        entry['findings'][finding['risk_id']] = finding
        for slot, paths in finding['evidence'].items():
            for path in paths:
                aid = assignment_id(user, path)
                assignment = entry['assignments'].setdefault(aid, dict(
                    id=aid, user=user, role=path.get('actual_assigned_role', ''), valid_from=path.get('role_valid_from'),
                    valid_to=path.get('role_valid_to'), user_group=path.get('user_group', ''),
                    interval_status=path.get('interval_status'), matching_status=path.get('matching_status'),
                    catalogue_roles=set(), single_roles=set(), supplies=defaultdict(set), risks=set()))
                assignment['catalogue_roles'].add(path['matched_catalogue_pattern'])
                assignment['single_roles'].add(path['single_role'])
                assignment['supplies'][path['activity']].add(path['matrix_transaction'])
                assignment['risks'].add(finding['risk_id'])
                activity = entry['activities'].setdefault(path['activity'], dict(
                    activity=path['activity'], key=activity_key(user, path['activity']), risks=set(), slots=set(), tcodes=set(), assignments=set()))
                activity['risks'].add(finding['risk_id'])
                activity['slots'].add(slot)
                activity['tcodes'].add(path['matrix_transaction'])
                activity['assignments'].add(aid)
                if path.get('user_group'):
                    entry['groups'].add(path['user_group'])
    for entry in users.values():
        for activity in entry['activities'].values():
            activity['evidence_version'] = _digest(['sod-activity-evidence', 1, entry['user'], activity['activity'], sorted(activity['tcodes'])])
        for assignment in entry['assignments'].values():
            assignment['evidence_version'] = _digest(['sod-assignment-evidence', 1, assignment['id'],
                                                      sorted((name, code) for name, codes in assignment['supplies'].items() for code in codes)])
    return users


def listify(value):
    """JSON-ready copy: sets become sorted lists, defaultdicts plain dicts."""
    if isinstance(value, (set, frozenset)):
        return sorted(listify(item) for item in value)
    if isinstance(value, dict):
        return {key: listify(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [listify(item) for item in value]
    return value


def activity_detail(entry, key_or_name):
    """Activity row including the contributing assignments, duplicate coverage and sibling activities."""
    activity = entry['activities'].get(key_or_name) or next((item for item in entry['activities'].values() if item['key'] == key_or_name), None)
    if activity is None:
        return None
    assignments = []
    for aid in sorted(activity['assignments']):
        assignment = entry['assignments'][aid]
        assignments.append(dict(id=aid, role=assignment['role'], valid_from=assignment['valid_from'], valid_to=assignment['valid_to'],
                                user_group=assignment['user_group'], interval_status=assignment['interval_status'],
                                tcodes=sorted(assignment['supplies'][activity['activity']]),
                                other_activities=sorted(name for name in assignment['supplies'] if name != activity['activity']),
                                risks=sorted(assignment['risks']), catalogue_roles=sorted(assignment['catalogue_roles']),
                                evidence_version=assignment['evidence_version']))
    return dict(activity=activity['activity'], key=activity['key'], risks=sorted(activity['risks']), slots=sorted(activity['slots']),
                tcodes=sorted(activity['tcodes']), evidence_version=activity['evidence_version'], assignments=assignments,
                duplicate_coverage=len(assignments) > 1)


def simulate(entry, removed, decisions=None):
    """Non-destructive what-if: remove assignments for one user and recompute using the same two-sided rule.

    ``decisions`` maps activity name -> latest decision, only used to warn about approved access that
    would disappear. The input evidence is never changed.
    """
    removed = set(removed)
    unknown = removed - set(entry['assignments'])
    if unknown:
        raise ValueError('Select assignments that contribute to this user\'s detected evidence.')
    before, after, resolved = [], [], []
    for risk_id, finding in sorted(entry['findings'].items()):
        before.append(risk_id)
        remaining = {slot: [path for path in paths if assignment_id(entry['user'], path) not in removed]
                     for slot, paths in finding['evidence'].items()}
        still = all(any(path.get('interval_status') == 'active' for path in paths) for paths in remaining.values()) \
            if finding['current_potential'] else all(remaining.values())
        (after if still else resolved).append(risk_id)
    lost = []
    for name, activity in sorted(entry['activities'].items()):
        if activity['assignments'] and activity['assignments'] <= removed:
            lost.append(name)
    affected = sorted(name for name in lost if (decisions or {}).get(name) in {'Approved', 'Conditional'})
    return dict(removed=sorted(removed), before=before, after=after, resolved=resolved, lost_activities=lost,
                affected_approved_activities=affected,
                warnings=[f'Removal would end approved access to activity {name}.' for name in affected],
                eliminates_all=bool(before) and not after)


def removal_options(entry, risk_id, decisions=None):
    """Valid remediation alternatives for one risk: all providers of either activity side."""
    finding = entry['findings'].get(risk_id)
    if finding is None:
        return []
    options = []
    for slot, paths in sorted(finding['evidence'].items()):
        providers = sorted({assignment_id(entry['user'], path) for path in paths})
        activities = sorted({path['activity'] for path in paths})
        result = simulate(entry, providers, decisions)
        options.append(dict(slot=slot, activities=activities, assignments=providers,
                            roles=sorted({entry['assignments'][aid]['role'] for aid in providers}),
                            resolves_risk=risk_id in result['resolved'], also_resolves=[item for item in result['resolved'] if item != risk_id],
                            affected_approved_activities=result['affected_approved_activities'], warnings=result['warnings']))
    return options


def single_assignment_impact(entry, aid, decisions=None):
    result = simulate(entry, {aid}, decisions)
    return dict(assignment_id=aid, resolves=result['resolved'], remaining=result['after'], lost_activities=result['lost_activities'],
                affected_approved_activities=result['affected_approved_activities'], warnings=result['warnings'],
                eliminates_all=result['eliminates_all'])


def role_suffix(name):
    """Organizational suffix token of an assigned role: the text after its last ':', '_' or '-' separator ('' without one)."""
    cut = max(name.rfind(mark) for mark in ':_-')
    return name[cut + 1:] if cut >= 0 else ''


def shown(entry):
    """Assignments of a (possibly restricted) user entry that pass the assignment-level filters; all of them when none apply."""
    allowed = entry.get('visible_assignments')
    return entry['assignments'] if allowed is None else {aid: item for aid, item in entry['assignments'].items() if aid in allowed}


def restrict(model, visible, allowed=None):
    """View of ``model`` limited to visible (user, risk) cells; evidence versions and assignments stay complete.

    ``allowed`` maps user -> assignment ids that pass the assignment-level filters (role, suffix, group, activity,
    transaction, assignment review). Lists of assignments (access list, role lookup, review queue, remediation)
    show only those, while evidence and decisions keep using the complete assignment records.
    """
    result = {}
    for user, entry in model.items():
        risks = visible.get(user)
        if not risks:
            continue
        result[user] = dict(entry, visible_assignments=None if allowed is None else allowed.get(user, set()), findings={risk: item for risk, item in entry['findings'].items() if risk in risks},
                            activities={name: dict(item, risks=item['risks'] & risks) for name, item in entry['activities'].items() if item['risks'] & risks})
    return result


def states(model, latest, today=None):
    """Decision lifecycle per review item, keyed by subject key. ``latest`` is decisions.latest(context)."""
    result = dict(activity={}, assignment={}, acceptance={})
    for entry in model.values():
        for activity in entry['activities'].values():
            event = latest['activity'].get(activity['key'])
            result['activity'][activity['key']] = (lifecycle('activity', event, activity['evidence_version'], today), event)
        for assignment in entry['assignments'].values():
            event = latest['assignment'].get(assignment['id'])
            result['assignment'][assignment['id']] = (lifecycle('assignment', event, assignment['evidence_version'], today), event)
        for finding in entry['findings'].values():
            event = latest['acceptance'].get(finding['finding_id'])
            result['acceptance'][finding['finding_id']] = (lifecycle('acceptance', event, finding['evidence_version'], today), event)
    return result


def _bucket(values):
    counts = defaultdict(int)
    for value in values:
        counts[value] += 1
    return dict(counts)


def risk_matrix(model, state):
    """Distinct user-risk cells; totals count distinct users and distinct user-risk pairs, never cell sums."""
    columns, rows = {}, []
    for user, entry in sorted(model.items()):
        cells = {}
        for risk_id, finding in sorted(entry['findings'].items()):
            sides = sorted({name for name, activity in entry['activities'].items() if risk_id in activity['risks']})
            review = _bucket(state['activity'][entry['activities'][name]['key']][0] for name in sides)
            acceptance = state['acceptance'][finding['finding_id']][0]
            cells[risk_id] = dict(finding_id=finding['finding_id'], criticality=finding['criticality'], acceptance=acceptance, activities=review)
            risk = finding.get('risk') or {}
            column = columns.setdefault(risk_id, dict(risk_id=risk_id, criticality=finding['criticality'], display_name=risk.get('display_name', ''),
                                                      source_text=risk.get('source_text', ''), category=risk.get('business_category', ''), users=set()))
            column['users'].add(user)
        rows.append(dict(user=user, groups=sorted(entry['groups']), cells=cells))
    ordered = [dict(item, users=len(item['users'])) for _, item in sorted(columns.items())]
    criticality = defaultdict(lambda: dict(risks=0, user_risk=0, users=set()))
    for item in columns.values():
        criticality[item['criticality']]['risks'] += 1
        criticality[item['criticality']]['user_risk'] += len(item['users'])
        criticality[item['criticality']]['users'] |= item['users']
    return dict(columns=ordered, rows=rows,
                totals=dict(users=len(rows), user_risk=sum(len(row['cells']) for row in rows), risks=len(ordered)),
                criticality={key: dict(risks=value['risks'], user_risk=value['user_risk'], users=len(value['users'])) for key, value in sorted(criticality.items())})


def activity_matrix(model, state):
    columns, rows = {}, []
    for user, entry in sorted(model.items()):
        cells = {}
        for name, activity in sorted(entry['activities'].items()):
            lifecycle_name = state['activity'][activity['key']][0]
            cells[name] = dict(key=activity['key'], decision=lifecycle_name, roles=len(activity['assignments']), risks=sorted(activity['risks']),
                               duplicate=len(activity['assignments']) > 1)
            column = columns.setdefault(name, dict(activity=name, risks=set(), users=set()))
            column['risks'] |= activity['risks']
            column['users'].add(user)
        rows.append(dict(user=user, groups=sorted(entry['groups']), cells=cells))
    ordered = [dict(activity=item['activity'], risks=sorted(item['risks']), users=len(item['users'])) for _, item in sorted(columns.items())]
    return dict(columns=ordered, rows=rows, totals=dict(users=len(rows), user_activity=sum(len(row['cells']) for row in rows), activities=len(ordered)))


def aggregate_by_group(matrix, key='cells'):
    """Rows per SAP user group (a user in several groups counts in each); totals remain distinct users."""
    groups = defaultdict(lambda: dict(users=set(), cells=defaultdict(set)))
    for row in matrix['rows']:
        for group in row['groups'] or ['(no group)']:
            groups[group]['users'].add(row['user'])
            for column in row['cells']:
                groups[group]['cells'][column].add(row['user'])
    rows = [dict(user=group, groups=[group], users=len(item['users']), cells={column: dict(users=len(users)) for column, users in sorted(item['cells'].items())})
            for group, item in sorted(groups.items())]
    return dict(matrix, rows=rows)


def place_in_groups(rows, preferred=(), reverse=False):
    """Rows ordered by SAP User Group for the grouped matrix view, each user exactly once.

    A user in several groups is placed under the first of their groups that the filter selected, otherwise under
    their first group, so the groups partition the users (no duplicates, none omitted). Returns the ordered rows
    (each with ``group``) and one summary per group: distinct users, finding cells and the index of its first row.
    """
    wanted = {name.casefold() for name in preferred}
    buckets = {}
    for row in rows:
        groups = row['groups']
        pick = next((name for name in groups if name.casefold() in wanted), groups[0] if groups else '(no group)')
        buckets.setdefault(pick, []).append(dict(row, group=pick))
    names = sorted(buckets, key=lambda name: (name == '(no group)', name.casefold(), name))
    if reverse:
        names.reverse()
    ordered, summaries = [], []
    for name in names:
        members = buckets[name]
        summaries.append(dict(name=name, users=len(members), findings=sum(len(row['cells']) for row in members), start=len(ordered)))
        ordered += members
    return ordered, summaries


def explorer_rows(table, model, state):
    """Flat investigation tables for the Access Explorer; every row traces back to user, risk, activity and assignment."""
    rows = []
    for user, entry in sorted(model.items()):
        if table == 'user_risk':
            for risk_id, finding in sorted(entry['findings'].items()):
                names = sorted(name for name, activity in entry['activities'].items() if risk_id in activity['risks'])
                rows.append(dict(user=user, risk_id=risk_id, criticality=finding['criticality'], category=(finding.get('risk') or {}).get('business_category', ''),
                                 groups=sorted(entry['groups']), activities=names,
                                 roles=sorted({entry['assignments'][aid]['role'] for name in names for aid in entry['activities'][name]['assignments'] if aid in shown(entry)}),
                                 acceptance=state['acceptance'][finding['finding_id']][0], finding_id=finding['finding_id']))
        elif table == 'user_activity':
            for name, activity in sorted(entry['activities'].items()):
                rows.append(dict(user=user, activity=name, risks=sorted(activity['risks']), tcodes=sorted(activity['tcodes']), roles=len(activity['assignments']),
                                 duplicate=len(activity['assignments']) > 1, decision=state['activity'][activity['key']][0], key=activity['key']))
        elif table == 'access_list':
            for aid, assignment in sorted(shown(entry).items(), key=lambda pair: (pair[1]['role'], pair[0])):
                rows.append(dict(user=user, id=aid, role=assignment['role'], suffix=role_suffix(assignment['role']), evidence_version=assignment['evidence_version'], valid_from=assignment['valid_from'], valid_to=assignment['valid_to'],
                                 interval_status=assignment['interval_status'], user_group=assignment['user_group'],
                                 activities=sorted(assignment['supplies']), risks=sorted(assignment['risks']),
                                 catalogue_roles=sorted(assignment['catalogue_roles']), decision=state['assignment'][aid][0]))
    if table == 'lookup':
        roles = {}
        for user, entry in model.items():
            for assignment in shown(entry).values():
                role = roles.setdefault(assignment['role'], dict(role=assignment['role'], users=set(), activities=set(), risks=set(), catalogue_roles=set()))
                role['users'].add(user)
                role['activities'] |= set(assignment['supplies'])
                role['risks'] |= assignment['risks']
                role['catalogue_roles'] |= assignment['catalogue_roles']
        rows = [dict(role=name, users=len(item['users']), activities=sorted(item['activities']), risks=sorted(item['risks']),
                     catalogue_roles=sorted(item['catalogue_roles'])) for name, item in sorted(roles.items())]
    return rows


def queue_items(model, state, context_info=None):
    """Work-queue rows for activity, assignment and risk-acceptance reviews of the visible population."""
    items = []
    for user, entry in sorted(model.items()):
        for name, activity in sorted(entry['activities'].items()):
            lifecycle_name, event = state['activity'][activity['key']]
            items.append(dict(kind='activity', key=activity['key'], user=user, ref=name, risks=sorted(activity['risks']), lifecycle=lifecycle_name,
                              roles=len(activity['assignments']), event=event, evidence_version=activity['evidence_version']))
        for aid, assignment in sorted(shown(entry).items()):
            lifecycle_name, event = state['assignment'][aid]
            items.append(dict(kind='assignment', key=aid, user=user, ref=assignment['role'], risks=sorted(assignment['risks']), lifecycle=lifecycle_name,
                              roles=len(assignment['supplies']), event=event, evidence_version=assignment['evidence_version']))
        for risk_id, finding in sorted(entry['findings'].items()):
            lifecycle_name, event = state['acceptance'][finding['finding_id']]
            items.append(dict(kind='acceptance', key=finding['finding_id'], user=user, ref=risk_id, risks=[risk_id], lifecycle=lifecycle_name,
                              roles=0, event=event, evidence_version=finding['evidence_version']))
    return items


GROUPS = ('Remove assignment', 'Investigate assignment', 'Apply compensating control', 'Maintain access', 'No action required')


def conflict_concentration(model):
    """Users with more than one distinct risk, and the assigned roles behind the most distinct user-risk findings.

    A finding is one (user, risk) pair, so a role is never counted twice for the same user and risk however many
    activities or assignments of it supply that risk.
    """
    roles = {}
    for user, entry in model.items():
        for assignment in entry['assignments'].values():
            for risk in assignment['risks'] & entry['findings'].keys():
                item = roles.setdefault(assignment['role'], dict(users=set(), findings=set()))
                item['users'].add(user)
                item['findings'].add((user, risk))
    ranked = sorted(((role, len(item['users']), len(item['findings'])) for role, item in roles.items()), key=lambda row: (-row[2], -row[1], row[0].casefold()))
    return dict(multi_risk_users=sum(1 for entry in model.values() if len(entry['findings']) > 1),
                top_roles=[dict(role=role, users=users, findings=findings) for role, users, findings in ranked[:50]], top_roles_total=len(ranked))


def remediation_rows(model, state, actions, verify, today=None, include_pending=False):
    """Recommended handling per (user, activity, assignment) for decided items; pending items are excluded.

    ``verify(user, assignment_id)`` returns the verification text for a tracked removal. A completed action
    is a manual claim only; verification comes from later source evidence.
    """
    from datetime import date as _date
    today = today or _date.today()
    tracked = {}
    for action in sorted(actions, key=lambda item: item.modified):
        if action.assignment_id and action.status != 'Cancelled':
            tracked[(action.assignment_id, action.recommended)] = action
    rows, undecided = [], 0
    for user, entry in sorted(model.items()):
        for aid, assignment in sorted(shown(entry).items(), key=lambda pair: (pair[1]['role'], pair[0])):
            a_state, a_event = state['assignment'][aid]
            for name in sorted(assignment['supplies']):
                activity = entry['activities'].get(name)
                if activity is None:
                    continue
                risks = sorted(assignment['risks'] & activity['risks'])
                c_state, c_event = state['activity'][activity['key']]
                accept = [state['acceptance'][entry['findings'][risk]['finding_id']] for risk in risks if risk in entry['findings']]
                accept_states = {item[0] for item in accept}
                if a_state == 'Removal required':
                    recommended, reason = 'Remove assignment', (a_event.justification if a_event else '')
                elif a_state == 'Investigate':
                    recommended, reason = 'Investigate assignment', (a_event.justification if a_event else '')
                elif c_state == 'Removal required':
                    recommended, reason = 'Investigate assignment', 'Activity marked for removal: ' + (c_event.justification if c_event else '')
                elif 'Rejected' in accept_states:
                    recommended, reason = 'Investigate assignment', 'Risk acceptance rejected.'
                elif c_state == 'Conditional':
                    recommended, reason = 'Apply compensating control', (c_event.controls if c_event else '')
                elif a_state == 'Keep' or c_state == 'Approved' and a_state == 'Pending':
                    recommended = 'No action required' if accept_states == {'Accepted'} else 'Maintain access'
                    reason = (a_event or c_event).justification if (a_event or c_event) else ''
                else:
                    undecided += 1
                    if not include_pending:
                        continue
                    recommended, reason = 'Awaiting review', ''
                action = tracked.get((aid, recommended)) if recommended in ('Remove assignment', 'Investigate assignment') else None
                rows.append(dict(user=user, activity=name, risks=risks, role=assignment['role'], catalogue_roles=sorted(assignment['catalogue_roles']), assignment_id=aid, valid_from=assignment['valid_from'],
                                 valid_to=assignment['valid_to'], user_group=assignment['user_group'], activity_decision=c_state, assignment_decision=a_state,
                                 risk_acceptance=sorted(accept_states), recommended=recommended, reason=reason,
                                 controls=(c_event.controls if c_event and c_event.controls else next((e.controls for _, e in accept if e and e.controls), '')),
                                 action=action.model_dump(mode='json') if action else None,
                                 owner=action.owner if action else '', due_date=action.due_date.isoformat() if action and action.due_date else None,
                                 action_status=action.status if action else 'Not tracked',
                                 overdue=bool(action and action.due_date and action.due_date < today and action.status in {'Open', 'In progress'}),
                                 verification=(verify(user, aid) if recommended == 'Remove assignment' else 'Not verifiable from source evidence') if action else 'Not tracked'))
    summary = {name: sum(row['recommended'] == name for row in rows) for name in GROUPS + (('Awaiting review',) if include_pending else ())}
    summary.update(undecided=undecided, overdue=sum(row['overdue'] for row in rows))
    return rows, summary
