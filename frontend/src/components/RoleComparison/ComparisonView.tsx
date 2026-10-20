import { onColor } from '@/lib/theme'
import { useEffect, useMemo, useState } from 'react'
import {
  ArrowLeft, Loader2, AlertTriangle, RefreshCw, GitCompare, Share2,
  Lock, X, TrendingDown, TrendingUp, Layers, ChevronDown, ChevronRight,
  Hash, Zap
} from 'lucide-react'
import * as ScrollArea from '@radix-ui/react-scroll-area'
import { useModuleVisual } from '@/components/Modules/ModuleRegistry'
import { useComparison } from '@/hooks/useComparison'
import { useRoleDetail } from '@/hooks/useRoleDetail'
import type { TCode, SingleRoleInfo, ComparisonRole, PairwiseOverlap } from '@/api/types'

interface Props { roleNames: string[]; onBack: () => void }

const cleanDesc = (t:string|null) => t ? t.replace(/^[A-Z]{2,3}\s*-\s*/,'').trim() : ''
const shortAgr = (name:string) => name
const lbl = (r:ComparisonRole) => cleanDesc(r.text) || r.agr_name

function ModLabel({ r, center }: { r: ComparisonRole; center?: boolean }) {
  const {Icon,color} = useModuleVisual(r.function_key)
  const name = r.module_name ?? r.function_key ?? ''

  if (!name) return null

  return (
    <div className={`flex items-center gap-1.5 ${center ? 'justify-center' : ''}`}>
      <div
        className="w-5 h-5 rounded flex items-center justify-center flex-shrink-0"
        style={{ backgroundColor:color, color:onColor(color) }}
      >
        {Icon
          ? <Icon className="w-3 h-3 text-current" />
          : <span className="text-[8px] text-current font-black">{r.function_key}</span>}
      </div>
      <span
        className="text-[10px] font-semibold truncate"
        style={{ color:'var(--text2)' }}
      >
        {name}
      </span>
    </div>
  )
}

function cellBg(count: number, max: number): string {
  if (count === 0 || max === 0) return 'transparent'
  const t = Math.sqrt(count / max)
  if (t < 0.15) return 'color-mix(in srgb, var(--accent) 18%, transparent)'
  if (t < 0.35) return 'color-mix(in srgb, var(--accent) 35%, transparent)'
  if (t < 0.55) return 'color-mix(in srgb, var(--accent) 54%, transparent)'
  if (t < 0.75) return 'color-mix(in srgb, var(--accent) 72%, transparent)'
  return 'color-mix(in srgb, var(--accent) 90%, transparent)'
}

