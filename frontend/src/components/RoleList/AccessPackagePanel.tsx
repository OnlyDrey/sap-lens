import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Copy, Trash2 } from 'lucide-react'
import { SidePanel } from '@/components/Shared/SidePanel'
import { Button, IconButton } from '@/components/Shared/Button'
import { Combobox } from '@/components/Shared/Combobox'
import { ExportCSVButton } from '@/components/Shared/ExportCSVButton'
import { FormField, Input } from '@/components/Shared/Controls'
import { EmptyState, ErrorState, LoadingState, StatusBadge } from '@/components/Shared/Presentation'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import { announceExport } from '@/lib/exportNotice'
import { exportPackage, fetchNaming, previewPackage, useAccessPackage, type PackageRow } from '@/lib/accessPackage'

const STATUS: Record<PackageRow['status'], { text: string; tone: 'success' | 'warning' | 'error' }> = {
  ok: { text: 'Ready', tone: 'success' }, needs_suffix: { text: 'Needs suffix', tone: 'warning' }, ambiguous: { text: 'Ambiguous source', tone: 'warning' },
  invalid: { text: 'Invalid', tone: 'error' }, unknown_role: { text: 'Not in catalogue', tone: 'error' }, duplicate: { text: 'Duplicate name', tone: 'error' },
}
const matchText = (row: PackageRow) => {
  const match = row.catalogue
  if (!match) return ''
  return match.status === 'exact' ? 'Exists in the imported catalogue'
    : match.status === 'wildcard' ? `Covered by catalogue pattern ${match.candidates[0]}`
    : match.status === 'ambiguous' ? `Ambiguous catalogue match (${match.candidates.length} candidates)`
    : 'Not found in the imported catalogue'
}

/** Proposed access package: generated SAP role names for the collected catalogue roles. Names only; nothing is assigned or changed in SAP. */
export function AccessPackagePanel({ onClose }: { onClose: () => void }) {
  const cart = useAccessPackage(), [busy, setBusy] = useState(false)
  const naming = useQuery({ queryKey: ['role-naming'], queryFn: fetchNaming, staleTime: 60_000 })
  const key = JSON.stringify([cart.defaultSuffix, cart.items])
  const preview = useQuery({ queryKey: ['access-package', key], queryFn: () => previewPackage(cart), enabled: cart.items.length > 0, placeholderData: keepPreviousData })
  const rows = cart.items.length ? preview.data?.items || [] : []
  const names = [...new Set(rows.filter((row) => row.status === 'ok' && row.name).map((row) => row.name as string))].sort((a, b) => a.localeCompare(b, 'en', { sensitivity: 'base' }) || a.localeCompare(b))
  const problems = rows.filter((row) => row.status !== 'ok').length
  const copyAll = async () => {
    try { await navigator.clipboard.writeText(names.join('\n')); announceExport({ kind: 'success', message: `Copied ${names.length} generated role names.` }) } catch { announceExport({ kind: 'error', message: 'Copy failed. Export the CSV instead.' }) }
  }
  const download = async () => {
    setBusy(true)
    try { const name = await exportPackage(cart); announceExport(name ? { kind: 'success', message: `Exported ${name}.` } : { kind: 'info', message: 'Export cancelled.' }) }
    catch (error) { announceExport({ kind: 'error', message: error instanceof Error ? error.message : 'Export failed.' }) }
    finally { setBusy(false) }
  }
  return (
    <SidePanel title="Proposed access package" subtitle={<>Names only. Nothing here assigns roles or changes SAP access.</>} onClose={onClose}
      footer={<>
        <Button onClick={() => void copyAll()} disabled={!names.length}><Copy size={16} aria-hidden="true" />Copy all names</Button>
        <ExportCSVButton loading={busy} disabled={!names.length} onClick={() => void download()} title="Exports the valid generated names, sorted, one row per name." />
        <Button variant="ghost" onClick={cart.clear} disabled={!cart.items.length}><Trash2 size={16} aria-hidden="true" />Clear package</Button>
      </>}>
      <section className="grid gap-3" aria-label="Package suffix">
        <FormField label="Package default suffix">
          <Combobox label="Package default suffix" value={cart.defaultSuffix} options={(naming.data?.suffixes || []).map((item) => item.value)} onChange={cart.setDefault} placeholder="Choose or type a suffix" clearLabel="No default suffix" maxLength={16} />
        </FormField>
        <p className="ui-description">
          {naming.data?.suffixes.length ? `Suffixes found in the imported role names: ${naming.data.suffixes.map((item) => `${item.value} (${item.roles})`).join(', ')}. ` : 'No organizational suffix was found in the imported role names. '}
          The suffix replaces a wildcard or the existing organizational suffix of each role. A role-specific suffix overrides the default; changing the default never changes it.
        </p>
      </section>
      {!cart.items.length ? <EmptyState>The access package is empty. Use Add to access package on a role in Role Lookup.</EmptyState>
        : preview.isError ? <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
        : !preview.data ? <LoadingState />
        : <>
          <p role="status">{cart.items.length} {cart.items.length === 1 ? 'role' : 'roles'} · {names.length} valid {names.length === 1 ? 'name' : 'names'}{problems ? ` · ${problems} need attention` : ''}</p>
          <ul className="grid gap-0" aria-label="Roles in the package">
            {rows.map((row) => {
              const status = STATUS[row.status]
              return (
                <li key={row.role} className="ui-list-row grid min-w-0 gap-2 p-3">
                  <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                    <RoleIdentifier value={row.role} label="source role" />
                    <IconButton label={`Remove ${row.role} from access package`} onClick={() => cart.remove(row.role)}><Trash2 size={16} /></IconButton>
                  </div>
                  {row.description && <p className="ui-description">{row.description}</p>}
                  <FormField label={`Suffix for ${row.role}`}>
                    <Input value={cart.items.find((item) => item.role === row.role)?.suffix || ''} maxLength={16} placeholder={cart.defaultSuffix || 'Role suffix'} onChange={(event) => cart.setSuffix(row.role, event.target.value)} />
                  </FormField>
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <StatusBadge tone={status.tone}>{status.text}</StatusBadge>
                    {row.name ? <RoleIdentifier value={row.name} label="generated SAP role name" /> : <span className="text-xs text-muted">No name generated</span>}
                  </div>
                  {row.messages.map((message) => <p key={message} className="ui-description">{message}</p>)}
                  {row.catalogue && <p className="ui-description">{matchText(row)}</p>}
                </li>
              )
            })}
          </ul>
        </>}
    </SidePanel>
  )
}
