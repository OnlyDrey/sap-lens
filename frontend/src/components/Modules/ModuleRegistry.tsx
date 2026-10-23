import { defaultDark, defaultLight } from '@/lib/theme'
import {
  createContext,
  useContext,
  useMemo,
  useState,
  useEffect,
  type ReactNode
} from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  DollarSign,
  BarChart2,
  Package,
  Wrench,
  Users,
  TrendingUp,
  Cog,
  FolderKanban,
  CheckCircle,
  Server,
  Warehouse,
  Layers,
  Shield,
  Database,
  Truck,
  Building2,
  Globe,
  Code,
  FileText,
  Leaf,
  Hash
} from 'lucide-react'
import { catalogIcon } from './CatalogIcon'
import {
  fetchRegistry,
  fetchConfiguration,
  type RegistryEntry
} from '@/api/configuration'

export const icons = {
  DollarSign,
  BarChart2,
  Package,
  Wrench,
  Users,
  TrendingUp,
  Cog,
  FolderKanban,
  CheckCircle,
  Server,
  Warehouse,
  Layers,
  Shield,
  Database,
  Truck,
  Building2,
  Globe,
  Code,
  FileText,
  Leaf,
  Hash
}
const PaletteContext = createContext(defaultDark)
export const useModulePalette = () => useContext(PaletteContext)
function discoveredColor(value: string) {
  // Same stable ID hash/palette as backend.module_registry.discovered_color.
  const palette = ['#6f8fc5', '#a184bc', '#b08b60', '#629c9b', '#8da16d', '#b47f87', '#6599b0', '#b3879c']
  // Bound display-only hashing even if an imported source label is unusually long.
  let prefix = '', count = 0
  for (const character of value) {
    prefix += character
    if (++count === 256) break
  }
  let fingerprint = 2166136261
  for (const character of prefix.trim().toUpperCase().replace(/_/g, '-').replace(/ /g, '')) {
    fingerprint = Math.imul(fingerprint ^ character.codePointAt(0)!, 16777619) >>> 0
  }
  return palette[fingerprint % palette.length]
}
const Context = createContext<Record<string, RegistryEntry>>({})
export function ModuleRegistryProvider({ children }: { children: ReactNode }) {
  const [systemDark, setSystemDark] = useState(
    () => matchMedia('(prefers-color-scheme: dark)').matches
  )
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)')
    const change = () => setSystemDark(media.matches)
    media.addEventListener('change', change)
    return () => media.removeEventListener('change', change)
  }, [])
  const config = useQuery({
    queryKey: ['configuration'],
    queryFn: fetchConfiguration
  })
  const { data } = useQuery({
    queryKey: ['registry'],
    queryFn: fetchRegistry,
    staleTime: Infinity
  })
  const registry = useMemo(
    () => Object.fromEntries((data?.modules || []).map((m) => [m.id, m])),
    [data]
  )
  const mode = config.data?.settings.theme || 'dark'
  const dark = mode === 'dark' || (mode === 'system' && systemDark)
  const palette =
    config.data?.settings.theme_colors?.[dark ? 'dark' : 'light'] ||
    (dark ? defaultDark : defaultLight)
  return (
    <PaletteContext.Provider value={palette}>
        <Context.Provider value={registry}>{children}</Context.Provider>
    </PaletteContext.Provider>
  )
}
export const useModuleDefinitions = () => useContext(Context)

export function useModuleVisual(code?: string | null) {
  const registry = useContext(Context)
  const key = code || 'UNCLASSIFIED'
  const item = Object.prototype.hasOwnProperty.call(registry, key)
    ? registry[key]
    : undefined
  return {
    Icon:
      icons[(item?.icon || 'Hash') as keyof typeof icons] ||
      catalogIcon(item?.icon || 'Hash'),
    color: item?.color || (key === 'UNCLASSIFIED' ? '#8793a2' : discoveredColor(key)),
    name: item?.name || code || 'Unclassified',
    enabled: item?.enabled ?? true
  }
}
