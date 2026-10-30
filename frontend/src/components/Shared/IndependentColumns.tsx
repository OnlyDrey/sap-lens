import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'

/**
 * Cards in independent columns: expanding one card moves only the cards below it in its own column; the other columns and the card heights beside it stay put.
 * Cards keep their order, filling column one first, then column two (reading and focus order follow the DOM).
 */
export function IndependentColumns({ items, minWidth = 336, gap = 12, className = '' }: { items: ReactNode[]; minWidth?: number; gap?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null), [count, setCount] = useState(1)
  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    const measure = () => setCount(Math.max(1, Math.min(items.length || 1, Math.floor((element.clientWidth + gap) / (minWidth + gap)))))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [items.length, minWidth, gap])
  const size = Math.ceil(items.length / count), columns = Array.from({ length: count }, (_, index) => items.slice(index * size, (index + 1) * size))
  return (
    <div ref={ref} className={`independent-columns ${className}`.trim()} style={{ gridTemplateColumns: `repeat(${count}, minmax(0, 1fr))` }}>
      {columns.map((column, index) => <div key={index} className="independent-column">{column}</div>)}
    </div>
  )
}
