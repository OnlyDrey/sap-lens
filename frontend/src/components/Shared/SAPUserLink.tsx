import type {ButtonHTMLAttributes} from 'react'
import {PanelRightOpen} from 'lucide-react'
import {RoleIdentifier} from './RoleIdentifier'
import {Tooltip} from './Button'
import {useViewHistory,userHref} from '@/hooks/useViewHistory'
import {useSodReviewAction} from '@/hooks/useSodReviewNavigation'

/** Real user route, exact copy and optional shared SoD review capability. */
export function SAPUserLink({username,onOpen,reviewSupported=true,routeLink=true,copyLabel='SAP username',openButtonProps,openLabel=`Open SAP user ${username}`}:{username:string;onOpen?:()=>void;reviewSupported?:boolean;routeLink?:boolean;openLabel?:string;copyLabel?:string;openButtonProps?:ButtonHTMLAttributes<HTMLButtonElement>&{'data-user'?:string}}){
 const {change}=useViewHistory(), review=useSodReviewAction(username,reviewSupported)
 const openUser=()=>{if(onOpen){change({sodSubject:null});onOpen()}else change({page:'users',accessMode:'directory',user:username,userContext:{},detailRole:null,settings:false,sodSubject:null})}
 return <RoleIdentifier separateOpenAction value={username} label={copyLabel} href={routeLink?userHref(username):undefined} onOpen={openUser} openLabel={openLabel} openButtonProps={{'data-user':username,...openButtonProps}}
  action={review&&<Tooltip label="Open in SoD Review"><button type="button" aria-label={`Open ${username} in SoD Review`} aria-pressed={review.active} className="inline-flex min-h-[var(--copy-hit-size)] min-w-[var(--copy-hit-size)] items-center justify-center " onClick={event=>{event.stopPropagation();review.open()}}><PanelRightOpen size={14} aria-hidden="true"/></button></Tooltip>}/>
}
