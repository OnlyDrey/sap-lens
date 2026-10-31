import { useState, type Ref } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Upload } from 'lucide-react'
import { apiRequest, applicationToken } from '@/api/client'

export function BrowserSourceUpload({ source, onUploaded, disabled=false, fileInput }: {
  source:'roles'|'users'|'employees'|'sod'; onUploaded:(path:string)=>void|Promise<void>; disabled?:boolean; /** Lets Browse CSV open this chooser where native browsing is unavailable. */fileInput?:Ref<HTMLInputElement>
}) {
  const runtime=useQuery({queryKey:['runtime-capabilities'],queryFn:()=>apiRequest<{browser_upload:boolean}>('/api/runtime'),staleTime:Infinity,retry:false})
  const [busy,setBusy]=useState(false),[message,setMessage]=useState(''),[error,setError]=useState('')
  if(!runtime.data?.browser_upload)return null
  const name={roles:'Role Catalogue',users:'User Access',employees:'Employee Directory',sod:'SoD Matrix'}[source]
  return <section className="space-y-2" aria-label={`${name} browser upload`}>
    <label className="ui-field"><span className="flex items-center gap-2"><Upload size={16} aria-hidden="true"/>Upload {name} CSV</span><input ref={fileInput} type="file" accept=".csv,text/csv" disabled={disabled||busy} onChange={async e=>{
      const input=e.currentTarget,file=input.files?.[0];if(!file)return
      setBusy(true);setMessage('');setError('')
      try{
        const maximum=(source==='employees'?50:128)*1024*1024
        if(file.size>maximum)throw Error('CSV exceeds this source’s size limit.')
        const response=await fetch(`/api/server/uploads/${source}`,{method:'POST',headers:{'X-SAP-Lens':applicationToken(),'X-Upload-Filename':encodeURIComponent(file.name),'Content-Type':'text/csv'},body:file,credentials:'same-origin'})
        const result=await response.json()
        if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'CSV upload failed.')
        await onUploaded(result.path);setMessage(`${file.name} selected. Source activation status is shown below; browser uploads use Static mode.`)
      }catch(e){setError(e instanceof Error?e.message:'CSV upload failed.')}finally{input.value='';setBusy(false)}
    }}/></label>
    <p className="text-xs text-[var(--muted)]">Uploads are private import inputs, never dynamic paths on your device. Dynamic sources use files inside the server’s configured source directory.</p>
    {busy&&<p role="status">Uploading CSV…</p>}{message&&<p role="status">{message}</p>}{error&&<p role="alert">{error} Existing imported data is unchanged.</p>}
  </section>
}
