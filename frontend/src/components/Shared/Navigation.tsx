import { useId, type ReactNode } from 'react'
export function MainNavigation({
  children,
  label = 'Main navigation',
}: {
  children: ReactNode
  label?: string
}) {
  return (
    <nav aria-label={label} className="primary-navigation">
      {children}
    </nav>
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
  }[]
}) {
  return (
    <nav aria-label={label} className="ui-secondary-navigation">
      {items.map((item) => (
        <a
          key={item.value}
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
          <span>{item.label}</span>
        </a>
      ))}
    </nav>
  )
}
type TabItem = {
  value: string
  label: string
  count?: number
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
    <div
      role="tablist"
      aria-label={label}
      className={`ui-content-tabs ${className}`}
    >
      {items.map((item, index) => (
        <button
          type="button"
          key={item.value}
          id={`${idPrefix}-${item.value}`}
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
          {item.count !== undefined && (
            <span className="ui-tab-count">{item.count}</span>
          )}
        </button>
      ))}
    </div>
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
    <div className="ui-tabs">
      <ContentTabList
        label={label}
        value={value}
        items={items}
        onChange={onChange}
        idPrefix={uid}
        panelId={() => `${uid}-panel`}
      />
      <div
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

export function MainNavigationItem({
  label,
  icon,
  active,
  onClick,
}: {
  label: string
  icon: ReactNode
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      title={label}
      className="primary-nav-button"
      aria-current={active ? 'page' : undefined}
      onClick={onClick}
    >
      {icon}
      <span>{label}</span>
    </button>
  )
}
