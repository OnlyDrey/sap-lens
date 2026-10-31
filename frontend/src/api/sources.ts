import {apiRequest} from './client'
import type {Configuration,ImportProfile} from './configuration'
import type {RefreshSummary} from '@/components/Shared/RefreshReport'
export type CSVSource='roles'|'users'|'employees'|'sod'
export interface SourceSelection {path:string;revision:number;mode:'static'|'dynamic';profile?:ImportProfile}
export interface SourceActivation {settings:Configuration;refresh:RefreshSummary;source:CSVSource;records:number}
export const selectSource=(source:CSVSource,selection:SourceSelection)=>apiRequest<SourceActivation>(`/api/data-sources/${source}/select`,'POST',selection)
/** Only selected-source fields are adopted. Other unsaved Settings edits survive. */
export function rebaseSourceDraft(draft:Configuration,saved:Configuration,source:CSVSource):Configuration {
 const next={...draft,revision:saved.revision,data_lifecycle:saved.data_lifecycle,source_modes:{roles:'dynamic',users:'dynamic',employees:'static',sod:'static',...draft.source_modes,[source]:saved.source_modes?.[source]||'static'}} as Configuration
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
