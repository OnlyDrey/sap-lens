import { BulkAssignDialog } from './BulkAssignDialog'
import {SAPUserLink} from '@/components/Shared/SAPUserLink'
import {ExportCSVButton} from '@/components/Shared/ExportCSVButton'
import { ASSIGNMENT_BANDS, LEGACY_ASSIGNMENT_BANDS } from '@/lib/assignmentBands'
import { USER_ACCESS_VIEWS } from '@/lib/navigationItems'
import {useAssignmentCSVExport} from '@/hooks/useAssignmentCSVExport'
import { PageHeader } from '@/components/Shared/Presentation'
import { UsersRound as PageIcon } from 'lucide-react'
import { useRoles } from '@/hooks/useRoles'
import { FilterChip } from '@/components/Shared/FilterChip'
import { Button, ButtonGroup } from '@/components/Shared/Button'
import { SecondaryNavigation, ContentTabs } from '@/components/Shared/Navigation'
import { UserComparison, type ComparisonContext } from './UserComparison'
import { SavedFilters } from '@/components/Shared/SavedFilters'
import { AccountReview } from './AccountReview'
import { AccountStatus } from '@/components/Shared/AccountStatus'
import { useApplicationData } from '@/state/ApplicationData'
import { AssignmentDateFilters, emptyDates, dateParams, datesActive } from '@/components/Shared/AssignmentDateFilters'
import { UserProfile } from './UserProfile'
import { TransactionFilter, TransactionFilterGroups, useTransactionFilter } from '@/components/Shared/TransactionFilter';
import { FilterLayout, FilterSection, PageToolbar, SortControl } from '@/components/Shared/FilterLayout';
import { ClearFilterButton } from '@/components/Shared/ClearFilterButton';
import { Select } from '@/components/Shared/Select';
import { formatDate } from '@/lib/dateFormat';
import { exportAssignments } from '@/lib/accessExport';
import { announceExport } from '@/lib/exportNotice'
import { ArrowLeftRight, ArrowRight, Briefcase, Download, FileCheck2, Layers, UsersRound, X } from 'lucide-react';
import { useHistoryValue, useViewHistory, userAccessHref } from '@/hooks/useViewHistory';
import { useRecordNavigation, type RecordNavigationState } from "@/hooks/useRecordNavigation";
import { DetailNavigation, LockStatus, AssignmentStatus } from "@/components/Shared/InvestigationNavigation";
import { MultiSelectFilter } from '@/components/Shared/MultiSelectFilter';
import { ClassificationPill } from './FunctionalGroupPanel';
import { OrganizationFilter, useOrganizationLabel } from '@/components/Shared/OrganizationFilter';
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
import { RoleModuleBadge } from "@/components/Shared/RoleModuleBadge";
import {
  dates,
  EvidenceNote,
  Filter,
  inputClass,
  Pagination,
  QueryState,
} from "./Shared";

