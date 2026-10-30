import {ExportCSVButton} from '@/components/Shared/ExportCSVButton'
import {useAssignmentCSVExport} from '@/hooks/useAssignmentCSVExport'
import { PageHeader } from '@/components/Shared/Presentation'
import { FileCheck2 as PageIcon } from 'lucide-react'
import { Button, ButtonGroup } from '@/components/Shared/Button'
import { SavedFilters } from '@/components/Shared/SavedFilters'
import { FilterLayout, FilterSection, PageToolbar, SortControl } from '@/components/Shared/FilterLayout'
import { AccessPackageBar } from '@/components/Shared/AccessPackageBar'
import { PackageToggle } from '@/components/Shared/PackageToggle'
import { Dialog } from '@/components/Shared/Dialog'
import { AccessPackagePanel } from '@/components/RoleList/AccessPackagePanel'
import { useAccessPackage } from '@/lib/accessPackage'
import { announceExport } from '@/lib/exportNotice'
import { useApplicationData } from '@/state/ApplicationData'
import { formatDate } from '@/lib/dateFormat'
import { AssignmentDateFilters, emptyDates, dateParams, datesActive, type AssignmentDates } from '@/components/Shared/AssignmentDateFilters'
import { ClearFilterButton } from '@/components/Shared/ClearFilterButton'
import { Select } from '@/components/Shared/Select';
import { useHistoryValue, type ReleaseDrill } from '@/hooks/useViewHistory';
import { List, Grid3X3, Plus, Check, Copy, Download } from 'lucide-react';
import { useRecordNavigation, type RecordNavigationState } from "@/hooks/useRecordNavigation";
import { DetailNavigation, AssignmentStatus, DetailButton } from "@/components/Shared/InvestigationNavigation";
import { ReleaseFilter, ReleaseMultiFilter } from "./ReleaseFilter";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  accessQuery,
  type Assignment,
  type Cell,
  type Page,
  type ReleasePage,
  type ReleaseInfo,
  type ReleaseRoleListItem,
} from "@/api/access";
import { RoleIdentifier } from "@/components/Shared/RoleIdentifier";
import {
  dates,
  EvidenceNote,
  Filter,
  inputClass,
  Pagination,
  PAGE_SIZES,
  QueryState,
} from "./Shared";

type Drill = ReleaseDrill;
export const RELEASE_SORTS = [
  { value: 'role_name', label: 'Role name' }, { value: 'document_type', label: 'PR/PO' }, { value: 'release_group', label: 'Release Group' },
  { value: 'release_strategy', label: 'Release Strategy' }, { value: 'assigned_users', label: 'Assigned users' },
]
const STATUS_OPTIONS = [['active', 'Currently valid'], ['all', 'All, including expired / future / unknown'], ['expired', 'Expired'], ['future', 'Future'], ['unknown', 'Unknown validity']]
/** More roles than this need an explicit confirmation before a bulk add. */
export const BULK_CONFIRM_THRESHOLD = 500
const textList = (value: unknown) => Array.isArray(value) ? [...new Set(value.filter((item): item is string => typeof item === 'string' && item.trim() !== '' && item.length <= 100))].slice(0, 50) : []
/** Release Area = first character of the Release Group (E2 -> E); null for missing or malformed groups. */
export const releaseAreaOf = (group: string | null | undefined) => /^[A-Za-z0-9]+$/.test(group?.trim() || '') ? group!.trim()[0].toUpperCase() : null

