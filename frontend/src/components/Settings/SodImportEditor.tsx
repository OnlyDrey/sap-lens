import { useEffect, useState } from 'react'
import { apiRequest } from '@/api/client'
import type { Configuration, ImportProfile } from '@/api/configuration'
import { Button } from '@/components/Shared/Button'
import { DataTable, StatusBadge } from '@/components/Shared/Presentation'
import { SettingsSelect } from './Controls'
import { ImportSection } from './ImportSection'
import { ImportPreview, MappingField } from './ImportControls'
import { SodChecks } from './SodSourceInspection'

interface Inspection {
  valid: boolean; errors: string[]; issues: string[]; file_name: string; headers: string[]; format: { delimiter: string; encoding: string }
  columns: { column: string; detected: string; state: 'manual' | 'detected' | 'missing'; meaning: string; required: boolean }[]
  counts?: { parsed_rows: number; records: number; duplicate_rows: number; risks: number; evaluated_risks: number; unsupported_risks: number; activities: number; transactions: number }
  checks?: { name: string; status: 'passed' | 'warning'; detail: string }[]; warnings?: string[]; samples?: Record<string, string>[]
}
const DELIMITERS: [string, string][] = [['auto', 'Auto detect'], [',', 'Comma'], [';', 'Semicolon'], ['\t', 'Tab'], ['|', 'Pipe']]
const ENCODINGS = ['auto', 'utf-8-sig', 'utf-16', 'cp1252']
const DEFAULT_PROFILE: ImportProfile = { id: 'default', name: 'Standard SoD matrix', version: 1, mapping: {}, delimiter: 'auto', encoding: 'auto' }

/**
 * Format, column mapping and read-only validation of the SoD Matrix CSV, in the same three steps as the other sources. The documented
 * columns are fixed (the parser relies on their meaning); a mapping only chooses the source header that carries each one. Inspection parses the
 * selected file exactly as an import would but stores nothing: active data, risk definitions, decisions and review snapshots are never touched.
 */
