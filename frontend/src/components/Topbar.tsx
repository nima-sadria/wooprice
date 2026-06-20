import { useState } from 'react'
import { useLocation } from 'react-router-dom'

const PAGE_TITLES: Record<string, string> = {
  '/home': 'Dashboard',
  '/workspace': 'Workspace',
  '/analytics': 'Analytics',
  '/logs': 'Logs',
  '/settings': 'Settings',
  '/admin': 'Admin',
}

const SIGNOUT_ICON = (
  <svg viewBox="0 0 24 24" className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
    <polyline points="16 17 21 12 16 7" />
    <line x1="21" y1="12" x2="9" y2="12" />
  </svg>
)

interface Props {
  onMenuClick: () => void
  health: 'ok' | 'error' | 'loading'
  user: { username: string } | null
  onLogout: () => void
}

export default function Topbar({ onMenuClick, health, user, onLogout }: Props) {
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const title = PAGE_TITLES[location.pathname] ?? 'WooPrice'

  const healthDot =
    health === 'ok' ? 'bg-wp-green' :
    health === 'error' ? 'bg-wp-red' :
    'bg-border'

  const healthLabel =
    health === 'ok' ? 'Connected' :
    health === 'error' ? 'Offline' :
    '—'

  function handleLogout() {
    setMenuOpen(false)
    onLogout()
  }

  return (
    <header className="h-16 bg-bg-card border-b border-border flex items-center px-4 gap-4 flex-shrink-0">
      {/* Hamburger — mobile only */}
      <button
        onClick={onMenuClick}
        className="md:hidden flex items-center justify-center w-8 h-8 rounded text-wp-muted hover:text-text-base hover:bg-bg-base transition-colors"
        aria-label="Open navigation"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-5 h-5">
          <line x1="3" y1="6" x2="21" y2="6" />
          <line x1="3" y1="12" x2="21" y2="12" />
          <line x1="3" y1="18" x2="21" y2="18" />
        </svg>
      </button>

      {/* Breadcrumb */}
      <div className="flex items-center gap-1.5 text-[13px]">
        <span className="text-wp-muted">WooPrice</span>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-3 h-3 text-wp-muted rtl:rotate-180">
          <path d="m9 18 6-6-6-6" />
        </svg>
        <span className="font-medium text-text-base">{title}</span>
      </div>

      <div className="ms-auto flex items-center gap-4">
        {/* Health indicator */}
        <div className="flex items-center gap-1.5 text-[12px] text-wp-muted">
          <span className={['w-2 h-2 rounded-full flex-shrink-0', healthDot].join(' ')} />
          <span className="hidden sm:inline">{healthLabel}</span>
        </div>

        {/* Avatar — click opens user menu */}
        {user && (
          <div
            className="relative"
            onBlur={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
                setMenuOpen(false)
              }
            }}
          >
            <button
              onClick={() => setMenuOpen(o => !o)}
              aria-label="User menu"
              aria-expanded={menuOpen}
              className="w-8 h-8 rounded-full bg-accent flex items-center justify-center text-white text-xs font-bold select-none hover:ring-2 hover:ring-accent/40 transition-shadow"
            >
              {user.username.slice(0, 2).toUpperCase()}
            </button>

            {menuOpen && (
              <div className="absolute end-0 top-full mt-1.5 w-44 bg-bg-card border border-border rounded-lg shadow-card py-1 z-50">
                <div className="px-3 py-2 text-[12px] text-wp-muted border-b border-border truncate">
                  {user.username}
                </div>
                <button
                  onClick={handleLogout}
                  className="w-full flex items-center gap-2 px-3 py-2 text-[13px] text-wp-red hover:bg-bg-base transition-colors"
                >
                  {SIGNOUT_ICON}
                  Sign out
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </header>
  )
}
