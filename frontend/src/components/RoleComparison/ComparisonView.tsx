import {jaccard} from '@/lib/comparisonMetrics'
import { TransactionCount } from '@/components/Shared/TransactionCount'
import { ModuleIcon } from '@/components/Modules/ModuleIcon'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowLeft, Loader2, AlertTriangle, RefreshCw, GitCompare, Share2,
  Lock, X, TrendingDown, TrendingUp, Layers, ChevronDown, ChevronRight,
  Code2
} from 'lucide-react'
import { useComparison } from '@/hooks/useComparison'
import { useRoleDetail } from '@/hooks/useRoleDetail'
import type { TCode, SingleRoleInfo, ComparisonRole, PairwiseOverlap } from '@/api/types'

interface Props { roleNames: string[]; onBack: () => void }

const cleanDesc = (t:string|null) => t ? t.replace(/^[A-Z]{2,3}\s*-\s*/,'').trim() : ''
const lbl = (r:ComparisonRole) => cleanDesc(r.text) || r.agr_name

function ModLabel({ r, center }: { r: ComparisonRole; center?: boolean }) {
  const name = r.module_name ?? r.function_key ?? ''

  if (!name) return null

  return (
    <div className={`flex items-center gap-1.5 ${center ? 'justify-center' : ''}`}>
      <ModuleIcon moduleId={r.function_key} />
      <span
        className="text-xs font-semibold truncate"
        style={{ color:'var(--text2)' }}
      >
        {name}
      </span>
    </div>
  )
}

