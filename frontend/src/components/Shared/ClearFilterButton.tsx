import { Button } from './Button'
import { FilterX } from 'lucide-react'
import type { ButtonHTMLAttributes } from 'react'
export function ClearFilterButton({ children = 'Clear filter', className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <Button type="button" {...props} className={`clear-filter-button ${className}`}><FilterX size={15} aria-hidden="true"/>{children}</Button>
}
