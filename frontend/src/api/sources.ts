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
export {rebaseSourceDraft} from '@/lib/sourceDraft'

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
