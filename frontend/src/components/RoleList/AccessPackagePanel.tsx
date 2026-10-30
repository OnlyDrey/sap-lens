import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Copy, HelpCircle, Trash2, XCircle } from 'lucide-react'
import { SidePanel } from '@/components/Shared/SidePanel'
import { Button, IconButton } from '@/components/Shared/Button'
import { Combobox } from '@/components/Shared/Combobox'
import { ConfirmDialog } from '@/components/Shared/ConfirmDialog'
import { ExportCSVButton } from '@/components/Shared/ExportCSVButton'
import { FormField, Input } from '@/components/Shared/Controls'
import { EmptyState, ErrorState, LoadingState } from '@/components/Shared/Presentation'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import { RoleEntry } from '@/components/Shared/RoleEntry'
import { presentRoleDescription } from '@/lib/rolePresentation'
import { useModuleDefinitions } from '@/components/Modules/ModuleRegistry'
import { useRoleModules } from '@/hooks/useRoleModules'
import { announceExport } from '@/lib/exportNotice'
import { exportPackage, fetchNaming, previewPackage, useAccessPackage, type PackageRow } from '@/lib/accessPackage'

const VALIDATION: Record<PackageRow['validation'], { text: string; tone: 'success' | 'warning' | 'error'; icon: typeof CheckCircle2; hint: string }> = {
  confirmed: { text: 'Confirmed', tone: 'success', icon: CheckCircle2, hint: 'A valid SAP role name found in the imported catalogue.' },
  unconfirmed: { text: 'Unconfirmed', tone: 'warning', icon: HelpCircle, hint: 'A valid SAP role name that the imported catalogue does not contain. It can be copied and exported; check it in SAP first.' },
  invalid: { text: 'Invalid', tone: 'error', icon: XCircle, hint: 'Not a valid SAP role name or not resolvable. It is never copied or exported.' },
  needs_suffix: { text: 'Needs suffix', tone: 'warning', icon: AlertTriangle, hint: 'Set a package default suffix or a role suffix.' },
}
const matchText = (row: PackageRow) => {
  const match = row.catalogue
  if (!match) return ''
  return match.status === 'wildcard' ? `Covered by catalogue pattern ${match.candidates[0]}`
    : match.status === 'ambiguous' ? `Ambiguous catalogue match (${match.candidates.length} candidates)`
    : ''
}
const SUFFIX = /^[A-Z0-9_-]{0,16}$/