function TCodeTable({ rows }: { rows: TCode[] }) {
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
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function SRRow({ sr, parentRoleName }: { sr: SingleRoleInfo; parentRoleName: string }) {
  const [open, setOpen] = useState(false)
  const { data: detail, isLoading } = useRoleDetail(open ? parentRoleName : null)
  const tcodes = detail?.single_roles.find(s => s.child_agr === sr.child_agr)?.tcodes ?? []
  const mod = sr.function_key

  return (
    <div style={{ borderBottom:'1px solid var(--border)' }}>
      <div
        className="role-comparison-row"
        style={{
          backgroundColor: open
            ? 'color-mix(in srgb, var(--accent2) 8%, var(--surface))'
            : 'var(--surface)'
        }}
      >
        {mod && mod !== 'UNCLASSIFIED' ? <ModuleIcon moduleId={mod} /> : <Layers size={24} aria-hidden="true" className="shrink-0 text-[var(--accent2)]"/>}

        <button type="button" className="role-expand" aria-label={`Expand single role ${sr.child_agr}`} aria-expanded={open} onClick={() => setOpen(p => !p)}>{open
          ? <ChevronDown className="w-3.5 h-3.5 flex-shrink-0" style={{ color:'var(--accent2)' }} />
          : <ChevronRight className="w-3.5 h-3.5 flex-shrink-0" style={{ color:'var(--muted)' }} />}</button>

        <div className="min-w-0 flex-1">
          {sr.child_agr_text && (
            <p className="text-sm break-words mt-0.5" style={{ color:'var(--muted)' }}>
              {sr.child_agr_text}
            </p>
          )}
          <RoleIdentifier value={sr.child_agr} />
        </div>

        <TransactionCount count={sr.tcode_count}/>
      </div>

      {open && (
        <div style={{ borderTop:'1px solid var(--border)', backgroundColor:'var(--surface2)' }}>
          {isLoading && (
            <div className="flex items-center gap-2 px-4 py-3">
              <Loader2 className="w-4 h-4 animate-spin" style={{ color:'var(--accent2)' }}/>
              <span className="text-xs" style={{ color:'var(--muted)' }}>Loading...</span>
            </div>
          )}

          {!isLoading && tcodes.length === 0 && (
            <p className="px-6 py-3 text-xs italic" style={{ color:'var(--muted)' }}>
              No transactions
            </p>
          )}

          {!isLoading && tcodes.length > 0 && <TCodeTable rows={tcodes} />}
        </div>
      )}
    </div>
  )
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
  roles, pairwiseSR, pairwiseTC
}: {
  roles:ComparisonRole[]
  pairwiseSR:PairwiseOverlap[]
  pairwiseTC:PairwiseOverlap[]
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

      <div className="flex items-start gap-3 p-5" style={{ borderLeft:'1px solid var(--border)' }}>
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
      </div>

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

/** Pair summaries retain the existing comparison API and multi-role semantics. */
function PairSummary({a,b,pair,onCell}:{a:ComparisonRole;b:ComparisonRole;pair:PairwiseOverlap;onCell:(a:string,b:string,la:string,lb:string)=>void}) {
 const [expanded,setExpanded]=useState(false)
 const {mutate,data,isPending,isError}=useComparison()
 return <section className="min-w-0 rounded-card border border-line bg-surface p-3">
  <h3 className="text-sm font-semibold">{lbl(a)} · {lbl(b)}</h3>
  <div className="grid grid-cols-1 gap-3 py-3 sm:grid-cols-3">
   <button className="rounded-control bg-elevated p-3 text-left hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus" onClick={()=>onCell(a.agr_name,b.agr_name,lbl(a),lbl(b))}><strong className="block text-lg">{pair.shared_count}</strong>Shared single roles</button>
   <div className="rounded-control bg-elevated p-3"><strong className="block text-lg">{a.single_role_count-pair.shared_count}</strong>Only {lbl(a)}</div>
   <div className="rounded-control bg-elevated p-3"><strong className="block text-lg">{b.single_role_count-pair.shared_count}</strong>Only {lbl(b)}</div>
  </div>
  <details onToggle={event=>{const open=event.currentTarget.open;setExpanded(open);if(open&&!data&&!isPending)mutate([a.agr_name,b.agr_name])}}>
  <summary className="cursor-pointer text-sm font-semibold">Inspect single roles for {lbl(a)} · {lbl(b)}</summary>
  {expanded&&isPending&&<p role="status">Loading single-role evidence…</p>}
  {isError&&<p role="alert">Comparison evidence could not be loaded. <button onClick={()=>mutate([a.agr_name,b.agr_name])}>Retry</button></p>}
  {data&&<div className="grid min-w-0 gap-3 lg:grid-cols-3">{[{title:'Shared single roles',rows:data.shared_single_roles,parent:a.agr_name},...data.roles.map(role=>({title:`Only ${lbl(role)}`,rows:role.exclusive_single_roles,parent:role.agr_name}))].map(group=><section key={group.title} className="min-w-0"><h3 className="mb-2 text-sm font-semibold">{group.title}</h3>{group.rows.length?group.rows.map(sr=><SRRow key={sr.child_agr} sr={sr} parentRoleName={group.parent}/>):<p className="text-sm text-muted">No matching single roles.</p>}</section>)}</div>}
 </details></section>
}
function SingleRoleOverlap({roles,pairwise,onCell}:{roles:ComparisonRole[];pairwise:PairwiseOverlap[];onCell:(a:string,b:string,la:string,lb:string)=>void}) {
 return <section aria-label="Single role overlap" className="grid min-w-0 gap-3"><h2 className="text-base font-semibold">Single role overlap</h2><p className="text-sm text-muted">Inspect shared and exclusive building blocks for each pair. Transaction overlap is separate evidence; neither establishes effective authorization.</p>{pairwise.map(pair=>{const a=roles.find(role=>role.agr_name===pair.role_a),b=roles.find(role=>role.agr_name===pair.role_b);return a&&b?<PairSummary key={`${pair.role_a}|${pair.role_b}`} a={a} b={b} pair={pair} onCell={onCell}/>:null})}</section>
}

function ExclusiveColumn({ role }: { role: ComparisonRole }) {
  return (
    <div
      className="comparison-column min-w-0 rounded-2xl overflow-hidden  flex flex-col"
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
          <div className="min-w-0">
            <ModLabel r={role} />
            <p
              className="text-sm font-black leading-snug mt-1.5"
              style={{ color:'var(--text)' }}
            >
              {lbl(role)}
            </p>
          </div>
        </div>

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
        {role.exclusive_single_roles.length === 0
          ? (
            <div className="px-4 py-3 text-center">
              <p className="text-xs italic" style={{ color:'var(--muted)' }}>
                No exclusive single roles
              </p>
            </div>
          )
          : (
            <div>
              {role.exclusive_single_roles.map(sr => (
                <SRRow
                  key={sr.child_agr}
                  sr={sr}
                  parentRoleName={role.agr_name}
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

  useEffect(() => {
    if (roleNames.length >= 2) mutate(roleNames)
  }, [roleNames, mutate])

  return (
    <div className="comparison-view flex flex-col gap-8 pb-8">
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
          />

          <SingleRoleOverlap
            roles={data.roles}
            pairwise={data.pairwise_single_overlaps}
            onCell={(a,b,la,lb) => setPairModal({
              a,b,la,lb,mode:'single'
            })}
          />

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
              className="rounded-2xl overflow-hidden "
              style={{ border:'1px solid var(--border)' }}
            >
              {data.shared_single_roles.length === 0
                ? (
                  <div
                    className="px-6 py-8 text-center"
                    style={{ backgroundColor:'var(--surface2)' }}
                  >
                    <p className="text-sm italic" style={{ color:'var(--muted)' }}>
                      No single roles common to all selected composites
                    </p>
                  </div>
                )
                : (
                  <div>
                    {data.shared_single_roles.map(sr => <SRRow key={sr.child_agr} sr={sr} parentRoleName={roleNames[0]}/>)}
                  </div>
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

            <div className="comparison-columns">
              {data.roles.map(r => (
                <ExclusiveColumn
                  key={r.agr_name}
                  role={r}
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