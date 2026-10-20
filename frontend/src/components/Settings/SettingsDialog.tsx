import { useEffect, useRef, useState, type ReactNode } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { Settings, X } from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, applicationToken } from '@/api/client'
import { fetchConfiguration, fetchRegistry, saveConfiguration, detectHeaders, previewImport,
  previewClassification, type Configuration, type ConfigurationResponse, type ImportReport,
  type ClassificationReport, type ClassificationProfile, type ImportProfile } from '@/api/configuration'

const sections = ['System & Organization','Data Source & Import','SAP Modules','Domains & Classification','Appearance & Branding','Application & Diagnostics']
const fields = ['FUNCTION_KEY','AGR_NAME','TEXT','CHILD_AGR','CHILD_AGR_TEXT','PARENT_AGR','Effective_Role','TCODE','TTEXT']
const inputClass = 'w-full rounded-lg border px-3 py-2 text-sm bg-[var(--surface2)] border-[var(--border)] text-[var(--text)]'
const buttonClass = 'border rounded-lg px-3 py-2 text-sm font-semibold hover:opacity-80 disabled:opacity-50'
function Field({label,children}: {label:string;children:ReactNode}) { return <label className="flex flex-col gap-1 text-sm font-medium">{label}{children}</label> }
function Result({children}: {children:ReactNode}) { return <div className="border rounded-xl p-3 space-y-2 text-sm overflow-x-auto">{children}</div> }
const freshId = (kind:string) => `${kind}-${Date.now()}`

