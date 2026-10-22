import type { ReactNode } from 'react'

export function ImportSection({ step, title, description, children }: { step: number; title: string; description: string; children: ReactNode }) {
  return <section className="import-section" aria-label={title}>
    <div className="import-section-heading"><span aria-hidden="true">{step}</span><div><h2>{title}</h2><p>{description}</p></div></div>
    <div className="import-section-body">{children}</div>
  </section>
}
