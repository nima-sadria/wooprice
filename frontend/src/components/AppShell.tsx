import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import Sidebar, { type WpUser } from './Sidebar'
import Topbar from './Topbar'

type HealthStatus = 'ok' | 'error' | 'loading'

function readStoredUser(): WpUser | null {
  try {
    const raw = localStorage.getItem('wp_user')
    if (!raw) return null
    const u = JSON.parse(raw) as { username?: string; role?: string }
    if (!u.username) return null
    return { username: u.username, role: u.role ?? 'operator' }
  } catch {
    return null
  }
}

export default function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem('wp-sb-col') === '1'
  )
  const [health, setHealth] = useState<HealthStatus>('loading')
  const [user, setUser] = useState<WpUser | null>(readStoredUser)

  useEffect(() => {
    const check = async () => {
      try {
        const r = await fetch('/api/health')
        setHealth(r.ok ? 'ok' : 'error')
      } catch {
        setHealth('error')
      }
    }
    void check()
    const id = setInterval(() => { void check() }, 30_000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === 'wp_user') setUser(readStoredUser())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  function handleToggleCollapse() {
    setSidebarCollapsed(c => {
      const next = !c
      localStorage.setItem('wp-sb-col', next ? '1' : '0')
      return next
    })
  }

  return (
    <div className="flex h-screen bg-bg-base overflow-hidden">
      <Sidebar
        open={sidebarOpen}
        collapsed={sidebarCollapsed}
        onClose={() => setSidebarOpen(false)}
        onToggleCollapse={handleToggleCollapse}
        user={user}
      />
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Topbar
          onMenuClick={() => setSidebarOpen(o => !o)}
          health={health}
          user={user}
        />
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
