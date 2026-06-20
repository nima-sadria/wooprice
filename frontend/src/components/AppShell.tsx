import { useEffect, useState } from 'react'
import { Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import Sidebar from './Sidebar'
import Topbar from './Topbar'

type HealthStatus = 'ok' | 'error' | 'loading'

export default function AppShell() {
  const { user, clearAuth } = useAuth()
  const navigate = useNavigate()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem('wp-sb-col') === '1'
  )
  const [health, setHealth] = useState<HealthStatus>('loading')

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

  function handleLogout() {
    clearAuth()
    navigate('/login', { replace: true })
  }

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
          onLogout={handleLogout}
        />
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
