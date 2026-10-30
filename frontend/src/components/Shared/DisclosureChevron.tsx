import { ChevronDown, ChevronRight } from 'lucide-react'

/** The one expand/collapse glyph: right when collapsed, down when expanded (the pattern of the Single Roles list). Decorative; the control that wraps it owns the name and aria-expanded. */
export function DisclosureChevron({ open, size = 16 }: { open: boolean; size?: number }) {
  return open ? <ChevronDown size={size} aria-hidden="true" /> : <ChevronRight size={size} aria-hidden="true" />
}
