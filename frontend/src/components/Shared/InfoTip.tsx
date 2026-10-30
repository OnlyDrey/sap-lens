import type { ReactNode } from 'react'
import { Info } from 'lucide-react'
import { Popover } from './Popover'

/** Secondary explanation kept out of the card: an info button that opens a small anchored popover (keyboard and Escape handled by Popover). */
export function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Popover label={label} preferredWidth={320} triggerSize="icon" trigger={<span className="relative inline-flex"><Info size={16} aria-hidden="true" /><span className="sr-only">{label}</span></span>}>
      <div className="info-tip-body">{children}</div>
    </Popover>
  )
}
