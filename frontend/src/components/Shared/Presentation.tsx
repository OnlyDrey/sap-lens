import type { HTMLAttributes, ReactNode } from 'react'
import { Info, Loader2 } from 'lucide-react'
export function Toolbar({
  children,
  className = '',
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div {...props} className={`ui-toolbar ${className}`}>
      {children}
    </div>
  )
}
export function Card({
  children,
  className = '',
  ...props
}: HTMLAttributes<HTMLElement>) {
  return (
    <section {...props} className={`ui-card ${className}`}>
      {children}
    </section>
  )
}
export function PageHeader({
  title,
  children,
  icon,
  titleAction,
}: {
  icon?: ReactNode
  titleAction?: ReactNode
  title: string
  children?: ReactNode
}) {
  return (
    <header className="ui-page-header">
      <div className="ui-page-title">{icon}<h1>{title}</h1>{titleAction}</div>
      {children}
    </header>
  )
}
export function StatusBadge({
  tone = 'neutral',
  children,
  className = '',
  ...props
}: {
  tone?: 'neutral' | 'success' | 'warning' | 'error' | 'info'
  children: ReactNode
} & HTMLAttributes<HTMLSpanElement>) {
  return (
    <span {...props} className={`evidence-badge evidence-${tone} ${className}`}>
      {children}
    </span>
  )
}
export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="ui-empty-state">{children}</p>
}
export function LoadingState({
  children = 'Loading local records…',
}: {
  children?: ReactNode
}) {
  return (
    <p role="status" className="ui-loading">
      <Loader2 size={16} className="animate-spin" aria-hidden="true" />
      {children}
    </p>
  )
}
export function EvidenceDisclosure({
  title = 'About investigation evidence',
  children,
}: {
  title?: string
  children: ReactNode
}) {
  return (
    <details className="ui-evidence-disclosure">
      <summary>
        <Info size={16} aria-hidden="true" />
        {title}
      </summary>
      <div>{children}</div>
    </details>
  )
}
export function DataTable({
  caption,
  children,
  tableClassName = '',
  regionLabel,
}: {
  caption: string
  children: ReactNode
  tableClassName?: string
  regionLabel?: string
}) {
  return (
    <div
      className="access-table"
      tabIndex={0}
      role="region"
      aria-label={regionLabel || `Scrollable ${caption}`}
    >
      <table className={tableClassName}>
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  )
}

/** Compact full-width facts, not a multi-column dashboard. */
export function MetadataList({items}:{items:{label:string;value:ReactNode}[]}) {
 return <dl className="ui-metadata-list">{items.map(item=><div key={item.label}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}</dl>
}
