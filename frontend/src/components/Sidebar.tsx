import { NavLink, useNavigate } from 'react-router-dom'
import type { AuthUser } from '../auth'
import { useAuth } from '../auth'

interface Props {
  open: boolean
  collapsed: boolean
  onClose: () => void
  onToggleCollapse: () => void
  user: AuthUser | null
}

function initials(name: string) {
  return name.slice(0, 2).toUpperCase()
}

export default function Sidebar({ open, collapsed, onClose, onToggleCollapse, user }: Props) {
  const { clearAuth } = useAuth()
  const navigate = useNavigate()

  const linkCls = ({ isActive }: { isActive: boolean }) =>
    [
      'flex items-center gap-3 px-3 py-2.5 rounded-lg text-[13px] font-medium transition-colors mb-0.5',
      collapsed ? 'justify-center px-0' : '',
      isActive
        ? 'bg-accent text-white'
        : 'text-wp-muted hover:text-text-base hover:bg-bg-base',
    ].join(' ')

  function handleLogout() {
    clearAuth()
    navigate('/login', { replace: true })
  }

  return (
    <>
      {/* Mobile backdrop */}
      {open && (
        <div
          className="fixed inset-0 bg-black/40 z-20 md:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={[
          'flex flex-col bg-bg-card border-e border-border h-screen flex-shrink-0',
          'fixed md:sticky top-0 inset-y-0 start-0 z-30',
          'transition-all duration-200 ease-in-out',
          open ? 'translate-x-0' : '-translate-x-full rtl:translate-x-full md:!translate-x-0',
          collapsed ? 'w-[58px]' : 'w-60',
        ].join(' ')}
      >
        {/* Brand */}
        <div
          className={[
            'flex items-center h-16 border-b border-border flex-shrink-0',
            collapsed ? 'flex-col justify-center gap-1 py-3 px-2' : 'px-4 gap-3',
          ].join(' ')}
        >
          <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center flex-shrink-0">
            <svg viewBox="0 0 36 36" className="w-5 h-5 text-white" fill="currentColor">
              <path d="M14.747 9.125c.527-1.426 1.736-2.573 3.317-2.573 1.643 0 2.792 1.085 3.318 2.573l6.077 16.867c.186.496.248.931.248 1.147 0 1.209-.992 2.046-2.139 2.046-1.303 0-1.954-.682-2.264-1.611l-.931-2.915h-8.62l-.93 2.884c-.31.961-.961 1.642-2.232 1.642-1.24 0-2.294-.93-2.294-2.17 0-.496.155-.868.217-1.023l6.233-16.867zm.34 11.256h5.891l-2.883-8.992h-.062l-2.946 8.992z" />
            </svg>
          </div>

          {!collapsed && (
            <div className="flex-1 min-w-0">
              <div className="font-bold text-sm text-text-base leading-tight">WooPrice</div>
              <div className="text-[11px] text-wp-muted">Price Sync</div>
            </div>
          )}

          {/* Collapse button — desktop only */}
          <button
            onClick={onToggleCollapse}
            className="hidden md:flex items-center justify-center w-[26px] h-[26px] rounded border border-border text-wp-muted hover:text-accent hover:border-accent transition-colors flex-shrink-0"
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              className={[
                'w-3 h-3 transition-transform duration-200',
                collapsed ? 'rotate-180' : '',
              ].join(' ')}
            >
              <path d="m15 18-6-6 6-6" />
            </svg>
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 py-3 overflow-y-auto">
          {!collapsed && (
            <p className="px-2 mb-2 text-[10px] font-semibold uppercase tracking-wider text-wp-muted select-none">
              WooPrice
            </p>
          )}

          <NavLink to="/home" className={linkCls} onClick={onClose}>
            <svg viewBox="0 0 24 24" className="w-[18px] h-[18px] flex-shrink-0" fill="currentColor">
              <rect x="3" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="3" width="7" height="7" rx="1" />
              <rect x="3" y="14" width="7" height="7" rx="1" />
              <rect x="14" y="14" width="7" height="7" rx="1" />
            </svg>
            {!collapsed && <span>Dashboard</span>}
          </NavLink>

          <NavLink to="/workspace" className={linkCls} onClick={onClose}>
            <svg viewBox="0 0 24 24" className="w-[18px] h-[18px] flex-shrink-0" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M23 4v6h-6" />
              <path d="M1 20v-6h6" />
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
            </svg>
            {!collapsed && <span>Workspace</span>}
          </NavLink>

          <NavLink to="/analytics" className={linkCls} onClick={onClose}>
            <svg viewBox="0 0 24 24" className="w-[18px] h-[18px] flex-shrink-0" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="18" y1="20" x2="18" y2="10" />
              <line x1="12" y1="20" x2="12" y2="4" />
              <line x1="6" y1="20" x2="6" y2="14" />
            </svg>
            {!collapsed && <span>Analytics</span>}
          </NavLink>

          <NavLink to="/logs" className={linkCls} onClick={onClose}>
            <svg viewBox="0 0 24 24" className="w-[18px] h-[18px] flex-shrink-0" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
            </svg>
            {!collapsed && <span>Logs</span>}
          </NavLink>

          <NavLink to="/settings" className={linkCls} onClick={onClose}>
            <svg viewBox="0 0 24 24" className="w-[18px] h-[18px] flex-shrink-0" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
            {!collapsed && <span>Settings</span>}
          </NavLink>

          {user?.is_admin && (
            <NavLink to="/admin" className={linkCls} onClick={onClose}>
              <svg viewBox="0 0 24 24" className="w-[18px] h-[18px] flex-shrink-0" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                <circle cx="9" cy="7" r="4" />
                <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                <path d="M16 3.13a4 4 0 0 1 0 7.75" />
              </svg>
              {!collapsed && <span>Admin</span>}
            </NavLink>
          )}
        </nav>

        {/* Footer */}
        <div className="border-t border-border p-3 flex-shrink-0 flex flex-col gap-2">
          {/* User identity */}
          <div
            className={[
              'flex items-center gap-2.5',
              collapsed ? 'justify-center' : '',
            ].join(' ')}
          >
            <div className="w-8 h-8 rounded-full bg-accent flex items-center justify-center text-white text-xs font-bold flex-shrink-0 select-none">
              {user ? initials(user.username) : '?'}
            </div>
            {!collapsed && user && (
              <div className="flex-1 min-w-0">
                <div className="text-[13px] font-medium text-text-base truncate">{user.username}</div>
                <div className="text-[11px] text-wp-muted">{user.role}</div>
              </div>
            )}
          </div>

          {/* Logout */}
          <button
            onClick={handleLogout}
            title="Sign out"
            className={[
              'flex items-center gap-2 rounded-lg px-2 py-1.5 text-[13px] font-medium',
              'text-wp-muted hover:text-wp-red hover:bg-bg-base transition-colors',
              collapsed ? 'justify-center' : 'w-full',
            ].join(' ')}
          >
            <svg viewBox="0 0 24 24" className="w-[16px] h-[16px] flex-shrink-0" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
            {!collapsed && <span>Sign out</span>}
          </button>
        </div>
      </aside>
    </>
  )
}
