import type {Configuration} from '@/api/configuration'
import type {CSVSource} from '@/api/sources'
/** Only selected-source fields are adopted. Other unsaved Settings edits survive. */
export function rebaseSourceDraft(draft:Configuration,saved:Configuration,source:CSVSource):Configuration {
 // Keep the saved key order (the server sorts keys): Settings compares draft and saved as JSON text, so a reordered object would read as an
 // unsaved change after every activation. Unsaved modes of other sources survive; the activated source takes its saved mode.
 const modes:Record<string,string>={...saved.source_modes}
 for(const [key,value] of Object.entries({roles:'dynamic',users:'dynamic',employees:'static',sod:'static'}))if(!(key in modes))modes[key]=value
 for(const [key,value] of Object.entries(draft.source_modes??{}))if(key!==source)modes[key]=value
 modes[source]=saved.source_modes?.[source]||'static'
 const next={...draft,revision:saved.revision,data_lifecycle:saved.data_lifecycle,source_modes:modes} as Configuration
 if(source==='sod'){next.sod_csv_path=saved.sod_csv_path;next.sod_import=saved.sod_import??draft.sod_import}
 else if(source==='employees'){next.employee_csv_path=saved.employee_csv_path;next.employee_snapshot_id=saved.employee_snapshot_id}
 else if(source==='roles'){
  next.data_csv_path=saved.data_csv_path;next.active_import=saved.active_import
  next.import_profiles=draft.import_profiles.map(profile=>profile.id===saved.active_import?saved.import_profiles.find(p=>p.id===profile.id)!:profile)
 }else{
  next.user_csv_path=saved.user_csv_path;next.active_user_import=saved.active_user_import
  next.user_import_profiles=draft.user_import_profiles.map(profile=>profile.id===saved.active_user_import?saved.user_import_profiles.find(p=>p.id===profile.id)!:profile)
 }
 return next
}

