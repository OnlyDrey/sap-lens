import { Popover } from '@/components/Shared/Popover'
import { announceExport } from '@/lib/exportNotice'
import { ClearFilterButton } from '@/components/Shared/ClearFilterButton'
import { FilterPanel } from '@/components/Shared/InvestigationPatterns'
import { SearchInput } from '@/components/Shared/Controls'
import { AssignmentStatus } from '@/components/Shared/InvestigationNavigation'
import { FilterChip } from '@/components/Shared/FilterChip'
import { Button, IconButton } from '@/components/Shared/Button'
import { SAPUserSelector } from '@/components/Shared/SAPUserSelector'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import { RoleModuleBadge } from '@/components/Shared/RoleModuleBadge'
import { RoleEntry } from '@/components/Shared/RoleEntry'
import { presentRoleDescription } from '@/lib/rolePresentation'
import { useModuleDefinitions } from '@/components/Modules/ModuleRegistry'
import { moduleOfRoles, useRoleModules } from '@/hooks/useRoleModules'
import {
  Card,
  Toolbar,
  PageHeader,
  EvidenceDisclosure,
  DataTable,
} from '@/components/Shared/Presentation'
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeftRight, Download, ArrowUpRight } from 'lucide-react'
import { apiRequest, applicationToken } from '@/api/client'
import {
  accessQuery,
  type Assignment,
  type Page,
  type UserRow,
} from '@/api/access'
import { Combobox } from '@/components/Shared/Combobox'
import { Select } from '@/components/Shared/Select'
import { AccountStatus } from '@/components/Shared/AccountStatus'
import { SavedFilters } from '@/components/Shared/SavedFilters'
import { csvField } from '@/lib/accessExport'
import { formatDate } from '@/lib/dateFormat'
import { Filter, inputClass, Pagination, QueryState } from './Shared'
interface Row {
  identifier: string
  difference: string
  a: Assignment[] | string[]
  b: Assignment[] | string[]
  description?: string
  areas: string[]
  assignment_evidence?: Partial<Record<'a' | 'b', Record<string, {items: Assignment[]; total: number}>>>
  a_total: number
  b_total: number
}
interface Result extends Page<Row> {
  assignment_evidence?: Row['assignment_evidence']
  users: (UserRow & { identity_ambiguous?: boolean })[]
  summary: Record<string, Record<string, number>>
  areas: string[]
  catalogue_available: boolean
  data_revision: string
  as_of: string
}
function UserSelector({
  label,
  value,
  other,
  onChange,
}: {
  label: string
  value: string
  other: string
  onChange: (s: string) => void
}) {
  const [search, setSearch] = useState(''),
    [term, setTerm] = useState('')
  useEffect(() => {
    const timer = setTimeout(() => setTerm(search), 200)
    return () => clearTimeout(timer)
  }, [search])
  const result = useQuery({
    queryKey: ['compare-users', term],
    queryFn: () =>
      accessQuery<Page<UserRow>>('users', { search: term, limit: 25 }),
  })
  const rows =
    search === term
      ? result.data?.items.filter(
          (u) => u.username.trim().toUpperCase() !== other.trim().toUpperCase(),
        ) || []
      : []
  return (
    <>
      <SAPUserSelector
        label={label}
        value={value}
        options={rows}
        onSearch={setSearch}
        onChange={onChange}
        loading={result.isFetching || search !== term}
        hasMore={(result.data?.total || 0) > 25}
      />
      {result.error && <p role="alert">{result.error.message}</p>}
    </>
  )
}
/** Standard role presentation for the compared role: module badge, description, copyable identifier. Module comes from matched catalogue evidence only. */
function ComparisonRole({ row }: { row: Row }) {
  const modules = useRoleModules(), areas = Object.keys(useModuleDefinitions())
  const first = [...row.a, ...row.b].find((item): item is Assignment => typeof item !== 'string')
  const code = first && ['exact', 'wildcard'].includes(first.match_status) ? moduleOfRoles(modules, first.catalogue_roles) : undefined
  const description = presentRoleDescription(row.description, areas).description
  return <RoleEntry density="compact" moduleCode={code} showUnclassified title={description || (code ? '' : 'Unclassified role')} identifier={row.identifier} />
}
function EvidenceCell({
  row,
  side,
  params,
  revision,
  asOf,
  onRole,
  onAssignedRole,
}: {
  row: Row
  side: 'a' | 'b'
  params: URLSearchParams
  revision: string
  asOf: string
  onRole: (s: string) => void
  onAssignedRole: (s: string) => void
}) {
  const [offset, setOffset] = useState(0),
    key = params.toString()
  useEffect(() => setOffset(0), [key, row.identifier, side, revision, asOf])
  const query = new URLSearchParams(params)
  query.set('identifier', row.identifier)
  query.set('side', side)
  query.set('offset', String(offset))
  const result = useQuery({
    queryKey: [
      'comparison-evidence',
      key,
      row.identifier,
      side,
      offset,
      revision,
      asOf,
    ],
    queryFn: async () => {
      const page = await apiRequest<
        Page<Assignment | string> & { data_revision: string; as_of: string; assignment_evidence?: Record<string,{items: Assignment[];total:number}> }
      >(`/api/user-comparison/evidence?${query}`)
      if (page.data_revision !== revision || page.as_of !== asOf)
        throw Error(
          'Source changed. Refresh the comparison before opening more evidence.',
        )
      return page
    },
    enabled: offset > 0,
  })
  const items = offset ? result.data?.items || [] : row[side],
    total = row[(side + '_total') as 'a_total' | 'b_total']
  return (
    <>
      <QueryState
        loading={offset > 0 && result.isFetching}
        error={result.error}
      />
      {!total
        ? <span className="ui-description">No matching evidence</span>
        : items.map((e, i) =>
            typeof e === 'string' ? (
              <div key={e} className="comparison-evidence-item">
                <button className="text-link" onClick={() => onAssignedRole(e)}>{e}</button>
                <p className="ui-description">Role-derived transaction mapping</p>
                {(() => {
                  const evidence = offset ? result.data?.assignment_evidence?.[e] : row.assignment_evidence?.[side]?.[e]
                  const roleParams = new URLSearchParams(params); roleParams.set('kind','roles')
                  return evidence ? <EvidenceCell
                    row={{identifier:e,difference:row.difference,a:side==='a'?evidence.items:[],b:side==='b'?evidence.items:[],a_total:side==='a'?evidence.total:0,b_total:side==='b'?evidence.total:0,areas:[]}}
                    side={side} params={roleParams} revision={revision} asOf={asOf} onRole={onRole} onAssignedRole={onAssignedRole}
                  /> : <span className="ui-description">Assignment details unavailable</span>
                })()}
              </div>
            ) : (
              <div key={i} className="comparison-evidence-item">
                {e.role_name!==row.identifier&&<><RoleModuleBadge catalogueRoles={e.match_status==='exact'||e.match_status==='wildcard'?e.catalogue_roles:undefined}/>
                <RoleIdentifier value={e.role_name} onOpen={e.catalogue_roles.length===1&&['exact','wildcard'].includes(e.match_status)?()=>onRole(e.catalogue_roles[0]):undefined} openLabel={`Open catalogue details for ${e.role_name}`}/></>}
                <div className="assignment-status-control"><Popover label={`Assignment validity for ${e.role_name}`} trigger={<AssignmentStatus value={e.status}/>}><dl className="ui-metadata-list"><div><dt>Valid from</dt><dd>{formatDate(e.valid_from)}</dd></div><div><dt>Valid to</dt><dd>{formatDate(e.valid_to)}</dd></div><div><dt>Evaluated assignment status</dt><dd><AssignmentStatus value={e.status}/></dd></div></dl></Popover></div>
                <p className="ui-description whitespace-nowrap">SAP User Group: {e.user_group || 'Unknown'}</p>

              </div>
            ),
          )}
      <Pagination
        label={`${row.identifier} User ${side.toUpperCase()} evidence`}
        offset={offset}
        total={total}
        limit={25}
        onChange={setOffset}
      />
    </>
  )
}
export interface ComparisonContext {
  sort?: string
  descending?: boolean
  a: string
  b: string
  validity: string
  kind: string
  difference: string
  search: string
  area: string
}
export function UserComparison({
  initialUser = '',
  context,
  onContext,
  onUser,
  onRole,
  onTransaction,
}: {
  initialUser?: string
  context?: ComparisonContext
  onContext: (state: ComparisonContext) => void
  onUser: (s: string) => void
  onRole: (s: string) => void
  onTransaction: (s: string) => void
}) {
  const [a, setA] = useState(initialUser || context?.a || ''),
    [b, setB] = useState(context?.b || ''),
    [validity, setValidity] = useState(context?.validity || 'active'),
    [kind, setKind] = useState(context?.kind || 'roles'),
    [difference, setDifference] = useState(context?.difference || ''),
    [search, setSearch] = useState(context?.search || ''),
    [term, setTerm] = useState(context?.search || ''),
    [area, setArea] = useState(context?.area || ''),
    [offset, setOffset] = useState(0),
    [sort, setSort] = useState(context?.sort || 'identifier'),
    [descending, setDescending] = useState(context?.descending || false),
    [busy, setBusy] = useState(false)
  useEffect(() => {
    if (initialUser) {
      setA(initialUser)
      setB((previous) =>
        previous.trim().toUpperCase() === initialUser.trim().toUpperCase()
          ? ''
          : previous,
      )
    }
  }, [initialUser])
  useEffect(() => {
    const t = setTimeout(() => setTerm(search), 200)
    return () => clearTimeout(t)
  }, [search])
  useEffect(
    () =>
      onContext({
        a,
        b,
        validity,
        kind,
        difference,
        search,
        area,
        sort,
        descending,
      }),
    [
      a,
      b,
      validity,
      kind,
      difference,
      search,
      area,
      sort,
      descending,
      onContext,
    ],
  )
  const state = { validity, kind, difference, search, area, sort, descending }
  const params = new URLSearchParams({
    user_a: a,
    user_b: b,
    validity,
    kind,
    difference,
    search: term,
    area,
    sort,
    descending: String(descending),
  })
  const key = params.toString(),
    operationKey = JSON.stringify([
      a,
      b,
      validity,
      kind,
      difference,
      search,
      area,
      sort,
      descending,
    ]),
    current = useRef(operationKey)
  current.current = operationKey
  useEffect(
    () => () => {
      current.current = ''
    },
    [],
  )
  useEffect(() => setOffset(0), [key])
  const result = useQuery({
    queryKey: ['user-comparison', key, offset],
    queryFn: () =>
      apiRequest<Result>(`/api/user-comparison?${params}&offset=${offset}`),
    enabled: !!a && !!b && a !== b,
  })
  const data = result.data
  const apply = (s: Record<string, unknown>) => {
    if (
      ['active', 'expired', 'future', 'unknown', 'all'].includes(
        String(s.validity),
      )
    )
      setValidity(String(s.validity))
    if (['roles', 'transactions'].includes(String(s.kind)))
      setKind(String(s.kind))
    if (['', 'shared', 'a', 'b'].includes(String(s.difference)))
      setDifference(String(s.difference))
    if (typeof s.search === 'string') setSearch(s.search)
    if (typeof s.area === 'string') setArea(s.area)
    if (['identifier', 'difference', 'a', 'b'].includes(String(s.sort)))
      setSort(String(s.sort))
    if (typeof s.descending === 'boolean') setDescending(s.descending)
  }
  const clear = () => {
    setValidity('active')
    setKind('roles')
    setDifference('')
    setSearch('')
    setArea('')
    setSort('identifier')
    setDescending(false)
  }
  const exportCSV = async () => {
    if (!data) return
    setBusy(true)
    try {
      const chunks = [
        '\ufeff' +
          [
            'Username',
            'User group',
            'Compared with',
            'Category',
            'Kind',
            'Identifier',
            'Side',
            'Assigned role',
            'Valid from',
            'Valid to',
            'Assignment status',
            'Catalogue match',
            'Validity view',
            'As of',
          ]
            .map(csvField)
            .join(',') +
          '\r\n',
      ]
      const encoder = new TextEncoder()
      let bytes = encoder.encode(chunks[0]).byteLength
      for (let start = 0; start < data.total; start += 100) {
        const page = await apiRequest<Result>(
          `/api/user-comparison?${params}&offset=${start}&limit=100`,
        )
        if (
          current.current !== operationKey ||
          page.data_revision !== data.data_revision ||
          page.as_of !== data.as_of ||
          page.total !== data.total ||
          !page.items.length
        )
          throw Error('Comparison changed. Refresh before exporting.')
        for (const row of page.items)
          for (const side of ['a', 'b'] as const) {
            const total = row[(side + '_total') as 'a_total' | 'b_total']
            for (
              let evidenceOffset = 0;
              evidenceOffset < total;
              evidenceOffset += 100
            ) {
              const q = new URLSearchParams(params)
              q.set('identifier', row.identifier)
              q.set('side', side)
              q.set('offset', String(evidenceOffset))
              q.set('limit', '100')
              const evidencePage = await apiRequest<
                Page<Assignment | string> & {
                  data_revision: string
                  as_of: string
                }
              >(`/api/user-comparison/evidence?${q}`)
              if (
                current.current !== operationKey ||
                evidencePage.data_revision !== data.data_revision ||
                evidencePage.as_of !== data.as_of ||
                evidencePage.total !== total ||
                !evidencePage.items.length
              )
                throw Error('Comparison evidence changed; export cancelled.')
              for (const evidence of evidencePage.items) {
                const line =
                  [
                    side === 'a' ? a : b,
                    typeof evidence === 'string' ? '' : evidence.user_group,
                    side === 'a' ? b : a,
                    row.difference,
                    kind,
                    row.identifier,
                    side,
                    typeof evidence === 'string'
                      ? evidence
                      : evidence.role_name,
                    typeof evidence === 'string' ? '' : evidence.valid_from,
                    typeof evidence === 'string' ? '' : evidence.valid_to,
                    typeof evidence === 'string' ? '' : evidence.status,
                    typeof evidence === 'string' ? '' : evidence.match_status,
                    validity,
                    data.as_of,
                  ]
                    .map(csvField)
                    .join(',') + '\r\n'
                bytes += encoder.encode(line).byteLength
                if (bytes > 32 * 1024 * 1024)
                  throw Error('Export exceeds 32 MiB; narrow the filters.')
                chunks.push(line)
              }
            }
          }
      }
      const final = await apiRequest<Result>(
        `/api/user-comparison?${params}&limit=1`,
      )
      if (
        current.current !== operationKey ||
        final.data_revision !== data.data_revision ||
        final.as_of !== data.as_of
      )
        throw Error('Source changed; export cancelled.')
      const filename = `sap-lens-user-comparison-review-${data.as_of}.csv`,
        content = chunks.join('')
      if (window.pywebview) {
        if (!window.pywebview.api.save_user_access_csv)
          throw Error('Update the desktop application for CSV export.')
        const saved = await window.pywebview.api.save_user_access_csv(
          applicationToken(),
          filename,
          content,
        )
        announceExport(saved ? { kind: 'success', message: 'Comparison CSV saved.' } : { kind: 'info', message: 'Export cancelled.' })
      } else {
        const url = URL.createObjectURL(
            new Blob([content], { type: 'text/csv;charset=utf-8' }),
          ),
          link = document.createElement('a')
        link.href = url
        link.download = filename
        link.click()
        setTimeout(() => URL.revokeObjectURL(url), 1000)
        announceExport({ kind: 'success', message: 'Comparison CSV exported.' })
      }
    } catch (e) {
      announceExport({ kind: 'error', message: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }
  return (
    <section aria-label="User Comparison" className="space-y-4">
      <PageHeader title="Compare users" icon={<IconButton label="Swap users" variant="ghost" disabled={!a||!b} onClick={()=>{setA(b);setB(a)}}><ArrowLeftRight size={20} aria-hidden="true"/></IconButton>}/>
      <EvidenceDisclosure title="About comparison evidence">
        Role-derived transactions are investigation evidence, not proof of
        effective SAP authorization. Missing dates never establish active
        access; account status and lock state are separate.
      </EvidenceDisclosure>
      <div className="comparison-user-panels">
        {[
          { label: 'User A', value: a, other: b, change: setA },
          { label: 'User B', value: b, other: a, change: setB },
        ].map((side, index) => {
          const user = data?.users[index]
          return (
            <Card key={side.label}>
              <div className="flex items-end gap-2">
                <div className="flex-1 min-w-0">
                  <UserSelector
                    label={side.label}
                    value={side.value}
                    other={side.other}
                    onChange={side.change}
                  />
                </div>
                {user && (
                  <IconButton
                    label={`Open ${side.label}`}
                    variant="ghost"
                    onClick={() => onUser(user.username)}
                  >
                    <ArrowUpRight size={17} aria-hidden="true" />
                  </IconButton>
                )}
              </div>
              {user && (
                <>
                  <p className="text-sm">
                    {[user.first_name, user.last_name]
                      .filter(Boolean)
                      .join(' ') || 'Name unavailable'}{' '}
                    · {user.email || 'Email unavailable'}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <AccountStatus value={user.account_status} />
                    <AccountStatus kind="lock" value={user.lock_status} />
                  </div>
                  {user.identity_ambiguous && (
                    <p className="text-xs text-[var(--muted)]">
                      Multiple source identities; inspect User Details before
                      interpreting this account.
                    </p>
                  )}
                </>
              )}
            </Card>
          )
        })}
      </div>
      <SavedFilters
        showClear={false} view="comparison"
        state={state}
        apply={apply}
        clear={clear}
      />
      <FilterPanel label="Comparison filters" className="comparison-filter-bar">
        <Filter label="Assignment validity">
          <Select
            aria-label="Assignment validity"
            className={inputClass}
            value={validity}
            onChange={(e) => setValidity(e.target.value)}
          >
            {['active', 'expired', 'future', 'unknown', 'all'].map((v) => (
              <option key={v} value={v}>
                {v === 'active'
                  ? 'Currently valid'
                  : v === 'all'
                    ? 'All intervals'
                    : v.charAt(0).toUpperCase() + v.slice(1)}
              </option>
            ))}
          </Select>
        </Filter>
        <Filter label="Comparison section">
          <Select
            aria-label="Comparison section"
            className={inputClass}
            value={kind}
            onChange={(e) => {
              setKind(e.target.value)
              setSearch('')
            }}
          >
            <option value="roles">Roles</option>
            <option value="transactions">Role-derived transactions</option>
          </Select>
        </Filter>

        <Filter
          label={
            kind === 'roles'
              ? 'Search comparison roles'
              : 'Search comparison transactions'
          }
        >
          <SearchInput
            className={inputClass}
            value={search}
            maxLength={256}
            onChange={(e) => setSearch(e.target.value)}
          />
        </Filter>
        <Filter label="Comparison SAP area">
          <Combobox
            label="Comparison SAP area"
            value={area}
            options={data?.areas || []}
            onChange={setArea}
          />
        </Filter>
            <div className="sort-control"><Filter label="Sort comparison">
              <Select
                className={inputClass}
                value={sort}
                onChange={(e) => setSort(e.target.value)}
              >
                {[
                  ['identifier', 'Role / Transaction'],
                  ['difference', 'Difference'],
                  ['a', 'User A evidence count'],
                  ['b', 'User B evidence count'],
                ].map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </Filter>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={descending}
                onChange={(e) => setDescending(e.target.checked)}
              />
              Descending
            </label></div>
      <ClearFilterButton className="comparison-clear" onClick={clear}>Clear filters</ClearFilterButton>
      </FilterPanel>
      <QueryState loading={result.isFetching} error={result.error} />
      {(!a || !b) && (
        <p>
          Select two different SAP users to compare their imported assignments.
        </p>
      )}
      {data && (
        <>
          <p className="text-xs text-[var(--muted)]">
            Whole comparison · selected assignment validity · before result
            filters
          </p>
          <div className="comparison-metrics" aria-label="Comparison summary">
            {(kind === 'roles'
              ? [
                  ['Shared roles', 'shared', data.summary.roles.shared],
                  ['Only User A', 'a', data.summary.roles.a],
                  ['Only User B', 'b', data.summary.roles.b],
                ]
              : [
                  [
                    'Shared mapped transactions',
                    'shared',
                    data.summary.transactions.shared,
                  ],
                  [
                    'Mapped transactions only A',
                    'a',
                    data.summary.transactions.a,
                  ],
                  [
                    'Mapped transactions only B',
                    'b',
                    data.summary.transactions.b,
                  ],
                ]
            ).map(([label, value, count]) => (
              <Button
                key={label}
                variant="ghost"
                aria-pressed={difference === value}
                className="comparison-metric" data-difference={value}
                onClick={() =>
                  setDifference(difference === value ? '' : String(value))
                }
              >
                <span>{label}</span>
                <strong>{count}</strong>
              </Button>
            ))}
          </div>
          {difference && (
            <FilterChip
              removeLabel="Clear comparison difference"
              onRemove={() => setDifference('')}
            >
              Difference:{' '}
              {difference === 'shared'
                ? 'Shared'
                : difference === 'a'
                  ? 'Only User A'
                  : 'Only User B'}
            </FilterChip>
          )}
          {!data.catalogue_available && (
            <p role="status">
              Role catalogue unavailable. Transaction coverage is incomplete,
              not evidence of no access.
            </p>
          )}
          <Toolbar className="comparison-results">
            <span>
              {data.total} matching {kind}
            </span>
            <Button
              disabled={busy || result.isFetching || term !== search}
              onClick={() => void exportCSV()}
            >
              <Download size={16} />
              Export comparison CSV
            </Button>
          </Toolbar>
          {!data.total && (
            <p>
              No matching {kind}. Check validity and source coverage; absence is
              not proof of no effective SAP access.
            </p>
          )}
          <DataTable
            caption="User comparison evidence"
            tableClassName="comparison-table"
            regionLabel="Scrollable comparison evidence"
          >
            <thead>
              <tr>
                <th>Role / Transaction</th>
                <th>Difference</th>
                <th>User A Evidence</th>
                <th>User B Evidence</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => (
                <tr key={row.identifier}>
                  <td>
                    {kind === 'roles' ? (
                      <ComparisonRole row={row} />
                    ) : (
                      <>
                        <p className="comparison-row-title">{row.description || 'Transaction'}</p>
                        <button className="text-link" onClick={() => onTransaction(row.identifier)}>{row.identifier}</button>
                        {!!row.areas.length && <small>{row.areas.join(' · ')}</small>}
                      </>
                    )}
                  </td>
                  <td>
                    <span className="evidence-difference" data-difference={row.difference}>{row.difference === 'shared'
                      ? 'Shared'
                      : row.difference === 'a'
                        ? 'Only User A'
                        : 'Only User B'}</span>
                  </td>
                  {(['a', 'b'] as const).map((side) => (
                    <td key={side} aria-label={`User ${side.toUpperCase()} evidence for ${row.identifier}`}>
                      <EvidenceCell
                        row={{...row,assignment_evidence:data.assignment_evidence}} side={side} params={params}
                        revision={data.data_revision} asOf={data.as_of}
                        onRole={onRole}
                        onAssignedRole={(role) => { setKind('roles'); setSearch(role) }}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </DataTable>
          <Pagination
            label="Comparison pages"
            offset={offset}
            total={data.total}
            limit={25}
            onChange={setOffset}
          />
        </>
      )}
    </section>
  )
}
