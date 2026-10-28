import {textMatches} from '@/lib/searchMatching'
import { PageHeader } from '@/components/Shared/Presentation'
import { Search as PageIcon, ShoppingCart } from 'lucide-react'
import { Button } from '@/components/Shared/Button'
import { AccessPackagePanel } from './AccessPackagePanel'
import { useAccessPackage } from '@/lib/accessPackage'
import { SearchInput } from '@/components/Shared/Controls'
import { SavedFilters } from '@/components/Shared/SavedFilters'
import { useApplicationData } from '@/state/ApplicationData'
import { TransactionFilter, useTransactionFilter } from '@/components/Shared/TransactionFilter'
import { ClearFilterButton } from '@/components/Shared/ClearFilterButton'
import { ModuleIcon } from '@/components/Modules/ModuleIcon'
import { onColor } from '@/lib/theme'
import { useState, useEffect, useMemo, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  GitCompare, X,
  AlertTriangle, RefreshCw, ArrowUpDown, Zap
} from 'lucide-react'
import { useModules } from '@/hooks/useModules'
import { useRoles } from '@/hooks/useRoles'
import { RoleCard } from './RoleCard'
import type { RoleSummary } from '@/api/types'
import { apiRequest } from '@/api/client'

const fetchExactRoles = (codes: string[], mode: 'and' | 'or', exclude: boolean) => apiRequest<RoleSummary[]>(`/api/roles?${new URLSearchParams([...codes.map(code => ['tcodes', code]), ['transaction_mode', mode], ...(exclude ? [['exclude_matching', 'true']] : [])])}`)

