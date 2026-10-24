import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeftRight, Download } from 'lucide-react'
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
import {
  Filter,
  inputClass,
  Pagination,
  QueryState,
  EvidenceNote,
  dates,
} from './Shared'
interface Row {
  identifier: string
  difference: string
  a: Assignment[] | string[]
  b: Assignment[] | string[]
  description?: string
  areas: string[]
  a_total: number
  b_total: number
}
interface Result extends Page<Row> {
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
  const text = (u: UserRow) =>
    `${u.username} · ${[u.first_name, u.last_name].filter(Boolean).join(' ') || 'Name unavailable'} · ${u.email || 'Email unavailable'}`
  const selected = rows.find((u) => u.username === value)
  return (
    <Filter label={label}>
      <Combobox
        label={label}
        value={selected ? text(selected) : value}
        options={rows.map(text)}
        onSearch={setSearch}
        allowCustom={false}
        serverFiltered
        clearLabel="Choose user"
        loading={result.isFetching || search !== term}
        hasMore={(result.data?.total || 0) > 25}
        onChange={(s) =>
          onChange(rows.find((u) => text(u) === s)?.username || '')
        }
      />
      {result.error && <span role="alert">{result.error.message}</span>}
    </Filter>
  )
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
        Page<Assignment | string> & { data_revision: string; as_of: string }
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
        ? 'No matching evidence'
        : items.map((e, i) =>
            typeof e === 'string' ? (
              <p key={i}>
                <button className="text-link" onClick={() => onAssignedRole(e)}>
                  {e}
                </button>
              </p>
            ) : (
              <p key={i}>
                {e.role_name} · {dates(e.valid_from, e.valid_to)} · {e.status} ·{' '}
                {e.user_group || 'No group'} · {e.match_status}
                {e.catalogue_roles.map((r) => (
                  <button
                    key={r}
                    className="text-link ml-2"
                    onClick={() => onRole(r)}
                  >
                    {r}
                  </button>
                ))}
              </p>
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
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState('')
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
    () => onContext({ a, b, validity, kind, difference, search, area }),
    [a, b, validity, kind, difference, search, area, onContext],
  )
  const state = { validity, kind, difference, search, area }
  const params = new URLSearchParams({
    user_a: a,
    user_b: b,
    validity,
    kind,
    difference,
    search: term,
    area,
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
  }
  const clear = () => {
    setValidity('active')
    setKind('roles')
    setDifference('')
    setSearch('')
    setArea('')
  }
  const exportCSV = async () => {
    if (!data) return
    setBusy(true)
    setMessage('')
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
        setMessage(saved ? 'Comparison CSV saved.' : 'Export cancelled.')
      } else {
        const url = URL.createObjectURL(
            new Blob([content], { type: 'text/csv;charset=utf-8' }),
          ),
          link = document.createElement('a')
        link.href = url
        link.download = filename
        link.click()
        setTimeout(() => URL.revokeObjectURL(url), 1000)
        setMessage('Comparison CSV exported.')
      }
    } catch (e) {
      setMessage((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <section aria-label="User Comparison" className="space-y-4">
      <h1 className="text-xl font-semibold flex items-center gap-2">
        <ArrowLeftRight size={20} />
        Compare users
      </h1>
      <EvidenceNote />
      <div className="comparison-identity-grid">
        <UserSelector label="User A" value={a} other={b} onChange={setA} />
        <UserSelector label="User B" value={b} other={a} onChange={setB} />
      </div>
      <SavedFilters
        view="comparison"
        state={state}
        apply={apply}
        clear={clear}
      />
      <div className="directory-filter-grid investigation-filters">
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
                    : v}
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
        <Filter label="Differences">
          <Select
            aria-label="Differences"
            className={inputClass}
            value={difference}
            onChange={(e) => setDifference(e.target.value)}
          >
            <option value="">All</option>
            <option value="shared">Shared</option>
            <option value="a">Only User A</option>
            <option value="b">Only User B</option>
          </Select>
        </Filter>
        <Filter
          label={
            kind === 'roles'
              ? 'Search comparison roles'
              : 'Search comparison transactions'
          }
        >
          <input
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
      </div>
      <QueryState loading={result.isFetching} error={result.error} />
      {(!a || !b) && (
        <p>
          Select two different SAP users to compare their imported assignments.
        </p>
      )}
      {data && (
        <>
          <div className="comparison-identity-grid">
            {data.users.map((u, i) => (
              <article key={u.username} className="settings-panel">
                <h3>
                  {i === 0 ? 'User A' : 'User B'} ·{' '}
                  <button
                    className="text-link"
                    onClick={() => onUser(u.username)}
                  >
                    {u.username}
                  </button>
                </h3>
                <p>
                  {u.first_name} {u.last_name}
                </p>
                <p>{u.email || 'Email unavailable'}</p>
                {u.identity_ambiguous && (
                  <p className="text-sm">
                    Multiple source identities; inspect User Details before
                    interpreting this account.
                  </p>
                )}
                <div className="flex flex-wrap gap-2">
                  <AccountStatus value={u.account_status} />
                  <AccountStatus kind="lock" value={u.lock_status} />
                </div>
              </article>
            ))}
          </div>
          <p className="text-sm">
            Roles — shared: {data.summary.roles.shared}; only A:{' '}
            {data.summary.roles.a}; only B: {data.summary.roles.b}. Mapped
            transactions — shared: {data.summary.transactions.shared}; only A:{' '}
            {data.summary.transactions.a}; only B: {data.summary.transactions.b}
            .
          </p>
          {!data.catalogue_available && (
            <p role="status">
              Role catalogue unavailable. Transaction coverage is incomplete,
              not evidence of no access.
            </p>
          )}
          <div className="flex flex-wrap gap-3 items-center">
            <span>
              {data.total} matching {kind}
            </span>
            <button
              className="settings-secondary-button"
              disabled={busy || result.isFetching || term !== search}
              onClick={() => void exportCSV()}
            >
              <Download size={16} />
              Export comparison CSV
            </button>
          </div>
          {message && <p role="status">{message}</p>}
          {!data.total && (
            <p>
              No matching {kind}. Check validity and source coverage; absence is
              not proof of no effective SAP access.
            </p>
          )}
          <div
            className="overflow-x-auto"
            tabIndex={0}
            role="region"
            aria-label="Scrollable comparison evidence"
          >
            <table className="w-full text-sm comparison-table">
              <caption className="sr-only">User comparison evidence</caption>
              <thead>
                <tr>
                  <th>Role / Transaction</th>
                  <th>Category</th>
                  <th>User A evidence</th>
                  <th>User B evidence</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.identifier}>
                    <td>
                      {kind === 'roles' ? (
                        <strong>{row.identifier}</strong>
                      ) : (
                        <button
                          className="text-link"
                          onClick={() => onTransaction(row.identifier)}
                        >
                          {row.identifier}
                        </button>
                      )}
                      <p>{row.description}</p>
                      <small>{row.areas.join(' · ')}</small>
                    </td>
                    <td>
                      {row.difference === 'shared'
                        ? 'Shared'
                        : row.difference === 'a'
                          ? 'Only User A'
                          : 'Only User B'}
                    </td>
                    {(['a', 'b'] as const).map((side) => (
                      <td key={side}>
                        <EvidenceCell
                          row={row}
                          side={side}
                          params={params}
                          revision={data.data_revision}
                          asOf={data.as_of}
                          onRole={onRole}
                          onAssignedRole={(e) => {
                            setKind('roles')
                            setSearch(e)
                          }}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
