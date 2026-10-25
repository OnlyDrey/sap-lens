import { useRoles } from '@/hooks/useRoles'
import { FilterChip } from '@/components/Shared/FilterChip'
import { Button } from '@/components/Shared/Button'
import { SecondaryNavigation, ContentTabs } from '@/components/Shared/Navigation'
import { UserComparison, type ComparisonContext } from './UserComparison'
import { SavedFilters } from '@/components/Shared/SavedFilters'
import { AccountReview } from './AccountReview'
import { AccountStatus } from '@/components/Shared/AccountStatus'
import { useApplicationData } from '@/state/ApplicationData'
import { AssignmentDateFilters, emptyDates, dateParams, datesActive } from '@/components/Shared/AssignmentDateFilters'
import { UserProfile } from './UserProfile'
import { TransactionFilter, useTransactionFilter } from '@/components/Shared/TransactionFilter';
import { ClearFilterButton } from '@/components/Shared/ClearFilterButton';
import { Select } from '@/components/Shared/Select';
import { formatDate } from '@/lib/dateFormat';
import { exportAssignments } from '@/lib/accessExport';
import { ArrowRight, Download } from 'lucide-react';
import { useHistoryValue, useViewHistory, userAccessHref } from '@/hooks/useViewHistory';
import { useRecordNavigation, type RecordNavigationState } from "@/hooks/useRecordNavigation";
import { DetailNavigation, EvidenceBadge, LockStatus, AssignmentStatus } from "@/components/Shared/InvestigationNavigation";
import { Combobox } from "@/components/Shared/Combobox";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  accessQuery,
  type Page,
  type UserRow,
  type UserDetail,
  type Assignment,
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