interface Props {
  initialArea?:string
  selectedRoles: string[]
  onSelectRole: (n: string) => void
  onViewDetail: (n: string) => void
  onCompare: () => void
  onFilteredRoles?: (roles: string[]) => void
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
  initialArea,
  selectedRoles,
  onSelectRole,
  onViewDetail,
  onCompare,
  onFilteredRoles
}: Props) {
  const {loading:dataLoading}=useApplicationData()
  const [page,setPage] = useState(0)
  const cart = useAccessPackage()
  const [packageOpen,setPackageOpen] = useState(false)
  const transaction = useTransactionFilter()
  const [exclude, setExclude] = useState(false)
  const [search, setSearch] = useState('')
  const [activeModules, setActiveModules] = useState<string[]>(initialArea?[initialArea]:[])
  const [transactionMode, setTransactionMode] = useState<'and' | 'or'>('and')
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

  const exactTransactions = useQuery({
    queryKey: ['roles', 'exact-transactions', transaction.deferredCodes, transactionMode, exclude],
    queryFn: () => fetchExactRoles(transaction.deferredCodes, transactionMode, exclude),
    enabled: transaction.deferredCodes.length > 0,
    staleTime: 120_000,
  })
  const tcodeLoading = exactTransactions.isFetching || transaction.settling
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

  const visible = useMemo(() => {
    let results: RoleSummary[]

    if (debSearch.trim()) {
      const q = debSearch.trim().toLowerCase()

      results = allRolesRaw.filter(x =>
        textMatches(x.text??'',q) || textMatches(x.agr_name,q)
      )
    } else {
      results = allRolesRaw
    }

    if (activeModules.length) {
      results = results.filter(
        x => activeModules.includes(x.function_key ?? 'Other')
      )
    }

    if (transaction.deferredCodes.length) {
      const matches = new Map((exactTransactions.data || []).map(role => [role.agr_name, role]))
      results = results.filter(role => matches.has(role.agr_name)).map(role => ({ ...role, matching_tcodes: matches.get(role.agr_name)?.matching_tcodes }))
    }
    return applySort(results, sortBy)
  }, [
    allRolesRaw,
    debSearch,
    activeModules,
    sortBy, transaction.key, transaction.deferredCodes, exactTransactions.data
  ])

  useEffect(()=>setPage(0),[debSearch,activeModules,sortBy,transaction.key,transactionMode,exclude])
  const pageCount=Math.max(1,Math.ceil(visible.length/100))
  const currentPage=Math.min(page,pageCount-1)

  const isFiltering =
    !!debSearch.trim() ||
    activeModules.length > 0 || transaction.codes.length > 0 || exclude || sortBy !== 'name-asc'

  useEffect(() => { if (!isLoading && !isError) onFilteredRoles?.(visible.map(role => role.agr_name)) }, [visible, onFilteredRoles, isLoading, isError])

  useEffect(() => { if (!transaction.codes.length) setTransactionMode('and') }, [transaction.codes.length])

  const currentLabel =
    SORT_OPTIONS.find(o => o.key === sortBy)?.label ?? 'Sort'

  const clearSel = useCallback(
    () => selectedRoles.forEach(n => onSelectRole(n)),
    [selectedRoles, onSelectRole]
  )

  return (
    <div className="flex flex-col gap-4" role="region" aria-label="Role catalogue investigation" aria-busy={isLoading||search!==debSearch||transaction.settling||exactTransactions.isFetching}>
      <PageHeader title="Role Lookup" icon={<PageIcon size={22} aria-hidden="true"/>}>
        <Button onClick={()=>setPackageOpen(true)} aria-haspopup="dialog"><ShoppingCart size={16} aria-hidden="true"/>Access package ({cart.items.length})</Button>
      </PageHeader>
      {packageOpen&&<AccessPackagePanel onClose={()=>setPackageOpen(false)}/>}
      <SavedFilters showClear={false} view="roles" state={{search,activeModules,transactionMode,tcodes:transaction.codes,transactionExclude:exclude,sortBy}} apply={s=>{if(typeof s.search==='string')setSearch(s.search);if(Array.isArray(s.activeModules))setActiveModules(s.activeModules);if(s.transactionMode==='and'||s.transactionMode==='or')setTransactionMode(s.transactionMode);if(Array.isArray(s.tcodes)){transaction.setInput('');transaction.setChips(s.tcodes)};if(Array.isArray(s.notTcodes)&&s.notTcodes.length&&!(Array.isArray(s.tcodes)&&s.tcodes.length)){transaction.setInput('');transaction.setChips(s.notTcodes);setTransactionMode('or');setExclude(true)}else{const legacy=s.transactionOperator==='not'&&s.transactionExclude!==true;if(legacy)setTransactionMode('or');setExclude(s.transactionExclude===true||legacy)};if(SORT_OPTIONS.some(o=>o.key===s.sortBy))setSortBy(s.sortBy as SortKey)}} clear={()=>{setSearch('');setActiveModules([]);setTransactionMode('and');setExclude(false);transaction.clear();setSortBy('name-asc')}}/>
      <div
        className="catalogue-search-controls rounded-2xl border px-4 py-3 gap-3 "
        style={{
          backgroundColor:'var(--surface)',
          borderColor:'var(--border)'
        }}
      >
        <TransactionFilter compact label="Filter catalogue by transaction" filter={transaction} mode={transactionMode} onModeChange={setTransactionMode} exclude={exclude} onExcludeChange={setExclude} subject="roles" showClear={false}/>
        {exactTransactions.isError && transaction.codes.length > 0 && <p role="alert">Transaction filtering failed. {exactTransactions.error.message}</p>}
        <div className="catalogue-role-search flex gap-2">
          <div className="relative flex-1">
            <SearchInput aria-label="Search roles by name or description" value={search} onChange={event=>setSearch(event.target.value)} placeholder="Search roles by name or description..."/>


            {search && (
              <button
                onClick={() => setSearch('')}
                aria-label="Clear role search"
                className="absolute right-3 top-1/2 -translate-y-1/2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--focus)] rounded"
                style={{ color:'var(--muted)' }}
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>


        </div>

        {!isLoading && !isError && (
          <div className="catalogue-area-filter relative z-20 flex flex-wrap gap-1.5" role="group" aria-label="SAP areas">
            <button
              onClick={() => setActiveModules([])}
              aria-pressed={!activeModules.length}
              className="px-3 py-1.5 rounded-full text-xs font-bold border transition-all focus:outline-none"
              style={
                !activeModules.length
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
              const active = activeModules.includes(key)
              const color = modules.find(m=>m.function_key===key)?.color || '#64748b'
              const full = moduleNames[key] ?? key
              const short =
                full.length > 14
                  ? shortenModName(full)
                  : full

              return (
                <button
                  key={key}
                  onClick={() =>
                    setActiveModules(previous => active ? previous.filter(value => value !== key) : [...previous, key])
                  }
                  aria-pressed={active}
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
                  <ModuleIcon moduleId={key} selected={active} />
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

            {debSearch.trim() && (
              <span
                style={{
                  color:'var(--accent2)',
                  fontWeight:700
                }}
              >
                {' '}matching &ldquo;{debSearch.trim()}&rdquo;
              </span>
            )}

            {activeModules.length > 0 && (
              <span style={{ fontWeight:700 }}>
                {' '}{activeModules.map(key => moduleNames[key] || key).join(' / ')}
              </span>
            )}

            {!isFiltering && (
              <span className="text-xs opacity-60">
                {' '}&mdash; {currentLabel}
              </span>
            )}
          </p>

          <div className="flex items-center gap-2">
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
                  className="absolute right-0 top-full mt-1 z-30 rounded-xl border  overflow-hidden w-44"
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
            {tcodeLoading && (debSearch.trim() || transaction.codes.length > 0) && (
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
              <ClearFilterButton onClick={() => { setSearch(''); setActiveModules([]); transaction.clear(); setTransactionMode('and'); setExclude(false); setSortBy('name-asc') }}>Clear all filters</ClearFilterButton>
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

      {(isLoading || (dataLoading && !allRolesRaw.length)) && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} />
          ))}
        </div>
      )}

      {!isLoading && !isError && !(dataLoading && !allRolesRaw.length) && (
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
                {allRolesRaw.length
                  ? 'No roles match the selected name, description, SAP areas and exact transaction filters.'
                  : 'Open Settings to choose a CSV.'}
              </p>

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
                  inCart={cart.has(r.agr_name)}
                  onCart={name => (cart.has(name) ? cart.remove(name) : cart.add(name))}
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
          className="comparison-selection-bar fixed bottom-8 left-1/2 -translate-x-1/2 z-40 flex flex-wrap items-center gap-4 rounded-2xl  border px-6 py-3.5"
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

          <ClearFilterButton onClick={clearSel}>Clear selection</ClearFilterButton>
        </div>
      )}
    </div>
  )
}
