import { ApplicationFooter } from '@/components/Shared/ApplicationFooter'
import { IconButton } from '@/components/Shared/Button'
import { ExportNotice } from '@/components/Shared/ExportNotice'
import { RefreshBanner } from '@/components/Shared/RefreshReport'
import { useApplicationData } from '@/state/ApplicationData'
import { Notification } from '@/components/Shared/Notification'
import { useHistoryValue } from '@/hooks/useViewHistory'
import { type ReactNode, useState, useRef } from 'react'
import { RefreshCw, Sun, Moon, Settings, Loader2, Database } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { apiRequest, ApiError, recoverTrustedSession } from '@/api/client'
import { useSession } from '@/api/session'
import { SessionNotice } from './SessionNotice'
import { fetchConfiguration } from '@/api/configuration'
import { SettingsView } from '@/components/Settings/SettingsView'

interface Props {
  navigation: ReactNode
  children: ReactNode
  onDataChanged: () => void
  isDark: boolean
  onToggleTheme: () => Promise<void>
}

export function AppLayout({
  children,
  navigation,
  onDataChanged,
  isDark,
  onToggleTheme
}: Props) {
  const dataState=useApplicationData()
  const sessionIssue = ['manual', 'failed', 'reconnecting', 'disconnected'].includes(useSession().phase) // SessionNotice owns every connection or session message
  const configurationQuery = useQuery({
    queryKey: ['configuration'], queryFn: fetchConfiguration, retry:false
  })
  const configuration = configurationQuery.data
  const { data: application } = useQuery({
    queryKey: ['application-version'],
    queryFn: () => apiRequest<{ app: string; version: string; mode: string }>('/api/version'),
    staleTime: Infinity
  })
  const organization = configuration?.settings.organization
  const { data: customLogo } = useQuery({
    queryKey: ['logo', configuration?.settings.logo_id],
    queryFn: () => apiRequest<{ data_url: string }>('/api/branding/logo'),
    enabled: Boolean(configuration?.settings.logo_id),
    retry: false,
    staleTime: Infinity
  })
  const [savedFeedback, setSavedFeedback] = useState(false)
  const [settingsOpen, setSettingsOpen] = useHistoryValue('settings')
  const [dataSourceRequest, setDataSourceRequest] = useState(0)
  const reviewDataSource = () => {
    setDataSourceRequest((request) => request + 1)
    setSettingsOpen(true)
  }
  const [themeBusy, setThemeBusy] = useState(false)
  const busy = dataState.loading
  const [err, setErr] = useState<string | null>(null)

  const refreshLock=useRef(false)
  const handleRefresh = async () => {
    if(refreshLock.current||busy)return
    refreshLock.current=true
    setErr(null)
    try {
      await dataState.refresh()
    } catch (e) {
      setErr(e instanceof ApiError&&e.kind==='session'?null:e instanceof Error ? e.message : 'Refresh failed')
    } finally {refreshLock.current=false}
  }

  return (
    <div className={`${settingsOpen ? 'h-dvh overflow-hidden' : 'min-h-screen'} flex flex-col bg-[var(--bg)] transition-colors duration-300`}>
      {/* â”€â”€ Header â”€â”€ */}
      <header
        className=" sticky top-0 z-30 shrink-0"
        style={{
          backgroundColor: 'var(--primary)',
          color: 'var(--on-primary)'
        }}
        role="banner"
      >
        <div className="app-header-row max-w-screen-2xl mx-auto px-4 min-h-[4.5rem] flex items-center justify-between gap-3">
          {/* Brand: logo image + name */}
          <div className="app-brand flex items-center gap-3 shrink-0">
            {/* Logo image â€” fallback to styled "E" if file not found */}
            <img
              src={
                organization?.name.trim()
                  ? customLogo?.data_url || '/sap-lens.png'
                  : '/sap-lens.png'
              }
              alt={
                organization?.name.trim() && customLogo?.data_url
                  ? `${organization.name} logo`
                  : 'SAP Lens'
              }
              className="h-12 w-auto max-w-40 object-contain flex-shrink-0"
              onError={(e) => {
                if (!e.currentTarget.src.endsWith('/sap-lens.png'))
                  e.currentTarget.src = '/sap-lens.png'
              }}
            />
            <div>
              <p
                className="text-[var(--on-primary)] text-md leading-tight font-semibold truncate max-w-[38vw]"
                title={organization?.name.trim() || 'SAP Lens'}
              >
                {organization?.name.trim() || 'SAP Lens'}
              </p>
              <p
                className="text-[10px] font-semibold tracking-widest uppercase"
                style={{ color: 'var(--on-primary)' }}
              >
                {organization?.platform === 'Other / Custom'
                  ? organization.custom_platform || 'Other / Custom'
                  : organization?.platform || 'SAP S/4HANA'}{' '}
                &middot; {organization?.system_id || 'DEMO'}{' '}
                {organization?.client || '100'}
              </p>
            </div>
          </div>

          <div className="min-w-0">{navigation}</div>

          <div className="app-utilities">
            <IconButton label={isDark?'Switch to light mode':'Switch to dark mode'} variant="ghost" disabled={themeBusy||settingsOpen} loading={themeBusy} onClick={()=>{setErr(null);setThemeBusy(true);void onToggleTheme().catch(e=>setErr(e instanceof Error?e.message:'Could not save the theme.')).finally(()=>setThemeBusy(false))}}>{!themeBusy&&(isDark?<Sun size={17} aria-hidden="true"/>:<Moon size={17} aria-hidden="true"/>)}</IconButton>
            <IconButton label="Open settings" tooltip="Settings" variant="ghost" onClick={()=>setSettingsOpen(true)}><Settings size={17} aria-hidden="true"/></IconButton>
            <IconButton label={busy?'Refreshing data':'Refresh role data from CSV'} tooltip="Refresh data" variant="ghost" disabled={busy||settingsOpen} loading={busy} onClick={()=>void handleRefresh()}>{!busy&&<RefreshCw size={17} aria-hidden="true"/>}</IconButton>
          </div>
        </div>

        {savedFeedback && <Notification variant="success" onDismiss={()=>setSavedFeedback(false)}>Settings saved successfully.</Notification>}
        {err && <Notification variant="error" onDismiss={()=>setErr(null)}>{err}</Notification>}
      </header>

      <SettingsView
        applicationFooter={<ApplicationFooter version={application?.version} mode={application?.mode} note={organization?.footer}/>}
        open={settingsOpen}
        dataSourceRequest={dataSourceRequest}
        onOpen={() => setSettingsOpen(true)}
        onClose={() => {
          setSettingsOpen(false)
          document
            .querySelector<HTMLButtonElement>('[aria-label="Open settings"]')
            ?.focus()
        }}
        onSaved={() => setSavedFeedback(true)}
        onDataChanged={onDataChanged}
      />
      {configuration?.error && !configuration.loading && !settingsOpen && (
        <div className="w-full max-w-screen-2xl mx-auto px-4 sm:px-6 mt-4">
        <div
          role="alert"
          className="p-4 rounded-lg border border-[var(--warning)] text-[var(--text)] flex flex-wrap items-center gap-3"
        >
          <span className="text-sm mr-auto">{configuration.error}</span>
          <button
            type="button"
            onClick={reviewDataSource}
            className="settings-secondary-button data-source-action"
          >
            <Database size={16} aria-hidden="true" className="shrink-0"/>
            Review data source
          </button>
        </div>
        </div>
      )}
      {!settingsOpen && <SessionNotice onRetry={() => void configurationQuery.refetch()} retrying={configurationQuery.isFetching} />}
      {configurationQuery.isError && !settingsOpen && !sessionIssue && <div role="alert" className="service-notice">
        <strong>{configurationQuery.error instanceof ApiError&&configurationQuery.error.kind==='session'?'Local session changed.':configurationQuery.error instanceof ApiError&&['authentication','permission'].includes(configurationQuery.error.kind)?'Access needs attention.':'Local service unavailable.'}</strong><span>{configurationQuery.error instanceof Error?configurationQuery.error.message:'The current view is retained. Retry the connection.'}</span>
        {configurationQuery.error instanceof ApiError&&configurationQuery.error.kind==='session'&&<button className="settings-secondary-button" onClick={recoverTrustedSession}>Reload trusted session</button>}
        <button className="settings-secondary-button" onClick={() => void configurationQuery.refetch()} disabled={configurationQuery.isFetching}>Retry connection</button>
      </div>}
      {dataState.loading && !configurationQuery.isError && !settingsOpen && <div role="status" className="service-notice">
        <Loader2 size={20} className="animate-spin shrink-0" aria-hidden="true"/>
        <div><h2 className="font-semibold">Loading CSV data…</h2><p className="text-sm text-[var(--muted)]">Previous data remains visible while replacements are validated. Review or cancel a slow read in Settings.</p></div>
        <button className="settings-secondary-button" onClick={reviewDataSource}>Review data source</button>
      </div>}
      <main
        className={
          settingsOpen
            ? 'hidden'
            : 'flex-1 max-w-screen-2xl mx-auto w-full px-4 sm:px-6 py-5'
        }
        id="main-content" tabIndex={-1}
      >
        {dataState.report&&<RefreshBanner report={dataState.report} onDismiss={dataState.dismissReport}/>}
        {children}
      </main>

      <ExportNotice />
      {!configuration?.loading && !configuration?.error && (
        <p role="status" className="sr-only">
          Ready
        </p>
      )}
      {!settingsOpen&&<ApplicationFooter version={application?.version} mode={application?.mode} note={organization?.footer}/>}

    </div>
  )
}
