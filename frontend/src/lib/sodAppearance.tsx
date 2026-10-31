import { useQuery } from '@tanstack/react-query'
import { apiRequest } from '@/api/client'
import { IdPill } from '@/components/Shared/IdPill'
import { Popover } from '@/components/Shared/Popover'

interface Appearance { risks: Record<string, { name: string; color: string }>; activities: Record<string, { name: string; color: string }> }
const none: Appearance = { risks: {}, activities: {} }

/** A resolved description of a risk or activity: the imported value when the SoD CSV supplies one, otherwise the local business text, with the origin of each. */
export interface SodDescription {
  name?: string; description?: string; impact?: string; business_process?: string; type?: string
  criticality?: string; risks?: number
  origin: Record<string, 'imported' | 'local'>
  alternate?: Record<string, { value: string; origin: 'imported' | 'local' }>
}
interface Described { risks: Record<string, SodDescription>; activities: Record<string, SodDescription> }
const empty: Described = { risks: {}, activities: {} }

/** Local display names and colors for risk and activity identifiers; failures fall back to plain pills. */
export function useSodAppearance(): Appearance {
  return useQuery({ queryKey: ['sod-appearance'], queryFn: () => apiRequest<Appearance>('/api/sod/appearance'), staleTime: 60_000, retry: false }).data || none
}

/** Resolved descriptions shared by pills, popovers and Settings; failures leave the pills without a description. */
export function useSodMetadata(): Described {
  return useQuery({ queryKey: ['sod-metadata'], queryFn: () => apiRequest<Described>('/api/sod/metadata'), staleTime: 60_000, retry: false }).data || empty
}

const ORIGIN = { imported: 'Imported from the SoD CSV', local: 'Local business text' } as const
const MISSING = 'No description available'
const concise = (value: string, length = 150) => (value.length > length ? `${value.slice(0, length - 1).trimEnd()}…` : value)

/** The one-line text of the hover tooltip: identifier, name and the start of the description, or a neutral note. */
export function pillSummary(kind: 'risk' | 'activity', value: string, entry?: SodDescription, fallbackName = '') {
  const name = entry?.name || fallbackName, description = entry?.description
  const parts = [name, description && concise(description)].filter(Boolean)
  return `${kind === 'risk' ? 'Risk' : 'Activity'} ${value}${parts.length ? ` — ${parts.join(': ')}` : ` — ${MISSING}`}`
}

function Detail({ entry, field, label, required = false }: { entry: SodDescription; field: 'name' | 'description' | 'impact' | 'business_process' | 'type'; label: string; required?: boolean }) {
  const text = entry[field], origin = entry.origin[field], other = entry.alternate?.[field]
  if (!text && !other) return required ? <div><dt>{label}</dt><dd className="ui-description">{MISSING}</dd></div> : null  // a missing description is stated, never invented
  return (
    <div>
      <dt>{label}</dt>
      <dd>{text}{origin && <small className="sod-pill-origin"> {ORIGIN[origin]}</small>}
        {other && <span className="sod-pill-alternate">{ORIGIN[other.origin]}, differs: {other.value}</span>}</dd>
    </div>
  )
}

function Details({ kind, value, entry }: { kind: 'risk' | 'activity'; value: string; entry?: SodDescription }) {
  const shown: SodDescription = entry ?? { origin: {} }
  // Only descriptive fields count; the factual context of the imported definition (criticality, risk type) is not a description.
  const known = !!entry && (!!entry.name || !!entry.description || !!entry.business_process || (kind === 'risk' ? !!entry.impact : !!entry.type))
  return (
    <div className="sod-pill-details">
      <dl className="ui-metadata-list">
        <div><dt>{kind === 'risk' ? 'Risk' : 'Activity'}</dt><dd><code>{value}</code></dd></div>
        <>
          <Detail entry={shown} field="name" label="Display name" />
          <Detail entry={shown} field="description" label="Description" required />
          {kind === 'risk' && <Detail entry={shown} field="impact" label="Impact" />}
          <Detail entry={shown} field="business_process" label="Business process" />
          {kind === 'activity' && <Detail entry={shown} field="type" label="Type" />}
          {kind === 'risk' && shown.criticality && <div><dt>Source criticality</dt><dd>{shown.criticality}</dd></div>}
          {kind === 'activity' && typeof shown.risks === 'number' && <div><dt>Used in risks</dt><dd>{shown.risks.toLocaleString()}</dd></div>}
        </>
      </dl>
      {!known && <p className="ui-description">Add business text in Settings → SoD Risk Configuration, or import a SoD CSV that carries descriptions.</p>}
    </div>
  )
}

/** The resolved description of one risk or activity with the origin of every value (used in Settings so the editor shows what the rest of SAP Lens displays). */
export function SodDescriptionDetails({ kind, value }: { kind: 'risk' | 'activity'; value: string }) {
  const metadata = useSodMetadata()
  return <Details kind={kind} value={value} entry={(kind === 'risk' ? metadata.risks : metadata.activities)[value]} />
}

/**
 * A risk or activity pill. Hovering shows the identifier with its name and description; a free-standing pill is also a button that opens a
 * detail popover (keyboard: Enter or Space, Escape closes). Where the pill already sits inside a control with its own action, pass `details={false}`:
 * it keeps the tooltip and adds no second interactive element.
 */
export function SodPill({ kind, value, details = true }: { kind: 'risk' | 'activity'; value: string; details?: boolean }) {
  const appearance = useSodAppearance(), metadata = useSodMetadata(),
    entry = (kind === 'risk' ? appearance.risks : appearance.activities)[value],
    described = (kind === 'risk' ? metadata.risks : metadata.activities)[value],
    summary = pillSummary(kind, value, described, entry?.name),
    pill = <IdPill kind={kind} value={value} color={entry?.color} title={details ? undefined : summary} />
  if (!details) return pill
  return (
    <span className="sod-pill" title={summary}>
      <Popover label={`${kind === 'risk' ? 'Risk' : 'Activity'} ${value} details`} preferredWidth={360} triggerSize="compact" triggerVariant="ghost" triggerClassName="id-pill-trigger"
        trigger={<span aria-label={summary}>{pill}</span>}>
        <Details kind={kind} value={value} entry={described} />
      </Popover>
    </span>
  )
}
