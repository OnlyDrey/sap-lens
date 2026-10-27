import {useQuery} from '@tanstack/react-query'
import {applicationToken} from '@/api/client'
import {Toggle,Checkbox} from '@/components/Shared/Controls'
import type {Configuration} from '@/api/configuration'

/** Native capability detection; no registry/window APIs in browser or server modes. */
export function DesktopOptions({draft,onChange}:{draft:Configuration;onChange:(value:Configuration)=>void}) {
 const supported=!!window.pywebview?.api.desktop_runtime
 const runtime=useQuery({queryKey:['desktop-runtime'],enabled:supported,refetchInterval:5000,queryFn:()=>window.pywebview!.api.desktop_runtime!(applicationToken())})
 if(!supported||!runtime.data?.windows)return null
 const value=draft.desktop||{close_to_tray:false,run_at_signin:false,start_minimized:false}
 const patch=(update:Partial<typeof value>)=>onChange({...draft,desktop:{...value,...update}})
 return <section className="settings-card space-y-3" aria-label="Windows Desktop background operation">
  <h2 className="settings-subheading">Windows Desktop</h2>
  <Toggle label="Minimize to System Tray on Close" checked={value.close_to_tray} onChange={enabled=>patch({close_to_tray:enabled,...(!enabled?{start_minimized:false}:{})})}/>
  <p className="ui-description">Closing hides the window only when the tray icon and backend are ready. Use Exit SAP Lens in the tray menu to stop the application.</p>
  <Checkbox checked={value.run_at_signin} disabled={!runtime.data.startup_supported&&!value.run_at_signin} onChange={event=>patch({run_at_signin:event.target.checked})}>Start SAP Lens at Windows sign-in</Checkbox>
  {!runtime.data.startup_supported&&<p className="ui-description">Sign-in startup requires the packaged Windows EXE.</p>}
  <Checkbox checked={value.start_minimized} disabled={!value.close_to_tray} onChange={event=>patch({start_minimized:event.target.checked})}>Start minimized to the system tray</Checkbox>
  {runtime.data.warning&&<p role="status">{runtime.data.warning}</p>}
  <p className="ui-description">Apply settings to save these preferences. This is a per-user desktop application, not a Windows Service; it stops at sign-out. Browser access uses the same protected loopback backend.</p>
 </section>
}
