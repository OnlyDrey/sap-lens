import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Copy, Trash2 } from 'lucide-react'
import { SidePanel } from '@/components/Shared/SidePanel'
import { Button, IconButton } from '@/components/Shared/Button'
import { Combobox } from '@/components/Shared/Combobox'
import { ConfirmDialog } from '@/components/Shared/ConfirmDialog'
import { ExportCSVButton } from '@/components/Shared/ExportCSVButton'
import { FormField, Input } from '@/components/Shared/Controls'
import { EmptyState, ErrorState, LoadingState, StatusBadge } from '@/components/Shared/Presentation'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import { RoleEntry } from '@/components/Shared/RoleEntry'
import { presentRoleDescription } from '@/lib/rolePresentation'
import { useModuleDefinitions } from '@/components/Modules/ModuleRegistry'
import { useRoleModules } from '@/hooks/useRoleModules'
import { announceExport } from '@/lib/exportNotice'
import { exportPackage, fetchNaming, previewPackage, useAccessPackage, type PackageRow } from '@/lib/accessPackage'

const STATUS: Record<PackageRow['status'], { text: string; tone: 'success' | 'warning' | 'error' }> = {
  ok: { text: 'Ready', tone: 'success' }, needs_suffix: { text: 'Needs suffix', tone: 'warning' }, ambiguous: { text: 'Ambiguous source', tone: 'warning' },
  invalid: { text: 'Invalid', tone: 'error' }, unknown_role: { text: 'Not found in imported data', tone: 'error' }, duplicate: { text: 'Duplicate name', tone: 'error' },
}
const matchText = (row: PackageRow) => {
  const match = row.catalogue
  if (!match) return ''
  return match.status === 'exact' ? 'Exists in the imported catalogue'
    : match.status === 'wildcard' ? `Covered by catalogue pattern ${match.candidates[0]}`
    : match.status === 'ambiguous' ? `Ambiguous catalogue match (${match.candidates.length} candidates)`
    : 'Not found in the imported catalogue'
}
const SUFFIX = /^[A-Z0-9_-]{0,16}$/

