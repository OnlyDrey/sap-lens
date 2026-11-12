import {apiRequest,applicationHeaders} from './client'
import type {Configuration,ImportProfile} from './configuration'
import type {RefreshSummary} from '@/components/Shared/RefreshReport'
export type CSVSource='roles'|'users'|'employees'|'sod'
export interface SourceSelection {path:string;revision:number;mode:'static'|'dynamic';profile?:ImportProfile;confirm_anomalies?:boolean}
export interface ImportAnomaly {rule:'drop'|'group_missing';metric:string;old:number;new:number;message:string;percent?:number;group?:string}
/** A valid but suspicious replacement was staged and reported, not activated; it needs explicit confirmation. */
export interface HeldImport {code:'import_needs_confirmation';source:CSVSource;message:string;anomalies:ImportAnomaly[];old:Record<string,number>;new:Record<string,number>}
export const heldImport=(error:unknown):HeldImport|null=>{const detail=(error as {detail?:unknown}|null)?.detail as Partial<HeldImport>|undefined;return detail&&typeof detail==='object'&&detail.code==='import_needs_confirmation'?detail as HeldImport:null}
export interface SourceActivation {settings:Configuration;refresh:RefreshSummary;source:CSVSource;records:number;file_name?:string}
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

/** Multipart upload activates through the same backend selection service, never a browser filesystem path. */
export async function uploadSource(source:CSVSource,selection:SourceSelection,file:File):Promise<SourceActivation> {
 const body=new FormData();body.append('file',file);body.append('revision',String(selection.revision))
 if(selection.profile)body.append('profile',JSON.stringify(selection.profile))
 if(selection.confirm_anomalies)body.append('confirm_anomalies','true')
 const response=await fetch(`/api/server/uploads/${source}/activate`,{method:'POST',headers:{...applicationHeaders()},body,credentials:'same-origin'})
 const data=await response.json()
 if(!response.ok){const failure=Error(typeof data.detail==='string'?data.detail:data.detail?.message??'CSV upload or validation failed. Previous data is retained.') as Error&{detail?:unknown};failure.detail=data.detail;throw failure}
 return data as SourceActivation
}
