import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest } from '@/api/client'
import { sodPost, type OverviewAssignment, type Subject } from '@/api/sod'
import { invalidateSod } from './SodShared'

export const QUICK_RATIONALE = 'Reviewed in Role Assignment Review'
const reviewerKey = 'sap-lens-sod-reviewer'
const rememberedReviewer = () => { try { return sessionStorage.getItem(reviewerKey) || '' } catch { return '' } }

/** The one-click Role Assignment Review decision (Investigate, Keep, Remove), shared by the review panel and the Role Evidence modal.
 *  `params` is the subject query of the user (the cache key `['sod-subject', params]`). Decisions are saved through /api/sod/decisions/assignment,
 *  one assignment at a time, and a row changes only after the server confirmed it. */
export function useAssignmentQuickReview(user: string, params: URLSearchParams, data: Subject | undefined) {
  const qc = useQueryClient()
  const [quickReviewer, setQuickReviewer] = useState(rememberedReviewer)
  const [quickRationale, setQuickRationale] = useState('')
  const [quickBusy, setQuickBusy] = useState<Map<string, string>>(new Map())
  const [quickError, setQuickError] = useState('')
  const runtime = useQuery({ queryKey: ['review-runtime-identity'], queryFn: () => apiRequest<{ username: string; role: string }>('/api/runtime'), retry: false })
  const authenticated = !!runtime.data?.username
  const reviewer = runtime.data?.username || quickReviewer
  const item = (key: string, ref: string, version: string) => ({ key, user, ref, evidence_version: version })
  const queue = useRef<Promise<void>>(Promise.resolve())
  const pendingRows=useRef(new Set<string>())
  const quickDecide = (row: OverviewAssignment, decision: 'Keep' | 'Remove' | 'Investigate') => {
    if(pendingRows.current.has(row.id))return
    setQuickError('')
    if (!reviewer.trim()) { setQuickError('Enter a reviewer name above before recording a decision. It is self-reported and stored with each decision.'); return }
    pendingRows.current.add(row.id)
    setQuickBusy(previous=>new Map(previous).set(row.id,decision))
    const savedReviewer = reviewer.trim(), justification = quickRationale.trim() || QUICK_RATIONALE
    const save = async () => {
      let confirmed=false
      try {
        for (let attempt = 0; attempt < 2; attempt++) {
          const current = qc.getQueryData<Subject>(['sod-subject', params.toString()]) ?? data
          if (!current) return
          try {
            const recorded=await sodPost<{revision:number;confirmed_assignments?:Record<string,Pick<OverviewAssignment,'decision'|'event'|'decision_summary'|'review_coverage'>>}>('/api/sod/decisions/assignment', { context: current.context, expected_revision: current.revision, expected_generation: current.generation, items: [item(row.id, row.role, row.evidence_version)],
              decision, reviewer:savedReviewer, approver: '', justification, controls: '', expires: null })
            const patch=recorded.confirmed_assignments?.[row.id]
            confirmed=!!patch
            qc.setQueryData<Subject>(['sod-subject',params.toString()],previous=>previous&&previous.generation===current.generation&&previous.revision<=recorded.revision?{...previous,revision:recorded.revision,overview:{...previous.overview,assignments:previous.overview.assignments.map(item=>item.id===row.id&&patch?{...item,...patch}:item)}}:previous)
            break
          } catch (cause) {
            // Another save moved the shared revision: reload it once and retry this one assignment.
            if (attempt === 0 && cause instanceof Error && /decisions changed/i.test(cause.message)) {
              await invalidateSod(qc,['sod-subject',params.toString()])
              const fresh=qc.getQueryData<Subject>(['sod-subject',params.toString()])?.overview.assignments.find(item=>item.id===row.id)
              if(!fresh||fresh.evidence_version!==row.evidence_version||fresh.event?.event_id!==row.event?.event_id){cause.message='This assignment changed in another session. Review its current evidence and decision before choosing again.';throw cause}
              continue
            }
            throw cause
          }
        }
        try { sessionStorage.setItem(reviewerKey, savedReviewer) } catch { /* optional convenience */ }
        if(confirmed)void invalidateSod(qc,['sod-subject',params.toString()]).catch(()=>{})
        else await invalidateSod(qc,['sod-subject',params.toString()])
      } catch (cause) {
        setQuickError(`${decision === 'Keep' ? 'Keep' : decision === 'Investigate' ? 'Investigate' : 'Removal recommendation'} for ${row.role} was not saved. ${cause instanceof Error ? cause.message : 'Try again.'}`)
      } finally {
        pendingRows.current.delete(row.id)
        setQuickBusy(previous=>{const next=new Map(previous);next.delete(row.id);return next})
      }
    }
    queue.current = queue.current.then(save)
  }
  return { reviewer, authenticated, setQuickReviewer, quickRationale, setQuickRationale, quickBusy, quickError, setQuickError, quickDecide }
}
