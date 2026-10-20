import { useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { Settings, X } from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { applicationToken, fetchSettings, saveSettings } from '@/api/client'

export function SettingsDialog({ onDataChanged }: { onDataChanged: () => void }) {
  const [open, setOpen] = useState(false)
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [nativePicker, setNativePicker] = useState(Boolean(window.pywebview?.api))
  const [picking, setPicking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const qc = useQueryClient()
  const settings = useQuery({ queryKey: ['settings'], queryFn: fetchSettings,
    refetchInterval: query => query.state.data?.loading ? 1000 : false })

  useEffect(() => {
    const ready = () => setNativePicker(true)
    window.addEventListener('pywebviewready', ready)
    return () => window.removeEventListener('pywebviewready', ready)
  }, [])

  const pick = async () => {
    if (!window.pywebview?.api) return
    setPicking(true)
    setError(null)
    try {
      const chosen = await window.pywebview.api.choose_csv(applicationToken())
      if (chosen) setPath(chosen)
    } catch {
      setError('The file picker could not open. Enter the full file path instead.')
    } finally { setPicking(false) }
  }

  useEffect(() => {
    if (settings.data) {
      if (!settings.data.loading) setPath(settings.data.data_csv_path)
      if (settings.data.error || !settings.data.data_csv_path) setOpen(true)
    }
    if (settings.data && !settings.data.loading) {
      void qc.invalidateQueries({ predicate: query => query.queryKey[0] !== 'settings' })
    }
  }, [settings.data, qc])

  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const result = await saveSettings(path.trim())
      // Discard all data from the previous file, including inactive role details.
      await qc.resetQueries({ predicate: query => query.queryKey[0] !== 'settings' })
      qc.setQueryData(['settings'], result)
      onDataChanged()
      setOpen(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the file location.')
    } finally {
      setBusy(false)
    }
  }

  return <Dialog.Root open={open} onOpenChange={value => { if (!busy && !picking) setOpen(value) }}>
    <Dialog.Trigger asChild>
      <button className="text-white text-xs font-semibold px-3 py-2 rounded-lg hover:bg-white/10 flex gap-2 items-center" aria-label="Open settings">
        <Settings className="w-4 h-4" /> Settings
      </button>
    </Dialog.Trigger>
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 bg-black/60 z-50" />
      <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[min(36rem,95vw)] rounded-2xl border p-6 shadow-xl"
        style={{ background: 'var(--surface)', color: 'var(--text)', borderColor: 'var(--border)' }}>
        <Dialog.Title className="text-xl font-bold">SAP Lens settings</Dialog.Title>
        <Dialog.Description className="text-sm mt-2 mb-5" style={{ color: 'var(--muted)' }}>
          Choose the SAP role CSV to load. Your file location is saved for the next launch.
        </Dialog.Description>
        <form onSubmit={event => void save(event)} className="flex flex-col gap-3">
          <label htmlFor="csv-path" className="font-semibold text-sm">CSV file location</label>
          <input id="csv-path" value={path} onChange={e => setPath(e.target.value)} disabled={busy} required maxLength={4096}
            placeholder="C:/data/sap_roles.csv or //server/share/sap_roles.csv"
            className="border rounded-lg px-3 py-2 w-full text-sm" style={{ background: 'var(--surface2)', borderColor: 'var(--border)' }} />
          <button type="button" onClick={() => void pick()} disabled={!nativePicker || busy || picking}
            className="border rounded-lg px-3 py-2 text-sm font-semibold disabled:opacity-50"
            title={nativePicker ? 'Choose a CSV on this computer' : 'Native file picker is available in the Windows desktop app'}>
            {picking ? 'Choosing file…' : 'Browse for CSV…'}
          </button>
          {settings.data?.data_csv_path && <p className="text-xs break-all">Current file: {settings.data.data_csv_path}</p>}
          {settings.data?.loading && <p role="status" className="text-sm">Loading role data… You can close the app safely if a network share is unavailable.</p>}
          <p className="text-xs" style={{ color: 'var(--muted)' }}>Enter the full path on this computer or a readable network share. The file is validated before replacing your current data.</p>
          {(error || settings.isError) && <p role="alert" className="text-red-600 text-sm">{error || 'Could not read settings. Check the local service and try again.'}</p>}
          {!error && settings.data?.error && <p role="status" className="text-amber-600 text-sm">{settings.data.error}</p>}
          <button type="submit" disabled={busy || picking || settings.data?.loading || !path.trim()} className="bg-purple-800 text-white rounded-lg px-4 py-2 font-semibold disabled:opacity-50">
            {busy ? 'Loading…' : 'Save and load CSV'}
          </button>
        </form>
        <Dialog.Close className="absolute right-4 top-4 p-1" aria-label="Close settings" disabled={busy || picking}><X className="w-5 h-5" /></Dialog.Close>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>
}
