import {selectSource,type CSVSource,type SourceSelection,type SourceActivation} from '@/api/sources'
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchConfiguration } from '@/api/configuration'
import { refreshData } from '@/api/client'
import type { RefreshSummary } from '@/components/Shared/RefreshReport'

/** Source snapshot identity is separate from the SAP refresh timestamp. */
function datasetRevision(data:Awaited<ReturnType<typeof fetchConfiguration>>) {
 const sources=data.settings.data_lifecycle?.sources as Record<string,{snapshot?:string}>|undefined
 return JSON.stringify([data.data_revision??data.analysis,...['roles','users','sod'].map(source=>sources?.[source]?.snapshot||null),data.settings.employee_snapshot_id||null])
}
const Context = createContext<{
  loading: boolean
  importPhase:string|null
  activateSource:(source:CSVSource,selection:SourceSelection)=>Promise<SourceActivation>
  refresh: () => Promise<void>
  lastLoaded: string | null
  report: RefreshSummary | null
  dismissReport: () => void
}>({ loading: false, importPhase:null,activateSource:async()=>{throw Error('Application data is not ready.')}, refresh: async () => {}, lastLoaded: null, report:null,dismissReport:()=>{} })
const isDatasetQuery = (query: { queryKey: readonly unknown[] }) =>
  !['configuration', 'logo', 'application-version', 'application-info'].includes(
    String(query.queryKey[0]),
  )
/** Owns startup/background publication observation across every route. No CSV data is stored here. */
export function ApplicationDataProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient(),
    observed = useRef<string | null>(null)
  const [refreshing, setRefreshing] = useState(false),
    [synchronizing, setSynchronizing] = useState(false)
  const running = useRef(false)
  const [report,setReport]=useState<RefreshSummary|null>(null)
  const [importPhase,setImportPhase]=useState<string|null>(null)
  const configuration = useQuery({
    queryKey: ['configuration'],
    queryFn: fetchConfiguration,
    retry: false,
    refetchInterval: (query) => (query.state.data?.loading ? 500 : 3000),
  })
  const synchronize = useCallback(
    async (revision: string) => {
      if (observed.current === revision) return
      observed.current = revision
      setSynchronizing(true)
      try {
        // A late response from the previous publication must not repopulate a new route's cache.
        await qc.cancelQueries({ predicate: isDatasetQuery })
        await qc.invalidateQueries({
          predicate: isDatasetQuery,
          refetchType: 'active',
        })
      } finally {
        setSynchronizing(false)
      }
    },
    [qc],
  )
  useEffect(() => {
    const data = configuration.data
    if (!data) return
    const revision = datasetRevision(data)
    if (observed.current === null && data.loading) observed.current = revision
    if (!data.loading) void synchronize(revision)
  }, [configuration.data, synchronize])
  const refresh = useCallback(async () => {
    if (running.current || configuration.data?.loading) return
    running.current = true
    setRefreshing(true)
    try {
      const result=await refreshData()
      setReport(result.refresh || {id:null,timestamp:new Date().toISOString(),status:'unchanged',checked:0,updated:0,unchanged:0,failed:0,skipped:0,sources:[]})
      const data = await qc.fetchQuery({
        queryKey: ['configuration'],
        queryFn: fetchConfiguration,
        staleTime: 0,
      })
      await synchronize(datasetRevision(data))
      await qc.invalidateQueries({predicate:q=>['dashboard','diagnostics','refresh-history','employee-status','data-health'].includes(String(q.queryKey[0]))||String(q.queryKey[0]).startsWith('sod')})
    } finally {
      running.current = false
      setRefreshing(false)
      // Failed refreshes retain the publication and still update shared recovery information.
      void qc.invalidateQueries({ queryKey: ['configuration'] })
    }
  }, [qc, synchronize, configuration.data?.loading])
  const activateSource=useCallback(async(source:CSVSource,selection:SourceSelection)=>{
    if(running.current||configuration.data?.loading)throw Error('Another CSV operation is running. Wait for it to finish.')
    running.current=true;setRefreshing(true);setImportPhase('Reading file');setReport(null)
    try{
      const result=await selectSource(source,selection)
      setImportPhase('Updating dependent views')
      const data=await qc.fetchQuery({queryKey:['configuration'],queryFn:fetchConfiguration,staleTime:0})
      const revision=datasetRevision(data)
      // Directory-only publications intentionally retain the SAP generation.
      if(observed.current===revision)await qc.invalidateQueries({predicate:isDatasetQuery})
      else await synchronize(revision)
      setReport(result.refresh);setImportPhase('Completed');return result
    }catch(error){setImportPhase('Failed');throw error}
    finally{running.current=false;setRefreshing(false);void qc.invalidateQueries({queryKey:['configuration']})}
  },[qc,synchronize,configuration.data?.loading])
  return (
    <Context.Provider
      value={{
        loading:
          refreshing || synchronizing || Boolean(configuration.data?.loading),
        refresh,
        activateSource,
        importPhase:importPhase&&configuration.data?.loading?(configuration.data.progress?.stage||importPhase):importPhase,
        report,
        dismissReport:()=>setReport(null),
        lastLoaded:
          configuration.data?.data_revision &&
          configuration.data.data_revision !== 'empty'
            ? configuration.data.data_revision
            : null,
      }}
    >
      {children}
    </Context.Provider>
  )
}
export const useApplicationData = () => useContext(Context)
