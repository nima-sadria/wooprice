import { useLocation } from 'react-router-dom'

const PAGE_TITLES: Record<string, string> = {
  '/home': 'Dashboard',
  '/workspace': 'Workspace',
  '/analytics': 'Analytics',
  '/logs': 'Logs',
  '/settings': 'Settings',
  '/admin': 'Admin',
}

interface Props {
  onMenuClick: () => void
  health: 'ok' | 'error' | 'loading'
  user: { username: string } | null
}

export default function Topbar({ onMenuClick, health, user }: Props) {
  const location = useLocation()
  const title = PAGE_TITLES[location.pathname] ?? 'WooPrice'

  const healthDot =
    health === 'ok' ? 'bg-wp-green' :
    health === 'error' ? 'bg-wp-red' :
    'bg-border'

  const healthLabel =
    health === 'ok' ? 'Connected' :
    health === 'error' ? 'Offline' :
    '—'

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

      <div className="ml-auto flex items-center gap-4">
        {/* Health indicator */}
        <div className="flex items-center gap-1.5 text-[12px] text-wp-muted">
          <span className={['w-2 h-2 rounded-full flex-shrink-0', healthDot].join(' ')} />
          <span className="hidden sm:inline">{healthLabel}</span>
        </div>

        {/* Avatar */}
        {user && (
          <div
            className="w-8 h-8 rounded-full bg-accent flex items-center justify-center text-white text-xs font-bold cursor-pointer select-none"
            title={user.username}
          >
            {user.username.slice(0, 2).toUpperCase()}
          </div>
        )}
      </div>
    </header>
  )
}
