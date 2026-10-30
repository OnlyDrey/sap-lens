import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiRequest } from '@/api/client'
import { Button } from '@/components/Shared/Button'
import { Dialog } from '@/components/Shared/Dialog'
import { SearchInput } from '@/components/Shared/Controls'
import { DataTable, EmptyState, LoadingState, StatusBadge } from '@/components/Shared/Presentation'
import { SodPill } from '@/lib/sodAppearance'

export type Mapping = { activity?: string; tcode: string; ttext?: string }
export type SourceRisk = {
  risk_id: string
  current: boolean
  source: { criticality: string; risk_type: string; source_text: string; activity1: string; activity2: string; activities: Record<'ACTVT1' | 'ACTVT2', Mapping[]>; supported: boolean }
  local: { display_name: string }
}

/** Compact source pills; Criticality and Type are source metadata shown only in Settings. */
export function SourceMeta({ criticality, riskType }: { criticality: string; riskType: string }) {
  return <span className="source-meta-pills"><StatusBadge className="evidence-criticality">Criticality {criticality || '—'}</StatusBadge><StatusBadge className="evidence-type">Type {riskType || '—'}</StatusBadge></span>
}

/** A risk or activity identifier that opens its read-only details. */
export function PillButton({ kind, value, onOpen, label }: { kind: 'risk' | 'activity'; value: string; onOpen: () => void; label: string }) {
  return <button type="button" className="id-pill-button" aria-label={label} onClick={onOpen}><SodPill kind={kind} value={value} /></button>
}

/** Searchable, read-only transaction list for one activity or risk side. */
export function TransactionsDialog({ title, mappings, onClose }: { title: string; mappings: Mapping[]; onClose: () => void }) {
  const [search, setSearch] = useState('')
  const term = search.trim().toLowerCase()
  const shown = term ? mappings.filter(item => item.tcode.toLowerCase().includes(term) || (item.ttext || '').toLowerCase().includes(term)) : mappings
  return (
    <Dialog title={title} onClose={onClose} footer={<Button onClick={onClose}>Close</Button>}>
      <p className="ui-description">Imported transaction mappings. They come from the SoD matrix and cannot be edited.</p>
      <SearchInput aria-label="Search transactions" placeholder="Search transaction or description" value={search} onChange={event => setSearch(event.target.value)} onClear={() => setSearch('')} />
      <p role="status">{shown.length.toLocaleString()} of {mappings.length.toLocaleString()} transactions</p>
      {shown.length
        ? <div className="max-h-[50vh] overflow-auto"><DataTable caption={`${title} mappings`}><thead><tr><th>Transaction</th><th>Description</th></tr></thead><tbody>{shown.map(item => <tr key={item.tcode}><td>{item.tcode}</td><td>{item.ttext || 'Description unavailable'}</td></tr>)}</tbody></DataTable></div>
        : <EmptyState>No transactions match this search.</EmptyState>}
    </Dialog>
  )
}

/** Drill-down for one risk: its two activity sides with transaction counts, each opening the searchable transaction view. */
export function RiskSourceDialog({ risk, onClose }: { risk: SourceRisk; onClose: () => void }) {
  const [side, setSide] = useState<'ACTVT1' | 'ACTVT2' | null>(null)
  const name = (slot: 'ACTVT1' | 'ACTVT2') => (slot === 'ACTVT1' ? risk.source.activity1 : risk.source.activity2)
  return (
    <>
      <Dialog title={`Source details for risk ${risk.risk_id}`} onClose={onClose} footer={<Button onClick={onClose}>Close</Button>}>
        <p>{risk.source.source_text}</p>
        <div className="flex flex-wrap items-center gap-2"><SourceMeta criticality={risk.source.criticality} riskType={risk.source.risk_type} /><StatusBadge tone={risk.current ? 'success' : 'neutral'}>{risk.current ? 'Current source' : 'Historical source'}</StatusBadge>{!risk.source.supported && <StatusBadge tone="warning">Type not evaluated</StatusBadge>}</div>
        <p className="ui-description">Identifiers, relationships and transaction mappings come from the import and cannot be edited.</p>
        <ul className="grid gap-2" aria-label="Risk activities">
          {(['ACTVT1', 'ACTVT2'] as const).map(slot => (
            <li key={slot} className="ui-list-row flex flex-wrap items-center justify-between gap-2 p-3">
              <span className="flex min-w-0 items-center gap-2"><span className="text-xs font-semibold">{slot}</span><SodPill kind="activity" value={name(slot)} /></span>
              <Button size="compact" aria-label={`Show ${risk.source.activities[slot].length} transactions for ${name(slot)}`} onClick={() => setSide(slot)}>{risk.source.activities[slot].length.toLocaleString()} transactions</Button>
            </li>
          ))}
        </ul>
      </Dialog>
      {side && <TransactionsDialog title={`${name(side)} transactions (${side})`} mappings={risk.source.activities[side]} onClose={() => setSide(null)} />}
    </>
  )
}

/** Fetch one risk by identifier (current or historical) for a detail dialog. */
export function useSourceRisk(riskId: string | null) {
  return useQuery({
    queryKey: ['sod-source-risk', riskId],
    enabled: !!riskId,
    queryFn: async () => (await apiRequest<{ items: SourceRisk[] }>(`/api/sod/catalogue?${new URLSearchParams({ search: riskId || '', current: '', limit: '25' })}`)).items.find(item => item.risk_id === riskId) || null,
  })
}

export function RiskByIdDialog({ riskId, onClose }: { riskId: string; onClose: () => void }) {
  const risk = useSourceRisk(riskId)
  if (risk.isLoading) return <Dialog title={`Source details for risk ${riskId}`} onClose={onClose}><LoadingState /></Dialog>
  if (!risk.data) return <Dialog title={`Source details for risk ${riskId}`} onClose={onClose} footer={<Button onClick={onClose}>Close</Button>}><EmptyState>This risk is not available in the retained source definitions.</EmptyState></Dialog>
  return <RiskSourceDialog risk={risk.data} onClose={onClose} />
}
