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

const Context = createContext<{
  loading: boolean
  refresh: () => Promise<void>
  lastLoaded: string | null
  report: RefreshSummary | null
  dismissReport: () => void
}>({ loading: false, refresh: async () => {}, lastLoaded: null, report:null,dismissReport:()=>{} })
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
    const revision = data.data_revision ?? JSON.stringify(data.analysis)
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
      await synchronize(data.data_revision ?? JSON.stringify(data.analysis))
      await qc.invalidateQueries({predicate:q=>['dashboard','diagnostics','refresh-history','employee-status','data-health'].includes(String(q.queryKey[0]))})
    } finally {
      running.current = false
      setRefreshing(false)
      // Failed refreshes retain the publication and still update shared recovery information.
      void qc.invalidateQueries({ queryKey: ['configuration'] })
    }
  }, [qc, synchronize, configuration.data?.loading])
  return (
    <Context.Provider
      value={{
        loading:
          refreshing || synchronizing || Boolean(configuration.data?.loading),
        refresh,
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
