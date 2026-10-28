import { useEffect, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Clock } from 'lucide-react'
import { apiRequest } from '@/api/client'
import { DEFAULT_SCHEDULE, type Configuration, type RefreshSchedule, type SchedulePreview, type ScheduleStatus } from '@/api/configuration'
import { ButtonGroup } from '@/components/Shared/Button'
import { Combobox } from '@/components/Shared/Combobox'
import { FormField, Input, Toggle } from '@/components/Shared/Controls'
import { StatusBadge } from '@/components/Shared/Presentation'
import { formatTimestamp } from '@/lib/dateFormat'

const zones = (): string[] => {
  try { return ['local', 'UTC', ...(Intl as unknown as { supportedValuesOf: (key: string) => string[] }).supportedValuesOf('timeZone').filter((zone) => zone !== 'UTC')] } catch { return ['local', 'UTC'] }
}
const zoneLabel = (zone: string) => (zone === 'local' ? 'Local time' : zone)
const STATUS = { succeeded: 'success', partial: 'warning', failed: 'error', skipped: 'neutral' } as const
const STATUS_TEXT = { succeeded: 'Succeeded', partial: 'Partly failed', failed: 'Failed', skipped: 'Skipped' }

/** Scheduled background refresh. The backend runs it, so no browser tab has to stay open; Apply saves the schedule with the other settings. */
export function ScheduledRefresh({ draft, onChange }: { draft: Configuration; onChange: (value: Configuration) => void }) {
  const value: RefreshSchedule = { ...DEFAULT_SCHEDULE, ...draft.refresh_schedule }
  const patch = (update: Partial<RefreshSchedule>) => onChange({ ...draft, refresh_schedule: { ...value, ...update } })
  const [debounced, setDebounced] = useState(value)
  useEffect(() => { const timer = setTimeout(() => setDebounced(value), 300); return () => clearTimeout(timer) }, [value.mode, value.time, value.cron, value.timezone])
  const status = useQuery({ queryKey: ['refresh-schedule'], queryFn: () => apiRequest<ScheduleStatus>('/api/refresh-schedule'), refetchInterval: 30_000 })
  const preview = useQuery({
    queryKey: ['refresh-schedule-preview', debounced.mode, debounced.time, debounced.cron, debounced.timezone],
    queryFn: () => apiRequest<SchedulePreview>('/api/refresh-schedule/preview', 'POST', { mode: debounced.mode, time: debounced.time, cron: debounced.cron, timezone: debounced.timezone, enabled: true }),
    placeholderData: keepPreviousData,
  })
  const state = status.data?.state, runtime = status.data?.runtime
  const saved = status.data?.schedule
  const pending = saved && JSON.stringify(saved) !== JSON.stringify(value)
  return (
    <section className="settings-card space-y-3" aria-label="Scheduled refresh">
      <h2 className="settings-subheading flex items-center gap-2"><Clock size={18} aria-hidden="true" />Scheduled refresh</h2>
      <p className="ui-description">
        Refreshes the configured dynamic sources in the background, with the same checks as Refresh. Static sources are not re-read, and a failed refresh keeps the previously validated data.
      </p>
      <Toggle label="Enable scheduled refresh" checked={value.enabled} onChange={(enabled) => patch({ enabled })} />
      <ButtonGroup label="Schedule type" value={value.mode} onChange={(mode) => patch({ mode: mode === 'cron' ? 'cron' : 'daily' })} options={[{ value: 'daily', label: 'Daily' }, { value: 'cron', label: 'Advanced (cron)' }]} />
      {value.mode === 'daily'
        ? <FormField label="Daily time"><Input type="time" step={60} value={value.time} onChange={(event) => patch({ time: event.target.value })} /></FormField>
        : <FormField label="Cron expression"><Input value={value.cron} maxLength={100} spellCheck={false} placeholder="0 6 * * 1-5" onChange={(event) => patch({ cron: event.target.value })} /></FormField>}
      {value.mode === 'cron' && <p className="ui-description">Five fields: minute hour day-of-month month day-of-week. Lists (1,15), ranges (1-5), steps (*/15) and names (MON, JAN) are supported. Runs must be at least 5 minutes apart.</p>}
      <FormField label="Time zone">
        <Combobox label="Time zone" value={value.timezone} options={zones()} optionLabel={zoneLabel} onChange={(timezone) => patch({ timezone: timezone || 'local' })} clearLabel="Local time" placeholder="Local time" maxLength={64} />
      </FormField>
      {preview.data && (preview.data.valid
        ? <div role="status" className="grid gap-1">
            <p><strong>{preview.data.description}</strong></p>
            <p className="ui-description">Next runs: {preview.data.next_runs.slice(0, 3).map((run) => formatTimestamp(run)).join(' · ')}</p>
          </div>
        : <p role="alert" className="text-[var(--error)]">{preview.data.error}</p>)}
      {pending && <p className="ui-description" role="status">Apply settings to save this schedule.</p>}
      <dl className="grid gap-1 sm:grid-cols-2" aria-label="Scheduled refresh status">
        <div><dt className="text-xs text-muted">Next run</dt><dd>{saved?.enabled && status.data?.next_run ? formatTimestamp(status.data.next_run) : saved?.enabled ? 'Not scheduled' : 'Disabled'}</dd></div>
        <div><dt className="text-xs text-muted">Last attempted run</dt><dd>{formatTimestamp(state?.last_attempt, 'Never')}</dd></div>
        <div><dt className="text-xs text-muted">Last successful run</dt><dd>{formatTimestamp(state?.last_success, 'Never')}</dd></div>
        <div><dt className="text-xs text-muted">Last failure</dt><dd>{formatTimestamp(state?.last_failure, 'None')}{state?.consecutive_failures ? ` · ${state.consecutive_failures} in a row` : ''}</dd></div>
      </dl>
      {state?.last_status && <p><StatusBadge tone={STATUS[state.last_status]}>{STATUS_TEXT[state.last_status]}</StatusBadge> {state.last_message}</p>}
      {status.data?.error && <p role="alert" className="text-[var(--error)]">The saved schedule is not usable: {status.data.error}</p>}
      <details>
        <summary>Where it runs</summary>
        <ul className="ui-description">
          <li><strong>Windows Desktop:</strong> only while SAP Lens is running, in its window or in the system tray. A run missed while it was closed is skipped, not replayed.</li>
          <li><strong>Windows Service, Linux Docker, Linux native or systemd:</strong> runs continuously while the service or container is up, with no desktop session or browser open.</li>
          <li>Time zones other than Local time and UTC need the operating system's time zone database; if it is missing the setting is rejected.</li>
        </ul>
      </details>
      {runtime?.requires_running_application && value.enabled && <p className="ui-description">This installation is the desktop application: keep SAP Lens running (the tray option below keeps it running when the window is closed).</p>}
    </section>
  )
}
