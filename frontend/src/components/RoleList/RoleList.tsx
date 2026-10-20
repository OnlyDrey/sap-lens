import { onColor } from '@/lib/theme'
import { useState, useEffect, useMemo, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Search, GitCompare, X, Users, Activity, LayoutGrid,
  AlertTriangle, RefreshCw, ArrowUpDown, Zap
} from 'lucide-react'
import { fetchConfiguration } from '@/api/configuration'
import { useModuleVisual } from '@/components/Modules/ModuleRegistry'
import { useModules } from '@/hooks/useModules'
import { useRoles } from '@/hooks/useRoles'
import { RoleCard } from './RoleCard'
import type { RoleSummary } from '@/api/types'
import { fetchRolesByTcode } from '@/api/client'

interface Props {
  selectedRoles: string[]
  onSelectRole: (n: string) => void
  onViewDetail: (n: string) => void
  onCompare: () => void
}

function useDebounce<T>(v: T, ms: number): T {
  const [d, setD] = useState(v)

  useEffect(() => {
    const t = setTimeout(() => setD(v), ms)
    return () => clearTimeout(t)
  }, [v, ms])

  return d
}

type SortKey =
  | 'name-asc'
  | 'name-desc'
  | 'tcodes-desc'
  | 'tcodes-asc'
  | 'singles-desc'

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key:'name-asc',     label:'Name A to Z' },
  { key:'name-desc',    label:'Name Z to A' },
  { key:'tcodes-desc',  label:'Most T-codes' },
  { key:'tcodes-asc',   label:'Fewest T-codes' },
  { key:'singles-desc', label:'Most groups' },
]

function getName(r: RoleSummary) {
  return (r.text ?? r.agr_name)
    .replace(/^[A-Z]{2,3}\s*-\s*/, '')
    .toLowerCase()
}

function applySort(roles: RoleSummary[], key: SortKey): RoleSummary[] {
  const a = [...roles]

  switch (key) {
    case 'name-asc':
      return a.sort((x,y) => getName(x).localeCompare(getName(y)))

    case 'name-desc':
      return a.sort((x,y) => getName(y).localeCompare(getName(x)))

    case 'tcodes-desc':
      return a.sort((x,y) => y.tcode_count - x.tcode_count)

    case 'tcodes-asc':
      return a.sort((x,y) => x.tcode_count - y.tcode_count)

    case 'singles-desc':
      return a.sort(
        (x,y) => (y.single_role_count ?? 0) - (x.single_role_count ?? 0)
      )

    default:
      return a
  }
}

function shortenModName(name: string) {
  return name
    .replace('Management','Mgmt')
    .replace('Production','Prod.')
    .replace('Distribution','Dist.')
    .replace('Resources','Res.')
    .replace('Maintenance','Maint.')
    .replace('Planning','Plan.')
}

function Skeleton() {
  return (
    <div
      className="rounded-2xl border p-4 animate-pulse flex flex-col gap-3"
      style={{
        backgroundColor:'var(--surface)',
        borderColor:'var(--border)',
        minHeight:'148px'
      }}
    >
      <div className="flex justify-between items-start">
        <div
          className="h-5 rounded-md w-28"
          style={{ backgroundColor:'var(--surface2)' }}
        />
        <div
          className="w-7 h-7 rounded-full"
          style={{ backgroundColor:'var(--surface2)' }}
        />
      </div>

      <div
        className="h-5 rounded w-3/4"
        style={{ backgroundColor:'var(--surface2)' }}
      />

      <div
        className="h-3 rounded w-full"
        style={{ backgroundColor:'var(--surface2)' }}
      />

      <div className="flex gap-3 pt-2 mt-auto">
        <div
          className="h-4 rounded w-24"
          style={{ backgroundColor:'var(--surface2)' }}
        />
        <div
          className="h-4 rounded w-16"
          style={{ backgroundColor:'var(--surface2)' }}
        />
      </div>
    </div>
  )
}

