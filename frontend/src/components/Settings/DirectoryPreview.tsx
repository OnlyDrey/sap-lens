import { sentenceCase } from '@/lib/labels'
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiRequest } from '@/api/client'
import { FormField, SearchInput, Checkbox } from '@/components/Shared/Controls'
import { Select } from '@/components/Shared/Select'
import {
  DataTable,
  StatusBadge,
  Toolbar,
} from '@/components/Shared/Presentation'
import { Pagination } from '@/components/Access/Shared'
import type { Employee } from '@/components/Shared/EmployeeInformation'

interface PreviewPage {
  items: (Employee & { sap_match: string; validation: string[] })[]
  total: number
  current_records: number
  replacement: Record<string, number>
}
export function DirectoryPreview({
  path,
  digest,
  revision,
  snapshot=false,
}: {
  path: string
  digest: string
  revision: number
  snapshot?:boolean
}) {
  const [search, setSearch] = useState(''),
    [term, setTerm] = useState(''),
    [filter, setFilter] = useState(''),
    [sort, setSort] = useState('name'),
    [descending, setDescending] = useState(false),
    [offset, setOffset] = useState(0)
  useEffect(() => {
    const t = setTimeout(() => setTerm(search), 180)
    return () => clearTimeout(t)
  }, [search])
  useEffect(() => setOffset(0), [term, filter, sort, descending, digest])
  const query = useQuery({
    queryKey: [
      'directory-preview', snapshot,
      path,
      digest,
      revision,
      term,
      filter,
      sort,
      descending,
      offset,
    ],
    queryFn: () =>
      apiRequest<PreviewPage>(snapshot?'/api/data-sources/employees/inspect':'/api/employees/preview', 'POST', {
        path,
        digest:digest||undefined,
        revision,
        search: term,
        filter,
        sort,
        descending,
        offset,
      }),
  })
  return (
    <div className="space-y-3">
      <div className="refresh-report-filters">
        <FormField label="Search preview employees">
          <SearchInput
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </FormField>
        <FormField label="Preview records">
          <Select
            className="ui-control"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            {[
              ['', 'All records'],
              ['missing_email', 'Missing email'],
              ['duplicate_email', 'Duplicate email'],
              ['missing_identifier', 'Missing employee identifier'],
              ['duplicate_identifier', 'Duplicate employee identifier'],
              ['missing_manager', 'Missing or unresolved manager'],
              ['ambiguous_manager', 'Ambiguous manager'],
              ['matched', 'Matched SAP identity'],
              ['unmatched', 'Unmatched SAP identity'],
            ].map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="Sort preview">
          <Select
            className="ui-control"
            value={sort}
            onChange={(e) => setSort(e.target.value)}
          >
            {['name', 'email', 'department', 'manager'].map((value) => (
              <option key={value} value={value}>
                {value[0].toUpperCase() + value.slice(1)}
              </option>
            ))}
          </Select>
        </FormField>
      </div>
      <Toolbar>
        <span>
          {query.data
            ? `${query.data.total} matching preview records`
            : 'Loading preview records…'}
        </span>
        <Checkbox
          checked={descending}
          onChange={(e) => setDescending(e.target.checked)}
        >
          Descending preview
        </Checkbox>
      </Toolbar>
      {query.isFetching && <p role="status">Preparing preview…</p>}
      {query.error && <p role="alert">{query.error.message}</p>}
      <DataTable
        caption="Employee Directory import preview"
        tableClassName="directory-preview-table"
      >
        <thead>
          <tr>
            <th>Employee</th>
            <th>Email</th>
            <th>Department</th>
            <th>Manager</th>
            <th>SAP matching</th>
            <th>Validation</th>
          </tr>
        </thead>
        <tbody>
          {query.data?.items.map((row) => (
            <tr key={row.id}>
              <td>{row.name || 'Unnamed employee'}</td>
              <td>{row.email || 'Missing email'}</td>
              <td>{row.department || '—'}</td>
              <td>{row.manager.name || '—'}</td>
              <td>
                <StatusBadge
                  tone={row.sap_match === 'matched' ? 'success' : 'neutral'}
                >
                  {row.sap_match}
                </StatusBadge>
              </td>
              <td>
                <details>
                  <summary>
                    {row.validation.length
                      ? `${row.validation.length} warnings`
                      : 'Valid record'}
                  </summary>
                  <p>
                    {row.validation
                      .map((v) => sentenceCase(v))
                      .join(' · ') || 'No quality warnings.'}
                  </p>
                  <p>Manager relationship: {row.manager.status}</p>
                  <p>AD account: {row.account_status}</p>
                </details>
              </td>
            </tr>
          ))}
        </tbody>
      </DataTable>
      {query.data && !query.data.total && (
        <p>No preview records match these filters.</p>
      )}
      <Pagination
        label="Directory preview pages"
        total={query.data?.total || 0}
        offset={offset}
        limit={25}
        onChange={setOffset}
      />
    </div>
  )
}