export function UserAccess({
  initialUser,
  initialRole = "",
  initialTcode = "",
  onRole,
  onRelease,
}: {
  initialUser?: string;
  initialRole?: string;
  initialTcode?: string;
  onRole: (role: string) => void;
  onRelease: (role: string) => void;
}) {
  const {view:comparisonView,change:changeComparison}=useViewHistory();
  const comparisonContext=comparisonView.userComparison;
  const setComparisonContext=(state:ComparisonContext)=>changeComparison({userComparison:state},true);
  const [compareInitial,setCompareInitial]=useState('');
  const [accessMode,setAccessMode]=useHistoryValue('accessMode');
  const modeButtons=<SecondaryNavigation label="User Access view" items={(['directory','review','compare'] as const).map((value,index)=>({value,label:['User directory','Account Review','Compare users'][index],href:userAccessHref(value),active:(accessMode||'directory')===value,onSelect:()=>{setCompareInitial('');setAccessMode(value)}}))}/>;
  const {loading:dataLoading}=useApplicationData();
  const listScroll = useRef(0);
  const originUser = useRef(initialUser || "");
  const restoreList = useRef(false);
  const openUser = (username: string) => { listScroll.current = window.scrollY; originUser.current = username; setSelected(username) };
  const [search, setSearch] = useState(""),
    [sort, setSort] = useState("username"),
    [descending, setDescending] = useState(false);
  const [group, setGroup] = useState(""),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useHistoryValue('user');
  const [role, setRole] = useState(initialRole),
    [expired, setExpired] = useState(false);
  const [roleSearch, setRoleSearch] = useState(''), [roleTerm, setRoleTerm] = useState('')
  useEffect(() => { const timer = setTimeout(() => setRoleTerm(roleSearch), 200); return () => clearTimeout(timer) }, [roleSearch])
  const roleOptions = useRoles(undefined, roleTerm)
  const directoryTransaction = useTransactionFilter()
  const [transactionMode,setTransactionMode] = useState<'and'|'or'>('and')
  useEffect(()=>{ directoryTransaction.setChips(initialTcode ? [initialTcode.trim().toUpperCase()] : []) },[initialTcode])
  useEffect(()=>{ if (!directoryTransaction.codes.length) setTransactionMode('and') },[directoryTransaction.key])
  const clearEvidence = () => {setRole(''); directoryTransaction.clear(); setTransactionMode('and')}
  const [term, setTerm] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setTerm(search), 250);
    return () => clearTimeout(t);
  }, [search]);
  useEffect(() => {
    setOffset(0);
  }, [term, group, sort, descending, role, directoryTransaction.deferredKey, transactionMode, expired]);
  const filters = { search: term, group, sort, descending, role, tcodes: directoryTransaction.deferredCodes, transaction_mode: transactionMode, show_expired: expired };
  const navigation = useRecordNavigation('users', filters, selected, setSelected);
  const result = useQuery({
    queryKey: [
      "access-users",
      term,
      group,
      sort,
      descending,
      role,
      directoryTransaction.deferredCodes,
      transactionMode,
      offset,
      expired,
    ],
    queryFn: () =>
      accessQuery<Page<UserRow>>("users", { ...filters, offset }),
  });
  useEffect(() => {
    if (!result.data || result.isFetching) return;
    const limit = result.data.limit;
    const last = Math.max(0, Math.floor((result.data.total - 1) / limit) * limit);
    if (offset > last) setOffset(last);
  }, [result.data, result.isFetching, offset]);
  const previousSelected = useRef(selected);
  useLayoutEffect(() => {
    if (!selected && previousSelected.current) restoreList.current = true;
    previousSelected.current = selected;
    if (selected || !restoreList.current || !result.data || result.isFetching) return;
    const frame = requestAnimationFrame(() => {
      restoreList.current = false;
      const buttons = [...document.querySelectorAll<HTMLButtonElement>('[data-user]')];
      const original = buttons.find(button => button.dataset.user === originUser.current) || buttons[0];
      original?.focus({ preventScroll: true });
      window.scrollTo(0, listScroll.current);
    });
    return () => cancelAnimationFrame(frame);
  }, [selected, result.data, result.isFetching]);
  if(accessMode==='compare') return <><div hidden={!!selected}>{modeButtons}<UserComparison context={comparisonContext} onContext={setComparisonContext} initialUser={compareInitial} onUser={openUser} onRole={onRole} onTransaction={code=>{setCompareInitial('');directoryTransaction.setInput('');directoryTransaction.setChips([code]);setAccessMode('directory')}}/></div>{selected&&<UserDetails username={selected} onCompare={()=>{setCompareInitial(selected);setSelected('')}} onBack={()=>setSelected('')} onRole={onRole} onRelease={onRelease} navigation={{index:-1,total:0,loading:false,error:null,missing:false,onPrevious:undefined,onNext:undefined}}/>}</>;
  if(accessMode==='review') return <><div hidden={!!selected}>{modeButtons}<AccountReview onUser={openUser}/></div>{selected&&<UserDetails username={selected} onCompare={()=>{setCompareInitial(selected);setSelected('');setAccessMode('compare')}} onBack={()=>setSelected('')} onRole={onRole} onRelease={onRelease} navigation={{index:-1,total:0,loading:false,error:null,missing:false,onPrevious:undefined,onNext:undefined}}/>}</>;
  if (selected)
    return (
      <UserDetails
        username={selected}
        onCompare={()=>{setCompareInitial(selected);setSelected('');setAccessMode('compare')}}
        onBack={() => { restoreList.current = true; setSelected("") }}
        onRole={onRole}
        onRelease={onRelease}
        navigation={navigation}
      />
    );
  return (
    <section aria-label="User Access" className="space-y-4">
      {modeButtons}<h1 className="text-xl font-semibold">User Access</h1>
      <EvidenceNote />
      <SavedFilters showClear={false} view="users" state={{search,group,sort,descending,role,tcodes:directoryTransaction.codes,transactionMode,expired}} apply={s=>{if(typeof s.search==='string')setSearch(s.search);if(typeof s.group==='string')setGroup(s.group);if(typeof s.sort==='string'&&['username','group','first_name','last_name','email','account_status','relevant_roles'].includes(s.sort))setSort(s.sort);if(typeof s.descending==='boolean')setDescending(s.descending);if(typeof s.role==='string')setRole(s.role);if(Array.isArray(s.tcodes)){directoryTransaction.setInput('');directoryTransaction.setChips(s.tcodes)};if(s.transactionMode==='and'||s.transactionMode==='or')setTransactionMode(s.transactionMode);if(typeof s.expired==='boolean')setExpired(s.expired)}} clear={()=>{setSearch('');setGroup('');setSort('username');setDescending(false);setRole('');directoryTransaction.clear();setTransactionMode('and');setExpired(false)}}/>

      <div className="investigation-filters user-filters"><fieldset><legend>User directory</legend><div className="directory-filter-grid">
        <Filter label="Search users">
          <input
            className={inputClass}
            value={search}
            maxLength={256}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Username, name, email or group"
          />
        </Filter>
        <Filter label="SAP User Group">
          <Combobox label="SAP User Group" value={group} options={result.data?.groups || []} onChange={setGroup} placeholder="All groups; type a group to filter"/>
        </Filter>
        <Filter label="Filter users by role">
          <Combobox label="Filter users by role" value={role} options={(roleOptions.data || []).slice(0,100).map(item=>item.agr_name)} onChange={setRole} onSearch={setRoleSearch} serverFiltered loading={roleOptions.isFetching} hasMore={(roleOptions.data?.length||0)>100} optionLabel={value=>{const item=roleOptions.data?.find(item=>item.agr_name===value);return item?.text ? `${value} · ${item.text}` : value}} placeholder="Role name or description"/>
        </Filter>
        <div className="directory-sort"><Filter label="Sort users">
          <Select aria-label="Sort users"
            className={inputClass}
            value={sort}
            onChange={(e) => setSort(e.target.value)}
          >
            {[
              ["username", "Username"],
              ["group", "User group"],
              ["first_name", "First name"],
              ["last_name", "Last name"],
              ["email", "Email"],
              ["account_status", "Account status"],
              ["relevant_roles", "Relevant role count"],
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
        </div>
      <section className="directory-transaction" aria-label="User transaction filter">
        <TransactionFilter label="Filter users by transaction" filter={directoryTransaction} mode={transactionMode} onModeChange={setTransactionMode} showClear={false} chipPrefix="Transaction: "/>

      </section>
        <label className="filter-toggle">
          <input
            type="checkbox"
            checked={expired}
            onChange={(e) => setExpired(e.target.checked)}
          />
          Show expired assignments
        </label>
        <ClearFilterButton className="directory-clear" disabled={!search && !group && sort==='username' && !descending && !expired && !role && !directoryTransaction.codes.length} onClick={()=>{setSearch('');setTerm('');setGroup('');setSort('username');setDescending(false);setExpired(false);clearEvidence()}}>Clear filters</ClearFilterButton>
      </div></fieldset></div>
      {(role || group || search || expired) && <div className="active-filter-row" aria-label="Active user filters">
        {expired && <FilterChip removeLabel="Remove expired assignment filter" onRemove={()=>setExpired(false)}>Include Expired Assignments</FilterChip>}
        {role && <FilterChip removeLabel="Remove role filter" onRemove={()=>setRole('')}>Role: {role}</FilterChip>}
        {group && <FilterChip removeLabel="Remove user group filter" onRemove={()=>setGroup('')}>User Group: {group}</FilterChip>}
        {search && <FilterChip removeLabel="Remove user search filter" onRemove={()=>{setSearch('');setTerm('')}}>Search: {search}</FilterChip>}
      </div>}
      <QueryState loading={result.isLoading || (dataLoading && !result.data?.loaded)} error={result.error} />
      {result.data && !result.data.loaded && !dataLoading && (
        <p>
          No User Access CSV loaded. Choose the second source in Settings → Data
          Source &amp; Import.
        </p>
      )}
      {result.data?.loaded && !result.data.catalogue_loaded && (
        <p role="status">
          No role catalogue loaded. Assignments are retained as Unmapped;
          transaction access is not inferred. Transaction filters cannot be evaluated and are not applied; user search and group filters still apply.
        </p>
      )}
      {result.data && (
        <>
          <h2 className="text-base font-semibold">User directory <span className="text-sm font-normal text-[var(--muted)]">{result.data.total.toLocaleString()} {result.data.total === 1 ? 'user' : 'users'}</span></h2>
          <div className="access-table user-directory-table">
            <table>
              <thead>
                <tr>
                  {[
                    "User group",
                    "Username",
                    "First name",
                    "Last name",
                    "Email",
                    "User status",
                    "Lock status",
                    "Relevant roles",
                  ].map((h) => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.data.items.map((user) => (
                  <tr key={user.user_key}>
                    <td>
                      {user.groups
                        .map((group) => group || "Unknown group")
                        .join(", ") || "Unknown"}
                    </td>
                    <td>
                      <RoleIdentifier
                        value={user.username}
                        label="username"
                        onOpen={() => openUser(user.username)}
                        openLabel={user.username}
                        openButtonProps={{ 'data-user': user.username }}
                      />
                    </td>
                    <td>{user.first_name || "—"}</td>
                    <td>{user.last_name || "—"}</td>
                    <td>{user.email || "—"}</td>
                    <td aria-label="Account validity">
                      <AccountStatus value={user.account_status}/>
                    </td><td aria-label="Account lock"><LockStatus value={user.lock_status}/>
                    </td>
                    <td><button className="role-count-button" aria-label={`View ${user.relevant_roles} relevant roles for ${user.username}`} onClick={() => openUser(user.username)}>{user.relevant_roles.toLocaleString()} <span>{user.relevant_roles === 1 ? "role" : "roles"}</span></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.data.total === 0 && result.data.loaded && (
            <p>No users match these filters.</p>
          )}
          <Pagination
            offset={offset}
            total={result.data.total}
            onChange={setOffset}
            label="User pages"
          />
        </>
      )}
    </section>
  );
}

function UserDetails({
  username,
  onCompare,
  onBack,
  onRole,
  onRelease,
  navigation,
}: {
  navigation: RecordNavigationState;
  username: string;
  onCompare: () => void;
  onBack: () => void;
  onRole: (role: string) => void;
  onRelease: (role: string) => void;
}) {
  const {loading:dataLoading}=useApplicationData();
  const [exporting, setExporting] = useState(false);
  const [exportMessage, setExportMessage] = useState('');
  const [assignmentDates, setAssignmentDates] = useState({ ...emptyDates });
  const dateKey = JSON.stringify(assignmentDates);
  const transaction = useTransactionFilter(username);
  const transactionCodes = transaction.deferredCodes;
  const exportGeneration = useRef(0);
  const [scope, setScope] = useState("all"),
    [status, setStatus] = useState(""),
    [offset, setOffset] = useState(0),
    [accountOffset, setAccountOffset] = useState(0),
    [nameOffset, setNameOffset] = useState(0),
    [emailOffset, setEmailOffset] = useState(0);
  useEffect(() => { setOffset(0) }, [scope, status, username, transaction.key, dateKey]);
  useEffect(() => { exportGeneration.current++; setExportMessage(''); return () => { exportGeneration.current++ } }, [username, scope, status, transaction.key, dateKey]);

  useEffect(() => { setAssignmentDates({ ...emptyDates }); setAccountOffset(0); setNameOffset(0); setEmailOffset(0) }, [username]);
  const result = useQuery({
    queryKey: [
      "access-user",
      transactionCodes,
      assignmentDates,
      username,
      scope,
      status,
      offset,
      accountOffset,
      nameOffset,
      emailOffset,
    ],
    placeholderData: previous => previous?.username === username ? previous : undefined,
    queryFn: () =>
      accessQuery<UserDetail>(`users/${encodeURIComponent(username)}`, {
        scope,
        ...dateParams(assignmentDates),
        tcodes: transactionCodes,
        status: status === "all" ? "" : status,
        show_expired: status === "all",
        offset,
        account_offset: accountOffset,
        name_offset: nameOffset,
        email_offset: emailOffset,
      }),
  });
  const user = result.isError ? undefined : result.data;
  return (
    <section aria-label="User details" className="space-y-4">
      <DetailNavigation parent="User Access" current={username} onBack={onBack} {...navigation}/>
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-xl font-semibold">User details</h1><Button className="settings-secondary-button" onClick={onCompare}>Compare users</Button></div>
      <QueryState loading={result.isLoading || (dataLoading && !result.data)} error={dataLoading && !result.data ? null : result.error} />
      {user && (
        <>
          <UserProfile user={user}/>
          {user.account_total > 1 && <details className="settings-advanced"><summary>User validity and account evidence · {user.account_total} source records</summary>
            <p className="text-sm text-[var(--muted)]">Distinct source records are retained below; a summary does not override conflicting validity or lock evidence.</p>
            <div className="access-table"><table><thead><tr><th>User group</th><th>User validity</th><th>Account status</th><th>Lock status</th><th>User type</th></tr></thead><tbody>
              {user.accounts.map((a, i) => <tr key={i}><td>{a.user_group || 'Unknown'}</td><td>{dates(a.valid_from, a.valid_to)}</td><td><AccountStatus value={a.status}/></td><td><LockStatus value={a.locked == null ? 'Unknown' : a.locked ? 'Locked' : 'Unlocked'}/></td><td>{a.user_type || 'Unknown'}</td></tr>)}
            </tbody></table></div>
            <Pagination offset={accountOffset} total={user.account_total} onChange={setAccountOffset} label="Account evidence pages"/>
          </details>}
          {user.names_total > 100 && (
            <Pagination
              offset={nameOffset}
              total={user.names_total}
              limit={100}
              onChange={setNameOffset}
              label="Name variant pages"
            />
          )}
          {user.emails_total > 100 && (
            <Pagination
              offset={emailOffset}
              total={user.emails_total}
              limit={100}
              onChange={setEmailOffset}
              label="Email variant pages"
            />
          )}
          <EvidenceNote />
          <p className="text-xs">
            Validity evaluated on {formatDate(user.as_of)}. {user.retained_assignments}{" "}
            assignment records retained.
          </p>
          <ContentTabs label="User role sections" value={scope} onChange={setScope} items={[{value:'all',label:'All roles'},{value:'business',label:'Business Roles — ZC:*'},{value:'release',label:'Release Roles — ZO:*'}]}>
          <form aria-label="User role toolbar" className="user-role-toolbar" onSubmit={event => event.preventDefault()}>
            <Filter label="Assignment status">
              <Select aria-label="Assignment status"
                className={inputClass}
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                {[
                  ["", "All non-expired"],
                  ["active", "Currently valid"],
                  ["all", "All assignments"],
                  ["future", "Future"],
                  ["unknown", "Unknown validity"],
                  ["expired", "Expired"],
                ].map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </Select>
            </Filter>
          <AssignmentDateFilters value={assignmentDates} onChange={setAssignmentDates}/>
          {(datesActive(assignmentDates) || transaction.codes.length > 0 || status) && <ClearFilterButton onClick={() => { setAssignmentDates({ ...emptyDates }); transaction.clear(); setStatus('') }}>Clear all assignment filters</ClearFilterButton>}

            <TransactionFilter label="Find roles by transaction" filter={transaction}/>
            <Button type="button" className="settings-secondary-button user-export-button" disabled={exporting || result.isFetching || transaction.settling || !user.total} onClick={async () => {
              const generation = exportGeneration.current;
              setExporting(true); setExportMessage('Preparing CSV…');
              try { const saved = await exportAssignments(user, scope, status, () => generation === exportGeneration.current, transactionCodes, dateParams(assignmentDates));
                if (generation === exportGeneration.current) setExportMessage(saved ? 'CSV exported.' : 'Export cancelled.');
              } catch (error) { if (generation === exportGeneration.current) setExportMessage(error instanceof Error ? error.message : 'CSV export failed.'); }
              finally { setExporting(false); }
            }}><Download size={15} aria-hidden="true"/>{exporting ? 'Exporting…' : 'Export CSV'}</Button>
          </form>
          {transactionCodes.length > 0 && <section aria-label="Transaction search evidence"><p>Transactions {transactionCodes.join(' OR ')} · selected user, role view and assignment-status filter. Role-derived evidence is not proof of effective SAP authorization.</p>
            {!user.mapping_available && <p>Transaction mappings unavailable: no role catalogue is loaded.</p>}
            {Boolean(user.unmapped_assignments) && <p>{user.unmapped_assignments} assignments have unavailable or unresolved catalogue mappings; transaction coverage may be incomplete.</p>}
            {user.items.map(a => <div key={a.id} className="text-sm"><strong>{transactionCodes.join(' OR ')}</strong> · {a.role_name}{a.role_description && ` · ${a.role_description}`}{Boolean(a.transaction_roles?.length) && <span> · Via {a.transaction_roles?.join(', ')}</span>}</div>)}
          </section>}
          <p className="text-xs text-[var(--muted)]">Exports all assignments matching this role view, assignment status, assignment date bounds and live transaction filters.</p>
          <p role="status">{exportMessage}</p>
          <div className="access-table user-assignment-table" role="region" aria-label="User role assignments" tabIndex={0}>
            <table>
              <thead>
                <tr>
                  <th>Exact assigned role</th>
                  {scope === 'release' ? <><th>Type</th><th>Release group</th><th>Release strategy</th></> : <th>Catalogue match</th>}
                  <th>Valid from</th><th>Valid to</th>
                  <th>Assignment status</th>
                  <th>
                    Details
                  </th>
                </tr>
              </thead>
              <tbody>
                {user.items.map((a) => (
                  <AssignmentRow
                    key={a.id}
                    assignment={a}
                    releaseView={scope === "release"}
                    onRole={onRole}
                    onRelease={onRelease}
                  />
                ))}
              </tbody>
            </table>
          </div>
          {!user.items.length && (
            <p>
              {transactionCodes.length ? "No matching roles for this transaction in the selected role view and validity filters." : "No assignments in this section for the selected validity filters."}
            </p>
          )}
          <Pagination
            offset={offset}
            total={user.total}
            onChange={setOffset}
            label="User assignment pages"
          />
          </ContentTabs>
        </>
      )}
    </section>
  );
}

function AssignmentRow({
  assignment: a,
  releaseView,
  onRole,
  onRelease,
}: {
  assignment: Assignment;
  releaseView: boolean;
  onRole: (role: string) => void;
  onRelease: (role: string) => void;
}) {
  return (
    <tr>
      <td>
        <RoleIdentifier value={a.role_name} />
      </td>
      {releaseView ? <><td>{a.release?.document_type || 'Unparsed'}</td><td>{a.release?.release_group || '—'}</td><td>{a.release?.release_strategy || '—'}</td></> : <td>
          <div className="catalogue-match">
            {!a.catalogue_roles.length && <EvidenceBadge value="unmapped"/>}
            {a.catalogue_roles.map((name) => <RoleIdentifier key={name} value={name}/>)}
          </div></td>}
      <td className="assignment-date">{formatDate(a.valid_from)}</td><td className="assignment-date">{formatDate(a.valid_to)}</td>

      <td>
        <AssignmentStatus value={a.status}/>
      </td>
      <td>
        {a.scope === "release" ? (
          <Button className="settings-secondary-button" onClick={() => onRelease(a.role_name)}>View role details<ArrowRight size={15} aria-hidden="true"/></Button>
        ) : a.match_status === "exact" || a.match_status === "wildcard" ? (
          <>
            {a.catalogue_roles.map((name) => (
              <Button className="settings-secondary-button" key={name} aria-label={`View role details: ${name}`} onClick={() => onRole(name)}>
                View role details<ArrowRight size={15} aria-hidden="true"/>
              </Button>
            ))}
          </>
        ) : (
          <span>Catalogue evidence unavailable.</span>
        )}
      </td>
    </tr>
  );
}
