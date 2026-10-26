import {ExportCSVButton} from '@/components/Shared/ExportCSVButton'
import { TransactionCount } from '@/components/Shared/TransactionCount'
import { ReviewFindings } from '@/components/Shared/ReviewFindings'
import { ChangeRecordDetails } from '@/components/Shared/RefreshReport'
import { PageHeader, MetadataList, SectionHeader } from '@/components/Shared/Presentation'
import { LayoutDashboard } from 'lucide-react'
import { SourceFileField, MappingField, ImportPreview } from './ImportControls'
import { SourceHealthSummary } from './SourceStatus'
import { AssignmentDateFilters, emptyDates } from '@/components/Shared/AssignmentDateFilters'
import { StatusCard, FilterPanel, ResultsToolbar } from '@/components/Shared/InvestigationPatterns'
import { useRef, useState, useEffect } from 'react'
import { Copy, Download, Search, Users, Info } from 'lucide-react'
import { Button, IconButton, ButtonGroup } from '@/components/Shared/Button'
import {
  Input,
  SearchInput,
  FormField,
  Checkbox,
  Toggle,
} from '@/components/Shared/Controls'
import {
  MainNavigation,
  MainNavigationItem,
  SecondaryNavigation,
  ContentTabs,
} from '@/components/Shared/Navigation'
import { Popover } from '@/components/Shared/Popover'
import { Dialog } from '@/components/Shared/Dialog'
import {
  Card,
  Toolbar,
  StatusBadge,
  LoadingState,
  EmptyState,
  EvidenceDisclosure,
  DataTable,
} from '@/components/Shared/Presentation'
import { Select } from '@/components/Shared/Select'
import { Combobox } from '@/components/Shared/Combobox'
import { NorwegianDateInput } from '@/components/Shared/NorwegianDateInput'
import {
  SavedFilters,
  type Entry,
  type FilterStorage,
} from '@/components/Shared/SavedFilters'
import { AccountStatus } from '@/components/Shared/AccountStatus'
import { AssignmentStatus } from '@/components/Shared/InvestigationNavigation'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import {
  TransactionFilter,
  useTransactionFilter,
} from '@/components/Shared/TransactionFilter'
import { ClearFilterButton } from '@/components/Shared/ClearFilterButton'
import { Notification } from '@/components/Shared/Notification'
import { SAPUserSelector } from '@/components/Shared/SAPUserSelector'
import { Pagination, dates } from '@/components/Access/Shared'
import type { UserRow } from '@/api/access'
const demoUsers: UserRow[] = [
  {
    username: 'DEMO_ANALYST',
    user_key: 'DEMO_ANALYST',
    first_name: 'Demo',
    last_name: 'Analyst',
    email: 'analyst@example.test',
    groups: ['DEMO'],
    account_status: 'active',
    lock_status: 'Unlocked',
    relevant_roles: 2,
  },
  {
    username: 'DEMO_REVIEWER',
    user_key: 'DEMO_REVIEWER',
    first_name: 'Demo',
    last_name: 'Reviewer',
    email: 'reviewer@example.test',
    groups: ['DEMO'],
    account_status: 'unknown',
    lock_status: 'Mixed / unknown',
    relevant_roles: 0,
  },
]
function memoryStorage(): FilterStorage {
  let items: Entry[] = []
  return {
    key: 'component-library-' + crypto.randomUUID(),
    list: async () => ({ items: structuredClone(items) }),
    save: async (body) => {
      const previous = items.find((i) => i.id === body.id)
      if (
        items.some(
          (i) =>
            i.name.toLowerCase() === String(body.name).toLowerCase() &&
            i.id !== body.id,
        )
      )
        throw Error('A demo filter with that name exists.')
      const entry: Entry = {
        id: previous?.id || crypto.randomUUID(),
        name: String(body.name),
        view: String(body.view),
        filter_schema: 1,
        filters:
          body.rename && previous
            ? previous.filters
            : (body.filters as Entry['filters']),
        modified: new Date().toISOString(),
      }
      items = items.filter((i) => i.id !== entry.id).concat(entry)
      return entry
    },
    remove: async ({ id }) => {
      items = items.filter((i) => i.id !== id)
    },
  }
}
export function ComponentLibrary() {
  const [text, setText] = useState(''),
    [dialogOpen, setDialogOpen] = useState(false),
    [select, setSelect] = useState('all'),
    [check, setCheck] = useState(false),
    [toggle, setToggle] = useState(false),
    [date, setDate] = useState('24.10.2026'),
    [invalid, setInvalid] = useState(false),
    [busy, setBusy] = useState(false),
    [feedback, setFeedback] = useState(''),
    [section, setSection] = useState('directory'),
    [tab, setTab] = useState('all'),
    [offset, setOffset] = useState(0),
    [user, setUser] = useState('DEMO_ANALYST'),
    [role, setRole] = useState('ZC:DEMO:VIEW')
  const [demoPath,setDemoPath]=useState('C:/synthetic/catalogue.csv'),[demoMapping,setDemoMapping]=useState('AGR_NAME'),[demoDates,setDemoDates]=useState({...emptyDates})
  const storage = useRef<FilterStorage>()
  if (!storage.current) storage.current = memoryStorage()
  const timer = useRef<ReturnType<typeof setTimeout>>()
  useEffect(() => () => clearTimeout(timer.current), [])
  const transactions = useTransactionFilter()
  return (
    <div className="component-library" aria-label="Component Library previews">
      <p className="ui-description">
        Interactive reference using the real application components. Synthetic
        identities and isolated memory only; controls do not modify application
        settings, imported data or saved investigations.
      </p>
      <Card>
        <h2>Buttons &amp; actions</h2>
        <p className="ui-description">
          Operations use buttons. Primary for the main operation; destructive
          only for deletion. Every icon action has an accessible name.
        </p>
        <Toolbar>
          {(
            ['primary', 'secondary', 'outline', 'ghost', 'destructive'] as const
          ).map((variant) => (
            <Button
              key={variant}
              variant={variant}
              onClick={() => setFeedback(`${variant} demo action`)}
            >
              {variant.charAt(0).toUpperCase()+variant.slice(1)}
            </Button>
          ))}
          <IconButton
            label="Copy demo identifier"
            onClick={() => setFeedback('Demo copy action')}
          >
            <Copy size={16} />
          </IconButton>
          <Button loading>Loading</Button>
          <Button disabled>Disabled</Button>
          <Button
            loading={busy}
            onClick={() => {
              setBusy(true)
              timer.current = setTimeout(() => setBusy(false), 800)
            }}
          >
            Simulate loading
          </Button>
        </Toolbar>
        {feedback && <p role="status">{feedback}</p>}
      </Card>
      <Card>
        <h2>Navigation &amp; content</h2>
        <p className="ui-description">
          Major destinations, related pages and content switching have distinct
          semantics. Tabs use arrows/Home/End.
        </p>
        <div
          style={{
            background: 'var(--primary)',
            borderRadius: 'var(--radius-control)',
          }}
        >
          <MainNavigation label="Main navigation preview">
            <MainNavigationItem
              label="Lookup preview"
              icon={<Search size={16} />}
              active={section === 'directory'}
              onClick={() => setSection('directory')}
            />
            <MainNavigationItem
              label="Review preview"
              icon={<Users size={16} />}
              active={section === 'review'}
              onClick={() => setSection('review')}
            />
          </MainNavigation>
        </div>
        <SecondaryNavigation
          label="Secondary navigation preview"
          items={['directory', 'review'].map((value) => ({
            value,
            label:
              value === 'directory' ? 'Directory preview' : 'Review preview',
            href: '#/user-access',
            active: section === value,
            onSelect: () => setSection(value),
          }))}
        />
        <ContentTabs
          label="Content tabs preview"
          value={tab}
          items={[
            { value: 'all', label: 'All demo roles', count: 2 },
            { value: 'business', label: 'Business demo roles', count: 1 },
          ]}
          onChange={setTab}
        >
          <p className="text-sm">Selected content: {tab}</p>
        </ContentTabs>
      </Card>
      <Card><PageHeader title="Page header preview" icon={<LayoutDashboard size={22} aria-hidden="true"/>}/><MetadataList items={[{label:'Records',value:'2'},{label:'Last validated source check',value:'Not checked · Static source'}]}/><TransactionCount count={12}/><ExportCSVButton disabled title="Isolated preview; no records are exported."/><h2>Import and source controls</h2><p className="ui-description">Real import components with isolated synthetic state. Browse selects a demo string; no files, settings or datasets are changed.</p><SourceFileField label="Demo source file" value={demoPath} onChange={setDemoPath} native onBrowse={()=>setDemoPath('C:/synthetic/replacement.csv')} browseLabel="Browse demo source"/><div className="demo-grid"><MappingField field="AGR_NAME" label="Demo role name" required value={demoMapping} columns={['AGR_NAME','ROLE_NAME']} onChange={setDemoMapping}/><SourceHealthSummary source={{id:'roles',mode:'static',loaded:true,loading:false,error:null,records:2,last_successful_load:'2026-01-01T12:00:00Z',snapshot_available:true}}/></div><ImportPreview fileName="synthetic.csv" metrics={[{label:'Records',value:2}]} samples={[{AGR_NAME:'ZC:DEMO',TCODE:'MIGO'},{AGR_NAME:'ZC:EXAMPLE',TCODE:'ME23N'}]} warnings={['Example warning: an optional description was not supplied.']}/></Card>
      <Card><SectionHeader title="Investigation evidence" icon={<Info size={18}/>}/><ReviewFindings row={{sap_validity:'Valid',lock_status:'Unlocked',ad_status:'Unknown',match_status:'missing_email',findings:['directory_match'],stale:false}} labels={{directory_match:'Missing directory match'}}/><ChangeRecordDetails change={{source:'employees',source_name:'Synthetic directory',type:'modified',identifier:'SYNTHETIC_RECORD',fields:[{field:'Title',before:'Example analyst',after:'Example reviewer'}],before:{Name:'Synthetic Example'},after:{Name:'Synthetic Example'}}}/></Card>
      <Card><h2>Operational status and filtering</h2><div className="demo-grid"><StatusCard label="Demo service" value="Running" tone="success"/><StatusCard label="Demo source" value="Needs attention" tone="warning"/></div><FilterPanel label="Demo filters"><p className="ui-description">Apply commits only demo date state; Cancel leaves it unchanged. Calendar and filter popovers do not reflow their parent.</p><AssignmentDateFilters value={demoDates} onChange={setDemoDates}/></FilterPanel><ResultsToolbar><span>2 demo results</span><Button onClick={()=>setDemoDates({...emptyDates})}>Clear demo filters</Button></ResultsToolbar></Card>
      <Card>
        <h2>Form controls</h2>
        <p className="ui-description">
          Shared labels, control height, chevrons and visible focus. Invalid
          state is explicit rather than color-only.
        </p>
        <div className="demo-grid">
          <FormField label="Demo text" description="Supporting information">
            <Input
              value={text}
              onChange={(e) => setText(e.target.value)}
              aria-invalid={invalid}
              aria-describedby={invalid ? 'demo-validation' : undefined}
            />
            {invalid && (
              <span id="demo-validation" role="alert">
                Enter a valid demo value.
              </span>
            )}
          </FormField>
          <FormField label="Demo search">
            <SearchInput
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </FormField>
          <FormField label="Demo select">
            <Select
              className="ui-control"
              aria-label="Demo select"
              value={select}
              onChange={(e) => setSelect(e.target.value)}
            >
              <option value="all">All demo values</option>
              <option value="active">Active demo values</option>
            </Select>
          </FormField>
          <FormField label="Demo searchable role">
            <Combobox
              label="Demo searchable role"
              value={role}
              options={['ZC:DEMO:VIEW', 'ZO:DEMO:RELEASE']}
              onChange={setRole}
            />
          </FormField>
          <NorwegianDateInput
            label="Demo date"
            value={date}
            onChange={setDate}
          />
          <div>
            <Checkbox
              checked={check}
              onChange={(e) => setCheck(e.target.checked)}
            >
              Demo checkbox
            </Checkbox>
            <Toggle label="Demo toggle" checked={toggle} onChange={setToggle} />
          </div>
        </div>
        <Toolbar>
          <Button onClick={() => setInvalid((v) => !v)}>
            Toggle validation state
          </Button>
          <Input aria-label="Disabled demo input" disabled value="Disabled" />
        </Toolbar>
      </Card>
      <Card>
        <h2>Filters &amp; multi-value selection</h2>
        <ButtonGroup
          label="Demo display mode"
          value={tab}
          onChange={setTab}
          options={[
            { value: 'all', label: 'All demo values' },
            { value: 'business', label: 'Business demo values' },
          ]}
        />
        <TransactionFilter
          label="Demo multi-transaction filter"
          filter={transactions}
        />
        <SavedFilters
          view="library"
          storage={storage.current}
          state={{ search: text }}
          apply={(state) => {
            if (typeof state.search === 'string') setText(state.search)
          }}
          clear={() => setText('')}
        />
        <ClearFilterButton
          onClick={() => {
            transactions.clear()
            setText('')
          }}
        >
          Clear demo filters
        </ClearFilterButton>
        <Popover
          label="Demo popover"
          trigger={
            <>
              <Info size={16} />
              Open demo popover
            </>
          }
        >
          {(close) => (
            <>
              <p className="text-sm">
                Escape and outside click dismiss this anchored panel.
              </p>
              <Button onClick={close}>Close demo popover</Button>
            </>
          )}
        </Popover>
        <Button onClick={() => setDialogOpen(true)}>Open demo dialog</Button>
        {dialogOpen && (
          <Dialog
            title="Isolated component dialog"
            onClose={() => setDialogOpen(false)}
          >
            <p>
              This preview uses the real modal with isolated state. Escape
              closes it and restores focus.
            </p>
            <Input aria-label="Demo dialog input" />
          </Dialog>
        )}
      </Card>
      <Card>
        <h2>Status &amp; feedback</h2>
        <Toolbar>
          {(['success', 'warning', 'error', 'info', 'neutral'] as const).map(
            (tone) => (
              <StatusBadge key={tone} tone={tone}>
                {tone}
              </StatusBadge>
            ),
          )}
        </Toolbar>
        <Notification variant="info">Informational demo message</Notification>
        <Notification variant="warning">Warning demo message</Notification>
        <Notification variant="error">Error demo message</Notification>
        <LoadingState>Loading demo records…</LoadingState>
        <EmptyState>No demo results match.</EmptyState>
      </Card>
      <Card>
        <h2>SAP components &amp; data display</h2>
        <SAPUserSelector
          label="Demo SAP user"
          value={user}
          options={demoUsers}
          onChange={setUser}
        />
        <Toolbar>
          <span>SAP account</span>
          <AccountStatus value="active" />
          <AccountStatus kind="lock" value="Locked" />
          <span>AD account</span>
          <AccountStatus kind="ad" value="Disabled" />
          <AssignmentStatus value="unknown" />
          <RoleIdentifier value="ZC:DEMO:VIEW" />
        </Toolbar>
        <EvidenceDisclosure>
          Demo role-to-transaction mapping is not effective SAP authorization.
        </EvidenceDisclosure>
        <Toolbar aria-label="Demo table toolbar">
          <span>2 demo records</span>
          <Button onClick={() => setFeedback('Demo export action')}>
            <Download size={16} />
            Demo export
          </Button>
        </Toolbar>
        <DataTable caption="Component demo records">
          <thead>
            <tr>
              <th>Identifier</th>
              <th>Validity</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <RoleIdentifier value="ZC:DEMO:VIEW" />
              </td>
              <td>{dates('2020-01-01', '9999-12-31')}</td>
              <td>
                <AssignmentStatus value="active" />
              </td>
            </tr>
            <tr>
              <td>DEMO_REVIEW</td>
              <td>Unknown</td>
              <td>
                <StatusBadge>Unknown</StatusBadge>
              </td>
            </tr>
          </tbody>
        </DataTable>
        <Pagination
          label="Demo pagination"
          offset={offset}
          total={6}
          limit={2}
          onChange={setOffset}
        />
      </Card>
    </div>
  )
}
