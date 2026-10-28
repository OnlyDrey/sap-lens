import { useId, type ReactNode } from 'react'
/** One layout primitive; routes remain links and content switches remain tabs. */
function NavigationStrip({ variant, label, children, className = '' }: {
  variant: 'main' | 'secondary' | 'tabs'; label: string; children: ReactNode; className?: string
}) {
  const classes = `ui-navigation flex min-w-0 items-stretch gap-2 overflow-x-auto ${variant === 'main' ? '' : 'mb-3'} ${variant === 'main' ? 'primary-navigation' : variant === 'secondary' ? 'ui-secondary-navigation' : 'ui-content-tabs'} ${className}`
  return variant === 'tabs'
    ? <div role="tablist" aria-label={label} className={classes}>{children}</div>
    : <nav aria-label={label} className={classes}>{children}</nav>
}
export function MainNavigation({
  children,
  label = 'Main navigation',
}: {
  children: ReactNode
  label?: string
}) {
  return (
    <NavigationStrip variant="main" label={label}>
      {children}
    </NavigationStrip>
  )
}
export function SecondaryNavigation({
  label,
  items,
}: {
  label: string
  items: {
    value: string
    label: string
    href: string
    active: boolean
    onSelect: () => void
    icon?: ReactNode
  }[]
}) {
  return (
    <NavigationStrip variant="secondary" label={label}>
      {items.map((item) => (
        <a
          key={item.value}
          className="inline-flex min-h-control items-center gap-2 whitespace-nowrap border-b-2 border-transparent px-3 py-2 text-sm text-secondary no-underline hover:border-content hover:text-content focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus aria-[current=page]:border-action aria-[current=page]:text-content aria-[current=page]:font-semibold"
          href={item.href}
          aria-current={item.active ? 'page' : undefined}
          onClick={(event) => {
            if (
              event.button === 0 &&
              !event.ctrlKey &&
              !event.metaKey &&
              !event.shiftKey &&
              !event.altKey
            ) {
              event.preventDefault()
              item.onSelect()
            }
          }}
        >
          {item.icon}
          <span>{item.label}</span>
        </a>
      ))}
    </NavigationStrip>
  )
}
type TabItem = {
  value: string
  label: string
  icon?: ReactNode
}
export function ContentTabList({
  label,
  value,
  items,
  onChange,
  idPrefix,
  panelId,
  className = '',
}: {
  label: string
  value: string
  items: TabItem[]
  onChange: (value: string) => void
  idPrefix: string
  panelId: (value: string) => string
  className?: string
}) {
  return (
    <NavigationStrip variant="tabs" label={label} className={className}>
      {items.map((item, index) => (
        <button
          type="button"
          key={item.value}
          id={`${idPrefix}-${item.value}`}
          className="inline-flex min-h-control items-center gap-2 whitespace-nowrap border-b-2 border-transparent px-3 py-2 text-sm text-secondary hover:border-content hover:text-content focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus aria-selected:border-action aria-selected:text-content aria-selected:font-semibold"
          role="tab"
          aria-controls={panelId(item.value)}
          aria-selected={value === item.value}
          tabIndex={value === item.value ? 0 : -1}
          onClick={() => onChange(item.value)}
          onKeyDown={(event) => {
            if (
              ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)
            ) {
              event.preventDefault()
              const target =
                items[
                  event.key === 'Home'
                    ? 0
                    : event.key === 'End'
                      ? items.length - 1
                      : (index +
                          (event.key === 'ArrowRight' ? 1 : items.length - 1)) %
                        items.length
                ]
              onChange(target.value)
              document.getElementById(`${idPrefix}-${target.value}`)?.focus()
            }
          }}
        >
          {item.icon}
          <span>{item.label}</span>
        </button>
      ))}
    </NavigationStrip>
  )
}
export function ContentTabs({
  label,
  value,
  items,
  onChange,
  children,
}: {
  label: string
  value: string
  items: TabItem[]
  onChange: (value: string) => void
  children: ReactNode
}) {
  const uid = useId(),
    selected = items.find((item) => item.value === value) || items[0]
  return (
    <div className="ui-tabs min-w-0">
      <ContentTabList
        label={label}
        value={value}
        items={items}
        onChange={onChange}
        idPrefix={uid}
        panelId={() => `${uid}-panel`}
      />
      <div
        className="grid min-w-0 gap-4"
        role="tabpanel"
        id={`${uid}-panel`}
        aria-labelledby={`${uid}-${selected.value}`}
        tabIndex={0}
      >
        {children}
      </div>
    </div>
  )
}

/** Primary destinations are real links: modified clicks open a new tab, a plain click navigates inside the app. */
export function MainNavigationItem({
  label,
  icon,
  active,
  href,
  onNavigate,
}: {
  label: string
  icon: ReactNode
  active: boolean
  href: string
  onNavigate: () => void
}) {
  return (
    <a
      href={href}
      title={label}
      className="primary-nav-button"
      aria-current={active ? 'page' : undefined}
      onClick={(event) => {
        if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
        event.preventDefault()
        onNavigate()
      }}
    >
      {icon}
      <span>{label}</span>
    </a>
  )
}