/** Proposed access package: generated SAP role names for catalogue roles (suffix applied) and release roles (exact names). Names only; nothing is assigned or changed in SAP. */
export function AccessPackagePanel({ onClose }: { onClose: () => void }) {
  const cart = useAccessPackage(), [busy, setBusy] = useState(false), [confirmClear, setConfirmClear] = useState(false), modules = useRoleModules(), areas = Object.keys(useModuleDefinitions())
  const naming = useQuery({ queryKey: ['role-naming'], queryFn: fetchNaming, staleTime: 60_000 })
  const key = JSON.stringify([cart.defaultSuffix, cart.items])
  const preview = useQuery({ queryKey: ['access-package', key], queryFn: () => previewPackage(cart), enabled: cart.items.length > 0, placeholderData: keepPreviousData })
  const rows = cart.items.length ? preview.data?.items || [] : []
  const names = [...new Set(rows.filter((row) => row.status === 'ok' && row.name).map((row) => row.name as string))].sort((a, b) => a.localeCompare(b, 'en', { sensitivity: 'base' }) || a.localeCompare(b))
  const problems = rows.filter((row) => row.status !== 'ok').length
  const suffixes = naming.data?.suffixes || []
  const copyAll = async () => {
    try { await navigator.clipboard.writeText(names.join('\n')); announceExport({ kind: 'success', message: `Copied ${names.length} generated role names.` }) } catch { announceExport({ kind: 'error', message: 'Copy failed. Export the CSV instead.' }) }
  }
  const download = async () => {
    setBusy(true)
    try { const name = await exportPackage(cart); announceExport(name ? { kind: 'success', message: `Exported ${name}.` } : { kind: 'info', message: 'Export cancelled.' }) }
    catch (error) { announceExport({ kind: 'error', message: error instanceof Error ? error.message : 'Export failed.' }) }
    finally { setBusy(false) }
  }
  const defaultInvalid = !SUFFIX.test(cart.defaultSuffix)
  return (
    <>
      <SidePanel className="package-panel" title="Proposed access package"
        subtitle={<>{cart.items.length} {cart.items.length === 1 ? 'role' : 'roles'} selected. Names only: nothing here assigns roles or changes SAP access.</>}
        headerActions={<Button size="compact" variant="ghost" onClick={() => setConfirmClear(true)} disabled={!cart.items.length}><Trash2 size={14} aria-hidden="true" />Clear package</Button>}
        footer={<div className="package-footer">
          {!!cart.items.length && !!preview.data && (<p role="status" className="package-summary">
              <span>{cart.items.length} {cart.items.length === 1 ? 'role' : 'roles'}</span>
              <span className="package-summary-ok"><CheckCircle2 size={14} aria-hidden="true" />{names.length} valid {names.length === 1 ? 'name' : 'names'}</span>
              {problems > 0 && <span className="package-summary-warn"><AlertTriangle size={14} aria-hidden="true" />{problems} need attention</span>}
            </p>)}
          <Button onClick={() => void copyAll()} disabled={!names.length}><Copy size={16} aria-hidden="true" />Copy all names</Button>
          <ExportCSVButton loading={busy} disabled={!names.length} onClick={() => void download()} title="Exports the valid generated names, sorted, one row per name." />
        </div>}
        onClose={onClose}>
        <section className="package-config" aria-label="Package suffix">
          <FormField label="Package default suffix">
            <Combobox label="Package default suffix" value={cart.defaultSuffix} options={suffixes.map((item) => item.value)} onChange={cart.setDefault} placeholder="Choose or type a suffix" clearLabel="No default suffix" maxLength={16} />
          </FormField>
          {defaultInvalid && <p role="alert" className="package-alert"><AlertTriangle size={14} aria-hidden="true" />Use letters, digits, underscore or hyphen (up to 16 characters).</p>}
          {suffixes.length > 0 && (
            <div className="package-suffix-chips" role="group" aria-label="Suffixes found in the imported role names">
              <span className="text-muted">Found in your roles:</span>
              {suffixes.slice(0, 8).map((item) => <button key={item.value} type="button" className="package-suffix-chip" aria-pressed={cart.defaultSuffix === item.value} onClick={() => cart.setDefault(item.value)}>{item.value}<span>{item.roles}</span></button>)}
            </div>
          )}
          <p className="ui-description">The suffix replaces a wildcard or the existing organizational suffix of each catalogue role. A role-specific suffix overrides the default; changing the default never changes it. Release roles keep their exact assigned names.</p>
        </section>
        {!cart.items.length ? <EmptyState>The access package is empty. Use Add to access package on a role in Role Lookup or Release Roles.</EmptyState>
          : preview.isError ? <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
          : !preview.data ? <LoadingState />
          : <>

            <ul className="package-list" aria-label="Roles in the package">
              {rows.map((row) => {
                const status = STATUS[row.status], release = row.source === 'release'
                return (
                  <li key={row.role} className="package-row">
                    <RoleEntry density="compact" moduleCode={release ? undefined : modules.get(row.role) ?? undefined} title={presentRoleDescription(row.description, areas).description} identifier={row.role} identifierLabel={release ? 'release role' : 'source role'}
                      actions={<IconButton label={`Remove ${row.role} from access package`} onClick={() => cart.remove(row.role)}><Trash2 size={16} /></IconButton>}>
                      <div className="package-row-fields">
                        {release
                          ? <div className="package-generated"><span className="package-generated-label">Source</span><StatusBadge tone="info">Release role</StatusBadge></div>
                          : <FormField label="Role suffix">
                            <Input aria-label={`Suffix for ${row.role}`} value={cart.items.find((item) => item.role === row.role)?.suffix || ''} maxLength={16} placeholder={cart.defaultSuffix || 'Default'} onChange={(event) => cart.setSuffix(row.role, event.target.value)} />
                          </FormField>}
                        <div className="package-generated">
                          <span className="package-generated-label">Generated SAP role name</span>
                          <div className="package-generated-value">
                            {row.name ? <RoleIdentifier value={row.name} label="generated SAP role name" /> : <span className="text-xs text-muted">No name generated</span>}
                            <StatusBadge tone={status.tone}>{status.text}</StatusBadge>
                          </div>
                        </div>
                      </div>
                      {row.messages.map((message) => <p key={message} className="package-message">{message}</p>)}
                      {row.catalogue && <p className="package-message">{matchText(row)}</p>}
                    </RoleEntry>
                  </li>
                )
              })}
            </ul>
          </>}
      </SidePanel>
      {confirmClear && (
        <ConfirmDialog title="Clear the access package?" confirmLabel="Clear package" onCancel={() => setConfirmClear(false)} onConfirm={() => { cart.clear(); setConfirmClear(false) }}>
          <p>This removes all {cart.items.length} {cart.items.length === 1 ? 'role' : 'roles'}, the default suffix and every role-specific suffix from the package. SAP roles and the imported data are not changed.</p>
        </ConfirmDialog>
      )}
    </>
  )
}
