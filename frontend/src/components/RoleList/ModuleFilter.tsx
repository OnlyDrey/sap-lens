import { cn } from '@/lib/utils'
import type { ModuleInfo } from '@/api/types'

interface ModuleFilterProps { modules: ModuleInfo[]; selectedModule: string | null; onSelect: (key: string | null) => void }

export function ModuleFilter({ modules, selectedModule, onSelect }: ModuleFilterProps) {
  const btnCls = (active: boolean) => cn(
    'px-3 py-1 rounded-full text-sm font-medium border transition-colors focus:outline-none focus:ring-2 focus:ring-[#003366]',
    active ? 'bg-[#003366] text-white border-[#003366]' : 'bg-white text-gray-600 border-gray-300 hover:bg-blue-50 hover:border-[#003366] hover:text-[#003366]'
  )
  return (
    <nav className="flex flex-wrap gap-2 py-2">
      <button onClick={() => onSelect(null)} className={btnCls(selectedModule === null)}>All</button>
      {modules.map((mod) => (
        <button key={mod.function_key} onClick={() => onSelect(mod.function_key)} title={mod.module_name} className={btnCls(selectedModule === mod.function_key)}>
          {mod.function_key}
        </button>
      ))}
    </nav>
  )
}