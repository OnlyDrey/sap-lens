"""Atomic data generations; parsing/previews never silently rewrite role relationships."""
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable

from config import get_settings
from csv_import import CsvImport
from classification import Classifier, legacy_child_module
from module_registry import module_definition, resolve_module
from models import ModuleInfo, RoleDetail, RoleSummary, SingleRole, TCode, AssignmentSource, RoleRelationship

logger = logging.getLogger(__name__)


@dataclass
class _CacheState:
    roles: dict[str, RoleDetail] = field(default_factory=dict)
    modules: list[ModuleInfo] = field(default_factory=list)
    last_loaded: datetime | None = None
    summaries: list[RoleSummary] = field(default_factory=list)
    tcode_index: dict[str, set[str]] = field(default_factory=dict)
    import_report: dict = field(default_factory=dict)
    analysis: dict = field(default_factory=dict)


_cache = _CacheState()
_load_lock = threading.Lock()


def build_cache(path=None, configuration=None):
    settings = configuration or get_settings()
    csv_path = path if path is not None else settings.data_csv_path
    if not csv_path or '://' in csv_path: raise ValueError('Choose a filesystem CSV in Settings.')
    import_profile = next(p for p in settings.import_profiles if p.id == settings.active_import)
    classification = next(p for p in settings.classification_profiles if p.id == settings.active_classification)
    parser = CsvImport(Path(csv_path).expanduser(), import_profile)
    raw = {}
    assignments = set()
    warnings = []
    for row in parser.records():
        name = row['AGR_NAME']
        data = raw.setdefault(name, dict(text=row['TEXT'] or None, modules=[], singles={}, relationships=set(), texts=set()))
        if row['FUNCTION_KEY'] and row['FUNCTION_KEY'] not in data['modules']: data['modules'].append(row['FUNCTION_KEY'])
        if row['TEXT']: data['texts'].add(row['TEXT'])
        if row['TEXT'] and not data['text']: data['text'] = row['TEXT']
        relationship = (row['CHILD_AGR'],row['PARENT_AGR'],row['Effective_Role'])
        data['relationships'].add(relationship)
        child = row['CHILD_AGR'] or row['Effective_Role'] or (name if row['TCODE'] else '')
        if not child: continue
        single = data['singles'].setdefault(child, dict(text=row['CHILD_AGR_TEXT'] or None, texts=set(), tcodes={}, kinds=set()))
        single['kinds'].add('child' if row['CHILD_AGR'] else 'effective' if row['Effective_Role'] else 'direct')
        if row['CHILD_AGR_TEXT']: single['texts'].add(row['CHILD_AGR_TEXT'])
        if not single['text'] and row['CHILD_AGR_TEXT']: single['text'] = row['CHILD_AGR_TEXT']
        if not row['TCODE']: continue
        if not row['CHILD_AGR'] and not row['Effective_Role']:
            warnings.append('Transactions without CHILD_AGR/Effective_Role are retained as direct composite assignments.')
        source = AssignmentSource(child_agr=row['CHILD_AGR'] or None, parent_agr=row['PARENT_AGR'] or None,
                                  effective_role=row['Effective_Role'] or None)
        tc = single['tcodes'].setdefault(row['TCODE'], TCode(tcode=row['TCODE'],ttext=row['TTEXT'] or None))
        if not tc.ttext and row['TTEXT']: tc.ttext = row['TTEXT']
        if row['TTEXT'] and row['TTEXT'] != tc.ttext and row['TTEXT'] not in tc.alternate_texts:
            tc.alternate_texts.append(row['TTEXT'])
            warnings.append('Conflicting transaction descriptions are retained as alternate texts.')
        if source not in tc.assignment_sources: tc.assignment_sources.append(source)
        assignments.add((name,*relationship,row['TCODE']))
    classifier = Classifier(classification)
    roles, summaries, index, module_infos = {}, [], {}, {}
    transaction_codes = set()
    analysis = dict(profile_id=classification.id, profile_version=classification.version,
                    profile_fingerprint=classifier.fingerprint, import_profile_id=import_profile.id,
                    import_profile_version=import_profile.version, configuration_revision=settings.revision)
    for name,data in raw.items():
        sources = data['modules']
        result = classifier.classify(name, sources[0] if sources else None, data['text'])
        if len({resolve_module(s) or s for s in sources}) > 1:
            result['ambiguous'] = True
            if classification.mode == 'generic': result['module_id'] = 'UNCLASSIFIED'
            warnings.append('Some composite roles have conflicting FUNCTION_KEY values; review their classification/provenance.')
        module = module_definition(result['module_id'], settings.module_overrides)
        singles = []
        for child,single in data['singles'].items():
            child_code = ((legacy_child_module(child,single['text']) or 'UNCLASSIFIED') if classification.mode == 'legacy'
                          else classifier.classify(child)['module_id'])
            child_module = module_definition(child_code,settings.module_overrides)
            singles.append(SingleRole(assignment_kind=next(iter(single['kinds'])) if len(single['kinds'])==1 else 'mixed',child_agr=child,child_agr_text=single['text'],tcodes=list(single['tcodes'].values()),
                                      function_key=child_code,module_name=child_module['name'],
                                      alternate_descriptions=sorted(single['texts']-{single['text']})))
        codes = {tc.tcode for single in singles for tc in single.tcodes}
        relationships = [RoleRelationship(child_agr=c or None,parent_agr=p or None,effective_role=e or None)
                         for c,p,e in sorted(data['relationships'])]
        role = RoleDetail(agr_name=name,text=data['text'],function_key=result['module_id'], module_name=module['name'],
                          tcode_count=len(codes),single_roles=singles,domain_id=result['domain_id'],
                          classification_ambiguous=result['ambiguous'],source_modules=sources,
                          relationships=relationships, analysis=analysis,alternate_descriptions=sorted(data['texts']-{data['text']}))
        roles[name] = role
        summaries.append(RoleSummary(**role.model_dump(exclude={'single_roles','relationships','analysis','single_role_count','alternate_descriptions'}), single_role_count=len(singles)))
        module_infos[module['id']] = ModuleInfo(function_key=module['id'],module_name=module['name'],icon=module['icon'],
                                               color=module['color'],enabled=module['enabled'],category=module['category'])
        for code in codes:
            transaction_codes.add(code)
            index.setdefault(code.upper(),set()).add(name)
    if any(r.alternate_descriptions or any(s.alternate_descriptions for s in r.single_roles) for r in roles.values()):
        warnings.append('Conflicting role descriptions are retained as alternate descriptions.')
    report = parser.report()
    report.update(unique_roles=len(roles), unique_transactions=len(transaction_codes),transaction_assignments=len(assignments),
                  relationship_count=sum(len(r.relationships) for r in roles.values()),analysis=analysis)
    report['warnings'] = list(dict.fromkeys([*report['warnings'],*warnings]))
    report['count_definitions'] = dict(parsed_rows='Logical CSV records before blank/duplicate filtering',
        transaction_assignments='Distinct composite/child/parent/effective-role/T-code tuples',
        unique_transactions='Distinct source transaction spellings; search remains case-insensitive',unique_roles='Distinct AGR_NAME composites')
    return _CacheState(roles=roles,summaries=summaries,modules=sorted(module_infos.values(),key=lambda m:m.function_key),
                       last_loaded=datetime.now(timezone.utc),tcode_index=index,import_report=report,analysis=analysis)


def load_cache(path: str | None = None, before_commit: Callable[[],None] | None = None, configuration=None):
    global _cache
    state = build_cache(path,configuration)
    with _load_lock:
        if before_commit: before_commit()
        _cache = state
        logger.info('Loaded %d composite roles', len(state.roles))


def cancel_publication(event):
    with _load_lock: event.set()


def clear_cache():
    global _cache
    _cache = _CacheState()


def get_snapshot(): return _cache

def get_role_detail(name): return _cache.roles.get(name)

def get_modules(): return _cache.modules
