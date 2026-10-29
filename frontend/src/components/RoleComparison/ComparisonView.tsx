import {useQueries} from '@tanstack/react-query'
import {fetchRoleDetail} from '@/api/client'
import {matchingTransactions} from '@/lib/searchMatching'
import {presentRoleDescription} from '@/lib/rolePresentation'
import {RoleEntryHeader} from '@/components/Shared/RoleMetadata'
import {TransactionFilter,useTransactionFilter} from '@/components/Shared/TransactionFilter'
import {jaccard} from '@/lib/comparisonMetrics'
import { ModuleBadge } from '@/components/Modules/ModuleBadge'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import { TransactionCount } from '@/components/Shared/TransactionCount'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowLeft, Loader2, AlertTriangle, RefreshCw, GitCompare, Share2,
  Lock, X, TrendingDown, TrendingUp, ChevronDown, ChevronRight,
  Code2
} from 'lucide-react'
import { useComparison } from '@/hooks/useComparison'
import { useRoleDetail } from '@/hooks/useRoleDetail'
import type { TCode, SingleRoleInfo, ComparisonRole, PairwiseOverlap, RoleDetail } from '@/api/types'

interface Props { roleNames: string[]; onBack: () => void }

const lbl = (r:ComparisonRole) => presentRoleDescription(r.text,r.function_key?[r.function_key]:[]).description || r.agr_name

function ModLabel({ r, center }: { r: ComparisonRole; center?: boolean }) {
  if (!r.function_key) return null
  return (
    <div className={`flex items-center gap-1.5 ${center ? 'justify-center' : ''}`}>
      <ModuleBadge moduleId={r.function_key} />
    </div>
  )
}

