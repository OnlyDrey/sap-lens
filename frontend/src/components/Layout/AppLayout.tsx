import {LocalReviewerProfile} from '@/components/Auth/LocalReviewerProfile'
import {useAuthentication,MyProfile} from '@/components/Auth/Authentication'
import { ApplicationFooter } from '@/components/Shared/ApplicationFooter'
import { Button, IconButton, Tooltip } from '@/components/Shared/Button'
import { Popover } from '@/components/Shared/Popover'
import { Dialog } from '@/components/Shared/Dialog'
import { NavigationPresentation } from '@/components/Shared/Navigation'
import { ExportNotice } from '@/components/Shared/ExportNotice'
import { RefreshBanner } from '@/components/Shared/RefreshReport'
import { useApplicationData } from '@/state/ApplicationData'
import { Notification } from '@/components/Shared/Notification'
import { useHistoryValue } from '@/hooks/useViewHistory'
import { type ReactNode, lazy, Suspense, useEffect, useState, useRef } from 'react'
import { RefreshCw, Sun, Moon, Settings, Loader2, Database, Menu, UserRound } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { apiRequest, ApiError } from '@/api/client'
import { useSession } from '@/api/session'
import { SessionNotice } from './SessionNotice'
import { fetchConfiguration } from '@/api/configuration'
const SettingsView = lazy(() => import('@/components/Settings/SettingsView').then((module) => ({ default: module.SettingsView })))

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
  const auth=useAuthentication(),[profileOpen,setProfileOpen]=useState(false)
  const [navigationOpen,setNavigationOpen]=useState(false)
  useEffect(()=>{
    const desktop=window.matchMedia('(min-width: 1024px)')
    const close=()=>setNavigationOpen(false)
    const resize=()=>{if(desktop.matches)close()}
    window.addEventListener('hashchange',close);desktop.addEventListener('change',resize)
    return()=>{window.removeEventListener('hashchange',close);desktop.removeEventListener('change',resize)}
  },[])
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
  // Settings is large but must exist early (it opens itself on first launch and listens for the native bridge). It loads as its own chunk right after the first render instead of inside the entry bundle, and then stays mounted so drafts survive.
  const [settingsMounted, setSettingsMounted] = useState(false)
  useEffect(() => { setSettingsMounted(true) }, [])
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
    <div className={`${settingsOpen ? 'h-dvh overflow-hidden' : 'min-h-screen'} flex min-w-0 flex-col bg-[var(--bg)] transition-colors duration-300`}>
      {/* â”€â”€ Header â”€â”€ */}
      <header
        className=" sticky top-0 z-30 shrink-0"
        style={{
          backgroundColor: 'var(--primary)',
          color: 'var(--on-primary)'
        }}
        role="banner"
      >
        <div className="app-header-row max-w-screen-2xl mx-auto px-3 sm:px-4 min-h-[3.5rem] lg:min-h-[4.5rem] flex items-center justify-between gap-2 lg:gap-3">
          <div className="app-navigation-trigger lg:hidden"><IconButton label="Open navigation" variant="ghost" aria-haspopup="dialog" aria-expanded={navigationOpen} onClick={()=>setNavigationOpen(true)}><Menu size={22} aria-hidden="true"/></IconButton></div>
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
                  : 'AuthLens'
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
                title={organization?.name.trim() || 'AuthLens'}
              >
                {organization?.name.trim() || 'AuthLens'}
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

          <div className="hidden min-w-0 lg:block">{navigation}</div>

          <div className="app-utilities">
            <div className="hidden lg:block"><IconButton label={isDark?'Switch to light mode':'Switch to dark mode'} variant="ghost" disabled={!auth.canAdmin||themeBusy||settingsOpen} loading={themeBusy} onClick={()=>{setErr(null);setThemeBusy(true);void onToggleTheme().catch(e=>setErr(e instanceof Error?e.message:'Could not save the theme.')).finally(()=>setThemeBusy(false))}}>{!themeBusy&&(isDark?<Sun size={17} aria-hidden="true"/>:<Moon size={17} aria-hidden="true"/>)}</IconButton></div>
            <Tooltip label={auth.session?'My Profile':'Reviewer profile'}><Popover label={auth.session?'My Profile':'Reviewer profile'} triggerLabel={auth.session?'My Profile':'Reviewer profile'} trigger={<UserRound size={20} aria-hidden="true"/>} triggerSize="icon" triggerVariant="ghost" preferredWidth={240} className="ui-popover-menu">
              {close=><div className="grid gap-2"><Button onClick={()=>{close();setProfileOpen(true)}}>{auth.session?'Profile & sessions':'Edit reviewer profile'}</Button>{auth.session&&<Button onClick={()=>{close();void auth.logout().catch(e=>setErr(e instanceof Error?e.message:'Could not sign out.'))}}>Sign out</Button>}</div>}
            </Popover></Tooltip>
            <div className="hidden lg:block"><IconButton disabled={!auth.canAdmin} label="Open settings" tooltip="Settings" variant="ghost" onClick={()=>setSettingsOpen(true)}><Settings size={17} aria-hidden="true"/></IconButton></div>
            <div className="hidden lg:block"><IconButton label={busy?'Refreshing data':'Refresh role data from CSV'} tooltip="Refresh data" variant="ghost" disabled={!auth.canAdmin||busy||settingsOpen} loading={busy} onClick={()=>void handleRefresh()}>{!busy&&<RefreshCw size={17} aria-hidden="true"/>}</IconButton></div>
          </div>
        </div>

        {savedFeedback && <Notification variant="success" onDismiss={()=>setSavedFeedback(false)}>Settings saved successfully.</Notification>}
        {err && <Notification variant="error" onDismiss={()=>setErr(null)}>{err}</Notification>}
      </header>

      {navigationOpen&&<Dialog title="Navigation" presentation="drawer" footer={null} onClose={()=>setNavigationOpen(false)}>
        <div className="mobile-navigation" onClick={event=>{const target=event.target as HTMLElement;if(target.closest('a[href]'))setNavigationOpen(false)}}>
          <NavigationPresentation.Provider value="drawer">{navigation}</NavigationPresentation.Provider>
        </div>
        <div className="grid gap-2 border-t border-line pt-4">
          <Button disabled={!auth.canAdmin} onClick={()=>{setNavigationOpen(false);setSettingsOpen(true)}}><Settings size={18} aria-hidden="true"/>Settings</Button>
          <Button disabled={!auth.canAdmin||themeBusy||settingsOpen} onClick={()=>{setNavigationOpen(false);setErr(null);setThemeBusy(true);void onToggleTheme().catch(e=>setErr(e instanceof Error?e.message:'Could not save the theme.')).finally(()=>setThemeBusy(false))}}>{isDark?<Sun size={18} aria-hidden="true"/>:<Moon size={18} aria-hidden="true"/>}{isDark?'Switch to light mode':'Switch to dark mode'}</Button>
          <Button disabled={!auth.canAdmin||busy||settingsOpen} onClick={()=>{setNavigationOpen(false);void handleRefresh()}}><RefreshCw size={18} aria-hidden="true"/>Refresh role data from CSV</Button>
        </div>
      </Dialog>}

      {profileOpen&&(auth.session?<MyProfile onClose={()=>setProfileOpen(false)}/>:<LocalReviewerProfile onClose={()=>setProfileOpen(false)}/>)}
      {auth.canAdmin&&(settingsOpen || settingsMounted) && <Suspense fallback={null}>
      <SettingsView
        applicationFooter={<ApplicationFooter version={application?.version} mode={application?.mode} note={organization?.footer}/>}
        open={settingsOpen}
        dataSourceRequest={dataSourceRequest}
        onOpen={() => setSettingsOpen(true)}
        onClose={() => {
          setSettingsOpen(false)
          const target=[...document.querySelectorAll<HTMLButtonElement>('[aria-label="Open settings"],[aria-label="Open navigation"]')].find(button=>button.getClientRects().length>0&&!button.disabled)
          target?.focus()
        }}
        onSaved={() => setSavedFeedback(true)}
        onDataChanged={onDataChanged}
      />
      </Suspense>}
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
            : 'flex-1 min-w-0 max-w-screen-2xl mx-auto w-full px-4 sm:px-6 py-5'
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
