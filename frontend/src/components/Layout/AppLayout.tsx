import { type ReactNode, useState } from 'react'
import { RefreshCw, Sun, Moon, Settings, Loader2 } from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { refreshData, apiRequest } from '@/api/client'
import { fetchConfiguration } from '@/api/configuration'
import { SettingsView } from '@/components/Settings/SettingsView'
import { cn } from '@/lib/utils'

interface Props {
  navigation: ReactNode
  children: ReactNode
  lastLoaded: string | null
  onRefresh: () => void
  onDataChanged: () => void
  isDark: boolean
  onToggleTheme: () => Promise<void>
}

export function AppLayout({
  children,
  navigation,
  lastLoaded,
  onRefresh,
  onDataChanged,
  isDark,
  onToggleTheme
}: Props) {
  const qc = useQueryClient()
  const { data: configuration } = useQuery({
    queryKey: ['configuration'],
    queryFn: fetchConfiguration
  })
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
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [dataSourceRequest, setDataSourceRequest] = useState(0)
  const reviewDataSource = () => {
    setDataSourceRequest((request) => request + 1)
    setSettingsOpen(true)
  }
  const [themeBusy, setThemeBusy] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const handleRefresh = async () => {
    setBusy(true)
    setErr(null)
    try {
      await refreshData()
      await qc.invalidateQueries()
      onRefresh()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Refresh failed')
    } finally {
      setBusy(false)
    }
  }

  const fmt = lastLoaded
    ? new Date(lastLoaded).toLocaleString('en-GB', {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit'
      })
    : null

  return (
    <div className={`${settingsOpen ? 'h-dvh overflow-hidden' : 'min-h-screen'} flex flex-col bg-[var(--bg)] transition-colors duration-300`}>
      {/* â”€â”€ Header â”€â”€ */}
      <header
        className="shadow-lg sticky top-0 z-30 shrink-0"
        style={{
          backgroundColor: 'var(--primary)',
          color: 'var(--on-primary)'
        }}
        role="banner"
      >
        <div className="max-w-screen-2xl mx-auto px-4 min-h-20 flex items-center justify-between gap-3">
          {/* Brand: logo image + name */}
          <div className="flex items-center gap-3 shrink-0">
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

          <fieldset disabled={settingsOpen} className="min-w-0">{navigation}</fieldset>

          {/* Right controls */}
          <div className="flex items-center gap-3 shrink-0">
            {fmt && (
              <span
                className="text-[11px] hidden lg:block font-medium"
                style={{ color: 'var(--on-primary)' }}
              >
                Updated {fmt}
              </span>
            )}

            {/* Theme toggle â€” WCAG: descriptive aria-label */}
            <button
              disabled={themeBusy || settingsOpen}
              onClick={() => {
                setErr(null)
                setThemeBusy(true)
                void onToggleTheme()
                  .catch((e) =>
                    setErr(
                      e instanceof Error
                        ? e.message
                        : 'Could not save the theme.'
                    )
                  )
                  .finally(() => setThemeBusy(false))
              }}
              aria-label={
                isDark ? 'Switch to light mode' : 'Switch to dark mode'
              }
              className="flex items-center gap-1.5 text-[var(--on-primary)] text-xs font-semibold px-2.5 py-1.5 rounded-lg hover:bg-white/10 transition-all focus:outline-none focus:ring-2 focus:ring-[var(--on-primary)] focus:ring-offset-1 focus:ring-offset-[var(--primary)]"
            >
              {isDark ? (
                <Sun className="w-4 h-4" aria-hidden="true" />
              ) : (
                <Moon className="w-4 h-4" aria-hidden="true" />
              )}
              <span className="hidden sm:inline">
                {isDark ? 'Light' : 'Dark'}
              </span>
            </button>

            <button
              onClick={() => setSettingsOpen(true)}
              className="text-[var(--on-primary)] text-xs font-semibold px-3 py-2 rounded-lg hover:bg-white/10 flex gap-2 items-center focus-visible:ring-2 focus-visible:ring-[var(--on-primary)]"
              aria-label="Open settings"
            >
              <Settings size={16} aria-hidden="true" /> Settings
            </button>

            {/* Refresh */}
            <button
              onClick={handleRefresh}
              disabled={busy || settingsOpen}
              aria-label={
                busy ? 'Refreshing data' : 'Refresh role data from CSV'
              }
              className={cn(
                'flex items-center gap-2 text-[var(--on-primary)] text-xs font-bold px-3 py-1.5 rounded-lg border border-[var(--on-primary)] transition-all',
                'hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-[var(--on-primary)] focus:ring-offset-1 focus:ring-offset-[var(--primary)]',
                busy && 'opacity-50 cursor-not-allowed'
              )}
            >
              <RefreshCw
                className={cn('w-3.5 h-3.5', busy && 'animate-spin')}
                aria-hidden="true"
              />
              <span className="hidden sm:inline">
                {busy ? 'Refreshing...' : 'Refresh Data'}
              </span>
            </button>
          </div>
        </div>

        {configuration?.loading && (
          <div
            role="status"
            className="bg-[var(--info-bg)] text-[var(--info)] text-sm px-5 py-2"
          >
            Loading role data…
          </div>
        )}
        {savedFeedback && (
          <div
            role="status"
            className="bg-[var(--surface)] text-[var(--success)] px-5 py-2 text-xs flex justify-between"
          >
            Settings saved successfully.
            <button
              onClick={() => setSavedFeedback(false)}
              className="underline"
            >
              Dismiss
            </button>
          </div>
        )}
        {err && (
          <div
            role="alert"
            className="bg-[var(--error-bg)] text-[var(--error)] text-xs px-5 py-2 flex justify-between"
          >
            <span>{err}</span>
            <button onClick={() => setErr(null)} className="underline ml-4">
              Dismiss
            </button>
          </div>
        )}
      </header>

      <SettingsView
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
            onClick={reviewDataSource}
            className="text-sm underline"
          >
            Review data source
          </button>
        </div>
        </div>
      )}
      {configuration?.loading && !settingsOpen && (
        <div role="status" className="flex-1 grid place-items-center p-8">
          <div className="text-center max-w-md">
            <img
              src="/sap-lens.png"
              alt="SAP Lens"
              className="w-20 h-20 mx-auto object-contain"
            />
            <Loader2 className="animate-spin text-[var(--accent2)] mx-auto mt-6" />
            <h1 className="text-xl font-semibold mt-4">Loading role data…</h1>
            <p className="text-sm text-[var(--muted)] mt-2">
              Your configuration is loaded. You can review the source or cancel
              a slow read in Settings.
            </p>
            <button
              className="mt-5 rounded-lg px-4 py-2 bg-[var(--accent)] text-[var(--on-accent)]"
              onClick={reviewDataSource}
            >
              Review data source
            </button>
          </div>
        </div>
      )}
      <main
        className={
          settingsOpen || configuration?.loading
            ? 'hidden'
            : 'flex-1 max-w-screen-2xl mx-auto w-full px-4 sm:px-6 py-5'
        }
        id="main-content"
      >
        {children}
      </main>

      {!configuration?.loading && !configuration?.error && (
        <p role="status" className="sr-only">
          Ready
        </p>
      )}
      <footer
        className={settingsOpen ? 'hidden' : 'h-20'}
        style={{
          backgroundColor: 'var(--primary)',
          color: 'var(--on-primary)'
        }}
      >
        <p className="text-[11px] py-2.5 text-center font-medium">
          <span>{organization?.footer ||
            `© ${new Date().getFullYear()} ${organization?.name.trim() || 'SAP Lens'} — SAP Lens`}</span>
          {application && <span className="block mt-1" aria-label="Application version">
            SAP Lens v{application.version}{application.mode === 'build' || application.mode === 'local' ? ' · Development build' : ''}
          </span>}
        </p>
      </footer>
    </div>
  )
}