/** Proposed access package: generated SAP role names for catalogue roles (suffix applied) and release roles (exact names). Names only; nothing is assigned or changed in SAP. */
export function AccessPackagePanel({ onClose }: { onClose: () => void }) {
  const cart = useAccessPackage(), [busy, setBusy] = useState(false), [confirmClear, setConfirmClear] = useState(false), modules = useRoleModules(), areas = Object.keys(useModuleDefinitions())
  const naming = useQuery({ queryKey: ['role-naming'], queryFn: fetchNaming, staleTime: 60_000 })
  const key = JSON.stringify([cart.defaultSuffix, cart.items])
  const preview = useQuery({ queryKey: ['access-package', key], queryFn: () => previewPackage(cart), enabled: cart.items.length > 0, placeholderData: keepPreviousData })
  const rows = cart.items.length ? preview.data?.items || [] : []
  const names = [...new Set(rows.filter((row) => row.exportable && row.name).map((row) => row.name as string))].sort((a, b) => a.localeCompare(b, 'en', { sensitivity: 'base' }) || a.localeCompare(b))
  const unconfirmed = new Set(rows.filter((row) => row.validation === 'unconfirmed' && row.name).map((row) => row.name)).size
  const problems = rows.filter((row) => !row.exportable).length
  const warning = unconfirmed ? ` ${unconfirmed} ${unconfirmed === 1 ? 'name is' : 'names are'} not confirmed by the imported catalogue.` : ''
  const suffixes = naming.data?.suffixes || []
  const copyAll = async () => {
    try { await navigator.clipboard.writeText(names.join('\n')); announceExport({ kind: unconfirmed ? 'info' : 'success', message: `Copied ${names.length} generated role names.${warning}` }) } catch { announceExport({ kind: 'error', message: 'Copy failed. Export the CSV instead.' }) }
  }
  const download = async () => {
    setBusy(true)
    try { const name = await exportPackage(cart); announceExport(name ? { kind: unconfirmed ? 'info' : 'success', message: `Exported ${name}.${warning}` } : { kind: 'info', message: 'Export cancelled.' }) }
    catch (error) { announceExport({ kind: 'error', message: error instanceof Error ? error.message : 'Export failed.' }) }
    finally { setBusy(false) }
  }
  const defaultInvalid = !SUFFIX.test(cart.defaultSuffix)
  return (
    <>
      <SidePanel className="package-panel" title="Proposed access package"
        subtitle={<>{cart.items.length} {cart.items.length === 1 ? 'role' : 'roles'} selected. Names only: nothing is assigned or changed in SAP.</>}
        footer={<div className="package-footer">
          {!!cart.items.length && !!preview.data && (<p role="status" className="package-summary">
              <span>{cart.items.length} {cart.items.length === 1 ? 'role' : 'roles'}</span>
              <span className="package-summary-ok"><CheckCircle2 size={14} aria-hidden="true" />{names.length} valid {names.length === 1 ? 'name' : 'names'}</span>
              {unconfirmed > 0 && <span className="package-summary-warn"><HelpCircle size={14} aria-hidden="true" />{unconfirmed} unconfirmed</span>}
              {problems > 0 && <span className="package-summary-error"><XCircle size={14} aria-hidden="true" />{problems} need attention</span>}
            </p>)}
          <Button variant="secondary" className="package-clear" onClick={() => setConfirmClear(true)} disabled={!cart.items.length}><Trash2 size={16} aria-hidden="true" />Clear package</Button>
          <Button onClick={() => void copyAll()} disabled={!names.length}><Copy size={16} aria-hidden="true" />Copy all names</Button>
          <ExportCSVButton loading={busy} disabled={!names.length} onClick={() => void download()} title="Exports the valid generated names (confirmed and unconfirmed), sorted, one row per name." />
        </div>}
        onClose={onClose}>
        <section className="package-config" aria-label="Package suffix">
          <FormField label="Package default suffix">
            <Combobox label="Package default suffix" value={cart.defaultSuffix} options={suffixes.map((item) => item.value)} onChange={cart.setDefault} placeholder="Choose or type a suffix" clearLabel="No default suffix" maxLength={16} />
          </FormField>
          {defaultInvalid && <p role="alert" className="package-alert"><AlertTriangle size={14} aria-hidden="true" />Use letters, digits, underscore or hyphen (up to 16 characters).</p>}
          <p className="ui-description">The suffix replaces a wildcard or the organizational suffix of each catalogue role. A role suffix overrides the default. Roles without suffix variants and release roles keep their exact names.</p>
        </section>
        {!cart.items.length ? <EmptyState>The access package is empty. Use Add to access package on a role in Role Lookup or Release Roles.</EmptyState>
          : preview.isError ? <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
          : !preview.data ? <LoadingState />
          : <>

            <ul className="package-list" aria-label="Roles in the package">
              {rows.map((row) => {
                const status = VALIDATION[row.validation], release = row.source === 'release', StatusIcon = status.icon, noteId = `package-note-${row.role}`
                const messages = [...(row.validation === 'needs_suffix' ? [] : row.messages), ...(matchText(row) ? [matchText(row)] : [])]
                return (
                  <li key={row.role} className="package-row" data-validation={row.validation}>
                    <RoleEntry density="compact" moduleCode={release ? undefined : modules.get(row.role) ?? undefined} title={presentRoleDescription(row.description, areas).description} identifier={row.name ?? row.role} identifierLabel={row.name ? 'generated SAP role name' : release ? 'release role' : 'source role'}
                      actions={<IconButton label={`Remove ${row.role} from access package`} onClick={() => cart.remove(row.role)}><Trash2 size={16} /></IconButton>}
                      identifierSlot={<div className="package-row-line">
                        {row.name ? <RoleIdentifier value={row.name} label="generated SAP role name" /> : <RoleIdentifier value={row.role} label={release ? 'release role' : 'source role'} />}
                        {!release && <Input className="package-suffix-input" aria-label={`Suffix for ${row.role}`} aria-describedby={row.suffix_eligible ? undefined : noteId} value={row.suffix_eligible ? cart.items.find((item) => item.role === row.role)?.suffix || '' : ''} disabled={!row.suffix_eligible}
                          maxLength={16} placeholder={row.suffix_eligible ? cart.defaultSuffix || 'Suffix' : 'Exact'} title={row.suffix_note ?? undefined} onChange={(event) => cart.setSuffix(row.role, event.target.value)} />}
                        <span className="package-status" data-tone={status.tone} title={status.hint}><StatusIcon size={14} aria-hidden="true" />{status.text}</span>
                      </div>}>
                      {!row.suffix_eligible && !release && row.suffix_note && row.source === 'catalogue' && row.name && <p id={noteId} className="package-message">{row.suffix_note}</p>}
                      {messages.map((message) => <p key={message} className="package-message">{message}</p>)}
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
