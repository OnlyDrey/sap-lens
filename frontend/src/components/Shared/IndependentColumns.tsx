import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'

/**
 * Cards in independent columns: expanding one card moves only the cards below it in its own column; the other columns stay put.
 * Cards keep their order, filling column one first, then the next (reading and focus order follow the DOM); leftovers go to the first columns.
 * The column count follows the viewport (`breakpoints`: [minimum width, columns], widest first) or, without them, the width of the container.
 */
export function IndependentColumns({ items, minWidth = 336, gap = 12, breakpoints, className = '' }: { items: ReactNode[]; minWidth?: number; gap?: number; breakpoints?: [number, number][]; className?: string }) {
  const ref = useRef<HTMLDivElement>(null), [count, setCount] = useState(1)
  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    const measure = () => {
      const wanted = breakpoints ? (breakpoints.find(([width]) => window.innerWidth >= width)?.[1] ?? 1) : Math.floor((element.clientWidth + gap) / (minWidth + gap))
      setCount(Math.max(1, Math.min(items.length || 1, wanted)))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    window.addEventListener('resize', measure)
    return () => { observer.disconnect(); window.removeEventListener('resize', measure) }
  }, [items.length, minWidth, gap, breakpoints])
  const base = Math.floor(items.length / count), extra = items.length % count
  let start = 0
  const columns = Array.from({ length: count }, (_, index) => { const size = base + (index < extra ? 1 : 0), column = items.slice(start, start + size); start += size; return column })
  return (
    <div ref={ref} className={`independent-columns ${className}`.trim()} style={{ gridTemplateColumns: `repeat(${count}, minmax(0, 1fr))` }}>
      {columns.map((column, index) => <div key={index} className="independent-column">{column}</div>)}
    </div>
  )
}