export function SodImportEditor({ draft, path, onChange }: { draft: Configuration; path: string; onChange: (profile: ImportProfile) => void }) {
  const profile = draft.sod_import ?? DEFAULT_PROFILE
  const [result, setResult] = useState<Inspection | null>(null), [error, setError] = useState(''), [busy, setBusy] = useState(false), [retry, setRetry] = useState(0)
  const mappingKey = JSON.stringify(profile.mapping)
  useEffect(() => {
    let live = true
    setResult(null); setError('')
    if (!path.trim()) return
    setBusy(true)
    const timer = setTimeout(() => {
      apiRequest<Inspection>('/api/data-sources/sod/inspect', 'POST', { path: path.trim(), delimiter: profile.delimiter, encoding: profile.encoding, mapping: profile.mapping })
        .then((value) => { if (live) setResult(value) })
        .catch((cause) => { if (live) setError(cause instanceof Error ? cause.message : 'The SoD CSV could not be inspected.') })
        .finally(() => { if (live) setBusy(false) })
    }, 400)
    return () => { live = false; clearTimeout(timer) }
  }, [path, profile.delimiter, profile.encoding, mappingKey, retry])
  const edit = (patch: Partial<ImportProfile>) => onChange({ ...profile, ...patch })
  const message = !path.trim() ? 'Choose a SoD Matrix CSV to inspect its columns. Nothing is uploaded.' : busy ? 'Inspecting the SoD CSV…' : result?.valid ? 'Columns detected and validated. Nothing has been imported.' : ''
  return (
    <section aria-label="SoD Matrix CSV configuration" className="import-source-panel space-y-4">
      <ImportSection step={2} title="CSV Import Format" description="The SoD Matrix has one fixed documented schema; only the delimiter and encoding are configurable.">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">Delimiter
            <SettingsSelect value={profile.delimiter} onChange={(event) => edit({ delimiter: event.target.value })}>
              {DELIMITERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </SettingsSelect>
          </label>
          <label className="block text-sm">Encoding
            <SettingsSelect value={profile.encoding} onChange={(event) => edit({ encoding: event.target.value })}>
              {ENCODINGS.map((value) => <option key={value}>{value}</option>)}
            </SettingsSelect>
          </label>
        </div>
        <p className="ui-description" role="status">{result ? `Header row · delimiter ${result.format.delimiter === '\t' ? 'tab' : `"${result.format.delimiter}"`} · encoding ${result.format.encoding}${profile.delimiter === 'auto' || profile.encoding === 'auto' ? ' (detected)' : ''}` : 'Header row required; delimiter and encoding are detected automatically.'}</p>
      </ImportSection>
      <ImportSection step={3} title="Column mapping" description="Documented columns are matched by name automatically. Choose a source column only where the header differs.">
        <p role="status" className="text-sm">{message}</p>
        {error && <p role="alert" className="text-[var(--error)]">{error}</p>}
        {result?.errors.map((item) => <p key={item} role="alert" className="text-[var(--error)]">{item}</p>)}
        <Button disabled={!path.trim() || busy} onClick={() => setRetry((count) => count + 1)}>Detect SoD columns</Button>
        <div className="import-mapping-grid">
          {(result?.columns ?? DEFAULT_COLUMNS.map((column) => ({ column, detected: '', state: 'missing' as const, meaning: '', required: column !== 'TTEXT' }))).map((column) => (
            <MappingField key={column.column} field={column.column} label={column.column} accessibleLabel={`SoD column ${column.column}`} value={profile.mapping[column.column] || ''} columns={result?.headers ?? []} required={column.required} disabled={busy}
              onChange={(value) => { const mapping = { ...profile.mapping }; if (value) mapping[column.column] = value; else delete mapping[column.column]; edit({ mapping }) }} />
          ))}
        </div>
        {result && <DataTable caption="SoD column status" density="compact">
          <thead><tr><th scope="col">Documented column</th><th scope="col">Source column</th><th scope="col">Required</th><th scope="col">Meaning</th></tr></thead>
          <tbody>{result.columns.map((column) => <tr key={column.column}>
            <td><code>{column.column}</code></td>
            <td>{column.detected ? <><code>{column.detected}</code> <StatusBadge tone={column.state === 'manual' ? 'info' : 'success'}>{column.state === 'manual' ? 'Mapped' : 'Detected'}</StatusBadge></> : <StatusBadge tone={column.required ? 'error' : 'warning'}>Missing</StatusBadge>}</td>
            <td className="whitespace-nowrap">{column.required ? 'Required' : 'Optional'}</td><td>{column.meaning}</td>
          </tr>)}</tbody>
        </DataTable>}
      </ImportSection>
      <ImportSection step={4} title="Validation & preview" description="Read-only: the file is parsed as an import would, but active data is never changed.">
        {!result ? <p className="ui-description" role="status">{path.trim() ? (busy ? 'Validating…' : 'No result yet.') : 'Choose a CSV to validate it.'}</p>
          : <>
            {result.valid && result.counts && <ImportPreview fileName={result.file_name} warnings={result.warnings} errors={[]} samples={result.samples}
              metrics={[{ label: 'Parsed rows', value: result.counts.parsed_rows }, { label: 'Unique records', value: result.counts.records }, { label: 'Duplicate rows', value: result.counts.duplicate_rows }, { label: 'Risks', value: result.counts.risks }, { label: 'Evaluated risks', value: result.counts.evaluated_risks }, { label: 'Not evaluated risks', value: result.counts.unsupported_risks }, { label: 'Activities', value: result.counts.activities }, { label: 'Transactions', value: result.counts.transactions }]} />}
            {!result.valid && <ImportPreview fileName={result.file_name} errors={result.errors.length ? result.errors : ['The file did not validate.']} metrics={[]} />}
            {result.valid && result.checks && <section aria-label="SoD validation results" className="space-y-2"><h3 className="text-base font-semibold">Validation results</h3><SodChecks checks={result.checks} /></section>}
          </>}
      </ImportSection>
    </section>
  )
}
const DEFAULT_COLUMNS = ['RISK', 'CRITICITY', 'TYPE', 'TEXT', 'ACTVT1', 'ACTVT2', 'ACTIVITY_SLOT', 'ACTIVITY', 'TCODE', 'TTEXT']
