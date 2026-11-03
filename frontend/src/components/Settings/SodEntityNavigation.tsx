import type {ReactNode} from 'react'
import {IdPill} from '@/components/Shared/IdPill'
import {InfoTip} from '@/components/Shared/InfoTip'
import {ArrowLeft,ArrowRight,CornerUpLeft} from 'lucide-react'
import {Button} from '@/components/Shared/Button'
import {Toolbar} from '@/components/Shared/Presentation'
import {apiRequest} from '@/api/client'

export type EntityKind='risk'|'activity'
export interface EntityScope {kind:EntityKind;query?:string;ids?:string[];revision?:number;sourceVersion?:string|null}
export interface EntityLocation {kind:EntityKind;id:string;scope:EntityScope}
export interface EditorNavigation {previous?:()=>void;next?:()=>void;back?:()=>void;position:string;error?:string;onEntity:(kind:EntityKind,id:string)=>void}

/** Keep the originating server filter/sort across pagination; reject mixed revisions. */
export async function filteredEntityIds(scope:EntityScope):Promise<string[]> {
 if(scope.ids)return scope.ids
 const ids:string[]=[];let revision=scope.revision,sourceVersion=scope.sourceVersion
 for(let offset=0;;offset+=100){
  const params=new URLSearchParams(scope.query);params.set('offset',String(offset));params.set('limit','100')
  const result=await apiRequest<{items:({risk_id?:string;activity?:string})[];total:number;revision:number;source_version?:string|null;source?:{version:string|null}}>(`/api/sod/${scope.kind==='risk'?'catalogue':'catalogue-activities'}?${params}`)
  const version=result.source_version??result.source?.version??null
  if(sourceVersion===undefined)sourceVersion=version
  if(version!==sourceVersion)throw Error('The imported SoD source changed. Close and reopen details to navigate the current source.')
  revision??=result.revision
  if(result.revision!==revision)throw Error('The filtered configuration list changed. Close and reopen the details to navigate the current revision.')
  ids.push(...result.items.map(row=>(scope.kind==='risk'?row.risk_id:row.activity)!))
  if(offset+result.items.length>=result.total)return ids
  if(!result.items.length||ids.length>10000)throw Error('The configuration list cannot be navigated safely. Refine the filters and reopen details.')
 }
}

export function EntityNavigation({navigation,request}:{navigation:EditorNavigation;request:(action:()=>void)=>void}) {
 return <><Toolbar aria-label="Entity navigation">
  <Button size="compact" variant="ghost" disabled={!navigation.back} onClick={()=>navigation.back&&request(navigation.back)}><CornerUpLeft size={14} aria-hidden="true"/>Back</Button>
  <Button size="compact" disabled={!navigation.previous} onClick={()=>navigation.previous&&request(navigation.previous)}><ArrowLeft size={14} aria-hidden="true"/>Previous</Button>
  <span className="text-xs text-muted" role="status">{navigation.position}</span>
  <Button size="compact" disabled={!navigation.next} onClick={()=>navigation.next&&request(navigation.next)}>Next<ArrowRight size={14} aria-hidden="true"/></Button>
 </Toolbar>{navigation.error&&<p role="alert">{navigation.error}</p>}</>
}

/** Same compact entity header; provenance and immutable mapping details remain discoverable. */
export function EntityHeader({kind,id,name,color,actions,metadata,children}:{kind:EntityKind;id:string;name?:string;color:string;actions?:ReactNode;metadata?:ReactNode;children?:ReactNode}) {
 return <section className="grid gap-2" aria-label={`Imported ${kind} definition`}>
  <div className="flex flex-wrap items-center justify-between gap-2"><div className="flex min-w-0 flex-wrap items-center gap-2"><IdPill kind={kind} value={id} color={color}/><span className="min-w-0 break-words font-semibold">{name||'Missing display name'}</span></div><div className="flex items-center gap-2">{actions}<InfoTip label="About imported mappings">Identifiers, relationships and transaction mappings come from the imported SoD matrix and cannot be edited here. Business guidance does not change detected conflicts.</InfoTip></div></div>
  {metadata&&<div className="flex flex-wrap items-center gap-2">{metadata}</div>}{children}
 </section>
}
