import {RoleIdentifier} from './RoleIdentifier'
import {useViewHistory,userHref} from '@/hooks/useViewHistory'

/** Real route link with independent exact-identifier copy; normal and modified clicks retain browser semantics. */
export function SAPUserLink({username,onOpen}:{username:string;onOpen?:()=>void}){
 const {change}=useViewHistory()
 return <RoleIdentifier value={username} label="SAP username" href={userHref(username)} onOpen={onOpen||(()=>change({page:'users',accessMode:'directory',user:username,userContext:{},detailRole:null,settings:false}))} openLabel={`Open SAP user ${username}`}/>
}
