import {useApplicationData} from '@/state/ApplicationData'
import {DesktopOptions} from './DesktopOptions'
import {ScheduledRefresh} from './ScheduledRefresh'
import { FormField, controlClass } from '@/components/Shared/Controls'
import { ContentTabList } from '@/components/Shared/Navigation'
import { DataHealth } from './DataHealth'
import { About } from './About'
import { useHistoryValue, useViewHistory } from '@/hooks/useViewHistory'
import { DirectoryDiagnostics, DirectorySnapshotRecovery, EmployeeBrowser, FeatureSettings } from './EmployeeDirectory'
import {SodRiskSettings} from './SodRiskSettings'
import {SourceManager} from './SourceManager'
import {rebaseSourceDraft,type CSVSource,type SourceActivation} from '@/api/sources'
import { MappingField, ImportPreview } from './ImportControls'
import { RefreshHistory } from '@/components/Shared/RefreshReport'
import { ImportSection } from './ImportSection'
import { SettingsSelect } from './Controls'
import { isHex } from '@/lib/theme'
import { useEffect, useRef, useState, lazy, Suspense } from 'react'
import {
  ArrowLeft,
  Save,
  RotateCcw,
  Image,
  Building2,
  Database,
  LibraryBig,
  UsersRound,
  Layers,
  Palette,
  Activity,
  CheckCircle,
  X,
  BookUser,
  ShieldCheck,
  Info,
  Clock
} from 'lucide-react'
import { ModuleEditor } from './ModuleEditor'
import { UserSourceEditor, PresetActions } from './ImportPresets'
import { ThemeEditor } from './ThemeEditor'
import { paletteErrors, defaultThemeColors } from '@/lib/theme'
import { Diagnostics } from './Diagnostics'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, applicationToken } from '@/api/client'
import {
  fetchConfiguration,
  fetchRegistry,
  saveConfiguration,
  detectHeaders,
  previewImport,
  type Configuration,
  type ConfigurationResponse,
  type ImportReport,
  type ImportProfile
} from '@/api/configuration'

