import { type ReactNode, useState } from 'react'
import { RefreshCw, Sun, Moon } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { refreshData } from '@/api/client'
import { cn } from '@/lib/utils'

interface Props {
  children: ReactNode
  lastLoaded: string | null
  onRefresh: () => void
  isDark: boolean
  onToggleTheme: () => void
}

export function AppLayout({ children, lastLoaded, onRefresh, isDark, onToggleTheme }: Props) {
  const qc = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const handleRefresh = async () => {
    setBusy(true); setErr(null)
    try { await refreshData(); await qc.invalidateQueries(); onRefresh() }
    catch (e) { setErr(e instanceof Error ? e.message : 'Refresh failed') }
    finally { setBusy(false) }
  }

  const fmt = lastLoaded
    ? new Date(lastLoaded).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
    : null

  return (
    <div className="min-h-screen flex flex-col bg-[#f4f6f9] dark:bg-[#0d0d1a] transition-colors duration-300">

      {/* â”€â”€ Header â”€â”€ */}
      <header className="shadow-lg sticky top-0 z-30" style={{ backgroundColor: '#1A003B' }} role="banner">
        <div className="max-w-screen-2xl mx-auto px-5 h-24 flex items-center justify-between gap-4">

          {/* Brand: logo image + name */}
          <div className="flex items-center gap-3">
            {/* Logo image â€” fallback to styled "E" if file not found */}
            <img
              src="/logo.png"
              alt="Company"
              className="h-12 w-auto object-contain flex-shrink-0"
              onError={(e) => {
                const t = e.currentTarget
                t.style.display = 'none'
                const fb = t.nextElementSibling as HTMLElement | null
                if (fb) fb.style.display = 'flex'
              }}
            />
            {/* Fallback box shown only if logo.png fails to load */}
            <div
              className="w-12 h-12 rounded-lg items-center justify-center font-black text-white text-md flex-shrink-0"
              style={{ background: 'linear-gradient(135deg, #FA6414, #EEA300)', display: 'none' }}
              aria-hidden="true">APP
			</div>
            <div>
              <p className="text-white text-md leading-tight">Company</p>
              <p className="text-[10px] font-semibold tracking-widest uppercase" style={{ color: '#6b8cb8' }}>
                SAP S/4HANA &middot; SAP System
              </p>
            </div>
          </div>

          {/* Right controls */}
          <div className="flex items-center gap-3">
            {fmt && (
              <span className="text-[11px] hidden lg:block font-medium" style={{ color: '#FBF315' }}>
                Updated {fmt}
              </span>
            )}

            {/* Theme toggle â€” WCAG: descriptive aria-label */}
            <button
              onClick={onToggleTheme}
              aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
              className="flex items-center gap-1.5 text-white/80 hover:text-white text-xs font-semibold px-2.5 py-1.5 rounded-lg hover:bg-white/10 transition-all focus:outline-none focus:ring-2 focus:ring-white/50 focus:ring-offset-1 focus:ring-offset-[#1A003B]">
              {isDark ? <Sun className="w-4 h-4" aria-hidden="true" /> : <Moon className="w-4 h-4" aria-hidden="true" />}
              <span className="hidden sm:inline">{isDark ? 'Light' : 'Dark'}</span>
            </button>

            {/* Refresh */}
            <button
              onClick={handleRefresh}
              disabled={busy}
              aria-label={busy ? 'Refreshing data' : 'Refresh role data from CSV'}
              className={cn(
                'flex items-center gap-2 text-white text-xs font-bold px-3 py-1.5 rounded-lg border border-white/30 transition-all',
                'hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-white/50 focus:ring-offset-1 focus:ring-offset-[#1A003B]',
                busy && 'opacity-50 cursor-not-allowed'
              )}>
              <RefreshCw className={cn('w-3.5 h-3.5', busy && 'animate-spin')} aria-hidden="true" />
              <span className="hidden sm:inline">{busy ? 'Refreshing...' : 'Refresh Data'}</span>
            </button>
          </div>
        </div>

        {err && (
          <div role="alert" className="bg-red-700 text-white text-xs px-5 py-2 flex justify-between">
            <span>{err}</span>
            <button onClick={() => setErr(null)} className="underline ml-4">Dismiss</button>
          </div>
        )}
      </header>

      <main className="flex-1 max-w-screen-2xl mx-auto w-full px-4 sm:px-6 py-5" id="main-content">
        {children}
      </main>

      <footer className="h-20" style={{ backgroundColor: '#1A003B', color: '#ffffff' }}>
         <p className="text-[11px] py-2.5 text-center font-medium" >&copy; {new Date().getFullYear()} Company &mdash; SAP Role Checker</p>
      </footer>
    </div>
  )
}