type ComparisonTCode=TCode & {sourceRoles?:string[]}
function TCodeTable({ rows }: { rows: ComparisonTCode[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr style={{ backgroundColor:'var(--surface2)' }}>
          <th
            className="text-left px-4 py-2.5 text-xs font-black uppercase tracking-wider w-40"
            style={{ color:'var(--muted)', borderBottom:'1px solid var(--border)' }}
          >
            T-code
          </th>
          <th
            className="text-left px-4 py-2.5 text-xs font-black uppercase tracking-wider"
            style={{ color:'var(--muted)', borderBottom:'1px solid var(--border)' }}
          >
            Description
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((tc,i) => (
          <tr
            key={tc.tcode}
            style={{ backgroundColor:i%2===1?'var(--surface2)':undefined }}
          >
            <td
              className="px-4 py-2 font-mono text-xs font-bold"
              style={{ color:'var(--accent2)', borderBottom:'1px solid var(--border)' }}
            >
              {tc.tcode}
            </td>
            <td
              className="px-4 py-2 text-sm"
              style={{ color:'var(--text2)', borderBottom:'1px solid var(--border)' }}
            >
              {tc.ttext ?? (
                <span className="italic" style={{ color:'var(--muted)' }}>
                  No description
                </span>
              )}
              {tc.alternate_texts?.filter(text=>text!==tc.ttext).map(text=><p key={text} className="text-xs text-muted">Also described as: {text}</p>)}
              {!!tc.sourceRoles?.length&&<div className="mt-2 flex flex-wrap items-center gap-1 text-xs text-muted">Mapped via catalogue:{tc.sourceRoles.map(name=><RoleIdentifier key={name} value={name}/>)}</div>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** variant tile: shared single role, expands inside its own tile. variant row: exclusive single role as a compact list row. */
function SRRow({sr,parentRoleName,patterns=[],variant='tile',mappedRows}:{sr:SingleRoleInfo;parentRoleName:string;patterns?:string[];variant?:'tile'|'row';mappedRows?:ComparisonTCode[]}) {
 const [expanded,setExpanded]=useState(false),[searchExpanded,setSearchExpanded]=useState(true)
 const key=JSON.stringify(patterns),searching=patterns.length>0
 useEffect(()=>setSearchExpanded(true),[key])
 const open=searching?searchExpanded:expanded
 const {data:detail,isLoading,isError}=useRoleDetail(open?parentRoleName:null)
 const rows=mappedRows||detail?.single_roles.find(row=>row.child_agr===sr.child_agr)?.tcodes||[]
 const visible=matchingTransactions(rows,patterns)
 const Wrapper=variant==='row'?'div':'article'
 return <Wrapper aria-label={`Single role ${sr.child_agr}`} data-expanded={open} className={variant==='row'?'single-role-row ui-list-row min-w-0':'single-role-tile min-w-0 self-start rounded-card border border-line bg-surface'}>
  <div className="flex min-w-0 items-start gap-2 p-3">
   <button type="button" className="role-expand" aria-label={`Expand single role ${sr.child_agr}`} aria-expanded={open} onClick={()=>searching?setSearchExpanded(value=>!value):setExpanded(value=>!value)}>{open?<ChevronDown size={16}/>:<ChevronRight size={16}/>}</button>
   <div className="min-w-0 flex-1"><RoleEntryHeader code={sr.function_key} name={sr.module_name} description={sr.child_agr_text} tcodeCount={sr.tcode_count} identifier={sr.child_agr}>{searching&&<span className="text-xs text-muted">{visible.length} matching transactions</span>}</RoleEntryHeader></div>
  </div>
  {open&&<div role="region" aria-label={`Transactions for ${sr.child_agr}`} tabIndex={0} className="min-w-0 overflow-x-auto border-t border-line">{isLoading?<p role="status" className="p-3 text-sm">Loading transactions…</p>:isError?<p role="alert" className="p-3">Transaction evidence unavailable; close and reopen to retry.</p>:visible.length?<TCodeTable rows={visible}/>:<p className="p-3 text-sm text-muted">{searching?'No matching transactions.':'No transaction mappings supplied.'}</p>}</div>}
 </Wrapper>
}

function PairModal({
  roleA, roleB, labelA, labelB, mode, onClose
}: {
  roleA:string
  roleB:string
  labelA:string
  labelB:string
  mode:'single'|'tcode'
  onClose:()=>void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current!
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    element.showModal()
    return () => { element.close(); if (previous?.isConnected) previous.focus({ preventScroll: true }) }
  }, [])
  const { mutate, data, isPending, isError } = useComparison()
  useEffect(() => { mutate([roleA, roleB]) }, [roleA, roleB, mutate])
  const count = data ? (mode === 'single' ? data.shared_single_roles.length : data.shared_tcodes.length) : null
  return (
    <dialog ref={dialog} aria-label={mode === 'single' ? 'Shared single roles' : 'Shared T-codes'}
      className="comparison-dialog"
      onCancel={event => { event.preventDefault(); onClose() }}
      onClick={event => { if (event.target === event.currentTarget) {
        const box = event.currentTarget.getBoundingClientRect()
        if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) onClose()
      } }}>
          <div
            className="flex items-center justify-between px-5 py-4 flex-shrink-0"
            style={{ backgroundColor:'var(--primary)', color:'var(--on-primary)', borderRadius:'1rem 1rem 0 0' }}
          >
            <div>
              <p className="text-sm font-black text-current">
                {mode === 'single' ? 'Shared single roles' : 'Shared T-codes'}
              </p>
              <p className="text-xs mt-0.5" style={{ color:'var(--on-primary)' }}>
                {labelA} &amp; {labelB}
              </p>
            </div>

            <div className="flex items-center gap-3">
              {count != null && !isPending && (
                <span
                  className="text-xs font-black px-2.5 py-1 rounded-full text-current"
                  style={{ backgroundColor:'var(--success)', color:'var(--on-success)' }}
                >
                  {count} shared
                </span>
              )}

              <button
                aria-label="Close comparison details"
                onClick={onClose}
                className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-white/10 focus:outline-none"
                style={{ color:'var(--on-primary)' }}
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          <div className="comparison-dialog-body">
            {isPending && (
              <div className="flex items-center justify-center py-16">
                <Loader2 className="w-8 h-8 animate-spin" style={{ color:'var(--accent2)' }} />
              </div>
            )}

            {isError && (
              <div className="p-5 text-sm" style={{ color:'var(--error)' }}>
                Failed to load
              </div>
            )}

            {data && !isPending && (
              <div>
                  {mode === 'single'
                    ? data.shared_single_roles.length === 0
                      ? (
                        <div className="py-12 text-center">
                          <p className="text-sm italic" style={{ color:'var(--muted)' }}>
                            No single roles shared
                          </p>
                        </div>
                      )
                      : (
                        <div>
                          {data.shared_single_roles.map(sr => (
                            <SRRow
                              key={sr.child_agr}
                              sr={sr}
                              parentRoleName={roleA}
                            />
                          ))}
                        </div>
                      )
                    : data.shared_tcodes.length === 0
                      ? (
                        <div className="py-12 text-center">
                          <p className="text-sm italic" style={{ color:'var(--muted)' }}>
                            No transactions shared
                          </p>
                        </div>
                      )
                      : <TCodeTable rows={data.shared_tcodes} />
                  }
              </div>
            )}
          </div>
    </dialog>
  )
}

function InsightBar({
  roles, pairwiseSR, pairwiseTC, onPair
}: {
  roles:ComparisonRole[]
  pairwiseSR:PairwiseOverlap[]
  pairwiseTC:PairwiseOverlap[]
  onPair:(a:string,b:string)=>void
}) {
  const ins = useMemo(() => {
    if (!pairwiseSR.length) return null

    const wp = pairwiseSR.map(p => {
      const ra = roles.find(r => r.agr_name === p.role_a)
      const rb = roles.find(r => r.agr_name === p.role_b)

      return {
        ...p,
        pct: jaccard(p.shared_count,ra?.single_role_count??0,rb?.single_role_count??0)
      }
    }).sort((a,b) => b.pct - a.pct || a.role_a.localeCompare(b.role_a) || a.role_b.localeCompare(b.role_b))

    const wpTC = pairwiseTC.map(p => {
      const ra = roles.find(r => r.agr_name === p.role_a)
      const rb = roles.find(r => r.agr_name === p.role_b)

      return {
        ...p,
        pct: jaccard(p.shared_count,ra?.tcode_count??0,rb?.tcode_count??0)
      }
    })

    return {
      avgSR: Math.round(wp.reduce((s,p) => s+p.pct, 0) / wp.length),
      avgTC: Math.round(wpTC.reduce((s,p) => s+p.pct, 0) / wpTC.length),
      most: wp[0],
      least: wp[wp.length-1],
      mostA: roles.find(r => r.agr_name === wp[0].role_a),
      mostB: roles.find(r => r.agr_name === wp[0].role_b),
      leastA: roles.find(r => r.agr_name === wp[wp.length-1].role_a),
      leastB: roles.find(r => r.agr_name === wp[wp.length-1].role_b),
    }
  }, [roles, pairwiseSR, pairwiseTC])

  if (!ins) return null

  return (
    <div
      className="grid grid-cols-2 sm:grid-cols-4 gap-0 rounded-2xl overflow-hidden "
      style={{ backgroundColor:'var(--surface)', border:'1px solid var(--border)' }}
    >
      {[
        {
          label:'Single role overlap',
          value:`${ins.avgSR}%`,
          sub:'mean Jaccard similarity',
          color:'var(--accent2)',
          Icon:<Share2 className="w-4 h-4"/>
        },
        {
          label:'T-code overlap',
          value:`${ins.avgTC}%`,
          sub:'mean mapped T-code Jaccard similarity',
          color:'var(--accent2)',
          Icon:<Code2 className="w-4 h-4"/>
        },
      ].map((item, i) => (
        <div
          key={item.label}
          className="flex items-start gap-3 p-5"
          style={i > 0 ? { borderLeft:'1px solid var(--border)' } : {}}
        >
          <div
            className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
            style={{ backgroundColor:'var(--surface2)', color:item.color }}
          >
            {item.Icon}
          </div>

          <div>
            <p className="text-xs font-black uppercase tracking-wider" style={{ color:'var(--muted)' }}>
              {item.label}
            </p>
            <p className="text-3xl font-black mt-0.5" style={{ color:item.color }}>
              {item.value}
            </p>
            <p className="text-xs mt-0.5" style={{ color:'var(--muted)' }}>
              {item.sub}
            </p>
          </div>
        </div>
      ))}

      <button type="button" aria-label="Inspect most similar roles" onClick={()=>onPair(ins.most.role_a,ins.most.role_b)} className="flex items-start gap-3 p-5 text-left hover:bg-hover" style={{ borderLeft:'1px solid var(--border)' }}>
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
          style={{ backgroundColor:'var(--surface2)' }}
        >
          <TrendingUp className="w-4 h-4" style={{ color:'var(--accent2)' }} />
        </div>

        <div>
          <p className="text-xs font-black uppercase tracking-wider" style={{ color:'var(--muted)' }}>
            Most similar
          </p>
          <p className="text-sm font-bold mt-0.5" style={{ color:'var(--text)' }}>
            {lbl(ins.mostA!)} &amp; {lbl(ins.mostB!)}
          </p>
          <p className="text-xs font-bold mt-0.5" style={{ color:'var(--accent2)' }}>
            {ins.most.shared_count} shared ({ins.most.pct}%)
          </p>
        </div>
      </button>

      <div className="flex items-start gap-3 p-5" style={{ borderLeft:'1px solid var(--border)' }}>
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
          style={{ backgroundColor:'var(--surface2)' }}
        >
          <TrendingDown className="w-4 h-4 text-[var(--info)]" />
        </div>

        <div>
          <p className="text-xs font-black uppercase tracking-wider" style={{ color:'var(--muted)' }}>
            Most distinct
          </p>
          <p className="text-sm font-bold mt-0.5" style={{ color:'var(--text)' }}>
            {lbl(ins.leastA!)} &amp; {lbl(ins.leastB!)}
          </p>
          <p className="text-xs font-bold mt-0.5" style={{ color:'var(--muted)' }}>
            {ins.least.shared_count} shared ({ins.least.pct}%)
          </p>
        </div>
      </div>
    </div>
  )
}

function ExclusiveColumn({role,rows,patterns}:{role:ComparisonRole;rows:SingleRoleInfo[];patterns:string[]}) {
  return (
    <div
      className="comparison-column min-w-0 self-start rounded-card overflow-hidden flex flex-col"
      style={{
        border:'1px solid var(--border)',
        backgroundColor:'var(--surface)'
      }}
    >
      <div
        className="px-4 py-3"
        style={{
          borderBottom:'1px solid var(--border)',
          backgroundColor:'var(--surface2)'
        }}
      >
        <div className="flex items-start justify-between gap-2 mb-2">
          <ModLabel r={role} />
          <TransactionCount count={role.tcode_count} />
        </div>
        <p className="mb-2 text-sm font-black leading-snug" style={{ color:'var(--text)' }}>{lbl(role)}</p>

        <RoleIdentifier value={role.agr_name} moduleId={role.function_key}/>

        <div className="role-comparison-exclusive">
          <span
            className="text-xs font-black px-2 py-0.5 rounded-lg text-current"
            style={{ backgroundColor:'var(--accent2)', color:'var(--on-accent2)' }}
          >
            {role.exclusive_single_roles.length} exclusive
          </span>

          <span className="text-xs" style={{ color:'var(--muted)' }}>
            {role.single_role_count} total
          </span>
        </div>
      </div>

      <div className="flex-1">
        {rows.length === 0
          ? (
            <div className="px-4 py-3 text-center">
              <p className="text-xs italic" style={{ color:'var(--muted)' }}>
                No matching exclusive single roles
              </p>
            </div>
          )
          : (
            <div>
              {rows.map(sr => (
                <SRRow
                  key={sr.child_agr}
                  sr={sr}
                  parentRoleName={role.agr_name}
                  patterns={patterns}
                  variant="row"
                />
              ))}
            </div>
          )}
      </div>
    </div>
  )
}

export function ComparisonView({ roleNames, onBack }: Props) {
  const { mutate, data, isPending, isError, error, reset } = useComparison()

  const [pairModal, setPairModal] = useState<{
    a:string
    b:string
    la:string
    lb:string
    mode:'single'|'tcode'
  }|null>(null)

  const filter=useTransactionFilter(roleNames.join('|'))
  const patterns=filter.deferredCodes,searching=patterns.length>0
  const details=useQueries({queries:roleNames.map(name=>({queryKey:['role',name],queryFn:()=>fetchRoleDetail(name),enabled:searching,staleTime:5*60*1000}))})
  const detailByRole=new Map<string,RoleDetail>(details.flatMap((query,index)=>query.data?[[roleNames[index],query.data] as [string,RoleDetail]]:[]))
  const mappingsLoading=searching&&details.some(query=>query.isPending||query.isFetching)
  const mappingsFailed=searching&&details.some(query=>query.isError)
  // Filter shared components against observations from every selected parent,
  // retaining provenance rather than treating one parent's mapping as complete.
  const sharedTransactions=(row:SingleRoleInfo):ComparisonTCode[]=>{
    const codes=new Map<string,ComparisonTCode>()
    for(const parent of roleNames)for(const tc of detailByRole.get(parent)?.single_roles.find(item=>item.child_agr===row.child_agr)?.tcodes||[]){
      const key=tc.tcode.toUpperCase(),previous=codes.get(key)
      if(previous){previous.sourceRoles=[...new Set([...(previous.sourceRoles||[]),parent])];previous.alternate_texts=[...new Set([...(previous.alternate_texts||[]),...(tc.alternate_texts||[]),...(tc.ttext?[tc.ttext]:[])])].filter(text=>text!==previous.ttext)}
      else codes.set(key,{...tc,sourceRoles:[parent]})
    }
    return [...codes.values()]
  }
  const selectRows=(rows:SingleRoleInfo[],parent?:string)=>searching?rows.filter(row=>matchingTransactions(parent?detailByRole.get(parent)?.single_roles.find(item=>item.child_agr===row.child_agr)?.tcodes||[]:sharedTransactions(row),patterns).length>0):rows

  useEffect(() => {
    if (roleNames.length >= 2) mutate(roleNames)
  }, [roleNames, mutate])

  return (
    <div role="region" aria-label="Role comparison" aria-busy={isPending||filter.settling||mappingsLoading} className="comparison-view flex min-w-0 flex-col gap-5 pb-8">
      <div className="flex items-center gap-4">
        <button
          onClick={onBack}
          className="flex items-center gap-2 text-sm font-bold hover:underline focus:outline-none"
          style={{ color:'var(--accent2)' }}
        >
          <ArrowLeft className="w-4 h-4" /> Back to roles
        </button>

        <div className="flex items-center gap-2">
          <GitCompare className="w-5 h-5" style={{ color:'var(--accent2)' }} />
          <h1 className="text-xl font-black" style={{ color:'var(--text)' }}>
            Comparing <span style={{ color:'var(--accent2)' }}>{roleNames.length}</span> roles
          </h1>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {roleNames.map(n => (
          <div key={n} className="min-w-0 rounded-card border border-line bg-surface p-3">
            <p className="mb-2 text-sm font-semibold text-content">{data?.roles.find(role=>role.agr_name===n)?.text || 'Description unavailable'}</p>
            <RoleIdentifier value={n}/>
          </div>
        ))}
      </div>

      {isPending && (
        <div className="flex flex-col items-center py-20 gap-3">
          <Loader2 className="w-10 h-10 animate-spin" style={{ color:'var(--accent2)' }} />
          <p className="text-sm font-semibold" style={{ color:'var(--muted)' }}>
            Comparing...
          </p>
        </div>
      )}

      {isError && (
        <div
          className="flex gap-3 rounded-2xl p-5"
          style={{
            backgroundColor:'var(--surface)',
            border:'1px solid var(--error)'
          }}
        >
          <AlertTriangle className="w-5 h-5 text-[var(--error)] flex-shrink-0" />

          <div>
            <p className="text-sm font-bold" style={{ color:'var(--error)' }}>
              Comparison failed
            </p>
            <p className="text-sm mt-0.5" style={{ color:'var(--error)' }}>
              {error?.message}
            </p>
            <button
              onClick={() => {
                reset()
                mutate(roleNames)
              }}
              className="mt-2 inline-flex items-center gap-1.5 text-sm hover:underline"
              style={{ color:'var(--error)' }}
            >
              <RefreshCw className="w-3.5 h-3.5" /> Retry
            </button>
          </div>
        </div>
      )}

      {data && !isPending && (
        <>
          <InsightBar
            roles={data.roles}
            pairwiseSR={data.pairwise_single_overlaps}
            pairwiseTC={data.pairwise_overlaps}
            onPair={(a,b)=>setPairModal({a,b,la:lbl(data.roles.find(role=>role.agr_name===a)!),lb:lbl(data.roles.find(role=>role.agr_name===b)!),mode:'single'})}
          />

          <div className="rounded-card bg-surface p-4"><TransactionFilter label="Search comparison transactions" filter={filter}/><p className="mt-2 text-xs text-muted">Exact transaction codes or SAP * patterns. Original comparison totals are unchanged.</p></div>
          {mappingsLoading&&<p role="status">Loading transaction mappings…</p>}
          {mappingsFailed&&<p role="alert">Some role mappings could not be loaded. Clear the filter or retry the role details; incomplete mappings are not proof of absent access.</p>}
          {searching&&!mappingsLoading&&!mappingsFailed&&data.shared_single_roles.every(row=>!selectRows([row]).length)&&data.roles.every(role=>!selectRows(role.exclusive_single_roles,role.agr_name).length)&&<p role="status">No single roles match this transaction filter.</p>}

          <section>
            <div className="flex items-center gap-2 mb-3">
              <Lock className="w-4 h-4" style={{ color:'var(--success)' }} />
              <h2 className="text-base font-black" style={{ color:'var(--text)' }}>
                Shared by all {roleNames.length} roles
              </h2>
              <span
                className="text-xs font-black px-2.5 py-0.5 rounded-full text-current"
                style={{ backgroundColor:'var(--success)', color:'var(--on-success)' }}
              >
                {data.shared_single_roles.length} single role
                {data.shared_single_roles.length !== 1 ? 's' : ''}
              </span>
              <span className="text-xs" style={{ color:'var(--muted)' }}>
                &mdash; common building blocks
              </span>
            </div>

            <div
              className="grid min-w-0 grid-cols-1 items-start gap-3 md:grid-cols-2 xl:grid-cols-3"
            >
              {selectRows(data.shared_single_roles).length === 0
                ? (
                  <div
                    className="px-6 py-8 text-center"
                    style={{ backgroundColor:'var(--surface2)' }}
                  >
                    <p className="text-sm italic" style={{ color:'var(--muted)' }}>
                      No matching shared single roles
                    </p>
                  </div>
                )
                : (
                  <>
                    {selectRows(data.shared_single_roles).map(sr => <SRRow key={sr.child_agr} sr={sr} parentRoleName={roleNames[0]} patterns={patterns} mappedRows={searching?sharedTransactions(sr):undefined}/>)}
                  </>
                )}
            </div>
          </section>

          <section>
            <div className="flex items-baseline gap-3 mb-4">
              <h2 className="text-base font-black" style={{ color:'var(--text)' }}>
                Exclusive single roles per composite
              </h2>
              <span className="text-xs" style={{ color:'var(--muted)' }}>
                building blocks only in that role &mdash; expand to see T-codes
              </span>
            </div>

            {searching&&!mappingsLoading&&data.roles.every(role=>!selectRows(role.exclusive_single_roles,role.agr_name).length)&&<p className="text-sm text-muted">No matching exclusive single roles.</p>}
            <div className="comparison-columns grid min-w-0 grid-cols-1 items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
              {data.roles.filter(role=>!searching||selectRows(role.exclusive_single_roles,role.agr_name).length>0).map(r => (
                <ExclusiveColumn
                  key={r.agr_name}
                  role={r}
                  rows={selectRows(r.exclusive_single_roles,r.agr_name)}
                  patterns={patterns}
                />
              ))}
            </div>
          </section>
        </>
      )}

      {pairModal && (
        <PairModal
          roleA={pairModal.a}
          roleB={pairModal.b}
          labelA={pairModal.la}
          labelB={pairModal.lb}
          mode={pairModal.mode}
          onClose={() => setPairModal(null)}
        />
      )}
    </div>
  )
}