export function ReleaseRoles({
  initialRole = "",
  onUser,
}: {
  initialRole?: string;
  onUser: (name: string) => void;
}) {
  const {loading:dataLoading}=useApplicationData();
  const cart = useAccessPackage();
  const [packageOpen, setPackageOpen] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false), [confirmBulk, setConfirmBulk] = useState<ReleaseRoleListItem[] | null>(null);
  const [assignmentDates, setAssignmentDates] = useState({ ...emptyDates });
  const dateKey = JSON.stringify(assignmentDates);
  const listScroll = useRef(0);
  const originFocus = useRef("");
  const originRole = useRef("");
  const openDrill = (value: Drill) => { listScroll.current = window.scrollY; originRole.current = value.role || ""; originFocus.current = document.activeElement?.getAttribute("aria-label") || ""; setDrill(value) };
  const [userGroups, setUserGroups] = useState<string[]>([]),
    [kind, setKind] = useState(""),
    [releaseAreas, setReleaseAreas] = useState<string[]>([]),
    [releaseGroups, setReleaseGroups] = useState<string[]>([]),
    [strategies, setStrategies] = useState<string[]>([]);
  const [username, setUsername] = useState(""),
    [role, setRole] = useState(""),
    [status, setStatus] = useState(initialRole ? "all" : "active"),
    [sort, setSort] = useState("role_name"),
    [descending, setDescending] = useState(false);
  const [matrix, setMatrix] = useState(true),
    [matrixOffset, setMatrixOffset] = useState(0),
    [compareGroups, setCompareGroups] = useState(false),
    [offset, setOffset] = useState(0),
    [pageSize, setPageSize] = useState(20),
    [drill, setDrill] = useHistoryValue('release'),
    [usersOf, setUsersOf] = useState('');
  const [query, setQuery] = useState({ username: "", role: "" });
  useEffect(() => {
    const t = setTimeout(() => setQuery(previous => previous.username === username && previous.role === role ? previous : { username, role }), 250);
    return () => clearTimeout(t);
  }, [username, role]);
  const areaKey = releaseAreas.join(','), groupKey = releaseGroups.join(','), strategyKey = strategies.join(',');
  useEffect(() => {
    setOffset(0);
    setMatrixOffset(0);
  }, [userGroups.join('|'), kind, areaKey, groupKey, strategyKey, query, status, sort, descending, compareGroups, dateKey, pageSize]);
  // Release Groups outside the selected areas can no longer match; drop them so the filter never hides a contradiction.
  const changeAreas = (areas: string[]) => {
    setReleaseAreas(areas);
    if (areas.length) setReleaseGroups(previous => { const kept = previous.filter(value => areas.includes(releaseAreaOf(value) || '')); return kept.length === previous.length ? previous : kept });
  };
  const filters = { ...dateParams(assignmentDates), user_groups: userGroups, document_type: kind, release_areas: releaseAreas, release_groups: releaseGroups, strategies, ...query, status, group_by_user_group: compareGroups, sort, descending };
  const navigation = useRecordNavigation('releases', { ...filters, status: drill?.status || status }, drill?.role || '', name => setDrill(previous => previous ? { ...previous, role: name } : previous));
  const result = useQuery({
    queryKey: ["release-roles", assignmentDates, userGroups, kind, areaKey, groupKey, strategyKey, query, status, compareGroups, sort, descending, offset, matrixOffset, matrix, pageSize],
    queryFn: () =>
      accessQuery<ReleasePage>("releases", { ...filters, offset: matrix ? 0 : offset, limit: pageSize, matrix_offset: matrixOffset, matrix_complete:matrix, list_complete:false }),
  });
  useEffect(() => {
    if (!result.data || result.isFetching) return;
    const last = Math.max(0, Math.floor((result.data.total - 1) / result.data.limit) * result.data.limit);
    const lastMatrix = Math.max(0, Math.floor((result.data.matrix_total - 1) / 200) * 200);
    if (offset > last) setOffset(last);
    if (matrixOffset > lastMatrix) setMatrixOffset(lastMatrix);
  }, [result.data, result.isFetching, offset, matrixOffset]);
  const {group_by_user_group:_grouping,...exportFilters}=filters
  const assignmentExport=useAssignmentCSVExport('releases',exportFilters,result.data?.data_revision,result.data?.as_of)
  const roleListExport=useAssignmentCSVExport('release-roles',exportFilters,result.data?.data_revision,result.data?.as_of)
  const settled = !dataLoading && !result.isFetching && username === query.username && role === query.role
  /** Distinct technical roles for the current filters, complete across pages. */
  const filteredRoles = async () => {
    const response = await accessQuery<{ items: ReleaseRoleListItem[]; total: number }>('release-roles', exportFilters)
    return response.items
  }
  const bulk = async (action: (roles: ReleaseRoleListItem[]) => void | Promise<void>) => {
    setBulkBusy(true)
    try { await action(await filteredRoles()) }
    catch (error) { announceExport({ kind: 'error', message: error instanceof Error ? error.message : 'The filtered release roles could not be loaded.' }) }
    finally { setBulkBusy(false) }
  }
  const addRoles = (roles: ReleaseRoleListItem[]) => {
    const { added, existing } = cart.addMany(roles.map(item => item.role_name), 'release')
    announceExport({ kind: 'success', message: `Added ${added.toLocaleString()} release ${added === 1 ? 'role' : 'roles'} to the access package; ${existing.toLocaleString()} already selected.` })
  }
  const addFiltered = () => void bulk(roles => {
    if (!roles.length) return announceExport({ kind: 'info', message: 'No release roles match the current filters.' })
    if (roles.length > BULK_CONFIRM_THRESHOLD) return setConfirmBulk(roles)
    addRoles(roles)
  })
  const copyNames = () => void bulk(async roles => {
    if (!roles.length) return announceExport({ kind: 'info', message: 'No release roles match the current filters.' })
    try { await navigator.clipboard.writeText(roles.map(item => item.role_name).join('\n')); announceExport({ kind: 'success', message: `Copied ${roles.length.toLocaleString()} release role ${roles.length === 1 ? 'name' : 'names'}.` }) }
    catch { announceExport({ kind: 'error', message: 'Copy failed. Export the role list instead.' }) }
  })
  const activeFilterCount = [kind, username, role].filter(Boolean).length + (userGroups.length ? 1 : 0) + (strategies.length ? 1 : 0) + (releaseAreas.length ? 1 : 0) + (releaseGroups.length ? 1 : 0) + (status !== 'active' ? 1 : 0) + (datesActive(assignmentDates) ? 1 : 0);
  const clearAll = () => { setUserGroups([]); setKind(''); setReleaseAreas([]); setReleaseGroups([]); setStrategies([]); setUsername(''); setRole(''); setStatus('active'); setSort('role_name'); setDescending(false); setAssignmentDates({ ...emptyDates }) };
  if (drill)
    return (
      <ReleaseDetail
        assignmentDates={assignmentDates} onDatesChange={setAssignmentDates}
        onStatusChange={value => { setStatus(value); setDrill(previous => previous ? { ...previous, status: value } : previous) }}
        drill={drill}
        status={drill.status || status}
        onBack={() => { setDrill(null); requestAnimationFrame(() => { const buttons = [...document.querySelectorAll<HTMLButtonElement>('button[aria-label]')];
          const original = buttons.find(button => originRole.current ? button.getAttribute('aria-label') === 'Release role details' && button.textContent === originRole.current : button.getAttribute('aria-label') === originFocus.current);
          original?.focus({ preventScroll: true }); window.scrollTo(0, listScroll.current) }) }}
        onUser={onUser}
        navigation={navigation}
      />
    );
  const drillCell = (cell: Cell) =>
    openDrill({
      username: query.username,
      role_search: query.role,
      ungrouped: compareGroups && !cell.user_group,
      ...(compareGroups ? { group: cell.user_group } : { user_groups: userGroups }),
      document_type: cell.document_type,
      release_group: cell.release_group,
      strategy: cell.release_strategy,
    });
  const context = { ...dateParams(assignmentDates), status };
  return (
    <section aria-label="Release Roles" className="space-y-4">
      <PageHeader title="Release Roles" icon={<PageIcon size={22} aria-hidden="true"/>}/>
      <p className="text-sm">
        PR/PO release assignments from the User Access CSV. M and ALL are opaque
        naming tokens; no release-authority meaning is assumed.
      </p>
      <EvidenceNote />
      <FilterLayout label="Filters" activeCount={activeFilterCount} onClear={clearAll} clearDisabled={!activeFilterCount}
        toolbar={<PageToolbar lead={<ButtonGroup label="Release results view" value={matrix?'matrix':'table'} onChange={value=>setMatrix(value==='matrix')} options={[{value:'matrix',label:'Matrix',icon:<Grid3X3 size={16} aria-hidden="true"/>},{value:'table',label:'Table',icon:<List size={16} aria-hidden="true"/>}]}/>}>
          <SortControl label="Sort release roles" value={sort} options={RELEASE_SORTS} descending={descending} onChange={setSort} onDescending={setDescending} />
        </PageToolbar>}
        sidebar={<div className="grid min-w-0 gap-3" role="search" aria-label="Release role filters">
          <FilterSection title="Saved Filters">
            <SavedFilters showClear={false} view="release" state={{userGroups,kind,releaseAreas,releaseGroups,strategies,username,role,status,sort,descending,...assignmentDates}}
              apply={s=>{
                // Filters saved before multi-select stored one SAP User Group string.
                setUserGroups(Array.isArray(s.userGroups)?textList(s.userGroups):typeof s.group==='string'&&s.group?[s.group]:[]);if(typeof s.kind==='string')setKind(s.kind);if(Array.isArray(s.strategies))setStrategies(s.strategies.filter((v:unknown):v is string=>typeof v==='string'));else if(typeof s.strategy==='string'&&s.strategy)setStrategies([s.strategy]);
                if(typeof s.username==='string')setUsername(s.username);if(typeof s.role==='string')setRole(s.role);
                setReleaseAreas(textList(s.releaseAreas).map(value=>value.toUpperCase()));
                // Filters saved before multi-select stored one Release Group string.
                setReleaseGroups(Array.isArray(s.releaseGroups)?textList(s.releaseGroups):typeof s.releaseGroup==='string'&&s.releaseGroup?[s.releaseGroup]:[]);
                if(['active','expired','future','unknown','all'].includes(String(s.status)))setStatus(String(s.status));
                if(RELEASE_SORTS.some(option=>option.value===s.sort))setSort(String(s.sort));if(typeof s.descending==='boolean')setDescending(s.descending);
                setAssignmentDates(previous=>Object.fromEntries(Object.entries(previous).map(([k,v])=>[k,typeof s[k]===typeof v?s[k]:v])) as typeof previous)}}
              clear={clearAll}/>
          </FilterSection>
          <FilterSection title="Release classification">
            <ReleaseMultiFilter field="group" label="Release SAP User Group" values={userGroups} onChange={setUserGroups} context={context}/>
            <ReleaseFilter field="document_type" label="PR/PO" value={kind} onChange={setKind} context={{ ...context, user_groups:userGroups }}/>
            <ReleaseMultiFilter field="release_area" label="Release Area" values={releaseAreas} onChange={changeAreas} context={{ ...context, user_groups:userGroups, document_type:kind }}/>
            <ReleaseMultiFilter field="release_group" label="Release Group" values={releaseGroups} onChange={setReleaseGroups} context={{ ...context, user_groups:userGroups, document_type:kind, release_areas:releaseAreas }}/>
            <ReleaseMultiFilter field="strategy" label="Release Strategy" values={strategies} onChange={setStrategies} context={{ ...context, user_groups:userGroups, document_type:kind, release_areas:releaseAreas, release_groups:releaseGroups }}/>
          </FilterSection>
          <FilterSection title="Assignment">
            <ReleaseFilter field="username" label="Release username" placeholder="All · separate several with commas" value={username} onChange={setUsername} context={{ ...context, user_groups:userGroups, document_type:kind, release_areas:releaseAreas, release_groups:releaseGroups, strategies }}/>
            <ReleaseFilter field="role" label="Release role name" placeholder="All · separate several with commas" value={role} onChange={setRole} context={{ ...context, user_groups:userGroups, document_type:kind, release_areas:releaseAreas, release_groups:releaseGroups, strategies }}/>
            <Filter label="Release assignment status">
              <Select className={inputClass} value={status} onChange={(e) => setStatus(e.target.value)}>
                {STATUS_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </Select>
            </Filter>
            <AssignmentDateFilters value={assignmentDates} onChange={setAssignmentDates}/>
          </FilterSection>
        </div>}>
      <div className="grid min-w-0 gap-4">
      <div className="results-toolbar release-toolbar">
        <h2>Release assignments <span>{result.data?.total.toLocaleString() ?? '…'} {result.data?.total === 1 ? 'role' : 'roles'}</span></h2>
        <div className="release-bulk-actions" role="group" aria-label="Release actions">
          {matrix && (
            <label className="filter-toggle release-compare-toggle">
              <input type="checkbox" checked={compareGroups} onChange={(e) => setCompareGroups(e.target.checked)} />
              Compare SAP User Groups
            </label>
          )}
          <Button onClick={addFiltered} disabled={!settled || bulkBusy || !result.data?.total} title="Adds every distinct release role matching the filters, across pages, to the access package."><Plus size={16} aria-hidden="true"/>Add filtered roles</Button>
          <Button onClick={copyNames} disabled={!settled || bulkBusy || !result.data?.total} title="Copies the distinct filtered release role names, one per line."><Copy size={16} aria-hidden="true"/>Copy role names</Button>
          <Button loading={roleListExport.busy} onClick={()=>void roleListExport.download()} disabled={!settled || !result.data?.total} title="Exports the distinct filtered release roles (name, description, area, group, strategy, PR/PO). Assignment export is separate."><Download size={16} aria-hidden="true"/>Export role list</Button>
          <ExportCSVButton loading={assignmentExport.busy} disabled={dataLoading||result.isFetching||!result.data?.export_assignments||username!==query.username||role!==query.role} title="Exports every release assignment matching these filters and date bounds, across pages. Table and Matrix use the same assignment set." onClick={()=>void assignmentExport.download()}/>
        </div>
      </div>
      <p className="ui-description">Export scope: {result.data?.export_assignments?.toLocaleString()??'…'} matching user–release-role assignments across all pages; identical in Table and Matrix.</p>
      <QueryState loading={result.isLoading || (dataLoading && !result.data?.loaded)} error={result.error} />
      {result.data && !result.data.loaded && !dataLoading && (
        <p>No User Access CSV loaded. Configure it in Settings.</p>
      )}
      {result.data &&
        (matrix ? (
          <>
            <ReleaseMatrix
              cells={result.data.matrix}
              onCell={drillCell}
              compare={compareGroups}
              partial={result.data.matrix_total>result.data.matrix.length}
            />

          </>
        ) : (
          <>
            <div className="access-table release-directory-table" role="region" aria-label="Release role results" tabIndex={0} data-density="compact">
              <table>
                <thead>
                  <tr>
                    <th>Role name</th>
                    <th>PR/PO</th>
                    <th>Area</th>
                    <th>Group</th>
                    <th>Strategy</th>
                    <th data-align="end">Users</th>
                    <th>Assignment validity</th>
                    <th className="col-actions">Package</th>
                  </tr>
                </thead>
                <tbody>
                  {result.data.items.map((r) => (
                    <tr key={r.role_name}>
                      <td>
                        <RoleIdentifier value={r.role_name} openLabel="Release role details" onOpen={() => openDrill({ role: r.role_name, user_groups: userGroups, username: query.username })}/>
                      </td>
                      <td>{r.document_type || "Unparsed"}</td>
                      <td>{r.release_area || "—"}</td>
                      <td>{r.release_group || "—"}</td>
                      <td>{r.release_strategy || "—"}</td>
                      <td data-align="end" title={`${r.assignment_count} assignment ${r.assignment_count === 1 ? "record" : "records"}`}>
                        <button type="button" className="role-count-button" aria-label={`Show ${r.assigned_users} ${r.assigned_users === 1 ? 'user' : 'users'} with ${r.role_name}`} onClick={() => setUsersOf(r.role_name)}><strong>{r.assigned_users}</strong></button>
                      </td>
                      <td>
                        <div className="release-validity">
                          {r.statuses.map(status => <AssignmentStatus key={status} value={status}/>)}
                          <span className="validity-evidence">{dates(r.valid_from, r.valid_to)}{r.missing_dates ? " · Missing dates present" : ""}</span>
                        </div>
                      </td>
                      <td className="col-actions">
                        <PackageToggle active={cart.has(r.role_name)} label={cart.has(r.role_name) ? `Remove ${r.role_name} from access package` : `Add ${r.role_name} to access package`}
                          onToggle={() => cart.has(r.role_name) ? cart.remove(r.role_name) : cart.add(r.role_name, 'release')}>
                          {cart.has(r.role_name) ? <Check className="w-3.5 h-3.5" strokeWidth={3} /> : <Plus className="w-3.5 h-3.5" strokeWidth={2.5} />}
                        </PackageToggle>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination label="Release role pages" offset={offset} total={result.data.total} limit={pageSize} onChange={setOffset} pageSizes={PAGE_SIZES} onPageSize={setPageSize} />
            {result.data.total === 0 && (
              <p>
                No release assignments match. Unknown or future validity is
                excluded from “Currently valid”.
              </p>
            )}

          </>
        ))}
      </div>
      </FilterLayout>
      {packageOpen && <AccessPackagePanel onClose={() => setPackageOpen(false)} />}
      {usersOf && <ReleaseRoleUsersPanel role={usersOf} filters={exportFilters} status={status} dates={assignmentDates} onUser={onUser} onClose={() => setUsersOf('')} />}
      {cart.items.length > 0 && <div className="floating-action-stack">
      <AccessPackageBar onOpen={() => setPackageOpen(true)} /></div>}
      {confirmBulk && <Dialog title="Add many release roles?" onClose={() => setConfirmBulk(null)}
        footer={<><Button variant="ghost" onClick={() => setConfirmBulk(null)}>Cancel</Button><Button variant="primary" onClick={() => { addRoles(confirmBulk); setConfirmBulk(null) }}>Add {confirmBulk.length.toLocaleString()} roles</Button></>}>
        <p>The current filters match {confirmBulk.length.toLocaleString()} distinct release roles. All of them will be added to the access package; roles already in the package are kept once.</p>
      </Dialog>}
    </section>
  );
}

function ReleaseMatrix({
  cells,
  onCell,
  compare,
  partial,
}: {
  cells: Cell[];
  onCell: (c: Cell) => void;
  compare: boolean;
  partial: boolean;
}) {
  if (!cells.length)
    return (
      <p>
        No parsed release roles match. Unparsed names remain available in Table
        view.
      </p>
    );
  const groups = [...new Set(cells.map((c) => (compare ? c.user_group : "")))];
  return (
    <div className="release-matrices">
      {groups.map((group) =>
        ["PR", "PO"].map((kind) => {
          const selected = cells.filter(
            (c) =>
              (!compare || c.user_group === group) && c.document_type === kind,
          );
          if (!selected.length) return null;
          const lookup=new Map(selected.map(cell=>[`${cell.release_group}|||${cell.release_strategy}`,cell]))
          const maximum=Math.max(1,...selected.map(cell=>cell.user_count))
          const strategies = [
              ...new Set(selected.map((c) => c.release_strategy)),
            ].sort(),
            rows = [...new Set(selected.map((c) => c.release_group))].sort();
          return (
            <div key={`${group}-${kind}`}>
              <h2 className="font-semibold">
                {compare ? `${group || "Unknown group"} · ` : ""}
                {kind} · distinct users
              </h2>
              <div className="access-table matrix-scroll" role="region" aria-label={`${kind} release matrix scroll area`} tabIndex={0}>
                <table
                  className="release-matrix" aria-label={`${compare ? (group || "Unknown group") + " " : ""}${kind} release matrix`}
                >
                  <thead>
                    <tr>
                      <th scope="col">Release group</th>
                      {strategies.map((s) => (
                        <th scope="col" key={s}>{s}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r}>
                        <th scope="row">{r}</th>
                        {strategies.map((s) => {
                          const cell = lookup.get(`${r}|||${s}`);
                          return (
                            <td key={s} data-intensity={!cell?undefined:cell.user_count===0?0:Math.ceil(3*cell.user_count/maximum)}>
                              {cell ? (
                                <DetailButton
                                  aria-label={`Investigate ${compare ? (group || "Unknown group") + " " : ""}${kind} ${r} ${s}: ${cell.user_count} users`}
                                  onClick={() => onCell(cell)}
                                >
                                  {cell.user_count}
                                </DetailButton>
                              ) : partial ? (
                                "—"
                              ) : (
                                "0"
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        }),
      )}
      <p className="text-xs text-[var(--muted)]">
        {partial &&
          "Matrix data is incomplete. A dash means no supplied cell, not a zero user count. "}
        A user is counted once per cell. Group comparisons use the group on each
        source assignment; counts across groups are not additive. Unparsed roles
        are excluded from the matrix only.
      </p>
    </div>
  );
}

function ReleaseDetail({
  drill,
  status,
  onBack,
  onUser,
  navigation,
  assignmentDates,
  onDatesChange,
  onStatusChange,
}: {
  navigation: RecordNavigationState
  drill: Drill
  status: string
  onBack: () => void
  onUser: (name: string) => void
  assignmentDates: AssignmentDates
  onDatesChange: (value: AssignmentDates) => void
  onStatusChange: (value: string) => void
}) {
  const {loading:dataLoading}=useApplicationData();
  const [offset, setOffset] = useState(0)
  const dateKey = JSON.stringify(assignmentDates)
  useEffect(() => setOffset(0), [drill, dateKey, status])
  const result = useQuery({
    queryKey: ['release-assignments', drill, status, offset, assignmentDates],
    queryFn: () =>
      accessQuery<
        Page<Assignment> & {
          distinct_users: number
          role_info: ReleaseInfo | null
        }
      >('release-assignments', {
        ...drill,
        ...dateParams(assignmentDates),
        status,
        offset,
      } as Record<string, string | number | boolean | string[]>),
  })
  const info = result.data?.role_info
  return (
    <section aria-label="Release role details" className="space-y-4">
      <DetailNavigation
        parent="Release Roles"
        current={drill.role || 'Release role details'}
        onBack={onBack}
        {...navigation}
      />
      <header className="information-card space-y-3">
        <h1 className="text-xl font-semibold">Release role details</h1>
        {drill.role && <RoleIdentifier value={drill.role} />}
        <dl
          className="release-role-metadata"
          aria-label="Release role metadata"
        >
          <div>
            <dt>Release type</dt>
            <dd>
              {drill.role ? (result.isLoading ? '…' : info?.document_type || 'Unparsed') : drill.document_type || 'All'}
            </dd>
          </div>
          <div>
            <dt>Release group</dt>
            <dd>{(drill.role ? info?.release_group : drill.release_group) || '—'}</dd>
          </div>
          <div>
            <dt>Release strategy</dt>
            <dd>{(drill.role ? info?.release_strategy : drill.strategy) || '—'}</dd>
          </div>
          <div>
            <dt>Distinct assigned users</dt>
            <dd>{result.data?.distinct_users ?? '…'}</dd>
          </div>
          <div>
            <dt>Assignment records</dt>
            <dd>{result.data?.total ?? '…'}</dd>
          </div>
        </dl>
        {drill.group && <p>SAP User Group: {drill.group}</p>}
        {!!drill.user_groups?.length && <p>SAP User Group: {drill.user_groups.join(', ')}</p>}
      </header>
      <div className="release-assignment-toolbar flex flex-wrap gap-3 items-end">
        <Filter label="Assignment status">
          <Select
            className={inputClass}
            value={status}
            onChange={(event) => onStatusChange(event.target.value)}
          >
            <option value="active">Currently valid</option>
            <option value="all">All assignments</option>
            <option value="expired">Expired</option>
            <option value="future">Future</option>
            <option value="unknown">Unknown validity</option>
          </Select>
        </Filter>
        <AssignmentDateFilters value={assignmentDates} onChange={onDatesChange} />
        {(datesActive(assignmentDates) || status !== 'active') && (
          <ClearFilterButton
            onClick={() => {
              onDatesChange({ ...emptyDates })
              onStatusChange('active')
            }}
          >
            Clear assignment filters
          </ClearFilterButton>
        )}
      </div>
      <QueryState loading={result.isLoading} error={result.error} />
      {result.data && (
        <>
          <p>
            {drill.role
              ? 'Counts reflect matching assignment records.'
              : `${result.data.distinct_users} distinct users · ${result.data.total} assignment records in the current filters`}
          </p>
          <div
            className="access-table"
            role="region"
            aria-label="Release role user assignments"
            tabIndex={0}
          >
            <table>
              <thead>
                <tr>
                  {!drill.role && <th>Exact assigned role</th>}
                  <th>Username</th>
                  <th>User group</th>
                  <th>Valid from</th>
                  <th>Valid to</th>
                  <th>Assignment status</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {result.data.items.map((a) => (
                  <tr key={a.id}>
                    {!drill.role && (
                      <td>
                        <RoleIdentifier value={a.role_name} />
                      </td>
                    )}
                    <td>
                      <RoleIdentifier
                        value={a.username}
                        label="username"
                        onOpen={() => onUser(a.username)}
                        openLabel={`Open user ${a.username}`}
                      />
                    </td>
                    <td>{a.user_group || 'Unknown'}</td>
                    <td className="assignment-date">
                      {formatDate(a.valid_from)}
                    </td>
                    <td className="assignment-date">
                      {formatDate(a.valid_to)}
                    </td>
                    <td>
                      <AssignmentStatus value={a.status} />
                    </td>
                    <td>
                      <DetailButton
                        onClick={() => onUser(a.username)}
                        aria-label={`View user details ${a.username}`}
                      >
                        View user details
                      </DetailButton>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!result.data.items.length && !dataLoading && (
            <p>No assignments match these assignment filters.</p>
          )}
          <Pagination
            offset={offset}
            total={result.data.total}
            onChange={setOffset}
            label="Release assignment pages"
          />
        </>
      )}
      <EvidenceNote />
    </section>
  )
}

/** Users holding one release role, within the list's validity scope and filters. Names are shown only when the user source carries them. */
function ReleaseRoleUsersPanel({ role, filters, status, dates, onUser, onClose }: { role: string; filters: Record<string, unknown>; status: string; dates: AssignmentDates; onUser: (name: string) => void; onClose: () => void }) {
  const [offset, setOffset] = useState(0)
  const scope = Object.fromEntries(Object.entries({ group: filters.group, user_groups: filters.user_groups, username: filters.username, document_type: filters.document_type, strategies: filters.strategies, status }).filter(([, value]) => value !== undefined && value !== '' && !(Array.isArray(value) && !value.length)))
  const result = useQuery({
    queryKey: ['release-role-users', role, scope, dates, offset],
    queryFn: () => accessQuery<Page<Assignment & { display_name?: string }> & { distinct_users: number }>('release-assignments', { ...(scope as Record<string, string>), ...dateParams(dates), role, offset } as Record<string, string | number | boolean>),
  })
  const exportFilters = { ...(filters as Record<string, string | string[] | boolean>), role, release_areas: [], release_groups: [] }
  const download = useAssignmentCSVExport('releases', exportFilters as never, result.data?.data_revision, result.data?.as_of)
  const data = result.data
  return (
    <Dialog title="Users with this release role" onClose={onClose}
      footer={<ExportCSVButton loading={download.busy} disabled={!data?.total} onClick={() => void download.download()} title="Exports the matching assignments of this release role." />}>
      <div className="release-users-role"><span className="ui-description">Release role</span><RoleIdentifier value={role} label="release role" /></div>
      <QueryState loading={result.isLoading} error={result.error} />
      {data && <>
        <p role="status" className="ui-description">{data.distinct_users} {data.distinct_users === 1 ? 'user' : 'users'} · {data.total} assignment {data.total === 1 ? 'record' : 'records'} in the current validity scope</p>
        <div className="access-table" role="region" aria-label="Users with this release role" tabIndex={0} data-density="compact">
          <table>
            <thead><tr><th>SAP username</th><th>Name</th><th>SAP User Group</th><th>Assignment</th><th className="col-actions"><span className="sr-only">Details</span></th></tr></thead>
            <tbody>{data.items.map((a) => (
              <tr key={a.id}>
                <td><RoleIdentifier value={a.username} label="SAP username" onOpen={() => onUser(a.username)} openLabel={`Open user ${a.username}`} /></td>
                <td className="release-user-name">{a.display_name || <span className="text-muted">Not available</span>}</td>
                <td className="whitespace-nowrap">{a.user_group || 'Unknown'}</td>
                <td><AssignmentStatus value={a.status} /><dl className="validity-dates"><div><dt>Valid from</dt><dd>{formatDate(a.valid_from)}</dd></div><div><dt>Valid to</dt><dd>{formatDate(a.valid_to)}</dd></div></dl></td>
                <td className="col-actions"><DetailButton onClick={() => onUser(a.username)} aria-label={`View user details ${a.username}`}>Details</DetailButton></td>
              </tr>))}</tbody>
          </table>
        </div>
        {!data.items.length && <p>No assignments match the current validity scope.</p>}
        <Pagination offset={offset} total={data.total} onChange={setOffset} label="Release role user pages" />
      </>}
    </Dialog>
  )
}
