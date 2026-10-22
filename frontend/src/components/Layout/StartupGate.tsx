import { type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, AlertTriangle } from 'lucide-react'
import { fetchConfiguration } from '@/api/configuration'
export function StartupGate({ children }: { children: ReactNode }) {
  const configuration = useQuery({
    queryKey: ['configuration'],
    queryFn: fetchConfiguration,
    retry: false
  })
  if (configuration.data) return children
  return (
    <div className="startup-screen">
      <div className="startup-card">
        <img
          src="/sap-lens.png"
          alt="SAP Lens"
          className="w-24 h-24 object-contain mx-auto"
        />
        <h1 className="text-3xl font-semibold mt-5">SAP Lens</h1>
        <p className="text-sm text-[var(--muted)] mt-2">
          Your local SAP role workspace
        </p>
        {configuration.isError ? (
          <>
            <AlertTriangle
              size={25}
              className="mx-auto mt-8 text-[var(--error)]"
            />
            <h2 className="font-semibold mt-4">
              Unable to connect to the local service
            </h2>
            <p role="alert" className="text-sm mt-3">
              Retry the connection. If the problem continues, close and reopen
              SAP Lens. Your saved configuration is retained.
            </p>
            <button
              className="mt-5 rounded-lg px-4 py-2 bg-[var(--accent)] text-[var(--on-accent)]"
              onClick={() => void configuration.refetch()}
            >
              Retry connection
            </button>
          </>
        ) : (
          <>
            <Loader2 className="animate-spin mx-auto mt-8 text-[var(--accent2)]" />
            <p role="status" className="mt-4">
              Loading configuration…
            </p>
            <p className="text-xs mt-3 text-[var(--muted)]">
              Waiting for configuration from the local service.
            </p>
          </>
        )}
      </div>
    </div>
  )
}