export function RoleList({
  selectedRoles,
  onSelectRole,
  onViewDetail,
  onCompare
}: Props) {
  const [page,setPage] = useState(0)
  const [search, setSearch] = useState('')
  const [activeDomain,setActiveDomain] = useState<string | null>(null)
  const {data:configuration} = useQuery({queryKey:['configuration'],queryFn:fetchConfiguration})
  const domains = configuration?.settings.classification_profiles.find(p=>p.id===configuration.settings.active_classification)?.domains || []
  useEffect(()=>setActiveDomain(null),[configuration?.settings.active_classification])
  const [activeModule, setActiveModule] = useState<string | null>(null)
  const [sortBy, setSortBy] = useState<SortKey>('name-asc')
  const [sortOpen, setSortOpen] = useState(false)

  const debSearch = useDebounce(search, 300)

  const { data: modules = [] } = useModules()

  const {
    data: allRolesRaw = [],
    isLoading,
    isError,
    error,
    refetch
  } = useRoles()

  const {
    data: tcodeRoles = [],
    isFetching: tcodeLoading
  } = useQuery({
    queryKey: ['roles', 'tcode', debSearch.trim().toUpperCase()],
    queryFn: () => fetchRolesByTcode(debSearch.trim()),
    enabled: debSearch.trim().length >= 2,
    staleTime: 120_000,
    placeholderData: [],
  })

  const domainCounts = useMemo(() => {const counts:Record<string,number>=Object.create(null);for(const r of allRolesRaw){const key=r.domain_id||'$unassigned';counts[key]=(counts[key]||0)+1}return counts},[allRolesRaw])

  const moduleNames = useMemo(
    () => Object.assign(Object.create(null),Object.fromEntries(
      modules.map(m => [m.function_key, m.module_name])
    )),
    [modules]
  )

  const moduleGroups = useMemo(() => {
    const map: Record<string, number> = Object.create(null)

    for (const r of allRolesRaw) {
      const k = r.function_key ?? 'Other'
      map[k] = (map[k] ?? 0) + 1
    }

    return Object.entries(map).filter(([key]) => modules.find(m=>m.function_key===key)?.enabled !== false).sort(([a],[b]) => a.localeCompare(b))
  }, [allRolesRaw, modules])

  const totalTcodes = useMemo(
    () => allRolesRaw.reduce((s, r) => s + r.tcode_count, 0),
    [allRolesRaw]
  )

  const hasTcodeResults =
    tcodeRoles.length > 0 &&
    debSearch.trim().length >= 2

  const visible = useMemo(() => {
    let results: RoleSummary[]

    if (hasTcodeResults) {
      results = tcodeRoles
    } else if (debSearch.trim()) {
      const q = debSearch.trim().toLowerCase()

      results = allRolesRaw.filter(x =>
        (x.text ?? '').toLowerCase().includes(q) ||
        x.agr_name.toLowerCase().includes(q) ||
        (x.module_name ?? '').toLowerCase().includes(q)
      )
    } else {
      results = allRolesRaw
    }

    if (activeModule) {
      results = results.filter(
        x => x.function_key === activeModule
      )
    }

    if (activeDomain) results=results.filter(r=>activeDomain==='$unassigned' ? !r.domain_id : r.domain_id===activeDomain)
    return applySort(results, sortBy)
  }, [
    allRolesRaw,
    tcodeRoles,
    hasTcodeResults,
    debSearch,
    activeModule,
    activeDomain,
    sortBy
  ])

  useEffect(()=>setPage(0),[debSearch,activeModule,activeDomain,sortBy])
  const pageCount=Math.max(1,Math.ceil(visible.length/100))
  const currentPage=Math.min(page,pageCount-1)

  const isFiltering =
    !!debSearch.trim() ||
    !!activeModule || !!activeDomain

  const currentLabel =
    SORT_OPTIONS.find(o => o.key === sortBy)?.label ?? 'Sort'

  const clearSel = useCallback(
    () => selectedRoles.forEach(n => onSelectRole(n)),
    [selectedRoles, onSelectRole]
  )

  return (
    <div className="flex flex-col gap-4">

      {!isLoading && !isError && allRolesRaw.length > 0 && (
        <div className="grid grid-cols-3 gap-3">
          {[
            {
              label:'Roles',
              value:allRolesRaw.length.toLocaleString(),
              color:'var(--accent2)',
              Icon:Users
            },
            {
              label:'Enabled areas',
              value:moduleGroups.length.toString(),
              color:'var(--accent2)',
              Icon:LayoutGrid
            },
            {
              label:'Role / T-code pairs',
              value:totalTcodes.toLocaleString(),
              color:'var(--text)',
              Icon:Activity
            },
          ].map(({ label, value, color, Icon }) => (
            <div
              key={label}
              className="rounded-xl border px-4 py-3 shadow-sm flex items-center gap-3"
              style={{
                backgroundColor:'var(--surface)',
                borderColor:'var(--border)'
              }}
            >
              <div
                className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor:'var(--surface2)' }}
              >
                <Icon className="w-4 h-4" style={{ color }} />
              </div>

              <div>
                <p
                  className="text-xl font-black leading-none"
                  style={{ color }}
                >
                  {value}
                </p>
                <p
                  className="text-[10px] font-medium mt-0.5"
                  style={{ color:'var(--muted)' }}
                >
                  {label}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}

      {domains.length>0 && <label className="flex items-center gap-3 text-sm" style={{color:'var(--text2)'}}>Customer domain
        <select aria-label="Customer domain" value={activeDomain||''} onChange={e=>setActiveDomain(e.target.value||null)} className="border rounded-lg px-3 py-2" style={{background:'var(--surface)',borderColor:'var(--border)'}}>
          <option value="">All domains</option>
          {domains.filter(d=>domainCounts[d.id]).map(d=><option key={d.id} value={d.id}>{d.label} ({domainCounts[d.id]||0})</option>)}
          <option value="$unassigned">Unclassified domain ({domainCounts['$unassigned']||0})</option>
        </select>
      </label>}
      <div
        className="rounded-2xl border px-4 py-3 flex flex-col gap-3 shadow-sm"
        style={{
          backgroundColor:'var(--surface)',
          borderColor:'var(--border)'
        }}
      >
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search
              className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 pointer-events-none"
              style={{ color:'var(--muted)' }}
            />

            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search roles by name, description or T-code (e.g. ME33K, FB01)..."
              className="w-full pl-9 pr-8 py-2.5 rounded-xl border text-sm focus:outline-none transition-all"
              style={{
                backgroundColor:'var(--surface2)',
                borderColor:'var(--border)',
                color:'var(--text)'
              }}
              onFocus={e => {
                e.currentTarget.style.backgroundColor = 'var(--surface)'
                e.currentTarget.style.borderColor = 'var(--accent2)'
                e.currentTarget.style.boxShadow = '0 0 0 3px color-mix(in srgb, var(--accent) 15%, transparent)'
              }}
              onBlur={e => {
                e.currentTarget.style.backgroundColor = 'var(--surface2)'
                e.currentTarget.style.borderColor = 'var(--border)'
                e.currentTarget.style.boxShadow = 'none'
              }}
            />

            {search && (
              <button
                onClick={() => setSearch('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 focus:outline-none"
                style={{ color:'var(--muted)' }}
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>

          <div className="relative flex-shrink-0">
            <button
              onClick={() => setSortOpen(p => !p)}
              className="flex items-center gap-2 px-3 py-2.5 rounded-xl border text-xs font-semibold focus:outline-none whitespace-nowrap"
              style={{
                backgroundColor:'var(--surface2)',
                borderColor:'var(--border)',
                color:'var(--text2)'
              }}
            >
              <ArrowUpDown
                className="w-3.5 h-3.5"
                style={{ color:'var(--muted)' }}
              />
              {currentLabel}
            </button>

            {sortOpen && (
              <>
                <div
                  className="fixed inset-0 z-10"
                  onClick={() => setSortOpen(false)}
                />

                <div
                  className="absolute right-0 top-full mt-1 z-30 rounded-xl border shadow-lg overflow-hidden w-44"
                  style={{
                    backgroundColor:'var(--surface)',
                    borderColor:'var(--border)'
                  }}
                >
                  {SORT_OPTIONS.map(opt => (
                    <button
                      key={opt.key}
                      onClick={() => {
                        setSortBy(opt.key)
                        setSortOpen(false)
                      }}
                      className="w-full text-left px-4 py-2.5 text-xs font-semibold focus:outline-none hover:opacity-80"
                      style={{
                        backgroundColor:
                          sortBy === opt.key
                            ? 'var(--accent2)'
                            : 'transparent',
                        color:
                          sortBy === opt.key
                            ? 'var(--on-accent2)'
                            : 'var(--text2)',
                      }}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>

        {!isLoading && !isError && (
          <div className="relative z-20 flex flex-wrap gap-1.5">
            <button
              onClick={() => { setActiveModule(null); setActiveDomain(null) }}
              className="px-3 py-1.5 rounded-full text-xs font-bold border transition-all focus:outline-none"
              style={
                activeModule === null
                  ? {
                      backgroundColor:'var(--accent)',
                      color:'var(--on-accent)',
                      borderColor:'var(--primary)'
                    }
                  : {
                      backgroundColor:'var(--surface2)',
                      color:'var(--muted)',
                      borderColor:'var(--border)'
                    }
              }
            >
              All ({allRolesRaw.length})
            </button>

            {moduleGroups.map(([key, count]) => {
              const active = activeModule === key
              const color = modules.find(m=>m.function_key===key)?.color || '#64748b'
              const Icon = RegistryIcon
              const full = moduleNames[key] ?? key
              const short =
                full.length > 14
                  ? shortenModName(full)
                  : full

              return (
                <button
                  key={key}
                  onClick={() =>
                    setActiveModule(active ? null : key)
                  }
                  title={full}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-bold border transition-all focus:outline-none"
                  style={
                    active
                      ? {
                          backgroundColor:color,
                          color:onColor(color),
                          borderColor:color
                        }
                      : {
                          backgroundColor:'var(--surface2)',
                          color:'var(--muted)',
                          borderColor:'var(--border)'
                        }
                  }
                >
                  <Icon moduleId={key} className="w-3 h-3" />
                  {key} &ndash; {short}

                  <span className="opacity-60 font-medium">
                    ({count})
                  </span>
                </button>
              )
            })}
          </div>
        )}
      </div>

      {!isLoading && !isError && (
        <div className="flex items-center justify-between px-1">
          <p className="text-sm" style={{ color:'var(--muted)' }}>
            <span style={{ fontWeight:700, color:'var(--text)' }}>
              {visible.length}
            </span>

            {' '}role{visible.length !== 1 ? 's' : ''} in

            {hasTcodeResults && debSearch.trim() && (
              <span className="inline-flex items-center gap-1 ml-1">
                <span style={{ color:'var(--muted)' }}>
                  containing T-code
                </span>

                <span
                  className="font-mono font-black px-1.5 py-0.5 rounded text-[10px]"
                  style={{
                    backgroundColor:'color-mix(in srgb, var(--accent) 15%, transparent)',
                    color:'var(--accent2)'
                  }}
                >
                  {debSearch.trim().toUpperCase()}
                </span>
              </span>
            )}

            {!hasTcodeResults && debSearch.trim() && (
              <span
                style={{
                  color:'var(--accent2)',
                  fontWeight:700
                }}
              >
                {' '}matching &ldquo;{debSearch.trim()}&rdquo;
              </span>
            )}

            {activeModule && (
              <span style={{ fontWeight:700 }}>
                {' '}{moduleNames[activeModule] ?? activeModule}
              </span>
            )}

            {!isFiltering && (
              <span className="text-xs opacity-60">
                {' '}&mdash; {currentLabel}
              </span>
            )}
          </p>

          <div className="flex items-center gap-2">
            {tcodeLoading && debSearch.trim() && (
              <span
                className="text-[10px] flex items-center gap-1"
                style={{ color:'var(--muted)' }}
              >
                <Zap
                  className="w-3 h-3 animate-pulse"
                  style={{ color:'var(--accent2)' }}
                />
                Searching T-codes...
              </span>
            )}

            {isFiltering && (
              <button
                onClick={() => {
                  setSearch('')
                  setActiveModule(null); setActiveDomain(null)
                }}
                className="text-xs underline focus:outline-none"
                style={{ color:'var(--muted)' }}
              >
                Clear filters
              </button>
            )}
          </div>
        </div>
      )}

      {isError && (
        <div
          className="flex items-start gap-3 rounded-xl p-4 border"
          style={{
            backgroundColor:'var(--surface)',
            borderColor:'var(--error)'
          }}
        >
          <AlertTriangle className="w-5 h-5 text-[var(--error)] flex-shrink-0 mt-0.5" />

          <div>
            <p className="text-sm font-bold" style={{ color:'var(--error)' }}>
              Failed to load roles
            </p>

            <p className="text-sm mt-0.5" style={{ color:'var(--error)' }}>
              {error?.message}
            </p>

            <button
              onClick={() => void refetch()}
              className="mt-2 inline-flex items-center gap-1 text-sm hover:underline"
              style={{ color:'var(--error)' }}
            >
              <RefreshCw className="w-3.5 h-3.5" /> Retry
            </button>
          </div>
        </div>
      )}

      {isLoading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} />
          ))}
        </div>
      )}

      {!isLoading && !isError && (
        visible.length === 0
          ? (
            <div
              className="py-16 text-center rounded-2xl border"
              style={{
                backgroundColor:'var(--surface)',
                borderColor:'var(--border)'
              }}
            >
              <p className="text-lg font-bold" style={{ color:'var(--muted)' }}>
                {debSearch.trim() && !tcodeLoading
                  ? 'No matches found'
                  : 'No roles found'}
              </p>

              <p className="text-sm mt-1" style={{ color:'var(--muted)' }}>
                {debSearch.trim()
                  ? `No roles contain T-code "${debSearch.trim().toUpperCase()}" or match that name`
                  : 'Open Settings to choose a CSV, or try a different filter'}
              </p>

              {isFiltering && (
                <button
                  onClick={() => {
                    setSearch('')
                    setActiveModule(null); setActiveDomain(null)
                  }}
                  className="mt-3 text-sm underline focus:outline-none"
                  style={{ color:'var(--accent2)' }}
                >
                  Clear all filters
                </button>
              )}
            </div>
          )
          : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {visible.slice(currentPage*100,(currentPage+1)*100).map(r => (
                <RoleCard
                  key={r.agr_name}
                  role={r}
                  isSelected={selectedRoles.includes(r.agr_name)}
                  onSelect={onSelectRole}
                  onClick={onViewDetail}
                />
              ))}
            </div>
          )
      )}

      {visible.length>100 && <nav aria-label="Role pages" className="flex items-center justify-center gap-4 text-sm" style={{color:'var(--text2)'}}>
        <button className="border rounded-lg px-3 py-2 disabled:opacity-40" disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}>Previous page</button>
        <span>Showing {currentPage*100+1}–{Math.min((currentPage+1)*100,visible.length)} of {visible.length} roles</span>
        <button className="border rounded-lg px-3 py-2 disabled:opacity-40" disabled={currentPage===pageCount-1} onClick={()=>setPage(currentPage+1)}>Next page</button>
      </nav>}

      {selectedRoles.length >= 2 && (
        <div
          className="fixed bottom-8 left-1/2 -translate-x-1/2 z-40 flex items-center gap-4 rounded-2xl shadow-2xl border px-6 py-3.5"
          style={{
            backgroundColor:'var(--surface)',
            borderColor:'var(--border)'
          }}
        >
          <div>
            <p
              className="text-base font-black leading-none"
              style={{ color:'var(--text)' }}
            >
              <span style={{ color:'var(--accent2)' }}>
                {selectedRoles.length}
              </span>{' '}
              roles selected
            </p>

            <p
              className="text-[10px] mt-0.5"
              style={{ color:'var(--muted)' }}
            >
              up to 5 total
            </p>
          </div>

          <div
            className="w-px h-8"
            style={{ backgroundColor:'var(--border)' }}
          />

          <button
            onClick={onCompare}
            className="flex items-center gap-2 text-white font-black px-6 py-2.5 rounded-xl text-sm focus:outline-none hover:opacity-90 active:scale-95"
            style={{ backgroundColor:'var(--accent)', color:'var(--on-accent)' }}
          >
            <GitCompare className="w-4 h-4" />
            Compare now
          </button>

          <button
            onClick={clearSel}
            className="text-xs font-semibold hover:underline focus:outline-none"
            style={{ color:'var(--muted)' }}
          >
            Clear
          </button>
        </div>
      )}
    </div>
  )
}
function RegistryIcon({moduleId,className}: {moduleId:string; className?:string}) {
  const {Icon,color} = useModuleVisual(moduleId)
  return <Icon className={className} style={{color}} />
}