export function SettingsDialog({ onDataChanged }: { onDataChanged: () => void }) {
  const [open,setOpen] = useState(false)
  const [section,setSection] = useState(0)
  const [draft,setDraft] = useState<Configuration | null>(null)
  const [busy,setBusy] = useState(false)
  const [native,setNative] = useState(Boolean(window.pywebview?.api))
  const [error,setError] = useState<string | null>(null)
  const [message,setMessage] = useState<string | null>(null)
  const [columns,setColumns] = useState<string[]>([])
  const [importResult,setImportResult] = useState<ImportReport | null>(null)
  const [classResult,setClassResult] = useState<ClassificationReport | null>(null)
  const [testRole,setTestRole] = useState('')
  const [moduleSearch,setModuleSearch] = useState('')
  const [logoPath,setLogoPath] = useState('')
  const [logoPreview,setLogoPreview] = useState<string | null>(null)
  const [includePrivate,setIncludePrivate] = useState(false)
  const autoOpened = useRef(false)
  const qc = useQueryClient()
  const config = useQuery({queryKey:['configuration'],queryFn:fetchConfiguration,
    refetchInterval:query => busy || query.state.data?.loading ? 1000 : false})
  const registry = useQuery({queryKey:['registry'],queryFn:fetchRegistry,staleTime:Infinity})
  const logo = useQuery({queryKey:['logo',config.data?.settings.logo_id],queryFn:() => apiRequest<{data_url:string}>('/api/branding/logo'),
    enabled:Boolean(config.data?.settings.logo_id),retry:false,staleTime:Infinity})

  useEffect(() => {
    const ready = () => setNative(true)
    window.addEventListener('pywebviewready',ready)
    return () => window.removeEventListener('pywebviewready',ready)
  },[])
  useEffect(() => {
    if (config.data) setDraft(previous=>previous || structuredClone(config.data.settings))
    if (config.data && !autoOpened.current) {
      autoOpened.current = true
      if (!config.data.settings.data_csv_path || config.data.error || config.data.notice) {
        setSection(config.data.notice ? 5 : 1); setOpen(true)
      }
    }
  },[config.data])
  useEffect(()=>{if(config.data && !config.data.loading)void qc.invalidateQueries({predicate:q=>['roles','modules'].includes(String(q.queryKey[0]))})},[config.data?.loading,config.data?.analysis,qc])

  const run = async (action:() => Promise<void>) => {
    setBusy(true); setError(null); setMessage(null)
    try { await action() } catch(e) { setError(e instanceof Error ? e.message : 'The operation failed. Your saved configuration is retained.') }
    finally { setBusy(false) }
  }
  const accepted = async (result:ConfigurationResponse) => {
    const previous=qc.getQueryData<ConfigurationResponse>(['configuration'])?.settings
    const dataKeys=['data_csv_path','import_profiles','active_import','classification_profiles','active_classification','module_overrides'] as const
    const dataChanged=!previous || dataKeys.some(k=>JSON.stringify(previous[k])!==JSON.stringify(result.settings[k]))
    setDraft(structuredClone(result.settings)); qc.setQueryData(['configuration'],result)
    await qc.invalidateQueries({predicate:q => q.queryKey[0] !== 'configuration'})
    if(dataChanged)onDataChanged()
  }
  const show = (value:boolean) => {
    if (busy) return
    if (value && config.data) { setDraft(structuredClone(config.data.settings)); setError(null); setMessage(null); setLogoPreview(null) }
    setOpen(value)
  }
  const update = <K extends keyof Configuration>(key:K,value:Configuration[K]) => setDraft(prev => prev ? {...prev,[key]:value} : prev)
  const imports = draft?.import_profiles.find(p => p.id === draft.active_import)
  const profile = draft?.classification_profiles.find(p => p.id === draft.active_classification)
  const editImport = (patch:Partial<ImportProfile>) => draft && imports && update('import_profiles',draft.import_profiles.map(p => p.id===imports.id ? {...p,...patch} : p))
  const editProfile = (patch:Partial<ClassificationProfile>) => draft && profile && update('classification_profiles',draft.classification_profiles.map(p => p.id===profile.id ? {...p,...patch} : p))
  const pickCsv = () => run(async () => { const path = await window.pywebview?.api.choose_csv(applicationToken()); if(path) update('data_csv_path',path) })
  const previewLogo = (path:string) => run(async () => { const result = await apiRequest<{logo_id:string;data_url:string}>('/api/branding/preview','POST',{path}); update('logo_id',result.logo_id);setLogoPreview(result.data_url) })
  const exportConfig = () => run(async () => {
    if (window.pywebview?.api.export_configuration) {
      const saved = await window.pywebview.api.export_configuration(applicationToken(),includePrivate)
      if(saved) setMessage('Configuration exported. The package never contains CSV records or a file path.')
    } else {
      const packageData = await apiRequest(`/api/configuration/export?include_private=${includePrivate}`,'POST')
      const url = URL.createObjectURL(new Blob([JSON.stringify(packageData,null,2)],{type:'application/json'}))
      const link = document.createElement('a');link.href=url;link.download='SAP-Lens.sap-lens.json';link.click();URL.revokeObjectURL(url)
      setMessage('Configuration exported; keep private packages secure.')
    }
  })

  return <Dialog.Root open={open} onOpenChange={show}>
    <Dialog.Trigger asChild><button className="text-white text-xs font-semibold px-3 py-2 rounded-lg hover:bg-white/10 flex gap-2 items-center" aria-label="Open settings"><Settings className="w-4 h-4" aria-hidden="true" /> Settings</button></Dialog.Trigger>
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 bg-black/60 z-50" />
      <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[min(64rem,96vw)] max-h-[94vh] flex flex-col rounded-2xl border p-5 shadow-xl"
        style={{background:'var(--surface)',color:'var(--text)',borderColor:'var(--border)'}}>
        <Dialog.Title className="text-xl font-bold">SAP Lens settings</Dialog.Title>
        <Dialog.Description className="text-sm mt-1 mb-4" style={{color:'var(--muted)'}}>One active SAP system. Organization details, files, logos and rules stay in your local application data.</Dialog.Description>
        <div role="tablist" aria-label="Settings sections" className="flex flex-wrap gap-1 mb-4 pr-5">
          {sections.map((label,index) => <button key={label} role="tab" id={`settings-tab-${index}`} aria-selected={section===index} aria-controls={`settings-panel-${index}`}
            tabIndex={section===index ? 0 : -1} onKeyDown={event => { if(event.key==='ArrowRight'||event.key==='ArrowLeft'){event.preventDefault();const next=(index+(event.key==='ArrowRight'?1:5))%6;setSection(next);document.getElementById(`settings-tab-${next}`)?.focus()} }}
            onClick={() => setSection(index)} className={`${buttonClass} ${section===index ? 'bg-purple-800 text-white' : ''}`}>{label}</button>)}
        </div>
        {config.data?.notice && <p role="status" className="text-amber-600 text-sm mb-3">{config.data.notice}</p>}
        {config.data?.loading && <div className="text-sm mb-3"><p role="status">Loading role data… You can cancel a stalled read and choose another file.</p><button className={buttonClass} onClick={()=>void apiRequest('/api/data/cancel','POST').then(()=>{setBusy(false);setMessage('Load canceled. Choose a local file or another share.');void qc.invalidateQueries({queryKey:['configuration']})}).catch(()=>setError('Could not cancel the read. Close and reopen SAP Lens.'))}>Cancel data load</button></div>}
        {error && <p role="alert" className="text-red-600 text-sm mb-3">{error}</p>}
        {config.isError && <p role="alert" className="text-red-600">Could not read configuration. Close and reopen SAP Lens.</p>}
        {message && <p role="status" className="text-green-600 text-sm mb-3">{message}</p>}
        <div role="tabpanel" id={`settings-panel-${section}`} aria-labelledby={`settings-tab-${section}`} className="overflow-y-auto flex-1 min-h-0 space-y-4 p-1">
          {!draft ? <p>Loading settings…</p> : <>
          {section===0 && <div className="grid sm:grid-cols-2 gap-4">
            <Field label="Organization name"><input className={inputClass} value={draft.organization.name} maxLength={120} onChange={e=>update('organization',{...draft.organization,name:e.target.value})} /></Field>
            <Field label="SAP platform"><select className={inputClass} value={draft.organization.platform} onChange={e=>update('organization',{...draft.organization,platform:e.target.value})}>{['SAP S/4HANA','SAP ECC','Other / Custom'].map(v=><option key={v}>{v}</option>)}</select></Field>
            {draft.organization.platform==='Other / Custom' && <Field label="Custom platform label"><input className={inputClass} value={draft.organization.custom_platform} maxLength={80} onChange={e=>update('organization',{...draft.organization,custom_platform:e.target.value})} /></Field>}
            <Field label="SAP system ID"><input className={inputClass} value={draft.organization.system_id} maxLength={20} onChange={e=>update('organization',{...draft.organization,system_id:e.target.value})} /></Field>
            <Field label="SAP client"><input className={inputClass} value={draft.organization.client} maxLength={10} onChange={e=>update('organization',{...draft.organization,client:e.target.value})} /></Field>
            <Field label="System description (optional)"><input className={inputClass} value={draft.organization.description} maxLength={200} onChange={e=>update('organization',{...draft.organization,description:e.target.value})} /></Field>
            <Field label="Footer override (blank uses organization and current year)"><input className={inputClass} value={draft.organization.footer} maxLength={240} onChange={e=>update('organization',{...draft.organization,footer:e.target.value})} /></Field>
          </div>}
          {section===1 && imports && <>
            <Field label="CSV file location"><input className={inputClass} value={draft.data_csv_path} maxLength={4096} onChange={e=>update('data_csv_path',e.target.value)} placeholder="C:/data/synthetic.csv or a permitted network share" /></Field>
            <button className={buttonClass} disabled={!native||busy} onClick={()=>void pickCsv()}>Browse for CSV…</button>
            {config.data?.settings.data_csv_path && <p className="text-xs break-all">Current file: {config.data.settings.data_csv_path}</p>}
            {config.data?.error && <p className="text-amber-600 text-sm">{config.data.error}</p>}
            <div className="flex gap-2 items-end"><Field label="Import profile"><select className={inputClass} value={draft.active_import} onChange={e=>update('active_import',e.target.value)}>{draft.import_profiles.map(p=><option key={p.id} value={p.id}>{p.name} · v{p.version}</option>)}</select></Field>
            <button className={buttonClass} onClick={()=>{const id=freshId('import');update('import_profiles',[...draft.import_profiles,{...structuredClone(imports),id,name:'Custom import',version:1}]);update('active_import',id)}}>Add profile</button></div>
            <Field label="Import profile name"><input className={inputClass} value={imports.name} onChange={e=>editImport({name:e.target.value})} /></Field>
            <div className="grid sm:grid-cols-2 gap-3"><Field label="Delimiter"><select className={inputClass} value={imports.delimiter} onChange={e=>editImport({delimiter:e.target.value})}>{[['auto','Auto detect'],[',','Comma'],[';','Semicolon'],['\t','Tab'],['|','Pipe']].map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></Field>
            <Field label="Encoding"><select className={inputClass} value={imports.encoding} onChange={e=>editImport({encoding:e.target.value})}>{['auto','utf-8-sig','utf-16','cp1252'].map(v=><option key={v}>{v}</option>)}</select></Field></div>
            <button className={buttonClass} disabled={busy||!draft.data_csv_path} onClick={()=>void run(async()=>setColumns((await detectHeaders(draft.data_csv_path,imports)).detected_columns))}>Detect columns</button>
            <p className="text-xs">AGR_NAME is required. Other fields are optional with warnings; preserve parent/effective fields when present. Blank mappings auto-detect standard headers.</p>
            <datalist id="csv-columns">{columns.map(c=><option key={c}>{c}</option>)}</datalist>
            <div className="grid sm:grid-cols-3 gap-3">{fields.map(field=><Field key={field} label={field==='AGR_NAME'?'AGR_NAME (required)':field}><input className={inputClass} list="csv-columns" value={imports.mapping[field]||''} placeholder="Automatic" onChange={e=>{const mapping={...imports.mapping};if(e.target.value)mapping[field]=e.target.value;else delete mapping[field];editImport({mapping})}} /></Field>)}</div>
            <button className={buttonClass} disabled={busy||!draft.data_csv_path} onClick={()=>void run(async()=>{const result=await previewImport(draft.data_csv_path,imports);setImportResult(result);setColumns(result.detected_columns)})}>Preview import</button>
            {importResult && <Result><p><b>{importResult.file_name}</b> · {importResult.parsed_rows} parsed rows · {importResult.unique_roles} composite roles · {importResult.unique_transactions} unique transactions · {importResult.transaction_assignments} assignments</p><p className="text-xs">Assignments count distinct composite/child/parent/effective-role/T-code tuples.</p>
              {importResult.warnings.map(w=><p key={w} className="text-amber-600">{w}</p>)}
              <table className="text-xs"><thead><tr>{fields.map(f=><th key={f} className="p-1 text-left">{f}</th>)}</tr></thead><tbody>{importResult.samples.map((row,i)=><tr key={i}>{fields.map(f=><td key={f} className="p-1">{row[f]}</td>)}</tr>)}</tbody></table></Result>}
          </>}
          {section===2 && <>
            <p className="text-sm">Stable SAP area IDs are separate from customer domains. Disabled areas stay in the data but are hidden from module-filter choices.</p>
            <Field label="Find SAP module or area"><input className={inputClass} value={moduleSearch} onChange={e=>setModuleSearch(e.target.value)} /></Field>
            {(registry.data?.modules||[]).filter(m=>`${m.id} ${m.name} ${m.aliases.join(' ')}`.toLowerCase().includes(moduleSearch.toLowerCase())).map(m=>{const override=draft.module_overrides[m.id]||{enabled:true};const edit=(patch:Partial<typeof override>)=>update('module_overrides',{...draft.module_overrides,[m.id]:{...override,...patch}});return <div key={m.id} className="grid grid-cols-2 sm:grid-cols-5 gap-2 items-center border-b pb-2">
              <span className="text-xs font-semibold">{m.id} · {m.category}{m.parent?` / ${m.parent}`:''}</span>
              <input aria-label={`${m.id} display name`} className={inputClass} placeholder={m.name} value={override.display_name||''} onChange={e=>edit({display_name:e.target.value||null})} />
              <select aria-label={`${m.id} icon`} className={inputClass} value={override.icon||m.icon} onChange={e=>edit({icon:e.target.value})}>{registry.data?.icons.map(i=><option key={i}>{i}</option>)}</select>
              <input type="color" aria-label={`${m.id} color`} value={override.color||m.color} onChange={e=>edit({color:e.target.value})} />
              <label className="text-xs"><input type="checkbox" checked={override.enabled} onChange={e=>edit({enabled:e.target.checked})} /> Enabled</label>
            </div>})}
          </>}
          {section===3 && profile && <>
            <Field label="Classification profile"><select className={inputClass} value={draft.active_classification} onChange={e=>update('active_classification',e.target.value)}>{draft.classification_profiles.map(p=><option key={p.id} value={p.id}>{p.name} · v{p.version}</option>)}</select></Field>
            <button className={buttonClass} onClick={()=>{const id=freshId('classification');update('classification_profiles',[...draft.classification_profiles,{id,name:'Custom profile',version:1,mode:'custom',domains:[],rules:[],overrides:{},fallback_domain:null}]);update('active_classification',id)}}>Add Custom profile</button>
            <p className="text-sm">Generic SAP trusts explicit recognized FUNCTION_KEY evidence. Legacy also preserves prior child-label hints. Custom profiles use your local domains/rules; relationships and transactions are never reclassified.</p>
            {profile.mode==='custom' && <>
              <Field label="Profile name"><input className={inputClass} value={profile.name} onChange={e=>editProfile({name:e.target.value})} /></Field>
              <h3 className="font-bold">Domains</h3>
              {profile.domains.map((d,i)=><div key={i} className="grid sm:grid-cols-4 gap-2"><input aria-label={`Domain ${i+1} ID`} className={inputClass} value={d.id} onChange={e=>editProfile({domains:profile.domains.map((v,j)=>j===i?{...v,id:e.target.value}:v)})} /><input aria-label={`Domain ${i+1} label`} className={inputClass} value={d.label} onChange={e=>editProfile({domains:profile.domains.map((v,j)=>j===i?{...v,label:e.target.value}:v)})} /><select aria-label={`Domain ${i+1} module`} className={inputClass} value={d.module_id||''} onChange={e=>editProfile({domains:profile.domains.map((v,j)=>j===i?{...v,module_id:e.target.value||null}:v)})}><option value="">Unclassified</option>{registry.data?.modules.map(m=><option key={m.id} value={m.id}>{m.id} — {m.name}</option>)}</select><button className={buttonClass} onClick={()=>editProfile({domains:profile.domains.filter((_,j)=>j!==i)})}>Remove domain</button></div>)}
              <button className={buttonClass} onClick={()=>editProfile({domains:[...profile.domains,{id:freshId('domain'),label:'New domain',module_id:null}]})}>Add domain</button>
              <h3 className="font-bold">Rules</h3><p className="text-xs">Lower priority numbers win. Equal-priority matches for different domains are marked ambiguous. Regex is bounded; prefer exact/prefix/contains for clarity.</p>
              {profile.rules.map((rule,i)=><div key={rule.id} className="border rounded-xl p-2 grid sm:grid-cols-5 gap-2">
                <select aria-label={`Rule ${i+1} match`} className={inputClass} value={rule.kind} onChange={e=>editProfile({rules:profile.rules.map((v,j)=>j===i?{...v,kind:e.target.value as typeof rule.kind}:v)})}>{['prefix','exact','contains','regex'].map(k=><option key={k}>{k}</option>)}</select>
                <input aria-label={`Rule ${i+1} pattern`} className={inputClass} value={rule.pattern} onChange={e=>editProfile({rules:profile.rules.map((v,j)=>j===i?{...v,pattern:e.target.value}:v)})} />
                <select aria-label={`Rule ${i+1} domain`} className={inputClass} value={rule.domain_id} onChange={e=>editProfile({rules:profile.rules.map((v,j)=>j===i?{...v,domain_id:e.target.value}:v)})}><option value="">Choose domain</option>{profile.domains.map(d=><option key={d.id} value={d.id}>{d.label}</option>)}</select>
                <input aria-label={`Rule ${i+1} priority`} className={inputClass} type="number" min={0} max={10000} value={rule.priority} onChange={e=>editProfile({rules:profile.rules.map((v,j)=>j===i?{...v,priority:Number(e.target.value)}:v)})} />
                <label className="text-xs"><input type="checkbox" checked={rule.case_sensitive} onChange={e=>editProfile({rules:profile.rules.map((v,j)=>j===i?{...v,case_sensitive:e.target.checked}:v)})} /> Case sensitive</label>
                <button className={buttonClass} onClick={()=>editProfile({rules:profile.rules.filter((_,j)=>j!==i)})}>Remove rule</button>
              </div>)}
              <button className={buttonClass} onClick={()=>editProfile({rules:[...profile.rules,{id:freshId('rule'),kind:'prefix',pattern:'DEMO:',domain_id:profile.domains[0]?.id||'',priority:100,case_sensitive:false}]})}>Add rule</button>
              <Field label="Fallback domain"><select className={inputClass} value={profile.fallback_domain||''} onChange={e=>editProfile({fallback_domain:e.target.value||null})}><option value="">Use explicit module evidence, otherwise Unclassified</option>{profile.domains.map(d=><option key={d.id} value={d.id}>{d.label}</option>)}</select></Field>
              <h3 className="font-bold">Exact role overrides</h3>
              {Object.entries(profile.overrides).map(([name,domain])=><div key={name} className="flex gap-2"><span className="text-sm flex-1">{name}</span><select aria-label={`Override ${name}`} className={inputClass} value={domain} onChange={e=>editProfile({overrides:{...profile.overrides,[name]:e.target.value}})}>{profile.domains.map(d=><option key={d.id} value={d.id}>{d.label}</option>)}</select><button className={buttonClass} onClick={()=>{const overrides={...profile.overrides};delete overrides[name];editProfile({overrides})}}>Remove override</button></div>)}
              <button className={buttonClass} disabled={!testRole||!profile.domains.length} onClick={()=>editProfile({overrides:{...profile.overrides,[testRole]:profile.domains[0].id}})}>Override test role</button>
            </>}
            <Field label="Test an individual role name"><input className={inputClass} value={testRole} maxLength={512} onChange={e=>setTestRole(e.target.value)} /></Field>
            <button className={buttonClass} disabled={busy} onClick={()=>void run(async()=>setClassResult(await previewClassification(profile,testRole)))}>Preview classification</button>
            {classResult && <Result><p>{classResult.total_roles} roles · {classResult.unclassified_roles} unclassified · {classResult.ambiguous_matches} ambiguous · {classResult.changed_roles} changes</p><p>Domain/area counts: {Object.entries(classResult.counts).map(([k,v])=>`${k}: ${v}`).join(' · ')||'No active dataset'}</p><p>Conflicting rules: {classResult.conflicting_rules.length}</p>{classResult.conflicting_rules.map((c,i)=><p key={i}>{c.rule_ids.join(', ')}: {c.reason}</p>)}{classResult.samples.map(r=><p key={r.agr_name}>{r.agr_name} → {r.domain_id||r.module_id}{r.ambiguous?' (ambiguous)':''}{r.changed?' (changed)':''}</p>)}{classResult.test_result && <p>Test role: {String(classResult.test_result.domain_id||classResult.test_result.module_id)}{classResult.test_result.ambiguous?' (ambiguous)':''}</p>}<p className="text-xs">Profile fingerprint: {classResult.profile_fingerprint}</p></Result>}
          </>}
          {section===4 && <>
            <Field label="Theme"><select className={inputClass} value={draft.theme} onChange={e=>update('theme',e.target.value as Configuration['theme'])}>{['system','dark','light'].map(t=><option key={t}>{t}</option>)}</select></Field>
            <p className="text-sm">A custom logo changes only this header, never the Windows icon, README or product identity. Use PNG/JPEG/WebP up to 2 MB and 4096 pixels per side; SVG is rejected.</p>
            <img alt="Header logo preview" src={draft.logo_id ? (logoPreview||logo.data?.data_url||'/sap-lens.png') : '/sap-lens.png'} className="max-w-48 max-h-24 object-contain" onError={e=>{if(!e.currentTarget.src.endsWith('/sap-lens.png'))e.currentTarget.src='/sap-lens.png'}} />
            {logo.isError && <p role="status" className="text-amber-600 text-sm">The saved custom logo is unavailable; SAP Lens uses its default logo.</p>}
            <Field label="Logo file location"><input className={inputClass} value={logoPath} onChange={e=>setLogoPath(e.target.value)} /></Field>
            <button className={buttonClass} disabled={!native||busy||!window.pywebview?.api.choose_logo} onClick={()=>void run(async()=>{const path=await window.pywebview?.api.choose_logo?.(applicationToken());if(path){setLogoPath(path);const result=await apiRequest<{logo_id:string;data_url:string}>('/api/branding/preview','POST',{path});update('logo_id',result.logo_id);setLogoPreview(result.data_url)}})}>Select custom logo…</button>
            <button className={buttonClass} disabled={!logoPath||busy} onClick={()=>void previewLogo(logoPath)}>Preview logo</button>
            <button className={buttonClass} onClick={()=>{update('logo_id',null);setLogoPreview(null)}}>Remove custom logo / restore SAP Lens default</button>
            <p className="text-xs">Previewed files are copied into managed local storage. Apply settings to activate the logo; moving the original will not break it.</p>
          </>}
          {section===5 && <>
            <p>Configuration schema {draft.schema_version} · revision {draft.revision}. Settings and backups live in your per-user SAP Lens application directory.</p>
            <p className="text-sm">Active analysis: {JSON.stringify(config.data?.analysis||{})}</p>
            <button className={buttonClass} disabled={!native||!window.pywebview?.api.open_configuration_folder} onClick={()=>void run(async()=>{await window.pywebview?.api.open_configuration_folder?.(applicationToken())})}>Open configuration folder</button>
            <label className="block text-sm"><input type="checkbox" checked={includePrivate} onChange={e=>setIncludePrivate(e.target.checked)} /> Include private organization details, profiles and branding in export</label>
            <p className="text-xs">Exports exclude CSV data and paths. The default export is redacted; a private export may disclose naming conventions and organization details. Store it securely.</p>
            <button className={buttonClass} disabled={busy} onClick={()=>void exportConfig()}>Export saved configuration</button>
            <Field label="Import configuration package"><input type="file" accept="application/json,.json" disabled={busy} onChange={e=>{const file=e.target.files?.[0];if(file)void run(async()=>{if(file.size>4_000_000)throw Error('Configuration package exceeds 4 MB.');if(!window.confirm('Validate and apply this configuration package? A local backup will be retained.'))return;const payload:unknown=JSON.parse(await file.text());const result=await apiRequest<ConfigurationResponse>('/api/configuration/import','POST',payload);await accepted(result);setMessage('Configuration imported. Your local CSV path is retained.')})}} /></Field>
            <button className={buttonClass} disabled={busy} onClick={()=>void run(async()=>{if(!window.confirm('Reset configuration to generic defaults and unload the dataset? A backup will be kept; source files are never deleted.'))return;await accepted(await apiRequest<ConfigurationResponse>('/api/configuration/reset','POST'));setMessage('Defaults restored. Previous configuration is backed up locally.')})}>Reset to defaults</button>
          </>}
          </>}
        </div>
        <div className="flex items-center gap-2 pt-4 border-t mt-4">
          <button className="bg-purple-800 text-white rounded-lg px-4 py-2 font-semibold disabled:opacity-50" disabled={busy||!draft||config.data?.loading} onClick={()=>draft&&void run(async()=>{await accepted(await saveConfiguration(draft));setOpen(false)})}>{busy?'Working…':section===1?'Save and load CSV':'Apply settings'}</button>
          <button className={buttonClass} disabled={busy} onClick={()=>show(false)}>Cancel</button>
          <span className="text-xs ml-auto" style={{color:'var(--muted)'}}>Changes apply after validation</span>
        </div>
        <Dialog.Close className="absolute right-4 top-4 p-1" aria-label="Close settings" disabled={busy}><X className="w-5 h-5" aria-hidden="true" /></Dialog.Close>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>
}