function TCodeTable({ rows }: { rows: TCode[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr style={{ backgroundColor:'var(--surface2)' }}>
          <th
            className="text-left px-4 py-2.5 text-[10px] font-black uppercase tracking-wider w-40"
            style={{ color:'var(--muted)', borderBottom:'1px solid var(--border)' }}
          >
            T-code
          </th>
          <th
            className="text-left px-4 py-2.5 text-[10px] font-black uppercase tracking-wider"
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
              className="px-4 py-2 text-xs"
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
  const {Icon,color} = useModuleVisual(mod)

  return (
    <div style={{ borderBottom:'1px solid var(--border)' }}>
      <button
        onClick={() => setOpen(p => !p)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:opacity-90 focus:outline-none transition-colors"
        style={{
          backgroundColor: open
            ? 'color-mix(in srgb, var(--accent2) 8%, var(--surface))'
            : 'var(--surface)'
        }}
      >
        <div
          className="w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0"
          style={{ backgroundColor:color, color:onColor(color) }}
        >
          {Icon
            ? <Icon className="w-3.5 h-3.5 text-current" />
            : <span className="text-[8px] font-black text-current">{mod ?? '?'}</span>}
        </div>

        {open
          ? <ChevronDown className="w-3.5 h-3.5 flex-shrink-0" style={{ color:'var(--accent2)' }} />
          : <ChevronRight className="w-3.5 h-3.5 flex-shrink-0" style={{ color:'var(--muted)' }} />}

        <div className="min-w-0 flex-1">
          <p className="font-mono text-xs font-bold truncate" style={{ color:'var(--text)' }}>
            {sr.child_agr}
          </p>
          {sr.child_agr_text && (
            <p className="text-[11px] truncate mt-0.5" style={{ color:'var(--muted)' }}>
              {sr.child_agr_text}
            </p>
          )}
        </div>

        <div
          className="flex items-center gap-1 px-2.5 py-1 rounded-lg flex-shrink-0"
          style={{ backgroundColor:'color-mix(in srgb, var(--accent) 12%, transparent)' }}
        >
          <Zap className="w-3 h-3" style={{ color:'var(--accent2)' }} />
          <span className="text-[11px] font-black tabular-nums" style={{ color:'var(--accent2)' }}>
            {sr.tcode_count}
          </span>
        </div>
      </button>

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
              No T-codes
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
  const { mutate, data, isPending, isError } = useComparison()

  useEffect(() => {
    mutate([roleA, roleB])
  }, [roleA, roleB, mutate])

  const count = mode === 'single'
    ? data?.shared_single_roles.length
    : data?.shared_tcodes.length

  return (
    <>
      <div
        className="fixed inset-0 z-50"
        style={{ backgroundColor:'rgba(0,0,0,0.65)' }}
        onClick={onClose}
      />

      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div
          className="w-full max-w-2xl rounded-2xl shadow-2xl flex flex-col pointer-events-auto"
          style={{
            backgroundColor:'var(--surface)',
            border:'1px solid var(--border)',
            maxHeight:'80vh'
          }}
        >
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
                onClick={onClose}
                className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-white/10 focus:outline-none"
                style={{ color:'var(--on-primary)' }}
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-hidden">
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
              <ScrollArea.Root>
                <ScrollArea.Viewport
                  className="w-full"
                  style={{ maxHeight:'calc(80vh - 80px)' }}
                >
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
                            No T-codes shared
                          </p>
                        </div>
                      )
                      : <TCodeTable rows={data.shared_tcodes} />
                  }
                </ScrollArea.Viewport>

                <ScrollArea.Scrollbar
                  orientation="vertical"
                  className="flex select-none touch-none p-0.5 w-2"
                  style={{ backgroundColor:'var(--surface2)' }}
                >
                  <ScrollArea.Thumb
                    className="flex-1 rounded-full"
                    style={{ backgroundColor:'var(--accent2)', color:'var(--on-accent2)' }}
                  />
                </ScrollArea.Scrollbar>
              </ScrollArea.Root>
            )}
          </div>
        </div>
      </div>
    </>
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
        pct: Math.round(
          (p.shared_count / Math.min(
            ra?.single_role_count ?? 1,
            rb?.single_role_count ?? 1
          )) * 100
        )
      }
    }).sort((a,b) => b.pct - a.pct)

    const wpTC = pairwiseTC.map(p => {
      const ra = roles.find(r => r.agr_name === p.role_a)
      const rb = roles.find(r => r.agr_name === p.role_b)

      return {
        ...p,
        pct: Math.round(
          (p.shared_count / Math.min(
            ra?.tcode_count ?? 1,
            rb?.tcode_count ?? 1
          )) * 100
        )
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
      className="grid grid-cols-2 sm:grid-cols-4 gap-0 rounded-2xl overflow-hidden shadow-sm"
      style={{ backgroundColor:'var(--surface)', border:'1px solid var(--border)' }}
    >
      {[
        {
          label:'Single role overlap',
          value:`${ins.avgSR}%`,
          sub:'structural similarity',
          color:'var(--accent2)',
          Icon:<Share2 className="w-4 h-4"/>
        },
        {
          label:'T-code overlap',
          value:`${ins.avgTC}%`,
          sub:'access similarity',
          color:'var(--accent2)',
          Icon:<Hash className="w-4 h-4"/>
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
            <p className="text-[10px] font-black uppercase tracking-wider" style={{ color:'var(--muted)' }}>
              {item.label}
            </p>
            <p className="text-3xl font-black mt-0.5" style={{ color:item.color }}>
              {item.value}
            </p>
            <p className="text-[10px] mt-0.5" style={{ color:'var(--muted)' }}>
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
          <p className="text-[10px] font-black uppercase tracking-wider" style={{ color:'var(--muted)' }}>
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
          <p className="text-[10px] font-black uppercase tracking-wider" style={{ color:'var(--muted)' }}>
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

function SRMatrix({
  roles, pairwise, onCell
}: {
  roles:ComparisonRole[]
  pairwise:PairwiseOverlap[]
  onCell:(a:string,b:string,la:string,lb:string)=>void
}) {
  const lookup = new Map<string,number>()

  for (const p of pairwise) {
    lookup.set(`${p.role_a}|||${p.role_b}`, p.shared_count)
    lookup.set(`${p.role_b}|||${p.role_a}`, p.shared_count)
  }

  const max = Math.max(...pairwise.map(p => p.shared_count), 1)

  const TH = {
    backgroundColor:'var(--surface2)',
    borderBottom:'1px solid var(--border)',
    borderRight:'1px solid var(--border)'
  }

  return (
    <section>
      <div className="flex items-center gap-2 mb-1">
        <Layers className="w-4 h-4" style={{ color:'var(--accent2)' }} />
        <h2 className="text-base font-black" style={{ color:'var(--text)' }}>
          Single role overlap
        </h2>
        <span
          className="text-[10px] px-2 py-0.5 rounded-full font-black text-current"
          style={{ backgroundColor:'var(--accent2)', color:'var(--on-accent2)' }}
        >
          Primary
        </span>
      </div>

      <p className="text-xs mb-3" style={{ color:'var(--muted)' }}>
        Single roles are the building blocks of composite roles. Click any cell to see which ones are shared.
      </p>

      <div
        className="overflow-x-auto rounded-2xl shadow-sm"
        style={{ border:'1px solid var(--border)' }}
      >
        <table className="text-xs border-collapse w-full">
          <thead>
            <tr>
              <th
                className="p-3 text-left text-[10px] font-black uppercase tracking-wide min-w-[200px]"
                style={{ ...TH, color:'var(--muted)' }}
              >
                Composite role
              </th>

              {roles.map(r => (
                <th
                  key={r.agr_name}
                  className="px-3 py-3 min-w-[160px] text-center"
                  style={TH}
                >
                  <div className="flex flex-col items-center gap-1.5">
                    <ModLabel r={r} center />

                    <span
                      className="text-[12px] font-bold leading-tight text-center"
                      style={{ color:'var(--text)' }}
                    >
                      {cleanDesc(r.text) || shortAgr(r.agr_name)}
                    </span>

                    <span
                      className="font-mono text-[9px]"
                      style={{ color:'var(--muted)', opacity:0.6 }}
                      title={r.agr_name}
                    >
                      {r.agr_name.length > 26
                        ? r.agr_name.slice(0,24)+'...'
                        : r.agr_name}
                    </span>

                    <span className="text-[9px]" style={{ color:'var(--muted)' }}>
                      {r.single_role_count} single roles
                    </span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>

          <tbody>
            {roles.map(row => (
              <tr key={row.agr_name}>
                <td
                  className="px-3 py-3"
                  style={{
                    backgroundColor:'var(--surface2)',
                    borderBottom:'1px solid var(--border)',
                    borderRight:'1px solid var(--border)'
                  }}
                >
                  <ModLabel r={row} />

                  <p className="text-xs font-bold mt-1.5" style={{ color:'var(--text)' }}>
                    {cleanDesc(row.text) || shortAgr(row.agr_name)}
                  </p>

                  <p
                    className="font-mono text-[9px] mt-0.5"
                    style={{ color:'var(--muted)', opacity:0.6 }}
                    title={row.agr_name}
                  >
                    {row.agr_name.length > 26
                      ? row.agr_name.slice(0,24)+'...'
                      : row.agr_name}
                  </p>

                  <p className="text-[9px] mt-0.5" style={{ color:'var(--muted)' }}>
                    {row.single_role_count} single roles &middot; {row.tcode_count.toLocaleString()} T
                  </p>
                </td>

                {roles.map(col => {
                  if (row.agr_name === col.agr_name) {
                    return (
                      <td
                        key={col.agr_name}
                        className="px-3 py-4 text-center"
                        style={{
                          backgroundColor:'var(--primary)', color:'var(--on-primary)',
                          borderBottom:'1px solid var(--border)',
                          borderRight:'1px solid var(--border)'
                        }}
                      >
                        <p className="font-black text-current text-xl leading-none">
                          {row.single_role_count}
                        </p>
                        <p className="text-[9px] text-current mt-0.5">
                          single roles
                        </p>
                      </td>
                    )
                  }

                  const count = lookup.get(`${row.agr_name}|||${col.agr_name}`) ?? 0
                  const pct = row.single_role_count > 0
                    ? Math.round((count / row.single_role_count) * 100)
                    : 0

                  const la = cleanDesc(row.text) || shortAgr(row.agr_name)
                  const lb = cleanDesc(col.text) || shortAgr(col.agr_name)

                  return (
                    <td
                      key={col.agr_name}
                      onClick={() => onCell(row.agr_name, col.agr_name, la, lb)}
                      className="px-3 py-4 text-center cursor-pointer hover:brightness-110 transition-all"
                      style={{
                        backgroundColor:cellBg(count, max),
                        borderBottom:'1px solid var(--border)',
                        borderRight:'1px solid var(--border)'
                      }}
                      title={`${count} shared single roles (${pct}%)`}
                    >
                      <p
                        className="font-black text-lg leading-none"
                        style={{ color: count > 0 ? 'var(--on-accent)' : 'var(--muted)' }}
                      >
                        {count > 0 ? count : ''}
                      </p>

                      <p
                        className="text-[9px] mt-0.5 font-semibold"
                        style={{
                          color: count > 0
                            ? 'var(--on-accent)'
                            : 'var(--muted)'
                        }}
                      >
                        {count > 0 ? `${pct}%` : ''}
                      </p>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function ExclusiveColumn({ role }: { role: ComparisonRole }) {
  return (
    <div
      className="flex-1 min-w-[270px] rounded-2xl overflow-hidden shadow-sm flex flex-col"
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

        <p
          className="font-mono text-[9px] mb-2"
          style={{ color:'var(--muted)', opacity:0.6 }}
        >
          {role.agr_name}
        </p>

        <div className="flex items-center gap-2">
          <span
            className="text-[10px] font-black px-2 py-0.5 rounded-lg text-current"
            style={{ backgroundColor:'var(--accent2)', color:'var(--on-accent2)' }}
          >
            {role.exclusive_single_roles.length} exclusive
          </span>

          <span className="text-[10px]" style={{ color:'var(--muted)' }}>
            {role.single_role_count} total
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto" style={{ maxHeight:'500px' }}>
        {role.exclusive_single_roles.length === 0
          ? (
            <div className="px-4 py-8 text-center">
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
    <div className="flex flex-col gap-8 pb-8">
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
          <span
            key={n}
            className="font-mono text-xs px-3 py-1.5 rounded-xl font-bold text-current"
            style={{ backgroundColor:'var(--accent2)', color:'var(--on-accent2)' }}
          >
            {n}
          </span>
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

          <SRMatrix
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
              className="rounded-2xl overflow-hidden shadow-sm"
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
                  <ScrollArea.Root>
                    <ScrollArea.Viewport
                      style={{ maxHeight:'280px' }}
                      className="w-full"
                    >
                      <div>
                        {data.shared_single_roles.map(sr => (
                          <SRRow
                            key={sr.child_agr}
                            sr={sr}
                            parentRoleName={roleNames[0]}
                          />
                        ))}
                      </div>
                    </ScrollArea.Viewport>

                    <ScrollArea.Scrollbar
                      orientation="vertical"
                      className="flex select-none touch-none p-0.5 w-2"
                      style={{ backgroundColor:'var(--surface2)' }}
                    >
                      <ScrollArea.Thumb
                        className="flex-1 rounded-full"
                        style={{ backgroundColor:'var(--accent2)', color:'var(--on-accent2)' }}
                      />
                    </ScrollArea.Scrollbar>
                  </ScrollArea.Root>
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

            <div className="flex gap-3 overflow-x-auto pb-2">
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