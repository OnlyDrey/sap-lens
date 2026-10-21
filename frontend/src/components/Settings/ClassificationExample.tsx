import type { ClassificationProfile, ClassificationExample as Example, RegistryEntry } from '@/api/configuration'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'

const reasons: Record<string, string> = {
  csv: 'Recognized SAP area from CSV',
  'legacy-source': 'Source area preserved by Legacy compatibility',
  rule: 'Matched a custom role-name rule',
  override: 'Explicit override for this role',
  fallback: 'Configured fallback domain',
  unmatched: 'No matching rule or recognized CSV area',
  ambiguous: 'Conflicting source areas or equal-priority rules'
}

export function ClassificationExample({ result, profile, modules }: {
  result: Example
  profile: ClassificationProfile
  modules: RegistryEntry[]
}) {
  const area = modules.find((module) => module.id === result.module_id)
  const domain = profile.domains.find((item) => item.id === result.domain_id)
  const normalize = (value: string) => value.trim().toUpperCase().replace(/_/g, '-').replace(/ /g, '')
  const sourceAreas = result.source_modules.map((source) => modules.find((module) =>
    [module.id, ...module.aliases].some((alias) => normalize(alias) === normalize(source)))?.id || source)
  const replacesSource = ['rule', 'override', 'fallback'].includes(result.resolution) &&
    sourceAreas.length > 0 && !sourceAreas.includes(result.module_id)
  return <section aria-label="Individual classification result" className="settings-card space-y-3">
    <h3 className="font-semibold">Individual role result</h3>
    <p className="text-sm text-[var(--text2)]">
      {reasons[result.resolution] || 'Preview result'}. This preview has not changed stored data.
    </p>
    <dl className="settings-status-list">
      <dt>Role</dt><dd><RoleIdentifier value={result.agr_name} /></dd>
      <dt>Preview method</dt><dd>{profile.name}</dd>
      <dt>CSV area evidence</dt><dd>{result.source_modules.join(', ') || 'No CSV area provided'}</dd>
      <dt>SAP area</dt><dd>{area ? `${area.id} — ${area.name}` : result.module_id}</dd>
      <dt>Business domain</dt><dd>{domain?.label || result.domain_id || 'No business domain'}</dd>
      <dt>Matched rules</dt><dd>{result.matched_rules.length ? result.matched_rules.map((id) => {
        const rule = profile.rules.find((item) => item.id === id)
        return rule ? `${rule.kind}: ${rule.pattern} (${id})` : id
      }).join(' · ') : 'None'}</dd>
      <dt>Fallback</dt><dd>{result.is_fallback ? result.resolution === 'fallback' ? 'Yes — configured fallback domain' : 'Yes — Unclassified because no evidence matched' : 'No'}</dd>
      <dt>Stored data</dt><dd>Unchanged — only Apply settings can change the active classification</dd>
    </dl>
    {result.source_conflict && <p role="status" className="text-sm text-[var(--warning)]">
      This composite has conflicting CSV areas. Review the source evidence before applying a different method.
    </p>}
    {replacesSource && <p role="status" className="text-sm text-[var(--warning)]">
      Proposed area {result.module_id} replaces CSV area {result.source_modules.join(', ')}. Stored data is unchanged.
    </p>}
  </section>
}
