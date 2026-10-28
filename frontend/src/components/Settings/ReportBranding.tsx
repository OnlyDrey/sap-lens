import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ImagePlus, Trash2 } from 'lucide-react'
import { apiRequest } from '@/api/client'
import { Button } from '@/components/Shared/Button'
import { formatTimestamp } from '@/lib/dateFormat'

interface Branding {
  logo: null | { logo_id: string; data_url: string; width: number; height: number; bytes: number; filename: string; updated: string | null }
  limits: { formats: string[]; max_bytes: number; min_pixels: number; max_pixels: number }
}
const TYPES = ['image/png', 'image/jpeg']
const kilobytes = (bytes: number) => `${Math.max(1, Math.round(bytes / 1000)).toLocaleString()} KB`

/** Logo used only on generated SoD reports (PDF and DOCX). Saved immediately, independent of Apply settings. */
export function ReportBranding() {
  const qc = useQueryClient(),
    input = useRef<HTMLInputElement>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [message, setMessage] = useState('')
  const query = useQuery({ queryKey: ['report-branding'], queryFn: () => apiRequest<Branding>('/api/sod/reports/branding') })
  const data = query.data
  const refresh = (value: Branding) => qc.setQueryData(['report-branding'], value)
  const choose = async (file: File | undefined) => {
    if (!file || !data) return
    setError('')
    setMessage('')
    if (!TYPES.includes(file.type)) return setError('Choose a PNG or JPEG image. SVG and WebP are not accepted.')
    if (file.size > data.limits.max_bytes) return setError(`The image is ${kilobytes(file.size)}. The limit is ${kilobytes(data.limits.max_bytes)}.`)
    setBusy(true)
    try {
      const encoded = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result).split(',')[1] || '')
        reader.onerror = () => reject(new Error('The image could not be read.'))
        reader.readAsDataURL(file)
      })
      refresh(await apiRequest<Branding>('/api/sod/reports/branding', 'PUT', { image_base64: encoded, filename: file.name }))
      setMessage('Report logo saved. New PDF and DOCX reports use it.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The report logo could not be saved.')
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }
  const remove = async () => {
    setBusy(true)
    setError('')
    setMessage('')
    try {
      refresh(await apiRequest<Branding>('/api/sod/reports/branding', 'DELETE'))
      setMessage('Report logo removed. Reports use the application logo when one is set.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The report logo could not be removed.')
    } finally {
      setBusy(false)
    }
  }
  const logo = data?.logo
  return (
    <section className="settings-card grid max-w-3xl gap-3" aria-label="Report branding">
      <h2 className="settings-subheading">Report branding</h2>
      <p className="ui-description">An optional logo for generated SoD reports (PDF and DOCX). It is stored locally with your settings, is not part of review evidence, and never leaves this computer. Without it, reports use the application logo when one is set.</p>
      {logo ? (
        <div className="grid gap-2 sm:grid-cols-[10rem_1fr] sm:items-center">
          <div className="flex min-h-24 items-center justify-center rounded-card border border-line bg-elevated p-3"><img src={logo.data_url} alt="Report logo preview" className="max-h-20 max-w-full object-contain" /></div>
          <p className="text-sm">{logo.filename || 'Report logo'} · {logo.width} × {logo.height} px · {kilobytes(logo.bytes)}{logo.updated ? ` · saved ${formatTimestamp(logo.updated)}` : ''}</p>
        </div>
      ) : <p className="text-sm">{query.isError ? 'Report branding could not be loaded.' : 'No report logo selected.'}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <input ref={input} type="file" accept="image/png,image/jpeg" className="sr-only" aria-label="Report logo file" onChange={(event) => void choose(event.target.files?.[0])} />
        <Button loading={busy} disabled={!data} onClick={() => input.current?.click()}><ImagePlus size={16} aria-hidden="true" />{logo ? 'Replace logo' : 'Upload logo'}</Button>
        {logo && <Button variant="ghost" disabled={busy} onClick={() => void remove()}><Trash2 size={16} aria-hidden="true" />Remove logo</Button>}
      </div>
      {data && <p className="text-xs text-muted">PNG or JPEG, up to {kilobytes(data.limits.max_bytes)}, {data.limits.min_pixels}–{data.limits.max_pixels} pixels per side. Images are decoded, resized to at most 1024 px and stripped of metadata.</p>}
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
    </section>
  )
}
