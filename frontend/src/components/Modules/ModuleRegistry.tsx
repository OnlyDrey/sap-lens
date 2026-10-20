import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { DollarSign, BarChart2, Package, Wrench, Users, TrendingUp, Cog, FolderKanban,
  CheckCircle, Server, Warehouse, Layers, Shield, Database, Truck, Building2, Globe,
  Code, FileText, Leaf, Hash } from 'lucide-react'
import { fetchRegistry, fetchConfiguration, type RegistryEntry } from '@/api/configuration'

export const icons = { DollarSign, BarChart2, Package, Wrench, Users, TrendingUp, Cog, FolderKanban,
  CheckCircle, Server, Warehouse, Layers, Shield, Database, Truck, Building2, Globe, Code, FileText, Leaf, Hash }
const DomainContext = createContext<Record<string,string>>({})
const Context = createContext<Record<string,RegistryEntry>>({})
export function ModuleRegistryProvider({children}: {children:ReactNode}) {
  const config = useQuery({queryKey:['configuration'],queryFn:fetchConfiguration})
  const {data} = useQuery({queryKey:['registry'],queryFn:fetchRegistry,staleTime:Infinity})
  const registry = useMemo(() => Object.fromEntries((data?.modules || []).map(m => [m.id,m])),[data])
  const domains = useMemo(() => Object.fromEntries((config.data?.settings.classification_profiles.find(p=>p.id===config.data?.settings.active_classification)?.domains||[]).map(d=>[d.id,d.label])),[config.data])
  return <DomainContext.Provider value={domains}><Context.Provider value={registry}>{children}</Context.Provider></DomainContext.Provider>
}
export function useModuleVisual(code?: string | null) {
  const registry = useContext(Context)
  const key=code||'UNCLASSIFIED'
  const item = Object.prototype.hasOwnProperty.call(registry,key) ? registry[key] : undefined
  return { Icon: icons[(item?.icon || 'Hash') as keyof typeof icons] || Hash,
    color:item?.color || '#64748b', name:item?.name || code || 'Unclassified', enabled:item?.enabled ?? true }
}

export function useDomainLabel(id?:string|null) {
  const labels=useContext(DomainContext)
  return id ? (Object.prototype.hasOwnProperty.call(labels,id) ? labels[id] : id) : null
}
