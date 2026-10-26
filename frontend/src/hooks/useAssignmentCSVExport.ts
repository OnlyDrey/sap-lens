import {useEffect,useRef,useState} from 'react'
import {applicationToken} from '@/api/client'
type Filters=Record<string,string|number|boolean|string[]>
/** The server owns selection and one snapshot/day. The browser owns cancellation/save. */
export function useAssignmentCSVExport(view:'users'|'releases',filters:Filters,revision?:string,asOf?:string) {
 const key=JSON.stringify([view,filters,revision,asOf]),current=useRef(key),controller=useRef<AbortController|null>(null)
 current.current=key
 const [busy,setBusy]=useState(false),[message,setMessage]=useState(''),[failed,setFailed]=useState(false)
 useEffect(()=>{setMessage('');return()=>controller.current?.abort()},[key])
 const download=async()=>{
  if(controller.current)return
  const active=new AbortController(),started=key;controller.current=active;setBusy(true);setMessage('');setFailed(false)
  try {
   const query=new URLSearchParams(Object.entries(filters).flatMap(([name,value])=>Array.isArray(value)?value.map(item=>[name,item]):[[name,String(value)]]))
   const response=await fetch(`/api/access/exports/${view}?${query}`,{headers:{'X-SAP-Lens':applicationToken()},cache:'no-store',signal:active.signal})
   if(!response.ok)throw Error('Assignment export could not be created. Refresh the view and check source availability.')
   if(revision&&response.headers.get('X-SAP-Lens-Data-Revision')!==revision)throw Error('Source data changed. Refresh before exporting.')
   if(asOf&&response.headers.get('X-SAP-Lens-As-Of')!==asOf)throw Error('Assignment validity date changed. Refresh before exporting.')
   const filename=response.headers.get('Content-Disposition')?.match(/filename="(sap-lens-(?:user-directory|release-roles)-review-\d{4}-\d{2}-\d{2}\.csv)"/)?.[1]
   if(!filename||!response.headers.get('Content-Type')?.startsWith('text/csv'))throw Error('Assignment export response is invalid.')
   const reader=response.body?.getReader();if(!reader)throw Error('Export stream is unavailable.')
   const decoder=new TextDecoder('utf-8',{fatal:true}),parts:string[]=[];let bytes=0
   try {while(true){const {value,done}=await reader.read();if(done)break;bytes+=value.byteLength;if(bytes>32*1024*1024){await reader.cancel();throw Error('Export exceeds 32 MiB. Narrow the user or release filters.')}parts.push(decoder.decode(value,{stream:true}))}parts.push(decoder.decode())}finally{reader.releaseLock()}
   if(current.current!==started||active.signal.aborted)throw Error('Export cancelled because filters or source data changed.')
   const content='\ufeff'+parts.join('').replace(/^\ufeff/,'')
   let saved=true
   if(window.pywebview){if(!window.pywebview.api.save_user_access_csv)throw Error('Update the desktop application for assignment export.');saved=await window.pywebview.api.save_user_access_csv(applicationToken(),filename,content)}
   else{const url=URL.createObjectURL(new Blob([content],{type:'text/csv;charset=utf-8'})),link=document.createElement('a');link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
   if(current.current===started)setMessage(saved?`${Number(response.headers.get('X-SAP-Lens-Assignment-Count')||0).toLocaleString()} assignments exported.`:'Export cancelled.')
  }catch(error){if(current.current===started){setFailed(true);setMessage(active.signal.aborted?'Export cancelled because the view changed.':error instanceof Error?error.message:'Export failed.')}}
  finally{if(controller.current===active){controller.current=null;setBusy(false)}}
 }
 return {busy,message,failed,download}
}
