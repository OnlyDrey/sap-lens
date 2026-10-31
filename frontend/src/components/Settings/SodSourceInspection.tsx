import { useQuery } from '@tanstack/react-query'
import { Dialog } from '@/components/Shared/Dialog'
import { Button } from '@/components/Shared/Button'
import { DataTable, StatusBadge } from '@/components/Shared/Presentation'
import { apiRequest } from '@/api/client'
import { formatTimestamp } from '@/lib/dateFormat'
import { ImportPreview } from './ImportControls'

interface Check { name: string; status: 'passed' | 'warning'; detail: string }
interface Inspection {
  loaded: boolean; file_name?: string
  columns?: { column: string; detected: string; meaning: string; required: boolean }[]
  counts?: { parsed_rows: number; records: number; duplicate_rows: number; risks: number; evaluated_risks: number; unsupported_risks: number; activities: number; transactions: number }
  criticality?: Record<string, number>; types?: Record<string, number>; checks?: Check[]; warnings?: string[]; samples?: Record<string, string>[]
  metadata: { path: string; mode: string; feature_enabled: boolean; imported_at: string | null; checked_at: string | null; snapshot: string | null }
}

/**
 * Read-only inspection of the SoD Matrix source, matching what the other CSV sources show before and after an import: record counts, column
 * interpretation, validation checks, quality warnings, a data preview and import metadata. The matrix has a fixed schema with its own risk and
 * activity semantics, so the columns are explained, never remapped.
 */
export function SodSourceInspection({ onClose, children }: { onClose: () => void; children?: React.ReactNode }) {
  const result = useQuery({
    queryKey: ['sod-source-inspection'],
    queryFn: () => apiRequest<Inspection>('/api/data-sources/sod/inspection'),
    retry: false, staleTime: 0, gcTime: 0,
  })
  const data = result.data, counts = data?.counts, meta = data?.metadata
  return (
    <Dialog title="SoD Matrix source inspection" onClose={onClose} footer={<Button onClick={onClose}>Close</Button>}>
      <p className="ui-description">The active validated snapshot; the original CSV is not read again. This view is read-only: it never changes active data, risk definitions, decisions or review snapshots.</p>
      {result.isError ? <p role="alert">{result.error instanceof Error ? result.error.message : 'The SoD source could not be inspected.'}</p>
        : !data ? <p role="status">Reading the SoD source…</p>
        : !data.loaded ? <p role="status">No SoD Matrix is loaded. Select a CSV to import one.</p>
        : <>
          <ImportPreview fileName={data.file_name || (meta?.path.split(/[\\/]/).pop() ?? 'SoD Matrix')} warnings={data.warnings} errors={[]} samples={data.samples}
            metrics={[['Parsed rows', counts!.parsed_rows], ['Unique records', counts!.records], ['Duplicate rows', counts!.duplicate_rows], ['Risks', counts!.risks], ['Evaluated risks', counts!.evaluated_risks], ['Not evaluated risks', counts!.unsupported_risks], ['Activities', counts!.activities], ['Transactions', counts!.transactions]].map(([label, value]) => ({ label: label as string, value: value as number }))}>
            <section aria-label="Validation results" className="space-y-2">
              <h3 className="text-base font-semibold">Validation results</h3>
              <ul className="sod-inspection-checks">{data.checks!.map((check) => <li key={check.name}><StatusBadge tone={check.status === 'passed' ? 'success' : 'warning'}>{check.status === 'passed' ? 'Passed' : 'Warning'}</StatusBadge><strong>{check.name}</strong><span>{check.detail}</span></li>)}</ul>
            </section>
            <section aria-label="Column interpretation" className="space-y-2">
              <h3 className="text-base font-semibold">Column interpretation</h3>
              <p className="ui-description">The SoD Matrix uses a fixed documented schema. Columns are interpreted as below and cannot be remapped, because the parser relies on these meanings.</p>
              <DataTable caption="SoD Matrix columns" density="compact"><thead><tr><th scope="col">Documented column</th><th scope="col">Found in file</th><th scope="col">Required</th><th scope="col">Meaning</th></tr></thead>
                <tbody>{data.columns!.map((column) => <tr key={column.column}><td><code>{column.column}</code></td><td>{column.detected ? <code>{column.detected}</code> : <StatusBadge tone="error">Missing</StatusBadge>}</td><td>{column.required ? 'Yes' : 'No'}</td><td>{column.meaning}</td></tr>)}</tbody></DataTable>
            </section>
            <section aria-label="Risk labels" className="space-y-1">
              <h3 className="text-base font-semibold">Source labels</h3>
              <p className="ui-description">Criticality {Object.entries(data.criticality!).map(([label, count]) => `${label}: ${count}`).join(', ') || '—'} · Type {Object.entries(data.types!).map(([label, count]) => `${label}: ${count}`).join(', ') || '—'} (risks per label, shown literally).</p>
            </section>
            <section aria-label="Import metadata" className="space-y-1">
              <h3 className="text-base font-semibold">Import metadata</h3>
              <dl className="preview-metrics">
                <div><dt>Source file</dt><dd>{meta!.path || '—'}</dd></div>
                <div><dt>Mode</dt><dd>{meta!.mode === 'dynamic' ? 'Dynamic' : 'Static'}</dd></div>
                <><div><dt>Imported</dt><dd>{formatTimestamp(meta!.imported_at)}</dd></div><div><dt>Last checked</dt><dd>{formatTimestamp(meta!.checked_at)}</dd></div><div><dt>Snapshot</dt><dd>{meta!.snapshot ? meta!.snapshot.slice(0, 12) : '—'}</dd></div><div><dt>Feature</dt><dd>{meta!.feature_enabled ? 'Enabled' : 'Disabled (data retained)'}</dd></div></>
              </dl>
            </section>
          </ImportPreview>
          {children}
        </>}
    </Dialog>
  )
}
