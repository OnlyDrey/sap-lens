import { FilterX } from 'lucide-react'
import type { ButtonHTMLAttributes } from 'react'
export function ClearFilterButton({ children = 'Clear filter', className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type="button" {...props} className={`settings-secondary-button clear-filter-button ${className}`}><FilterX size={15} aria-hidden="true"/>{children}</button>
}
