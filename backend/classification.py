"""Bounded, traceable classification. It never changes relationships or transactions."""
from analysis_errors import AnalysisValidationError
import hashlib
import json
import time
from collections import Counter
import regex
from config_models import ClassificationProfile
from module_registry import resolve_module


class Classifier:
    def __init__(self, profile: ClassificationProfile):
        self.profile = profile
        self.domains = {d.id:d for d in profile.domains}
        self.compiled = {}
        for rule in profile.rules:
            if rule.kind == 'regex':
                try:
                    self.compiled[rule.id] = regex.compile(rule.pattern, 0 if rule.case_sensitive else regex.IGNORECASE)
                except regex.error as exc:
                    raise AnalysisValidationError('A classification regular expression is invalid.') from exc
        self.fingerprint = hashlib.sha256(json.dumps(profile.model_dump(),sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()[:16]
        self.deadline = time.monotonic() + 5

    def classify(self, role: str, source_module: str | None = None, description: str | None = None):
        if len(role) > 512: raise AnalysisValidationError('A role identifier exceeds 512 characters.')
        if time.monotonic() > self.deadline: raise AnalysisValidationError('Classification exceeded its five-second budget. Simplify the rules.')
        p = self.profile
        recognized = resolve_module(source_module)
        base = recognized or (source_module if p.mode == 'legacy' and source_module else 'UNCLASSIFIED')
        result = dict(module_id=base, domain_id=None, ambiguous=False, matched_rules=[])
        if p.mode != 'custom': return result
        chosen = p.overrides.get(role)
        matches = []
        if not chosen:
            for rule in p.rules:
                text = role if rule.case_sensitive else role.casefold()
                pattern = rule.pattern if rule.case_sensitive else rule.pattern.casefold()
                try:
                    match = (text.startswith(pattern) if rule.kind == 'prefix' else
                             text == pattern if rule.kind == 'exact' else
                             pattern in text if rule.kind == 'contains' else
                             bool(self.compiled[rule.id].search(role, timeout=0.002)))
                except TimeoutError as exc:
                    raise AnalysisValidationError('A classification expression timed out. Use a simpler rule.') from exc
                if match: matches.append(rule)
            if matches:
                priority = min(rule.priority for rule in matches)
                winners = [rule for rule in matches if rule.priority == priority]
                result['matched_rules'] = [rule.id for rule in winners]
                domains = {rule.domain_id for rule in winners}
                if len(domains) > 1:
                    return {**result, 'module_id':'UNCLASSIFIED', 'ambiguous':True}
                chosen = winners[0].domain_id
            else:
                chosen = p.fallback_domain
        if chosen:
            domain = self.domains[chosen]
            result.update(domain_id=chosen, module_id=resolve_module(domain.module_id) or 'UNCLASSIFIED')
        elif not recognized:
            result['module_id'] = 'UNCLASSIFIED'
        return result

    def conflicts(self):
        groups = {}
        for rule in self.profile.rules:
            key = (rule.kind, rule.pattern if rule.case_sensitive else rule.pattern.casefold(), rule.priority, rule.case_sensitive)
            groups.setdefault(key, []).append(rule)
        return [dict(rule_ids=[r.id for r in rules], reason='Identical match and priority target different domains')
                for rules in groups.values() if len({r.domain_id for r in rules}) > 1]


def classification_preview(profile, records, current=None, test_role=None):
    classifier = Classifier(profile)
    counts = Counter()
    samples = []
    ambiguous = changes = unclassified = 0
    observed = set()
    for record in records:
        result = classifier.classify(record['agr_name'], record.get('source_module'), record.get('text'))
        if result['ambiguous']:
            ambiguous += 1
            observed.add(tuple(sorted(result['matched_rules'])))
        if result['module_id'] == 'UNCLASSIFIED' and not result['domain_id']: unclassified += 1
        counts[result['domain_id'] or result['module_id']] += 1
        old = (current or {}).get(record['agr_name'])
        changed = old is not None and (old.get('module_id'),old.get('domain_id')) != (result['module_id'],result['domain_id'])
        changes += int(changed)
        if len(samples) < 10: samples.append(dict(agr_name=record['agr_name'], **result, changed=changed))
    return dict(total_roles=len(records), counts=dict(counts), unclassified_roles=unclassified,
                ambiguous_matches=ambiguous, conflicting_rules=classifier.conflicts()+[dict(rule_ids=list(ids),reason='Equal-priority rules overlap in the active dataset') for ids in sorted(observed)], samples=samples,
                changed_roles=changes, profile_id=profile.id, profile_version=profile.version,
                profile_fingerprint=classifier.fingerprint,
                test_result=classifier.classify(test_role) if test_role else None)


def legacy_child_module(name, description=None):
    # Compatibility with the prior renderer: a standard area token in a text
    # prefix or the second colon-separated name segment. No private prefixes.
    match = regex.match(r'^([A-Z]{2,3})\s*[-:]', description or '')
    if match and resolve_module(match[1]): return resolve_module(match[1])
    parts = name.split(':',2)
    return resolve_module(parts[1]) if len(parts)>1 else None
