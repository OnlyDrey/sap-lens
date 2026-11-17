"""Python v1 reference for MIG-004 (functional_groups.py, functional_group_analysis.py).
Records user identity keys, text normalization, suggestion-rule matching, consolidated suggestions, the format 1 -> 2 migration of a legacy store and
the advisory group analysis over the synthetic SoD analysis users (fixed date). Usage: python -I tools/functional_groups_reference.py BACKEND_DIR FIXTURE_DIR"""
import json, os, shutil, sys, tempfile
from datetime import date
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
backend, fixtures = sys.argv[1:3]
sys.path.insert(0, backend)
from pathlib import Path
import cache, config
import functional_groups as fg
from functional_group_analysis import analyse
from user_access import build_users

names = ['user00001', ' User00001 ', 'ÆØÅ.user', 'quote"back\\slash', 'tab\tuser', 'ＦＵＬＬ']
texts = ['  Finance   Ops ', 'ﬁnance', 'STRASSE', 'Straße', '', 'Ｆｉｎａｎｃｅ Team']
groups = {'fg_aaaaaaaaaaaa': dict(id='fg_aaaaaaaaaaaa', name='Finance', description='', status='active', created='2026-01-01T00:00:00+00:00', modified='2026-01-01T00:00:00+00:00'),
          'fg_bbbbbbbbbbbb': dict(id='fg_bbbbbbbbbbbb', name='Procurement', description='', status='active', created='2026-01-01T00:00:00+00:00', modified='2026-01-01T00:00:00+00:00'),
          'fg_cccccccccccc': dict(id='fg_cccccccccccc', name='Old', description='', status='archived', created='2026-01-01T00:00:00+00:00', modified='2026-01-01T00:00:00+00:00')}
rules = [dict(id='fr_000000000001', group_id='fg_aaaaaaaaaaaa', department='Finance', title_contains='', department_mode='contains'),
         dict(id='fr_000000000002', group_id='fg_aaaaaaaaaaaa', department='', title_contains='Accountant', department_mode='contains'),
         dict(id='fr_000000000003', group_id='fg_bbbbbbbbbbbb', department='Finance Ops', title_contains='Buyer', department_mode='equals'),
         dict(id='fr_000000000004', group_id='fg_cccccccccccc', department='Finance', title_contains=''),
         dict(id='fr_000000000005', group_id='fg_bbbbbbbbbbbb', department='Procurement', title_contains='', department_mode='equals')]
people = [('Finance Ops', 'Senior Accountant'), ('finance  ops', 'Buyer'), ('Procurement', ''), ('', 'Accountant'), ('Group Finance', 'Analyst'), ('HR', 'Buyer')]
store = dict(format=2, groups=groups, users={}, history=[], rules=rules)
matches = [dict(rule=r['id'], department=d, title=t, reasons=fg.rule_matches(r, d, t)) for r in rules for d, t in people]
suggestions = [dict(department=d, title=t, held=['fg_aaaaaaaaaaaa'], result=fg.suggest(d, t, store, ['fg_aaaaaaaaaaaa'])) for d, t in people]
legacy = dict(format=1, groups=groups, history=[], rules=[dict(id='fr_000000000009', group_id='fg_aaaaaaaaaaaa', department='Finance', title_contains='')], users={
    fg.user_key('USER00001'): dict(username='USER00001', group_id='fg_aaaaaaaaaaaa', status='Confirmed', revision=2, confirmed_at='2026-01-02T00:00:00+00:00', confirmed_by='Ada',
                                   rationale='Owns AP', updated_at='2026-01-02T00:00:00+00:00', handled=['c1']),
    fg.user_key('USER00002'): dict(username='USER00002', group_id='fg_bbbbbbbbbbbb', status='Needs review', revision=3, confirmed_at='2026-01-02T00:00:00+00:00', confirmed_by='Ada',
                                   rationale='', review=dict(change_id='c9', reason='Department changed', required_since='2026-01-03T00:00:00+00:00'), handled=[]),
    fg.user_key('USER00003'): dict(username='USER00003', group_id=None, status='Unassigned', revision=1)})
migrated = fg.validate_storage(json.loads(json.dumps(legacy)))

work = Path(tempfile.mkdtemp())
source = Path(fixtures).resolve().parent / 'sod' / 'analysis'
shutil.copy(source / 'roles.sod.txt', work / 'roles.csv')
shutil.copy(source / 'users.sod.txt', work / 'users.csv')
settings = config.get_settings()
state = cache._build_catalog(str(work / 'roles.csv'), settings)
profile = next(p for p in settings.user_import_profiles if p.id == settings.active_user_import)
state.users = build_users(str(work / 'users.csv'), profile, state.roles)
group = groups['fg_aaaaaaaaaaaa']
members = ['USER00152', 'user00170', 'USER00017', 'USER00296', 'USER00287', 'GHOST01']
analyses = [dict(members=m, today='2026-11-16', result=analyse(state, m, group, date(2026, 11, 16))) for m in (members, members[:2], members[:4])]
out = dict(user_keys={n: fg.user_key(n) for n in names}, normalized={t: fg.name_key(t) for t in texts}, matches=matches, suggestions=suggestions, legacy=legacy,
           migrated=migrated, analyses=analyses)
(Path(fixtures).resolve() / 'functional-groups.python.json').write_text(json.dumps(out, ensure_ascii=False, indent=0, sort_keys=True) + '\n', encoding='utf-8')
print(len(matches), 'rule matches,', len(suggestions), 'suggestions,', len(analyses), 'analyses')