import { ReportBranding } from './ReportBranding'
import { DISCARD_PROMPT, setSettingsDirty } from '@/lib/settingsGuard'
const ComponentLibrary=lazy(()=>import('./ComponentLibrary').then(module=>({default:module.ComponentLibrary})))
const sectionIcons = [Building2, Database, Layers, Palette, Activity, BookUser, Info, Layers, ShieldCheck, Clock]
const sections = [
  'Organization & SAP System',
  'Data Sources',
  'SAP Modules',
  'Appearance & Branding',
  'Health & Diagnostics',
  'Features',
  'About SAP Lens',
  'Component Library',
  'SoD Risk Configuration',
  'Runtime & Scheduling'
]
const navigationOrder=[0,3,1,2,8,5,9,4,7,6]
const fieldLabels: Record<string, string> = {
  FUNCTION_KEY: 'SAP module or area',
  AGR_NAME: 'Role name (required)',
  TEXT: 'Role description',
  CHILD_AGR: 'Child role',
  CHILD_AGR_TEXT: 'Child role description',
  PARENT_AGR: 'Parent role',
  Effective_Role: 'Effective role',
  TCODE: 'Transaction code',
  TTEXT: 'Transaction description'
}
const fields = [
  'FUNCTION_KEY',
  'AGR_NAME',
  'TEXT',
  'CHILD_AGR',
  'CHILD_AGR_TEXT',
  'PARENT_AGR',
  'Effective_Role',
  'TCODE',
  'TTEXT'
]
const inputClass = controlClass
const buttonClass = 'ui-button ui-button-secondary ui-button-default'
const Field=FormField
export function SettingsView({
  open,
  dataSourceRequest = 0,
  onOpen,
  onClose,
  onDataChanged,
  onSaved
}: {
  open: boolean
  dataSourceRequest?: number
  onOpen: () => void
  onClose: () => void
  onDataChanged: () => void
  onSaved: () => void
}) {
  const applicationData=useApplicationData()
  const [section, setSection] = useState(0)
  const [importSource, setImportSource] = useState<CSVSource>('roles')
  const [advancedSource,setAdvancedSource]=useState(false)
  const [candidatePaths,setCandidatePaths]=useState<Partial<Record<CSVSource,string>>>({})
  const scrollPane = useRef<HTMLDivElement>(null)
  useEffect(() => {
    scrollPane.current?.scrollTo({ top: 0 })
  }, [section, open])
  const [draft, setDraft] = useState<Configuration | null>(null)
  const [busy, setBusy] = useState(false)
  const [native, setNative] = useState(Boolean(window.pywebview?.api))
  const [error, setError] = useState<string | null>(null)
  const [settingsTarget] = useHistoryValue('settingsTarget')
  const {change: changeSettingsTarget} = useViewHistory()
  useEffect(()=>{if(open && settingsTarget) {setSection(settingsTarget === 'diagnostics' ? 4 : settingsTarget === 'features' ? 5 : 1); if(['roles','users','employees','sod'].includes(settingsTarget)) setImportSource(settingsTarget as CSVSource); changeSettingsTarget({settingsTarget:undefined},true)}},[open,settingsTarget])
  const [message, setMessage] = useState<string | null>(null)
  const [columns, setColumns] = useState<string[]>([])
  const [inspectionMessage, setInspectionMessage] = useState('')
  const [inspecting, setInspecting] = useState(false)
  const [inspectionRetry, setInspectionRetry] = useState(0)
  const draftRef = useRef(draft)
  draftRef.current = draft
  const [importResult, setImportResult] = useState<ImportReport | null>(null)
  const csvPathInput = useRef<HTMLInputElement>(null)
  const handledDataSourceRequest = useRef(0)
  const headingDataSourceRequest = useRef(0)
  const focusDataSource = useRef(false)
  useEffect(() => {
    if (open && dataSourceRequest > handledDataSourceRequest.current) {
      handledDataSourceRequest.current = dataSourceRequest
      focusDataSource.current = true
      setSection(1)
      setImportSource('roles')
      setError(null)
      setMessage(null)
    }
  }, [open, dataSourceRequest])
  useEffect(() => {
    if (open && section === 1 && draft && focusDataSource.current) {
      csvPathInput.current?.focus({ preventScroll: true })
      csvPathInput.current?.scrollIntoView({ block: 'nearest' })
      focusDataSource.current = false
    }
  }, [open, section, draft])
  const [moduleSearch, setModuleSearch] = useState('')
  const [logoPath, setLogoPath] = useState('')
  const [logoPreview, setLogoPreview] = useState<string | null>(null)
  const [dismissedNotice, setDismissedNotice] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem('sap-lens-dismissed-notice')
    } catch {
      return null
    }
  })
  const [includePrivate, setIncludePrivate] = useState(false)
  const autoOpened = useRef(false)
  const qc = useQueryClient()
  const config = useQuery({
    queryKey: ['configuration'],
    queryFn: fetchConfiguration,
    retry: false
  })
  const registry = useQuery({
    queryKey: ['registry'],
    queryFn: fetchRegistry,
    staleTime: Infinity
  })
  const logo = useQuery({
    queryKey: ['logo', config.data?.settings.logo_id],
    queryFn: () => apiRequest<{ data_url: string }>('/api/branding/logo'),
    enabled: Boolean(config.data?.settings.logo_id),
    retry: false,
    staleTime: Infinity
  })

  useEffect(() => {
    const ready = () => setNative(true)
    window.addEventListener('pywebviewready', ready)
    return () => window.removeEventListener('pywebviewready', ready)
  }, [])
  useEffect(() => {
    if (config.data)
      setDraft((previous) => previous || structuredClone(config.data.settings))
    if (config.data && !autoOpened.current) {
      autoOpened.current = true
      if (
        !(config.data.settings.data_csv_path || config.data.settings.user_csv_path) ||
        config.data.error ||
        config.data.notice?.includes('invalid')
      ) {
        setSection(config.data.notice?.includes('invalid') ? 4 : 1)
        onOpen()
      }
    }
  }, [config.data])

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      await action()
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : 'The operation failed. Your saved configuration is retained.'
      )
    } finally {
      setBusy(false)
    }
  }
  const accepted = async (result: ConfigurationResponse) => {
    const previous = qc.getQueryData<ConfigurationResponse>([
      'configuration'
    ])?.settings
    const dataKeys = [
      'data_csv_path',
      'import_profiles',
      'active_import',
      'user_csv_path',
      'user_import_profiles',
      'active_user_import',
      'module_overrides'
    ] as const
    const dataChanged =
      !previous ||
      dataKeys.some(
        (k) =>
          JSON.stringify(previous[k]) !== JSON.stringify(result.settings[k])
      )
    setDraft(structuredClone(result.settings))
    setImportResult(null)
    qc.setQueryData(['configuration'], result)
    await qc.invalidateQueries({
      predicate: (q) => q.queryKey[0] !== 'configuration'
    })
    if (dataChanged) onDataChanged()
  }
  const dirty = Boolean(
    draft &&
    config.data &&
    JSON.stringify(draft) !== JSON.stringify(config.data.settings)
  )
  useEffect(() => { setSettingsDirty(dirty && open); return () => setSettingsDirty(false) }, [dirty, open])
  const show = (value: boolean) => {
    if (busy) return
    if (!value && dirty && !window.confirm(DISCARD_PROMPT))
      return
    if (!value) {
      if (config.data) setDraft(structuredClone(config.data.settings))
      setError(null)
      setMessage(null)
      setLogoPreview(null)
      setImportResult(null)
      setColumns([])
      onClose()
    }
  }
  useEffect(() => {
    if (open) {
      if (dataSourceRequest > headingDataSourceRequest.current) {
        headingDataSourceRequest.current = dataSourceRequest
        return
      }
      document.getElementById('settings-heading')?.focus()
      return
    }
    if (config.data) setDraft(structuredClone(config.data.settings))
  }, [open, config.data?.settings.revision])
  useEffect(() => {
    if (!dirty || !open) return
    const protect = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', protect)
    return () => window.removeEventListener('beforeunload', protect)
  }, [dirty, open])
  const dismissNotice = () => {
    const notice = config.data?.notice
    if (notice) {
      try {
        sessionStorage.setItem('sap-lens-dismissed-notice', notice)
      } catch {
        /* optional session hint */
      }
      setDismissedNotice(notice)
    }
  }
  const update = <K extends keyof Configuration>(
    key: K,
    value: Configuration[K]
  ) => {
      setDraft((prev) => (prev ? { ...prev, [key]: value } : prev))
  }
  const imports = draft?.import_profiles.find(
    (p) => p.id === draft.active_import
  )
  const editImport = (patch: Partial<ImportProfile>) =>
    draft &&
    imports &&
    update(
      'import_profiles',
      draft.import_profiles.map((p) =>
        p.id === imports.id ? { ...p, ...patch } : p
      )
    )
  const roleInspectionPath=candidatePaths.roles??draft?.data_csv_path??''
  useEffect(() => {
    if (!advancedSource || !open || section !== 1 || importSource !== 'roles' || !roleInspectionPath || !imports) {
      setInspecting(false)
      if (!draft?.data_csv_path) {
        setColumns([])
        setImportResult(null)
        setInspectionMessage(
          'Select a CSV file to inspect its columns and preview the import.'
        )
      }
      return
    }
    let cancelled = false
    const path = roleInspectionPath
    const profileId = imports.id
    setInspecting(true)
    const timer = window.setTimeout(async () => {
      try {
        const result = await detectHeaders(path, {
          ...imports,
          mapping: imports.mapping
        })
        if (cancelled) return
        setColumns(result.detected_columns)
        const current = draftRef.current
        if (
          !current ||
          current.active_import !== profileId
        )
          return
        const currentProfile = current.import_profiles.find(
          (p) => p.id === profileId
        )!
        // Detection is observational: never discard deliberate mappings, even on a new file.
        const mapping = currentProfile.mapping
        const missing = Object.values(mapping).filter(source => !result.detected_columns.includes(source))
        const mappingNotice = missing.length ? 'Some manual mappings reference missing columns. Review them before applying. ' : ''
        setInspectionMessage(
          mappingNotice +
            (result.issues.length
              ? result.issues.join(' ')
              : 'Columns detected automatically. Optional preview does not replace active data.')
        )
        const preview = await previewImport(path, {
          ...currentProfile,
          mapping
        })
        if (
          !cancelled &&
          JSON.stringify(
            draftRef.current?.import_profiles.find((p) => p.id === profileId)
              ?.mapping
          ) === JSON.stringify(mapping)
        )
          setImportResult(preview)
      } catch (e) {
        if (!cancelled)
          setInspectionMessage(previous =>
            (previous.startsWith('Some manual mappings') ? previous + ' ' : Object.keys(imports.mapping).length ? 'Manual mappings retained; review the selected columns. ' : '') +
            (e instanceof Error ? e.message : 'Could not inspect this file. Check its location and try again.')
          )
      } finally {
        if (!cancelled) setInspecting(false)
      }
    }, 450)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [
    open,
    section,
    importSource,
    roleInspectionPath,
    draft?.active_import,
    imports?.delimiter,
    imports?.encoding,
    JSON.stringify(imports?.mapping),
    inspectionRetry,
    advancedSource
  ])

  const sourceActivated=(result:SourceActivation)=>{
    setCandidatePaths(previous=>({...previous,[result.source]:result.source==='roles'?result.settings.data_csv_path:result.source==='users'?result.settings.user_csv_path:result.source==='sod'?result.settings.sod_csv_path||'':result.settings.employee_csv_path||''}))
    setDraft(previous=>previous?rebaseSourceDraft(previous,result.settings,result.source):previous)
  }
  const clearSource=async(source:CSVSource)=>{
    const current=await fetchConfiguration()
    if(source==='employees')await apiRequest('/api/employees/clear','POST',{path:current.settings.employee_csv_path||'',revision:current.settings.revision})
    else await saveConfiguration({...current.settings,[source==='roles'?'data_csv_path':source==='sod'?'sod_csv_path':'user_csv_path']:''})
    const saved=await fetchConfiguration()
    setCandidatePaths(previous=>({...previous,[source]:''}))
    qc.setQueryData(['configuration'],saved)
    setDraft(previous=>previous?rebaseSourceDraft(previous,saved.settings,source):previous)
    await qc.invalidateQueries({predicate:query=>query.queryKey[0]!=='configuration'})
    if(source!=='employees')onDataChanged()
  }
  const previewLogo = (path: string) =>
    run(async () => {
      const result = await apiRequest<{ logo_id: string; data_url: string }>(
        '/api/branding/preview',
        'POST',
        { path }
      )
      update('logo_id', result.logo_id)
      setLogoPreview(result.data_url)
    })
  const exportConfig = () =>
    run(async () => {
      if (window.pywebview?.api.export_configuration) {
        const saved = await window.pywebview.api.export_configuration(
          applicationToken(),
          includePrivate
        )
        if (saved)
          setMessage(
            'Configuration exported. The package never contains CSV records or a file path.'
          )
      } else {
        const packageData = await apiRequest(
          `/api/configuration/export?include_private=${includePrivate}`,
          'POST'
        )
        const url = URL.createObjectURL(
          new Blob([JSON.stringify(packageData, null, 2)], {
            type: 'application/json'
          })
        )
        const link = document.createElement('a')
        link.href = url
        link.download = 'SAP-Lens.sap-lens.json'
        link.click()
        URL.revokeObjectURL(url)
        setMessage('Configuration exported; keep private packages secure.')
      }
    })

  return (
    <section
      aria-label="SAP Lens settings"
      className={open ? 'settings-workspace' : 'hidden'}
    >
      <aside className="settings-sidebar">
        <button
          className={`${buttonClass} flex items-center gap-2 mb-6`}
          onClick={() => show(false)}
          disabled={busy}
          aria-label="Back to SAP Lens"
        >
          <ArrowLeft size={16} /> Back to SAP Lens
        </button>
        <p className="text-xs uppercase tracking-widest font-semibold px-3 mb-3 text-[var(--muted)]">
          Administration
        </p>
        <nav
          role="tablist"
          aria-label="Settings sections"
          aria-orientation="vertical"
          className="flex flex-col gap-1"
        >
          {navigationOrder.map((index, position) => {
            const label=sections[index]
            const Icon = sectionIcons[index]
            return (
              <div key={label}>{[0,1,5].includes(index)&&<p className="settings-nav-category">{index===0?'GENERAL':index===1?'DATA & MODULES':'APPLICATION'}</p>}<button
                role="tab"
                aria-label={label}
                id={`settings-tab-${index}`}
                aria-selected={section === index}
                aria-controls={`settings-panel-${index}`}
                tabIndex={section === index ? 0 : -1}
                onKeyDown={(event) => {
                  if (
                    ['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)
                  ) {
                    event.preventDefault()
                    const next =
                      event.key === 'Home'
                        ? navigationOrder[0]
                        : event.key === 'End'
                          ? navigationOrder[navigationOrder.length-1]
                          : navigationOrder[(position + (event.key === 'ArrowDown' ? 1 : navigationOrder.length - 1)) % navigationOrder.length]
                    setSection(next)
                    document.getElementById(`settings-tab-${next}`)?.focus()
                  }
                }}
                onClick={() => {
                  setSection(index)
                  setError(null)
                  setMessage(null)
                }}
                className={`settings-nav-item ${section === index ? 'active' : ''}`}
              >
                <Icon size={19} aria-hidden="true" />
                <span>{label}</span>
              </button></div>
            )
          })}
        </nav>
        <p className="text-xs text-[var(--muted)] px-3 mt-auto pt-8">
          One active SAP system.
          <br />
          Settings stay on this computer.
        </p>
      </aside>
      <div className="settings-main">
        <div className="settings-scroll" ref={scrollPane}>
          <div className="settings-content">
            <p className="text-xs uppercase tracking-widest text-[var(--muted)] mb-2">
              Settings
            </p>
            <h1
              id="settings-heading"
              tabIndex={-1}
              className="text-2xl font-semibold outline-none"
            >
              {sections[section]}
            </h1>
            <p className="text-sm text-[var(--muted)] mt-2 mb-7">
              {
                [
                  'Organization identity and SAP system details.',
                  'Connect an export, map its columns and validate before loading.',
                  'Manage area labels, icons and colors without changing their identifiers.',
                  'Personalize the appearance of your local application.',
                  'Service health, local storage and safe configuration recovery.',
                  'Enable optional capabilities and configure review classification.',
                  'Version, build and runtime information.',
                  'Interactive reference for shared UI components; isolated synthetic previews.',
                  'Review imported SoD risks and keep local business guidance and risk settings.',
                  'Schedule background refresh of dynamic sources and review the last runs.'
                ][section]
              }
            </p>
            {config.data?.notice && dismissedNotice !== config.data.notice && (
              <div
                role="status"
                className={`settings-notice ${config.data.notice.includes('invalid') ? 'recovery' : ''}`}
              >
                <CheckCircle size={18} className="shrink-0" />
                <span>{config.data.notice}</span>
                <button
                  aria-label="Dismiss configuration notice"
                  onClick={dismissNotice}
                  className="ml-auto p-1"
                >
                  <X size={16} />
                </button>
              </div>
            )}
            {config.data?.loading && (
              <div className="text-sm mb-3">
                <p role="status">
                  Loading role data… You can cancel a stalled read and choose
                  another file.
                </p>
                <button
                  className={buttonClass}
                  onClick={() =>
                    void apiRequest('/api/data/cancel', 'POST')
                      .then(() => {
                        setBusy(false)
                        setMessage(
                          'Load canceled. Choose a local file or another share.'
                        )
                        void qc.invalidateQueries({
                          queryKey: ['configuration']
                        })
                      })
                      .catch(() =>
                        setError(
                          'Could not cancel the read. Close and reopen SAP Lens.'
                        )
                      )
                  }
                >
                  Cancel data load
                </button>
              </div>
            )}
            {error && (
              <p role="alert" className="text-[var(--error)] text-sm mb-3">
                {error}
              </p>
            )}
            {config.isError && (
              <p role="alert" className="text-[var(--error)]">
                Could not read configuration. Close and reopen SAP Lens.
              </p>
            )}
            {message && (
              <p role="status" className="text-[var(--success)] text-sm mb-3">
                {message}
              </p>
            )}
            <div
              role="tabpanel"
              id={`settings-panel-${section}`}
              aria-labelledby={`settings-tab-${section}`}
              className="space-y-5 min-w-0"
            >
              {!draft ? (
                <p>Loading settings…</p>
              ) : (
                <>
                  {section === 0 && (
                    <div className="grid md:grid-cols-2 gap-5 max-w-3xl">
                      <Field label="Organization name">
                        <input
                          className={inputClass}
                          value={draft.organization.name}
                          maxLength={120}
                          onChange={(e) =>
                            update('organization', {
                              ...draft.organization,
                              name: e.target.value
                            })
                          }
                        />
                      </Field>
                      <Field label="SAP platform">
                        <SettingsSelect
                          className={inputClass}
                          value={draft.organization.platform}
                          onChange={(e) =>
                            update('organization', {
                              ...draft.organization,
                              platform: e.target.value
                            })
                          }
                        >
                          {['SAP S/4HANA', 'SAP ECC', 'Other / Custom'].map(
                            (v) => (
                              <option key={v}>{v}</option>
                            )
                          )}
                        </SettingsSelect>
                      </Field>
                      {draft.organization.platform === 'Other / Custom' && (
                        <Field label="Custom platform label">
                          <input
                            className={inputClass}
                            value={draft.organization.custom_platform}
                            maxLength={80}
                            onChange={(e) =>
                              update('organization', {
                                ...draft.organization,
                                custom_platform: e.target.value
                              })
                            }
                          />
                        </Field>
                      )}
                      <Field label="SAP system ID">
                        <input
                          className={inputClass}
                          value={draft.organization.system_id}
                          maxLength={20}
                          onChange={(e) =>
                            update('organization', {
                              ...draft.organization,
                              system_id: e.target.value
                            })
                          }
                        />
                      </Field>
                      <Field label="SAP client">
                        <input
                          className={inputClass}
                          value={draft.organization.client}
                          maxLength={10}
                          onChange={(e) =>
                            update('organization', {
                              ...draft.organization,
                              client: e.target.value
                            })
                          }
                        />
                      </Field>
                      <Field label="System description (optional)">
                        <input
                          className={inputClass}
                          value={draft.organization.description}
                          maxLength={200}
                          onChange={(e) =>
                            update('organization', {
                              ...draft.organization,
                              description: e.target.value
                            })
                          }
                        />
                      </Field>
                      <Field label="Footer text" description="Leave blank to use the organization name and current year.">
                        <input
                          className={inputClass}
                          value={draft.organization.footer}
                          maxLength={240}
                          onChange={(e) =>
                            update('organization', {
                              ...draft.organization,
                              footer: e.target.value
                            })
                          }
                        />
                      </Field>
                      <div className="md:col-span-2"><ReportBranding /></div>
                    </div>
                  )}
                  {section === 1 && imports && (
                    <>
                      <DataHealth onSource={key=>{setImportSource(key);requestAnimationFrame(()=>document.getElementById(`source-tab-${key}`)?.focus())}}/>
                      <details className="settings-advanced"><summary>Recent refresh reports</summary><RefreshHistory/></details>
                      <div className="flex flex-wrap gap-3">
                        <button className="settings-secondary-button" onClick={() => setSection(4)}>View data source diagnostics</button>

                      </div>
                      <ContentTabList label="Import source" value={importSource} onChange={value=>setImportSource(value as CSVSource)} idPrefix="source-tab" panelId={value=>`source-panel-${value}`} className="source-navigation" items={([['roles','Role Catalogue',LibraryBig],['users','User Access',UsersRound],['employees','Employee Directory',BookUser],['sod','SoD Matrix',ShieldCheck]] as const).map(([value,label,Icon])=>({value,label,icon:<Icon size={16} aria-hidden="true"/>}))}/>

                      {config.data?.error&&!applicationData.importPhase&&<p role="alert">{config.data.error}</p>}
                      <div id={`source-panel-${importSource}`} role="tabpanel" aria-labelledby={`source-tab-${importSource}`}>
                        <SourceManager key={importSource} source={importSource} draft={draft} candidatePath={candidatePaths[importSource]} inputRef={csvPathInput}
                          onMode={mode=>setDraft(previous=>previous?{...previous,source_modes:{roles:'dynamic',users:'dynamic',employees:'static',sod:'static',...previous.source_modes,[importSource]:mode}}:previous)}
                          onCandidate={path=>setCandidatePaths(previous=>({...previous,[importSource]:path}))} onActivated={sourceActivated} onClear={()=>clearSource(importSource)} onFeatures={()=>setSection(5)}/>
                        {importSource==='employees'&&<><DirectorySnapshotRecovery onPersisted={async()=>{const saved=await fetchConfiguration();qc.setQueryData(['configuration'],saved);setDraft(previous=>previous?rebaseSourceDraft(previous,saved.settings,'employees'):previous);await qc.invalidateQueries({predicate:query=>['diagnostics','data-health','dashboard'].includes(String(query.queryKey[0]))});setMessage('Validated directory records saved locally. The original CSV is no longer required for restart.')}}/><DirectoryDiagnostics sourceView onFeatureSettings={()=>setSection(5)}/><details className="settings-advanced mt-4"><summary>Employee Directory data preview</summary><EmployeeBrowser/></details></>}
                      {(importSource==='roles'||importSource==='users')&&<details className="settings-advanced" onToggle={event=>setAdvancedSource(event.currentTarget.open)}>
                        <summary>Advanced import format and column mapping</summary>
                        <p className="ui-description">Optional inspection and mapping. Selecting a file imports automatically using the selected format. Apply settings to save format-only changes.</p>
                        {advancedSource&&importSource==='users'&&<UserSourceEditor draft={{...draft,user_csv_path:candidatePaths.users??draft.user_csv_path}} onChange={value=>setDraft(previous=>previous?{...value,user_csv_path:previous.user_csv_path}:previous)} active/>}
                        {advancedSource&&importSource==='roles'&&<div className="import-source-panel space-y-4">
                      <ImportSection step={2} title="CSV Import Format" description="Choose a built-in format or create a reusable custom preset.">
                      <div className="import-preset-toolbar">
                        <Field label="CSV Import Format">
                          <SettingsSelect
                            className={inputClass}
                            value={draft.active_import}
                            onChange={(e) =>
                              update('active_import', e.target.value)
                            }
                          >
                            {draft.import_profiles.map((p) => (
                              <option key={p.id} value={p.id}>
                                {p.name} · {p.id === 'default' ? 'Built-in' : 'Custom'} · v{p.version}
                              </option>
                            ))}
                          </SettingsSelect>
                        </Field>
                        <PresetActions draft={draft} onChange={setDraft} />
                      </div>
                      <Field label="Import preset name">
                        <input
                          className={inputClass}
                          value={imports.name}
                          disabled={imports.id === 'default'}
                          onChange={(e) => editImport({ name: e.target.value })}
                        />
                      </Field>
                      <details className="settings-advanced"><summary>Advanced CSV options</summary>
                      <div className="grid sm:grid-cols-2 gap-3">
                        <Field label="Delimiter">
                          <SettingsSelect
                            className={inputClass}
                            value={imports.delimiter}
                            onChange={(e) =>
                              editImport({ delimiter: e.target.value })
                            }
                          >
                            {[
                              ['auto', 'Auto detect'],
                              [',', 'Comma'],
                              [';', 'Semicolon'],
                              ['\t', 'Tab'],
                              ['|', 'Pipe']
                            ].map(([v, l]) => (
                              <option key={v} value={v}>
                                {l}
                              </option>
                            ))}
                          </SettingsSelect>
                        </Field>
                        <Field label="Encoding">
                          <SettingsSelect
                            className={inputClass}
                            value={imports.encoding}
                            onChange={(e) =>
                              editImport({ encoding: e.target.value })
                            }
                          >
                            {['auto', 'utf-8-sig', 'utf-16', 'cp1252'].map(
                              (v) => (
                                <option key={v}>{v}</option>
                              )
                            )}
                          </SettingsSelect>
                        </Field>
                      </div>
                      </details>
                      </ImportSection>
                      <ImportSection step={3} title="Column mapping" description="Columns are inspected automatically. Manual mappings are preserved.">
                      <p role="status" className="text-sm text-[var(--text2)]">
                        {inspecting
                          ? 'Inspecting columns and updating the preview…'
                          : inspectionMessage}
                      </p>
                      <button
                        className={buttonClass}
                        disabled={busy || inspecting || !roleInspectionPath}
                        onClick={() => setInspectionRetry((n) => n + 1)}
                      >
                        Detect columns
                      </button>
                      <p className="text-xs">
                        AGR_NAME is required. Other fields are optional with
                        warnings; preserve parent/effective fields when present.
                        Blank mappings auto-detect standard headers.
                      </p>
                      <div className="import-mapping-grid">
                        {fields.map((field) => (
                          <MappingField key={field} field={field} label={fieldLabels[field]} accessibleLabel={field==='AGR_NAME'?'AGR_NAME (required)':field} required={field==='AGR_NAME'} value={imports.mapping[field]||''} columns={columns} disabled={busy||inspecting} onChange={value=>{setImportResult(null);const mapping={...imports.mapping};if(value)mapping[field]=value;else delete mapping[field];editImport({mapping})}}/>

                        ))}
                      </div>
                      </ImportSection>
                      <ImportSection step={4} title="Optional preview" description="Inspect parsing without replacing active data. File selection imports automatically.">
                      <button
                        className={buttonClass}
                        disabled={busy || !roleInspectionPath}
                        onClick={() =>
                          void run(async () => {
                            const result = await previewImport(
                              roleInspectionPath,
                              imports
                            )
                            setImportResult(result)
                            setColumns(result.detected_columns)
                          })
                        }
                      >
                        Preview import
                      </button>
                      {importResult && <ImportPreview fileName={importResult.file_name} metrics={[{label:'Parsed rows',value:importResult.parsed_rows},{label:'Catalogue roles',value:importResult.unique_roles},{label:'Unique transactions',value:importResult.unique_transactions},{label:'Role/T-code mappings',value:importResult.transaction_assignments}]} warnings={importResult.warnings} errors={importResult.errors} samples={importResult.samples}><p className="ui-description">Assignments count distinct composite/child/parent/effective-role/T-code tuples.</p></ImportPreview>}

                      </ImportSection>
                      </div>}
                      </details>}
                      </div>
                    </>
                  )}
                  {
                    <div className={section === 2 ? '' : 'hidden'}>
                      <ModuleEditor
                        modules={registry.data?.modules || []}
                        overrides={draft.module_overrides}
                        savedOverrides={
                          config.data?.settings.module_overrides || {}
                        }
                        onChange={(value) => update('module_overrides', value)}
                        search={moduleSearch}
                        onSearch={setModuleSearch}
                      />
                    </div>
                  }
                  {
                    <div className={section === 3 ? 'grid min-w-0 grid-cols-1 gap-5' : 'hidden'}>
                      <div className="min-w-0"><ThemeEditor
                        key={`${open}-${config.data?.settings.revision}`}
                        draft={draft}
                        logoSrc={draft.logo_id ? logoPreview || logo.data?.data_url || '/sap-lens.png' : '/sap-lens.png'}
                        onChange={(patch) => setDraft({ ...draft, ...patch })}
                      />
                      </div><div className="space-y-3"><h2 className="settings-subheading">Header logo</h2>
                      <p className="text-sm">
                        Currently active:{' '}
                        {config.data?.settings.logo_id
                          ? 'Custom organization logo'
                          : 'SAP Lens default logo'}
                        .{' '}
                        {draft.logo_id !== config.data?.settings.logo_id
                          ? 'A pending change will be applied when you save.'
                          : ''}
                      </p>
                      <p className="text-sm">
                        A custom logo changes only this header, never the
                        Windows icon, README or product identity. Use
                        PNG/JPEG/WebP up to 2 MB and 4096 pixels per side; SVG
                        is rejected.
                      </p>
                      <div className="branding-logo-grid">
                      <div className="flex min-h-32 items-center justify-center rounded-card border border-line bg-elevated p-4"><img alt="Selected header logo preview" src={draft.logo_id?logoPreview||logo.data?.data_url||'/sap-lens.png':'/sap-lens.png'} className="max-h-24 max-w-full object-contain" onError={event=>{if(!event.currentTarget.src.endsWith('/sap-lens.png'))event.currentTarget.src='/sap-lens.png'}}/></div>
                      <div className="branding-logo-controls">{logo.isError && (
                        <p
                          role="status"
                          className="text-[var(--warning)] text-sm"
                        >
                          The saved custom logo is unavailable; SAP Lens uses
                          its default logo.
                        </p>
                      )}
                      <Field label="Logo file location">
                        <input
                          className={inputClass}
                          value={logoPath}
                          onChange={(e) => setLogoPath(e.target.value)}
                        />
                      </Field>
                      <div className="branding-actions">
                      <button
                        className={buttonClass}
                        disabled={
                          !native || busy || !window.pywebview?.api.choose_logo
                        }
                        onClick={() =>
                          void run(async () => {
                            const path =
                              await window.pywebview?.api.choose_logo?.(
                                applicationToken()
                              )
                            if (path) {
                              setLogoPath(path)
                              const result = await apiRequest<{
                                logo_id: string
                                data_url: string
                              }>('/api/branding/preview', 'POST', { path })
                              update('logo_id', result.logo_id)
                              setLogoPreview(result.data_url)
                            }
                          })
                        }
                      >
                        <Image size={16} aria-hidden="true" /> Select custom
                        logo…
                      </button>
                      <button
                        className={buttonClass}
                        disabled={!logoPath || busy}
                        onClick={() => void previewLogo(logoPath)}
                      >
                        <Image size={16} aria-hidden="true" /> Preview logo
                      </button>
                      <button
                        className={buttonClass}
                        aria-label="Remove custom logo / restore SAP Lens default"
                        title="Remove custom logo and restore the SAP Lens default"
                        onClick={() => {
                          update('logo_id', null)
                          setLogoPreview(null)
                        }}
                      >
                        <RotateCcw size={16} aria-hidden="true" /> Restore default
                      </button>
                      </div>
                      <p className="text-xs">
                        Previewed files are copied into managed local storage.
                        Apply settings to activate the logo; moving the original
                        will not break it.
                      </p>
                      </div></div>
                      </div>
                    </div>
                  }
                  {section === 6 && <About/>}
                  {section === 9 && <><ScheduledRefresh draft={draft} onChange={setDraft}/><DesktopOptions draft={draft} onChange={setDraft}/></>}
                  {section === 8 && <SodRiskSettings onConfigure={()=>{setSection(1);setImportSource('sod')}}/>}
                  {section === 7 && <Suspense fallback={<p role="status">Loading component previews…</p>}><ComponentLibrary/></Suspense>}
                  {section === 5 && <><FeatureSettings draft={draft} onChange={setDraft} onConfigure={source => { setSection(1); setImportSource(source) }}/></>}
                  {section === 4 && (
                    <>
                      <Diagnostics onSource={source=>{setSection(1);setImportSource(source)}} native={native} onEmployeeFeatures={() => setSection(5)} onEmployeeSettings={() => { setSection(1); setImportSource('employees') }}/>
                      <h2 className="settings-subheading">Backup & recovery</h2>
                      <p className="text-sm text-[var(--text2)]">
                        Export saved settings before an update, or restore a
                        previously exported package. Import and reset keep a
                        local backup.
                      </p>
                      <label className="block text-sm">
                        <input
                          type="checkbox"
                          checked={includePrivate}
                          onChange={(e) => setIncludePrivate(e.target.checked)}
                        />{' '}
                        Include private organization details, profiles and
                        branding in export
                      </label>
                      <p className="text-xs">
                        Exports exclude CSV data and paths. The default export
                        is redacted; a private export may disclose naming
                        conventions and organization details. Store it securely.
                      </p>
                      <button
                        className={buttonClass}
                        disabled={busy}
                        onClick={() => void exportConfig()}
                      >
                        <Save size={16} aria-hidden="true" /> Export saved
                        configuration
                      </button>
                      <Field label="Import configuration package">
                        <input
                          type="file"
                          accept="application/json,.json"
                          disabled={busy}
                          onChange={(e) => {
                            const file = e.target.files?.[0]
                            if (file)
                              void run(async () => {
                                if (file.size > 4_000_000)
                                  throw Error(
                                    'Configuration package exceeds 4 MB.'
                                  )
                                if (
                                  !window.confirm(
                                    'Validate and apply this configuration package? A local backup will be retained.'
                                  )
                                )
                                  return
                                const payload: unknown = JSON.parse(
                                  await file.text()
                                )
                                const result =
                                  await apiRequest<ConfigurationResponse>(
                                    '/api/configuration/import',
                                    'POST',
                                    payload
                                  )
                                await accepted(result)
                                setMessage(
                                  'Configuration imported. Your local CSV path is retained.'
                                )
                              })
                          }}
                        />
                      </Field>
                      <button
                        className={buttonClass}
                        disabled={busy}
                        onClick={() =>
                          void run(async () => {
                            if (
                              !window.confirm(
                                'Reset configuration to generic defaults and unload the dataset? A backup will be kept; source files are never deleted.'
                              )
                            )
                              return
                            await accepted(
                              await apiRequest<ConfigurationResponse>(
                                '/api/configuration/reset',
                                'POST'
                              )
                            )
                            setMessage(
                              'Defaults restored. Previous configuration is backed up locally.'
                            )
                          })
                        }
                      >
                        <RotateCcw size={16} aria-hidden="true" /> Reset to
                        defaults
                      </button>
                    </>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
        <div className={section===7||section===8?'hidden':'settings-actions'}>
          <p role="status" className="text-xs text-[var(--muted)] mr-auto">
            {draft &&
            (['dark', 'light'] as const).some(
              (mode) =>
                paletteErrors((draft.theme_colors || defaultThemeColors)[mode])
                  .length
            ) ? (
              <button className="underline" onClick={() => setSection(3)}>
                Review invalid theme colors in Appearance & Branding
              </button>
            ) : dirty ? (
              'Unsaved changes'
            ) : (
              'All changes saved'
            )}
          </p>
          <button
            className={buttonClass}
            disabled={busy}
            onClick={() => show(false)}
          >
            Cancel
          </button>
          <button
            className="ui-button ui-button-primary ui-button-default"
            disabled={
              busy || applicationData.loading ||
              inspecting ||
              !dirty ||
              !draft ||
              Boolean(
                draft &&
                Object.values(draft.module_overrides).some(
                  (m) => m.color != null && !isHex(m.color)
                )
              ) ||
              config.data?.loading ||
              Boolean(
                draft &&
                ['dark', 'light'].some(
                  (mode) =>
                    paletteErrors(
                      (draft.theme_colors || defaultThemeColors)[
                        mode as 'dark' | 'light'
                      ]
                    ).length
                )
              )
            }
            onClick={() =>
              draft &&
              void run(async () => {
                await accepted(await saveConfiguration(draft))
                setMessage('Settings saved successfully.')
                onSaved()
                onClose()
              })
            }
          >
            <Save size={16} aria-hidden="true" />
            {busy ? 'Working…' : 'Apply settings'}
          </button>
        </div>
      </div>
    </section>
  )
}
