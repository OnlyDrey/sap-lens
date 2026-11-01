import { DataTable, StatusBadge } from '@/components/Shared/Presentation'

export interface MetadataIndicator {
  id: string; label: string; column: string; total: number; imported: number; local_fallback: number; available: number; missing: number
  percent: number; column_present: boolean; differing: number; state: 'complete' | 'values_missing' | 'column_absent' | 'empty'
}
export interface MetadataCoverage {
  indicators: MetadataIndicator[]
  optional_columns: { detected: string[]; missing: string[] }
  source_facts: { field: string; detected: boolean; values: string[] }[]
  sample: { id: string; kind: string; name?: string; description?: string; origin: Record<string, 'imported' | 'local'> }[]
  note: string
}

const STATE = {
  complete: { tone: 'success', label: 'Complete' },
  values_missing: { tone: 'warning', label: 'Values missing' },
  column_absent: { tone: 'neutral', label: 'Column not in CSV' },
  empty: { tone: 'neutral', label: 'No entities' },
} as const
const ORIGIN = { imported: 'Imported', local: 'Local' } as const

/**
 * Descriptive-metadata completeness of the SoD dataset over distinct risks, activities and transaction codes (not CSV rows). It separates a column the
 * CSV does not carry (normal, never an error) from a column whose values are missing, and imported values from local business text used as a fallback.
 */
export function SodMetadataCoverage({ data }: { data?: MetadataCoverage | null }) {
  if (!data) return <p className="ui-description" role="status">Metadata coverage is unavailable until the local annotations can be read.</p>
  return (
    <section aria-label="Metadata coverage" className="space-y-2">
      <h3 className="text-base font-semibold">Metadata coverage</h3>
      <p className="ui-description">{data.note} Optional columns are never required: a missing column is not an import error.</p>
      <DataTable caption="SoD metadata coverage" density="compact">
        <thead><tr><th scope="col">Metadata</th><th scope="col">Available / total</th><th scope="col">Coverage</th><th scope="col">Missing</th><th scope="col">Source</th><th scope="col">Status</th></tr></thead>
        <tbody>{data.indicators.map((item) => <tr key={item.id}>
          <td>{item.label}<small className="block text-muted"><code>{item.column}</code></small></td>
          <td className="whitespace-nowrap">{item.available.toLocaleString()} / {item.total.toLocaleString()}</td>
          <td className="whitespace-nowrap">{item.percent.toFixed(1)}%</td>
          <td className="whitespace-nowrap">{item.missing.toLocaleString()}</td>
          <td>{item.imported.toLocaleString()} imported{item.local_fallback > 0 && <> · {item.local_fallback.toLocaleString()} local fallback</>}{item.differing > 0 && <small className="block text-muted">{item.differing.toLocaleString()} differ from local text (both kept)</small>}</td>
          <td><StatusBadge tone={STATE[item.state].tone}>{STATE[item.state].label}</StatusBadge></td>
        </tr>)}</tbody>
      </DataTable>
      <dl className="preview-metrics" aria-label="Optional columns">
        <div><dt>Optional columns detected</dt><dd>{data.optional_columns.detected.length ? data.optional_columns.detected.join(', ') : 'None'}</dd></div>
        <div><dt>Optional columns not in the CSV</dt><dd>{data.optional_columns.missing.length ? data.optional_columns.missing.join(', ') : 'None'}</dd></div>
        {data.source_facts.filter((fact) => fact.detected).map((fact) => <div key={fact.field}><dt>{fact.field}</dt><dd>{fact.values.length ? fact.values.join(', ') : 'Column present, no values'}</dd></div>)}
      </dl>
      {data.sample.length > 0 && <DataTable caption="Resolved metadata sample" density="compact">
        <thead><tr><th scope="col">Risk</th><th scope="col">Name</th><th scope="col">Description</th><th scope="col">Origin</th></tr></thead>
        <tbody>{data.sample.map((row) => <tr key={row.id}><td><code>{row.id}</code></td><td>{row.name || '—'}</td><td>{row.description || '—'}</td>
          <td>{[...new Set(Object.values(row.origin))].map((origin) => ORIGIN[origin]).join(' and ') || '—'}</td></tr>)}</tbody>
      </DataTable>}
    </section>
  )
}