const USER_SORTS = [
  { value: 'username', label: 'Username' }, { value: 'group', label: 'User group' }, { value: 'first_name', label: 'First name' },
  { value: 'last_name', label: 'Last name' }, { value: 'email', label: 'Email' }, { value: 'account_status', label: 'Account status' },
  { value: 'relevant_roles', label: 'Relevant role count' },
]
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
  const assignmentBand=comparisonView.assignmentBand||'';
  const setAssignmentBand=(value:string)=>changeComparison({assignmentBand:value},true);
  const comparisonContext=comparisonView.userComparison;
  const setComparisonContext=(state:ComparisonContext)=>changeComparison({userComparison:state},true);
  const [compareInitial,setCompareInitial]=useState('');
  const [accessMode,setAccessMode]=useHistoryValue('accessMode');
  const modeButtons=<SecondaryNavigation label="User Access view" items={USER_ACCESS_VIEWS.map(({value,label,icon})=>({value,label,icon,href:userAccessHref(value),active:(accessMode||'directory')===value,onSelect:()=>{setCompareInitial('');setAccessMode(value)}}))}/>;
  const {loading:dataLoading}=useApplicationData();
  const listScroll = useRef(0);
  const originUser = useRef(initialUser || "");
  const restoreList = useRef(false);
  const openUser = (username: string) => { listScroll.current = window.scrollY; originUser.current = username; changeView({ user: username, userTrail: [] }) };
  const [search, setSearch] = useState(""),
    [sort, setSort] = useState("username"),
    [descending, setDescending] = useState(false);
  const organizationLabel = useOrganizationLabel()
  const [groups, setGroups] = useState<string[]>([]),
    [functionalGroups, setFunctionalGroups] = useState<string[]>([]),
    [managers, setManagers] = useState<string[]>([]),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useHistoryValue('user');
  const { change: changeView } = useViewHistory();
  const [roles, setRoles] = useState<string[]>(initialRole ? [initialRole] : []),
    [expired, setExpired] = useState(false);
  const [roleSearch, setRoleSearch] = useState(''), [roleTerm, setRoleTerm] = useState('')
  useEffect(() => { const timer = setTimeout(() => setRoleTerm(roleSearch), 200); return () => clearTimeout(timer) }, [roleSearch])
  const roleOptions = useRoles(undefined, roleTerm)
  const [missingRoles, setMissingRoles] = useState<string[]>([]), [missingMode, setMissingMode] = useState<'any' | 'all'>('any')
  const [missingSearch, setMissingSearch] = useState(''), [missingTerm, setMissingTerm] = useState('')
  useEffect(() => { const timer = setTimeout(() => setMissingTerm(missingSearch), 200); return () => clearTimeout(timer) }, [missingSearch])
  const missingOptions = useRoles(undefined, missingTerm)
  const directoryTransaction = useTransactionFilter()
  const [transactionMode,setTransactionMode] = useState<'and'|'or'>('and')
  const excludeTransaction = useTransactionFilter()
  const [excludeMode,setExcludeMode] = useState<'any'|'all'>('any')
  const transactionGroups = { include: directoryTransaction, includeMode: transactionMode, setIncludeMode: setTransactionMode, exclude: excludeTransaction, excludeMode, setExcludeMode }
  const activeFilterCount = [groups.length, functionalGroups.length, managers.length, roles.length, expired, assignmentBand, missingRoles.length, directoryTransaction.codes.length, excludeTransaction.codes.length].filter(Boolean).length
  useEffect(()=>{ directoryTransaction.setChips(initialTcode ? [initialTcode.trim().toUpperCase()] : []) },[initialTcode])
  useEffect(()=>{ if (!directoryTransaction.codes.length) setTransactionMode('and') },[directoryTransaction.key])
  const clearEvidence = () => {setRoles([]); directoryTransaction.clear(); setTransactionMode('and'); excludeTransaction.clear(); setExcludeMode('any'); setMissingRoles([]); setMissingMode('any')}
  const [term, setTerm] = useState("");
  const [assignOpen, setAssignOpen] = useState(false);
  const [usernames, setUsernames] = useState(''), [usernameDraft, setUsernameDraft] = useState('');
  const [selectionBusy, setSelectionBusy] = useState(false), [selectionNote, setSelectionNote] = useState('');
  const [picked, setPicked] = useState<Set<string>>(new Set());
  useEffect(() => {
    const t = setTimeout(() => setTerm(search), 250);
    return () => clearTimeout(t);
  }, [search]);
  const scopeKey = JSON.stringify([term, groups, roles, directoryTransaction.deferredKey, transactionMode, excludeTransaction.deferredKey, excludeMode, missingRoles, missingMode, expired, assignmentBand, functionalGroups, managers, usernames]);
  useEffect(() => { setPicked(new Set()); setSelectionNote('') }, [scopeKey]);
  useEffect(() => {
    setOffset(0);
  }, [term, groups, sort, descending, roles, directoryTransaction.deferredKey, transactionMode, excludeTransaction.deferredKey, excludeMode, missingRoles, missingMode, expired, assignmentBand, functionalGroups, managers, usernames]);
  const filters = { usernames, assignment_band:assignmentBand, search: term, groups, functional_groups: functionalGroups, managers, sort, descending, roles, tcodes: directoryTransaction.deferredCodes, transaction_mode: transactionMode, exclude_tcodes: excludeTransaction.deferredCodes, exclude_mode: excludeMode, missing_roles: missingRoles, missing_mode: missingMode, show_expired: expired };
  const navigation = useRecordNavigation('users', filters, selected, setSelected);
  const result = useQuery({
    queryKey: [
      "access-users", assignmentBand, usernames,
      term,
      groups,
      functionalGroups,
      managers,
      sort,
      descending,
      roles,
      directoryTransaction.deferredCodes,
      transactionMode,
      excludeTransaction.deferredCodes,
      excludeMode,
      missingRoles,
      missingMode,
      offset,
      expired,
    ],
    queryFn: () =>
      accessQuery<Page<UserRow>>("users", { ...filters, offset }),
  });
  const pageNames = (result.data?.items ?? []).map((u) => u.username);
  const pageAll = pageNames.length > 0 && pageNames.every((u) => picked.has(u));
  const pageSome = pageNames.some((u) => picked.has(u));
  useEffect(() => {
    if (!result.data || result.isFetching) return;
    const limit = result.data.limit;
    const last = Math.max(0, Math.floor((result.data.total - 1) / limit) * limit);
    if (offset > last) setOffset(last);
  }, [result.data, result.isFetching, offset]);
  const assignmentExport=useAssignmentCSVExport('users',filters,result.data?.data_revision,result.data?.as_of)
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
        onBack={() => { restoreList.current = true; changeView({ user: '', userTrail: [] }) }}
        onRole={onRole}
        onRelease={onRelease}
        navigation={navigation}
      />
    );
  const clearAll=()=>{setUsernames('');setUsernameDraft('');setAssignmentBand('');setSearch('');setGroups([]);setFunctionalGroups([]);setManagers([]);setSort('username');setDescending(false);setRoles([]);directoryTransaction.clear();setTransactionMode('and');excludeTransaction.clear();setExcludeMode('any');setExpired(false);setTerm('');setMissingRoles([]);setMissingMode('any');clearEvidence()}
  const clearDisabled=!activeFilterCount&&!search&&!roles.length&&!groups.length&&!functionalGroups.length&&!managers.length&&!expired&&!missingRoles.length&&sort==='username'&&!descending
  return (
    <section aria-label="User Access" className="space-y-4">
      {modeButtons}<PageHeader title="User Access" icon={<PageIcon size={22} aria-hidden="true"/>}/>
      <EvidenceNote />

      <FilterLayout label="Filters" activeCount={activeFilterCount} onClear={clearAll} clearDisabled={clearDisabled}
        toolbar={<PageToolbar>
          <SortControl label="Sort users" value={sort} options={USER_SORTS} descending={descending} onChange={setSort} onDescending={setDescending} />
        </PageToolbar>}
        sidebar={<div className="grid min-w-0 gap-3" role="search" aria-label="User filters">
          <FilterSection title="Saved Filters">
            <SavedFilters showClear={false} view="users" state={{usernames,assignmentBand,search,groups,sort,descending,roles,tcodes:directoryTransaction.codes,transactionMode,excludeTcodes:excludeTransaction.codes,excludeMode,missingRoles,missingMode,expired}} apply={s=>{if(typeof s.usernames==='string'){setUsernames(s.usernames.slice(0,12000));setUsernameDraft(s.usernames.slice(0,12000))};setMissingRoles(Array.isArray(s.missingRoles)?s.missingRoles.filter((name:unknown):name is string=>typeof name==='string').slice(0,20):[]);setMissingMode(s.missingMode==='all'?'all':'any');setAssignmentBand(typeof s.assignmentBand==='string'?s.assignmentBand:'');if(typeof s.search==='string')setSearch(s.search);if(Array.isArray(s.groups))setGroups(s.groups.filter((v:unknown):v is string=>typeof v==='string').slice(0,50));else if(typeof s.group==='string'&&s.group)setGroups([s.group]);if(typeof s.sort==='string'&&['username','group','first_name','last_name','email','account_status','relevant_roles'].includes(s.sort))setSort(s.sort);if(typeof s.descending==='boolean')setDescending(s.descending);if(Array.isArray(s.roles))setRoles(s.roles.filter((v:unknown):v is string=>typeof v==='string').slice(0,50));else if(typeof s.role==='string'&&s.role)setRoles([s.role]);if(Array.isArray(s.tcodes)){directoryTransaction.setInput('');directoryTransaction.setChips(s.tcodes)};if(s.transactionMode==='and'||s.transactionMode==='or')setTransactionMode(s.transactionMode);if(Array.isArray(s.excludeTcodes)){excludeTransaction.setInput('');excludeTransaction.setChips(s.excludeTcodes)}else excludeTransaction.clear();setExcludeMode(s.excludeMode==='all'?'all':'any');if(typeof s.expired==='boolean')setExpired(s.expired)}} clear={clearAll}/>
          </FilterSection>
          <FilterSection title="Users">
        <Filter label="SAP User Group">
          <MultiSelectFilter label="SAP User Group" values={groups} options={result.data?.groups || []} onChange={setGroups} placeholder="All groups · type to search"/>
        </Filter>
        <Filter label="Functional Group"><OrganizationFilter kind="functional_group" values={functionalGroups} onChange={setFunctionalGroups}/></Filter>
        <Filter label="Manager"><OrganizationFilter kind="manager" values={managers} onChange={setManagers}/></Filter>
        <Filter label="Filter users by role">
          <MultiSelectFilter label="Filter users by role" values={roles} options={(roleOptions.data || []).slice(0,100).map(item=>item.agr_name)} onChange={setRoles} onSearch={setRoleSearch} loading={roleOptions.isFetching} hasMore={(roleOptions.data?.length||0)>100} optionDescription={value=>roleOptions.data?.find(item=>item.agr_name===value)?.text ?? ''} placeholder="Role name or description" scope="in the role catalogue"/>
        </Filter>
          </FilterSection>
          <FilterSection title="Missing roles">
      <section className="directory-missing grid min-w-0 gap-2" aria-label="Users lacking roles">
        <Filter label="Roles the user must lack">
          <MultiSelectFilter label="Roles the user must lack" values={missingRoles} options={(missingOptions.data || []).slice(0,100).map(item=>item.agr_name)} optionDescription={value=>missingOptions.data?.find(item=>item.agr_name===value)?.text ?? ''} onChange={values=>setMissingRoles(values.slice(0,20))} onSearch={setMissingSearch} loading={missingOptions.isFetching} hasMore={(missingOptions.data?.length||0)>100} maxSelected={20} placeholder="Add catalogue roles to find users lacking them" scope="in the role catalogue"/>
        </Filter>
        {missingRoles.length>0&&<>
          <div className="flex flex-wrap items-center gap-2">
            <ButtonGroup label="Missing role operator" value={missingMode} onChange={value=>setMissingMode(value==='all'?'all':'any')} options={[{value:'any',label:'Missing ANY'},{value:'all',label:'Missing ALL'}]}/>
          </div>
          <p className="transaction-help text-xs text-[var(--muted)]" role="status">{missingMode==='all'?'Missing ALL: users lacking every selected role.':'Missing ANY: users lacking at least one selected role.'} Only users whose current assignments are all mapped to catalogue roles are listed; missing or unmapped evidence is never read as missing access.</p>
        </>}
      </section>
          </FilterSection>
          <FilterSection title="Transactions">
            <TransactionFilterGroups subject="users" groups={transactionGroups} includeLabel="Filter users by transaction" excludeLabel="Exclude users by transaction" />
          </FilterSection>
          <FilterSection title="Assignments">
            <Filter label="Currently valid roles">
              <Select aria-label="Currently valid roles" className={inputClass} value={assignmentBand} onChange={event => setAssignmentBand(event.target.value)}>
                <option value="">Any number of roles</option>
                {ASSIGNMENT_BANDS.map(band => <option key={band} value={band}>{band} roles</option>)}
                {(LEGACY_ASSIGNMENT_BANDS as readonly string[]).includes(assignmentBand) && <option value={assignmentBand}>{assignmentBand} roles (saved range)</option>}
              </Select>
            </Filter>
            <label className="filter-toggle"><input type="checkbox" checked={expired} onChange={(e) => setExpired(e.target.checked)} />Show expired assignments</label>
          </FilterSection>
        </div>}>
      <div className="grid min-w-0 gap-4">
        <Filter label="Search users">
          <input
            className={inputClass}
            value={search}
            maxLength={256}
            onChange={(e) => setSearch(e.target.value)}
            onPaste={(e) => {
              // Only a deliberate paste of a list converts: typing never does, and one ordinary term (name, e-mail, "two words") stays a text search.
              const text = e.clipboardData.getData('text')
              if (looksLikeUsernameList(text)) { e.preventDefault(); setUsernameDraft(text); setUsernames(text); setPicked(new Set()) }
            }}
            placeholder="Username, name, email or group"
          />
        </Filter>
        <Filter label="Exact usernames">
          <textarea className={inputClass} rows={3} value={usernameDraft} maxLength={16000} aria-label="Exact usernames" aria-describedby="exact-usernames-help"
            onChange={(e) => setUsernameDraft(e.target.value)} placeholder="Paste usernames from Excel or a list" />
          <p id="exact-usernames-help" className="ui-description">One per line, or separated by commas, semicolons or tabs. Exact, case-insensitive match; up to 500 names.</p>
          <div className="ui-toolbar">
            <Button variant="primary" disabled={usernameDraft === usernames} onClick={() => setUsernames(usernameDraft)}>{usernames ? 'Replace list' : 'Apply list'}</Button>
            {(usernames || usernameDraft) && <Button variant="outline" onClick={() => { setUsernames(''); setUsernameDraft('') }}>Clear list</Button>}
          </div>
        </Filter>
      {(assignmentBand || roles.length > 0 || groups.length > 0 || functionalGroups.length > 0 || managers.length > 0 || search || usernames || expired) && <div className="active-filter-row" aria-label="Active user filters">
        {assignmentBand&&<FilterChip removeLabel="Remove assignment count filter" onRemove={()=>setAssignmentBand('')}>{assignmentBand} currently valid roles</FilterChip>}
        {expired && <FilterChip removeLabel="Remove expired assignment filter" onRemove={()=>setExpired(false)}>Include Expired Assignments</FilterChip>}
        {roles.map(name => <FilterChip key={`role-${name}`} removeLabel={`Remove role filter ${name}`} onRemove={()=>setRoles(roles.filter(value=>value!==name))}>Role: {name}</FilterChip>)}
        {functionalGroups.map(value => <FilterChip key={`fg-${value}`} removeLabel={`Remove Functional Group filter ${organizationLabel('functional_group', value)}`} onRemove={()=>setFunctionalGroups(functionalGroups.filter(item=>item!==value))}>Functional Group: {organizationLabel('functional_group', value)}</FilterChip>)}
        {managers.map(value => <FilterChip key={`mgr-${value}`} removeLabel={`Remove Manager filter ${organizationLabel('manager', value)}`} onRemove={()=>setManagers(managers.filter(item=>item!==value))}>Manager: {organizationLabel('manager', value)}</FilterChip>)}
        {groups.map(name => <FilterChip key={`group-${name}`} removeLabel={`Remove user group filter ${name}`} onRemove={()=>setGroups(groups.filter(value=>value!==name))}>User group: {name}</FilterChip>)}
        {usernames && <FilterChip removeLabel="Remove exact username filter" onRemove={()=>{setUsernames('');setUsernameDraft('')}}>Exact usernames: {(result.data?.username_filter?.requested ?? parseUsernameList(usernames).length).toLocaleString()}</FilterChip>}
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
          <div className="results-toolbar">
            <h2 className="text-base font-semibold">User directory <span className="text-sm font-normal text-[var(--muted)]">{result.data.total.toLocaleString()} matching{picked.size>0?` · ${picked.size.toLocaleString()} selected`:''}</span></h2>
            <div className="results-toolbar-actions">
              {result.data.total>0&&picked.size<result.data.total&&<Button variant="outline" disabled={selectionBusy} onClick={async()=>{
                setSelectionBusy(true);setSelectionNote('')
                try{const all=await accessQuery<{usernames:string[];total:number;truncated:boolean;limit:number}>('users-selection',{...filters});setPicked(new Set(all.usernames));if(all.truncated)setSelectionNote(`Only the first ${all.limit.toLocaleString()} of ${all.total.toLocaleString()} matching users were selected.`)}
                catch(error){setSelectionNote(error instanceof Error?error.message:'The matching users could not be selected.')}
                finally{setSelectionBusy(false)}}}>Select all {result.data.total.toLocaleString()} matching</Button>}
              {picked.size>0&&<Button variant="primary" onClick={()=>setAssignOpen(true)}><UsersRound size={16} aria-hidden="true"/>Assign group</Button>}
              {picked.size>0&&<Button variant="outline" onClick={()=>setPicked(new Set())}><X size={16} aria-hidden="true"/>Clear selection</Button>}
              <ExportCSVButton loading={assignmentExport.busy} disabled={dataLoading||result.isFetching||search!==term||directoryTransaction.settling||!result.data.export_assignments} title="Exports every imported assignment for all matching users, across pages. MATCHED_FILTER marks assignments contributing to the active filters; expired and other assignments remain included." onClick={()=>void assignmentExport.download()}/>
            </div>
          </div>
          <UsernameFeedback feedback={result.data.username_filter}/>
          {assignOpen&&<BulkAssignDialog usernames={[...picked].sort()} onClose={()=>setAssignOpen(false)} onChanged={()=>undefined}/>}
          {selectionNote&&<p role="status" className="ui-description">{selectionNote}</p>}
          <details className="ui-evidence-disclosure"><summary>Export scope</summary><div><p className="ui-description">Exports all {result.data.export_assignments?.toLocaleString()??'available'} imported assignments for matching users, including other roles{expired?' and expired assignments':'; expired assignments are excluded while Show expired assignments is off'}. MATCHED_FILTER identifies assignment-level matches. Export covers all matching users and does not depend on the selection. Role-derived transactions are evidence, not proof of effective SAP authorization.</p></div></details>
          <div className="access-table user-directory-table" tabIndex={0} role="region" aria-label="User directory table">
            <table>
              <thead>
                <tr>
                  <th className="col-select ud-sticky-1"><input type="checkbox" aria-label="Select all users on this page" checked={pageAll} ref={el=>{if(el)el.indeterminate=pageSome&&!pageAll}} onChange={()=>setPicked(prev=>{const n=new Set(prev);if(pageAll)pageNames.forEach(u=>n.delete(u));else pageNames.forEach(u=>n.add(u));return n})}/></th>
                  <th className="ud-sticky-2">Username</th>
                  <th>Full name</th>
                  <th>Functional Group</th>
                  <th>SAP user group</th>
                  <th>Email</th>
                  <th>SAP account status</th>
                  <th>Lock status</th>
                  <th>Relevant roles</th>
                </tr>
              </thead>
              <tbody>
                {result.data.items.map((user) => {
                  const full=[user.first_name,user.last_name].filter(Boolean).join(' ')
                  const group=user.groups.map((g) => g || "Unknown group").join(", ") || "Unknown"
                  return (
                  <tr key={user.user_key} data-selected={picked.has(user.username)?'':undefined}>
                    <td className="col-select ud-sticky-1"><input type="checkbox" aria-label={`Select ${user.username}`} checked={picked.has(user.username)} onChange={()=>setPicked(prev=>{const n=new Set(prev);if(n.has(user.username))n.delete(user.username);else n.add(user.username);return n})}/></td>
                    <td className="ud-sticky-2">
                      <SAPUserLink username={user.username} copyLabel="username" onOpen={()=>openUser(user.username)} openLabel={user.username}/>
                    </td>
                    <td className="ud-cell" data-col="name"><span className="ud-ellipsis" title={full||undefined}>{full||"—"}</span></td>
                    <td className="ud-cell" data-col="fg">{user.functional_group?.name ? <span className="ud-ellipsis" title={user.functional_group.name}>{user.functional_group.name}</span> : <span className="text-muted">Unassigned</span>}{user.classification_status === "Needs review" && <> <ClassificationPill status="Needs review"/></>}</td>
                    <td className="ud-cell" data-col="group"><span className="ud-ellipsis" title={group}>{group}</span></td>
                    <td className="ud-cell" data-col="email"><span className="ud-ellipsis" title={user.email||undefined}>{user.email || "—"}</span></td>
                    <td aria-label="Account validity">
                      <AccountStatus value={user.account_status}/>
                    </td><td aria-label="Account lock"><LockStatus value={user.lock_status}/>
                    </td>
                    <td><button className="role-count-button" aria-label={`View ${user.relevant_roles} relevant roles for ${user.username}`} onClick={() => openUser(user.username)}>{user.relevant_roles.toLocaleString()} <span>{user.relevant_roles === 1 ? "role" : "roles"}</span></button></td>
                  </tr>)
                })}
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
      </div>
      </FilterLayout>
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
  const [assignmentDates, setAssignmentDates] = useState({ ...emptyDates });
  const dateKey = JSON.stringify(assignmentDates);
  const transaction = useTransactionFilter(username);
  const [transactionMode,setTransactionMode]=useState<'and'|'or'>('and');
  const transactionCodes = transaction.deferredCodes;
  const exportGeneration = useRef(0);
  const [scope, setScope] = useState("all"),
    [status, setStatus] = useState(""),
    [offset, setOffset] = useState(0),
    [accountOffset, setAccountOffset] = useState(0),
    [nameOffset, setNameOffset] = useState(0),
    [emailOffset, setEmailOffset] = useState(0);
  useEffect(() => { setOffset(0) }, [scope, status, username, transaction.key, transactionMode, dateKey]);
  useEffect(() => { exportGeneration.current++;  return () => { exportGeneration.current++ } }, [username, scope, status, transaction.key, transactionMode, dateKey]);

  useEffect(() => { setAssignmentDates({ ...emptyDates }); setTransactionMode('and'); setAccountOffset(0); setNameOffset(0); setEmailOffset(0) }, [username]);
  const result = useQuery({
    queryKey: [
      "access-user",
      transactionCodes,
      transactionMode,
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
        transaction_mode: transactionMode,
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
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-xl font-semibold">User details</h1><Button className="settings-secondary-button" onClick={onCompare}><ArrowLeftRight size={16} aria-hidden="true" />Compare users</Button></div>
      <QueryState subject="user details" loading={result.isLoading || (dataLoading && !result.data)} error={dataLoading && !result.data ? null : result.error} />
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
          <ContentTabs label="User role sections" value={scope} onChange={setScope} items={[{value:'all',label:'All roles',icon:<Layers size={16} aria-hidden="true"/>},{value:'business',label:'Business Roles — ZC:*',icon:<Briefcase size={16} aria-hidden="true"/>},{value:'release',label:'Release Roles — ZO:*',icon:<FileCheck2 size={16} aria-hidden="true"/>}]}>
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

          {(datesActive(assignmentDates) || transaction.codes.length > 0 || status) && <ClearFilterButton onClick={() => { setAssignmentDates({ ...emptyDates }); transaction.clear(); setTransactionMode('and'); setStatus('') }}>Clear all assignment filters</ClearFilterButton>}

            <TransactionFilter label="Find roles by transaction" filter={transaction} mode={transactionMode} onModeChange={setTransactionMode}/>
          <AssignmentDateFilters value={assignmentDates} onChange={setAssignmentDates}/>
            <Button type="button" className="settings-secondary-button user-export-button" title="Exports every assignment matching the selected role view, validity, date bounds and transaction matching mode." disabled={exporting || result.isFetching || transaction.settling || !user.total} onClick={async () => {
              const generation = exportGeneration.current;
              setExporting(true);
              try { const saved = await exportAssignments(user, scope, status, () => generation === exportGeneration.current, transactionCodes, dateParams(assignmentDates), transactionMode);
                if (generation === exportGeneration.current) announceExport(saved ? { kind: 'success', message: 'CSV exported.' } : { kind: 'info', message: 'Export cancelled.' });
              } catch (error) { if (generation === exportGeneration.current) announceExport({ kind: 'error', message: error instanceof Error ? error.message : 'CSV export failed.' }); }
              finally { setExporting(false); }
            }}><Download size={15} aria-hidden="true"/>{exporting ? 'Exporting…' : 'Export CSV'}</Button>
          </form>
          <div className="assignment-results-summary"><strong>{user.total.toLocaleString()} matching assignments</strong><span className="ui-description">Validity evaluated on {formatDate(user.as_of)}.</span></div>
          {transactionCodes.length > 0 && (!user.mapping_available || Boolean(user.unmapped_assignments)) && <details className="compact-evidence-warning"><summary>Catalogue coverage may be incomplete</summary><p>{user.mapping_available ? `${user.unmapped_assignments} assignment records have unresolved or unavailable catalogue mappings.` : 'No role catalogue is loaded.'} Transaction coverage is role-derived evidence, not effective SAP authorization.</p></details>}
          <div className="access-table user-assignment-table" role="region" aria-label="User role assignments" tabIndex={0}>
            <table>
              <thead>
                <tr>
                  <th>Exact assigned role</th>
                  {scope === 'release' && <><th>Type</th><th>Release group</th><th>Release strategy</th></>}
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
        <div className="assigned-role">
          {!releaseView && <div className="assigned-role-head"><RoleModuleBadge catalogueRoles={a.match_status === "exact" || a.match_status === "wildcard" ? a.catalogue_roles : undefined} /><span className="assigned-role-description">{a.role_description || 'Description unavailable'}</span></div>}
          <RoleIdentifier value={a.role_name} />
        </div>
      </td>
      {releaseView && <><td>{a.release?.document_type || 'Unparsed'}</td><td>{a.release?.release_group || '—'}</td><td>{a.release?.release_strategy || '—'}</td></>}
      <td className="assignment-date">{formatDate(a.valid_from)}</td><td className="assignment-date">{formatDate(a.valid_to)}</td>

      <td>
        <AssignmentStatus value={a.status}/>
      </td>
      <td>
        {!!a.transaction_roles?.length&&<details className="assignment-mapping-evidence"><summary>Transaction mapping evidence</summary>{a.transaction_roles.map(name=><p key={name}>Via <RoleIdentifier value={name}/></p>)}</details>}
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


const USERNAME_TOKEN = /^[^\s@,;<>"]{1,40}$/
export const parseUsernameList = (text: string) => [...new Set(text.split(/[\s,;]+/).map(item => item.trim()).filter(Boolean).map(item => item.toLocaleUpperCase()))]
/** A pasted block is an exact-username list only when it has at least two entries separated by a line break, tab, comma or semicolon and every entry is a single token without spaces or an at-sign. "Jane Doe, John Smith" and one ordinary term stay a text search. */
export function looksLikeUsernameList(text: string): boolean {
  const entries = text.split(/[\n\r\t,;]+/).map(item => item.trim()).filter(Boolean)
  return entries.length >= 2 && entries.every(entry => USERNAME_TOKEN.test(entry))
}

type UsernameFeedbackData = { requested: number; duplicates: number; invalid: string[]; found: number; matched: number; filtered_out: string[]; unmatched: string[]; limit: number; exceeds_limit: boolean } | null | undefined
function UsernameFeedback({ feedback }: { feedback: UsernameFeedbackData }) {
  if (!feedback) return null
  return (
    <div role="status" aria-label="Exact username filter result" className="ui-description">
      <p>Requested {feedback.requested.toLocaleString()} · matched {feedback.matched.toLocaleString()} · not found {feedback.unmatched.length.toLocaleString()}{feedback.invalid.length > 0 ? ` · invalid ${feedback.invalid.length.toLocaleString()}` : ''}{feedback.duplicates > 0 ? ` · duplicates removed ${feedback.duplicates.toLocaleString()}` : ''}{feedback.filtered_out.length > 0 ? ` · hidden by other filters ${feedback.filtered_out.length.toLocaleString()}` : ''}</p>
      {(feedback.unmatched.length > 0 || feedback.invalid.length > 0 || feedback.filtered_out.length > 0) && (
        <details><summary>Show details</summary>
          {feedback.unmatched.length > 0 && <p>Not found: {feedback.unmatched.join(', ')}</p>}
          {feedback.invalid.length > 0 && <p>Invalid entries (not usernames): {feedback.invalid.join(', ')}</p>}
          {feedback.filtered_out.length > 0 && <p>Found but excluded by other filters: {feedback.filtered_out.join(', ')}</p>}
        </details>
      )}
    </div>
  )
}
