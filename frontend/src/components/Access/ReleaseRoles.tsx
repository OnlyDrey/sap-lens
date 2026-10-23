import { formatDate } from '@/lib/dateFormat'
import { AssignmentDateFilters, emptyDates, dateParams, datesActive, type AssignmentDates } from '@/components/Shared/AssignmentDateFilters'
import { ClearFilterButton } from '@/components/Shared/ClearFilterButton'
import { Select } from '@/components/Shared/Select';
import { useHistoryValue, type ReleaseDrill } from '@/hooks/useViewHistory';
import { List, Grid3X3 } from 'lucide-react';
import { useRecordNavigation, type RecordNavigationState } from "@/hooks/useRecordNavigation";
import { DetailNavigation, AssignmentStatus, DetailButton } from "@/components/Shared/InvestigationNavigation";
import { ReleaseFilter } from "./ReleaseFilter";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  accessQuery,
  type Assignment,
  type Cell,
  type Page,
  type ReleasePage,
  type ReleaseInfo,
} from "@/api/access";
import { RoleIdentifier } from "@/components/Shared/RoleIdentifier";
import {
  dates,
  EvidenceNote,
  Filter,
  inputClass,
  Pagination,
  QueryState,
} from "./Shared";

type Drill = ReleaseDrill;
export function ReleaseRoles({
  initialRole = "",
  onUser,
}: {
  initialRole?: string;
  onUser: (name: string) => void;
}) {
  const [assignmentDates, setAssignmentDates] = useState({ ...emptyDates });
  const dateKey = JSON.stringify(assignmentDates);
  const listScroll = useRef(0);
  const originFocus = useRef("");
  const originRole = useRef("");
  const openDrill = (value: Drill) => { listScroll.current = window.scrollY; originRole.current = value.role || ""; originFocus.current = document.activeElement?.getAttribute("aria-label") || ""; setDrill(value) };
  const [group, setGroup] = useState(""),
    [kind, setKind] = useState(""),
    [releaseGroup, setReleaseGroup] = useState(""),
    [strategy, setStrategy] = useState("");
  const [username, setUsername] = useState(""),
    [role, setRole] = useState(""),
    [status, setStatus] = useState(initialRole ? "all" : "active"),
    [sort, setSort] = useState("role_name"),
    [descending, setDescending] = useState(false);
  const [matrix, setMatrix] = useState(false),
    [matrixOffset, setMatrixOffset] = useState(0),
    [compareGroups, setCompareGroups] = useState(false),
    [offset, setOffset] = useState(0),
    [drill, setDrill] = useHistoryValue('release');
  const [query, setQuery] = useState({ username: "", role: "" });
  useEffect(() => {
    const t = setTimeout(() => setQuery(previous => previous.username === username && previous.role === role ? previous : { username, role }), 250);
    return () => clearTimeout(t);
  }, [username, role]);
  useEffect(() => {
    setOffset(0);
    setMatrixOffset(0);
  }, [
    group,
    kind,
    releaseGroup,
    strategy,
    query,
    status,
    sort,
    descending,
    compareGroups, dateKey,
  ]);
  const filters = { ...dateParams(assignmentDates), group, document_type: kind, release_group: releaseGroup, strategy, ...query, status, group_by_user_group: compareGroups, sort, descending };
  const navigation = useRecordNavigation('releases', { ...filters, status: drill?.status || status }, drill?.role || '', name => setDrill(previous => previous ? { ...previous, role: name } : previous));
  const result = useQuery({
    queryKey: [
      "release-roles",
      assignmentDates,
      group,
      kind,
      releaseGroup,
      strategy,
      query,
      status,
      compareGroups,
      sort,
      descending,
      offset,
      matrixOffset,
    ],
    queryFn: () =>
      accessQuery<ReleasePage>("releases", { ...filters, offset, matrix_offset: matrixOffset }),
  });
  useEffect(() => {
    if (!result.data || result.isFetching) return;
    const last = Math.max(0, Math.floor((result.data.total - 1) / result.data.limit) * result.data.limit);
    const lastMatrix = Math.max(0, Math.floor((result.data.matrix_total - 1) / 200) * 200);
    if (offset > last) setOffset(last);
    if (matrixOffset > lastMatrix) setMatrixOffset(lastMatrix);
  }, [result.data, result.isFetching, offset, matrixOffset]);
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
      group: compareGroups ? cell.user_group : group,
      document_type: cell.document_type,
      release_group: cell.release_group,
      strategy: cell.release_strategy,
    });
  return (
    <section aria-label="Release Roles" className="space-y-4">
      <h1 className="text-xl font-semibold">Release Roles</h1>
      <p className="text-sm">
        PR/PO release assignments from the User Access CSV. M and ALL are opaque
        naming tokens; no release-authority meaning is assumed.
      </p>
      <EvidenceNote />
      <div className="investigation-filters release-filters">
        <fieldset><legend>Release classification</legend><div className="filter-grid">
        <ReleaseFilter field="group" label="Release SAP User Group" value={group} onChange={setGroup} context={{ ...dateParams(assignmentDates), status }}/>
        <ReleaseFilter field="document_type" label="PR/PO" value={kind} onChange={setKind} context={{ ...dateParams(assignmentDates), group, status }}/>
        <ReleaseFilter field="release_group" label="Release Group" value={releaseGroup} onChange={setReleaseGroup} context={{ ...dateParams(assignmentDates), group, document_type:kind, status }}/>
        <ReleaseFilter field="strategy" label="Release Strategy" value={strategy} onChange={setStrategy} context={{ ...dateParams(assignmentDates), group, document_type:kind, release_group:releaseGroup, status }}/>
        </div></fieldset>
        <fieldset><legend>Assignment</legend><div className="filter-grid">
        <ReleaseFilter field="username" label="Release username" value={username} onChange={setUsername} context={{ ...dateParams(assignmentDates), group, document_type:kind, release_group:releaseGroup, strategy, status }}/>
        <ReleaseFilter field="role" label="Release role name" value={role} onChange={setRole} context={{ ...dateParams(assignmentDates), group, document_type:kind, release_group:releaseGroup, strategy, status }}/>
        <Filter label="Release assignment status">
          <Select
            className={inputClass}
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            {[
              ["active", "Currently valid"],
              ["all", "All, including expired / future / unknown"],
              ["expired", "Expired"],
              ["future", "Future"],
              ["unknown", "Unknown validity"],
            ].map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </Select>
        </Filter>
        </div></fieldset>
        <fieldset><legend>Display</legend><div className="filter-grid">
        <Filter label="Sort release roles">
          <Select
            className={inputClass}
            value={sort}
            onChange={(e) => setSort(e.target.value)}
          >
            {[
              ["role_name", "Role name"],
              ["document_type", "PR/PO"],
              ["release_group", "Release Group"],
              ["release_strategy", "Release Strategy"],
              ["assigned_users", "Assigned users"],
            ].map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </Select>
        </Filter>
        <label className="filter-toggle">
          <input
            type="checkbox"
            checked={descending}
            onChange={(e) => setDescending(e.target.checked)}
          />
          Descending
        </label>
        </div></fieldset>
      </div>
      <AssignmentDateFilters value={assignmentDates} onChange={setAssignmentDates}/>
      {(group || kind || releaseGroup || strategy || username || role || status !== 'active' || datesActive(assignmentDates) || descending || sort !== 'role_name') && <ClearFilterButton onClick={() => { setGroup(''); setKind(''); setReleaseGroup(''); setStrategy(''); setUsername(''); setRole(''); setStatus('active'); setAssignmentDates({ ...emptyDates }); setSort('role_name'); setDescending(false) }}>Reset filters</ClearFilterButton>}
      <div className="results-toolbar">
        <h2>Release assignments <span>{result.data?.total.toLocaleString() ?? '…'} {result.data?.total === 1 ? 'role' : 'roles'}</span></h2>
        <div className="segmented-control" role="group" aria-label="Release results view">
          <button aria-pressed={!matrix} onClick={() => setMatrix(false)}><List size={16} aria-hidden="true"/>Table</button>
          <button aria-pressed={matrix} onClick={() => setMatrix(true)}><Grid3X3 size={16} aria-hidden="true"/>Matrix</button>
        </div>
        {matrix && (
          <label className="filter-toggle">
            <input
              type="checkbox"
              checked={compareGroups}
              onChange={(e) => setCompareGroups(e.target.checked)}
            />
            Compare SAP User Groups
          </label>
        )}
      </div>
      <QueryState loading={result.isLoading} error={result.error} />
      {result.data && !result.data.loaded && (
        <p>No User Access CSV loaded. Configure it in Settings.</p>
      )}
      {result.data &&
        (matrix ? (
          <>
            <ReleaseMatrix
              cells={result.data.matrix}
              onCell={drillCell}
              compare={compareGroups}
              partial={result.data.matrix_total > result.data.matrix.length}
            />
            <Pagination
              offset={matrixOffset}
              limit={200}
              total={result.data.matrix_total}
              onChange={setMatrixOffset}
              label="Release matrix pages"
            />
          </>
        ) : (
          <>
            <div className="access-table release-directory-table">
              <table>
                <thead>
                  <tr>
                    <th>PR/PO</th>
                    <th>Release Group</th>
                    <th>Release Strategy</th>
                    <th>Role name</th>
                    <th>Assigned users</th>
                    <th>Assignment validity</th>
                  </tr>
                </thead>
                <tbody>
                  {result.data.items.map((r) => (
                    <tr key={r.role_name}>
                      <td>{r.document_type || "Unparsed"}</td>
                      <td>{r.release_group || "—"}</td>
                      <td>{r.release_strategy || "—"}</td>
                      <td>
                        <RoleIdentifier value={r.role_name} openLabel="Release role details" onOpen={() => openDrill({ role: r.role_name, group, username: query.username })}/>
                      </td>
                      <td>
                        {r.assigned_users} {r.assigned_users === 1 ? "user" : "users"} · {r.assignment_count} {r.assignment_count === 1 ? "record" : "records"}
                      </td>
                      <td>
                        <div className="flex flex-wrap gap-1">{r.statuses.map(status => <AssignmentStatus key={status} value={status}/>)}</div>
                        <span className="validity-evidence text-sm text-[var(--muted)]">
                          Observed range: {dates(r.valid_from, r.valid_to)}
                          {r.missing_dates ? " · Missing dates present" : ""};
                          inspect individual intervals.
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {result.data.total === 0 && (
              <p>
                No release assignments match. Unknown or future validity is
                excluded from “Currently valid”.
              </p>
            )}
            <Pagination
              offset={offset}
              total={result.data.total}
              onChange={setOffset}
              label="Release role pages"
            />
          </>
        ))}
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
    <div className="space-y-4">
      {groups.map((group) =>
        ["PR", "PO"].map((kind) => {
          const selected = cells.filter(
            (c) =>
              (!compare || c.user_group === group) && c.document_type === kind,
          );
          if (!selected.length) return null;
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
              <div className="access-table">
                <table
                  aria-label={`${compare ? (group || "Unknown group") + " " : ""}${kind} release matrix`}
                >
                  <thead>
                    <tr>
                      <th>Release Group / Strategy</th>
                      {strategies.map((s) => (
                        <th key={s}>{s}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r}>
                        <th scope="row">{r}</th>
                        {strategies.map((s) => {
                          const cell = selected.find(
                            (c) =>
                              c.release_group === r && c.release_strategy === s,
                          );
                          return (
                            <td key={s}>
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
          "This matrix is paginated. A dash means no cell is shown on this page, not a zero user count. "}
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
      } as Record<string, string | number | boolean>),
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
      </header>
      <div className="flex flex-wrap gap-3 items-end">
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
      <AssignmentDateFilters value={assignmentDates} onChange={onDatesChange} />
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
          {!result.data.items.length && (
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
