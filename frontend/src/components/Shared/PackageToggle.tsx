import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** Round selection toggle shared by comparison and the access package (catalogue and release roles) so every list reads the same. */
export function PackageToggle({ active, label, onToggle, children, className }: { active: boolean; label: string; onToggle: () => void; children: ReactNode; className?: string }) {
  return (
    <button data-np type="button" onClick={e => { e.stopPropagation(); onToggle() }} aria-label={label} title={label} aria-pressed={active}
      className={cn('w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 transition-all focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--focus)] hover:scale-110 active:scale-95', className)}
      style={active
        ? { backgroundColor:'var(--accent)', color:'var(--on-accent)', border:'none' }
        : { backgroundColor:'var(--surface2)', color:'var(--muted)', border:'1.5px solid var(--border)' }}>
      {children}
    </button>
  )
}
