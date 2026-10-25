import { useQuery } from '@tanstack/react-query'
import { Info } from 'lucide-react'
import { apiRequest } from '@/api/client'
export function About() {
  const query = useQuery({
    queryKey: ['application-info'],
    queryFn: () =>
      apiRequest<{
        version: string
        mode: string
        source_sha: string
        file_version: number[]
        python: string
        platform: string
      }>('/api/application-info'),
  })
  const info = query.data
  return (
    <section className="settings-card space-y-4" aria-label="About SAP Lens">
      <h2 className="settings-subheading">
        <Info size={18} />
        SAP Lens
      </h2>
      <p>Local SAP role investigation and evidence-based account review.</p>
      {query.isError && (
        <p role="alert">Application information unavailable.</p>
      )}
      <dl className="settings-status-list">
        <dt>Application version</dt>
        <dd>{info?.version || 'Loading…'}</dd>
        <dt>Build mode</dt>
        <dd>{info?.mode || 'Loading…'}</dd>
        <dt>Interface</dt>
        <dd>
          {window.pywebview
            ? 'Windows desktop / WebView2'
            : 'Browser development session'}
        </dd>
      </dl>
      <details className="settings-advanced">
        <summary>Build and runtime details</summary>
        <dl className="settings-status-list">
          <dt>Source commit</dt>
          <dd>{info?.source_sha || 'Not supplied for this source checkout'}</dd>
          <dt>Windows file version</dt>
          <dd>{info?.file_version?.join('.') || 'Not supplied'}</dd>
          <dt>Runtime</dt>
          <dd>
            Python {info?.python} · {info?.platform}
          </dd>
        </dl>
        <p className="text-xs">
          Dependency licenses belong to their respective projects. Account
          review annotations do not authorize changes in SAP.
        </p>
      </details>
    </section>
  )
}
