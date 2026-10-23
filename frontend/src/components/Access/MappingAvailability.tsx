import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { UsersRound, Settings2 } from 'lucide-react'
import { fetchConfiguration } from '@/api/configuration'
import { useViewHistory } from '@/hooks/useViewHistory'

/** Unmount assignment views on disable so cached evidence cannot remain visible. */
export function MappingAvailability({ children }: { children: ReactNode }) {
  const config = useQuery({
    queryKey: ['configuration'],
    queryFn: fetchConfiguration,
  })
  const { change } = useViewHistory()
  if (!config.data)
    return (
      <p role={config.isError ? 'alert' : 'status'}>
        {config.isError
          ? 'Feature settings could not be checked.'
          : 'Checking feature availability…'}
      </p>
    )
  if (config.data.settings.features?.user_role_mapping === false)
    return (
      <section
        className="information-card space-y-3"
        aria-label="User–Role Mapping disabled"
      >
        <h1 className="flex items-center gap-2">
          <UsersRound size={20} />
          User–Role Mapping is disabled
        </h1>
        <p>
          Imported data and CSV configuration are retained. Enable User–Role
          Mapping in Settings → Features and apply settings to use assignment
          investigations. Role Lookup remains available.
        </p>
        <button
          className="settings-secondary-button"
          onClick={() => change({ settings: true, settingsTarget: 'features' })}
        >
          <Settings2 size={16} />
          Open Settings
        </button>
      </section>
    )
  return <>{children}</>
}
