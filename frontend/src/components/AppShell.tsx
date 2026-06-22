import { useEffect, useRef, useState } from 'react'
import { Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import Sidebar from './Sidebar'
import Topbar from './Topbar'

type HealthStatus = 'ok' | 'error' | 'loading'

const HEALTH_INTERVAL_MS = 15_000
const HEALTH_RETRY_MS = 5_000
const HEALTH_MAX_RETRIES = 3

export default function AppShell() {
  const { user, clearAuth, authFetch } = useAuth()
  const navigate = useNavigate()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem('wp-sb-col') === '1'
  )
  const [health, setHealth] = useState<HealthStatus>('loading')
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const retryCountRef = useRef(0)

  useEffect(() => {
    let intervalId: ReturnType<typeof setInterval>

    const cancelRetry = () => {
      if (retryRef.current !== null) {
        clearTimeout(retryRef.current)
        retryRef.current = null
      }
    }

    const check = async () => {
      cancelRetry()
      try {
        const r = await authFetch('/api/health')
        if (r.ok) {
          retryCountRef.current = 0
          setHealth('ok')
        } else {
          handleFailure()
        }
      } catch {
        handleFailure()
      }
    }

    const handleFailure = () => {
      retryCountRef.current += 1
      if (retryCountRef.current <= HEALTH_MAX_RETRIES) {
        // Show loading (checking) instead of hard error during retry window
        setHealth('loading')
        retryRef.current = setTimeout(() => { void check() }, HEALTH_RETRY_MS)
      } else {
        retryCountRef.current = 0
        setHealth('error')
      }
    }

    void check()
    intervalId = setInterval(() => {
      retryCountRef.current = 0
      void check()
    }, HEALTH_INTERVAL_MS)

    return () => {
      clearInterval(intervalId)
      cancelRetry()
    }
  }, [authFetch])

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
