import type { SelectHTMLAttributes } from 'react'
import { ChevronDown } from 'lucide-react'
export function Select({ className = '', ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <span className="settings-select shared-select"><select {...props} className={className}/><ChevronDown size={16} aria-hidden="true"/></span>
}
