import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest } from '@/api/client'
import { Button } from '@/components/Shared/Button'
import { formatTimestamp } from '@/lib/dateFormat'

interface Library { revision: number; digest: string; imported_at: string; risks: number; activities: number; terms: number }

/** Private reference guidance, independently versioned; never imports active access rules. */
export function SodReferenceLibrary() {
  const qc = useQueryClient(), input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [message, setMessage] = useState('')
  const query = useQuery({ queryKey: ['sod-reference'], queryFn: () => apiRequest<Library>('/api/sod/reference') })
  const choose = async (file?: File) => {
    if (!file || !query.data || busy) return
    setError(''); setMessage('')
    if (!file.name.toLowerCase().endsWith('.xlsx') || !file.size || file.size > 2 * 1024 * 1024) {
      setError('Choose a non-empty XLSX reference workbook up to 2 MB.'); return
    }
    setBusy(true)
    try {
      const encoded = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result).split(',')[1] || '')
        reader.onerror = () => reject(new Error('The reference workbook could not be read.'))
        reader.readAsDataURL(file)
      })
      const value = await apiRequest<Library>('/api/sod/reference', 'PUT', { expected_revision: query.data.revision, workbook_base64: encoded })
      qc.setQueryData(['sod-reference'], value)
      await qc.invalidateQueries({ predicate: item => String(item.queryKey[0]).startsWith('sod') && item.queryKey[0] !== 'sod-reference' })
      setMessage(`Reference library saved: ${value.risks} risks and ${value.activities} activities. Active matrix and review decisions were not changed.`)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Reference import failed; previous definitions are retained.') }
    finally { setBusy(false); if (input.current) input.current.value = '' }
  }
  return <section aria-label="SoD reference library" className="grid min-w-0 gap-2">
    <h3>Reference definitions</h3>
    <p className="ui-description">Curated business guidance, not verified SAP-standard metadata. Exact IDs enrich only elements in the active matrix. Non-empty local overrides take priority over imported metadata, then reference definitions. Importing replaces the reference library only.</p>
    <input ref={input} type="file" accept=".xlsx" aria-label="SoD reference workbook" className="sr-only" disabled={busy || !query.data} onChange={event => void choose(event.target.files?.[0])} />
    <Button loading={busy} disabled={!query.data} onClick={() => input.current?.click()}>Import reference workbook</Button>
    {query.data && <p className="ui-description">{query.data.risks} risks · {query.data.activities} activities · Revision {query.data.revision} · {formatTimestamp(query.data.imported_at || null)}</p>}
    {(error || query.isError) && <p role="alert">{error || (query.error instanceof Error ? query.error.message : 'Reference library could not be read.')}</p>}
    {message && <p role="status">{message}</p>}
  </section>
}
