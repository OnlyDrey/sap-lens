import { ApplicationDataProvider } from './state/ApplicationData'
import { ViewHistory, initializeViewHistory } from './hooks/useViewHistory'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ModuleRegistryProvider } from './components/Modules/ModuleRegistry'
import { StartupGate } from './components/Layout/StartupGate'
import { App } from './App'
import './index.css'
import './styles/components.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5 * 60 * 1000, retry: 2 } },
})
const rootElement = document.getElementById('root')
if (!rootElement) throw new Error('Root element #root not found')

rootElement.dataset.appMounted = 'true'

// Insert skip-to-content link before the root div
const skipLink = document.createElement('a')
skipLink.href = '#main-content'
skipLink.className = 'skip-link'
skipLink.textContent = 'Skip to main content'
skipLink.addEventListener('click', event => { event.preventDefault(); const main = document.getElementById('main-content'); main?.focus(); main?.scrollIntoView() })
document.body.insertBefore(skipLink, rootElement)

initializeViewHistory()

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ModuleRegistryProvider><ViewHistory><ApplicationDataProvider><StartupGate><App /></StartupGate></ApplicationDataProvider></ViewHistory></ModuleRegistryProvider>
    </QueryClientProvider>
  </StrictMode>
)