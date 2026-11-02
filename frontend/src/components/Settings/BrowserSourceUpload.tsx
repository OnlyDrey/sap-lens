import { useState, type RefObject } from 'react'
import { Button } from '@/components/Shared/Button'
import { Upload } from 'lucide-react'

/** The shared application-data owner performs upload, validation, activation and cache synchronization. */
export function BrowserSourceUpload({ source, onUpload, disabled=false, fileInput }: {
  source:'roles'|'users'|'employees'|'sod'; onUpload:(file:File)=>Promise<void>; disabled?:boolean; fileInput:RefObject<HTMLInputElement>
}) {
  const [busy,setBusy]=useState(false),[error,setError]=useState('')
  const name={roles:'Role Catalogue',users:'User Access',employees:'Employee Directory',sod:'SoD Matrix'}[source]
  return <section className="space-y-2" aria-label={`${name} browser upload`}>
    <Button loading={busy} disabled={disabled} onClick={()=>fileInput.current?.click()}><Upload size={16} aria-hidden="true"/>Browse / Upload file</Button>
    <label className="sr-only"><span>Upload {name} CSV</span><input ref={fileInput} type="file" accept=".csv,text/csv" disabled={disabled||busy} onChange={async event=>{
      const input=event.currentTarget,file=input.files?.[0];if(!file)return
      setBusy(true);setError('')
      try{
        const maximum=(source==='employees'?50:128)*1024*1024
        if(!file.size||file.size>maximum||!file.name.toLowerCase().endsWith('.csv'))throw Error('Choose a non-empty CSV within this source’s size limit.')
        await onUpload(file)
      }catch(cause){setError(cause instanceof Error?cause.message:'CSV upload failed. Existing imported data is unchanged.')}
      finally{input.value='';setBusy(false)}
    }}/></label>
    <p className="ui-description"><Upload size={14} className="inline" aria-hidden="true"/> Browser uploads use Static mode. No server path is required; active data changes only after complete validation.</p>
    {busy&&<p role="status">Uploading, validating and importing CSV…</p>}{error&&<p role="alert">{error}</p>}
  </section>
}
