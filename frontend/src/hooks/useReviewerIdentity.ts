import {useQuery,useQueryClient} from '@tanstack/react-query'
import {useState} from 'react'
import {apiRequest} from '@/api/client'
import {useAuthentication} from '@/components/Auth/Authentication'

export interface LocalReviewer {version:1;revision:number;identity:{id:string;username:string;display_name:string;provenance:'desktop-local'}}
export function useReviewerIdentity(){
 const auth=useAuthentication()
 const query=useQuery({queryKey:['local-reviewer-profile'],enabled:!auth.session,queryFn:()=>apiRequest<LocalReviewer>('/api/reviewer-profile')})
 return {name:auth.user?.username||query.data?.identity.display_name||'',displayName:auth.user?.display_name||query.data?.identity.display_name||'',authenticated:auth.session,canReview:auth.canReview&&(auth.session||!!query.data),retry:()=>query.refetch(),loading:!auth.session&&query.isLoading,error:query.error,local:query.data}
}
export function useReviewerName(initial:string|(()=>string)='') {
 const identity=useReviewerIdentity(),[fallback,setFallback]=useState(initial)
 return [identity.name||fallback,setFallback,identity] as const
}
export function useSaveLocalReviewer(){
 const qc=useQueryClient()
 return async(display_name:string,expected_revision:number)=>{
  const next=await apiRequest<LocalReviewer>('/api/reviewer-profile','POST',{display_name,expected_revision})
  qc.setQueryData(['local-reviewer-profile'],next)
 }
}
