import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ModuleRegistryProvider } from './components/Modules/ModuleRegistry'
import { App } from './App'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5 * 60 * 1000, retry: 2 } },
})
const rootElement = document.getElementById('root')
if (!rootElement) throw new Error('Root element #root not found')

// Insert skip-to-content link before the root div
const skipLink = document.createElement('a')
skipLink.href = '#main-content'
skipLink.className = 'skip-link'
skipLink.textContent = 'Skip to main content'
document.body.insertBefore(skipLink, rootElement)

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ModuleRegistryProvider><App /></ModuleRegistryProvider>
    </QueryClientProvider>
  </StrictMode>
)