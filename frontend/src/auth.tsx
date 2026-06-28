import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { effectiveHasPerm } from './utils/permissions'

type PermissionMap = Record<string, boolean>

export interface MaintenanceState {
  enabled: boolean
  message: string
}

export interface AuthUser {
  username: string
  role: string
  is_admin: boolean
  is_super_admin: boolean
  permissions: PermissionMap
  maintenance?: MaintenanceState
}

type AuthStatus = 'loading' | 'authenticated' | 'login_required' | 'permission_denied'

export interface AuthContextValue {
  user: AuthUser | null
  status: AuthStatus
  refreshUser: () => Promise<void>
  clearAuth: () => void
  authFetch: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

function clearStoredAuth() {
  localStorage.removeItem('wp_token')
  localStorage.removeItem('wp_refresh_token')
  localStorage.removeItem('wp_user')
}

function authHeaders(init?: RequestInit) {
  const headers = new Headers(init?.headers)
  const token = localStorage.getItem('wp_token') ?? ''
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return headers
}

async function attemptTokenRefresh(): Promise<boolean> {
  const refreshToken = localStorage.getItem('wp_refresh_token') ?? ''
  if (!refreshToken) return false
  try {
    const r = await fetch('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!r.ok) return false
    const data = await r.json() as { token: string; refresh_token: string }
    localStorage.setItem('wp_token', data.token)
    localStorage.setItem('wp_refresh_token', data.refresh_token)
    return true
  } catch {
    return false
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [status, setStatus] = useState<AuthStatus>('loading')

  const clearAuth = useCallback(() => {
    clearStoredAuth()
    setUser(null)
    setStatus('login_required')
  }, [])

  const refreshUser = useCallback(async () => {
    const token = localStorage.getItem('wp_token') ?? ''
    if (!token) {
      // No access token — try refresh before giving up
      const refreshed = await attemptTokenRefresh()
      if (!refreshed) {
        setUser(null)
        setStatus('login_required')
        return
      }
    }

    setStatus('loading')
    try {
      const r = await fetch('/api/auth/me', { headers: authHeaders() })
      if (r.status === 401) {
        // Access token rejected — attempt silent refresh once
        const refreshed = await attemptTokenRefresh()
        if (refreshed) {
          const r2 = await fetch('/api/auth/me', { headers: authHeaders() })
          if (r2.ok) {
            const nextUser = (await r2.json()) as AuthUser
            setUser(nextUser)
            setStatus('authenticated')
            localStorage.setItem('wp_user', JSON.stringify(nextUser))
            return
          }
        }
        clearStoredAuth()
        setUser(null)
        setStatus('login_required')
        return
      }
      if (r.status === 403) {
        setUser(null)
        setStatus('permission_denied')
        return
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const nextUser = (await r.json()) as AuthUser
      setUser(nextUser)
      setStatus('authenticated')
      localStorage.setItem('wp_user', JSON.stringify(nextUser))
    } catch {
      setUser(null)
      setStatus('login_required')
    }
  }, [])

  const authFetch = useCallback(async (input: RequestInfo | URL, init?: RequestInit) => {
    const r = await fetch(input, { ...init, headers: authHeaders(init) })
    if (r.status === 401) {
      // Silent refresh: try once, retry the original request, then logout
      const refreshed = await attemptTokenRefresh()
      if (refreshed) {
        return fetch(input, { ...init, headers: authHeaders(init) })
      }
      clearAuth()
    }
    if (r.status === 403) setStatus('permission_denied')
    if (r.status === 503) {
      // Detect a maintenance-mode block and immediately activate the overlay,
      // even for sessions that were already authenticated before maintenance was enabled.
      try {
        const body = await r.clone().json() as Record<string, unknown>
        if (body?.maintenance === true) {
          setUser(prev =>
            prev ? { ...prev, maintenance: { enabled: true, message: typeof body.detail === 'string' ? body.detail : '' } } : prev
          )
        }
      } catch { /* not a JSON maintenance response — ignore */ }
    }
    return r
  }, [clearAuth])

  useEffect(() => {
    void refreshUser()
  }, [refreshUser])

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === 'wp_token' || e.key === 'wp_refresh_token' || e.key === 'wp_user') {
        void refreshUser()
      }
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [refreshUser])

  const value = useMemo(() => ({
    user,
    status,
    refreshUser,
    clearAuth,
    authFetch,
  }), [user, status, refreshUser, clearAuth, authFetch])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}

export function AccessState({
  status,
  message,
}: {
  status: Exclude<AuthStatus, 'authenticated'>
  message?: string
}) {
  const title = status === 'permission_denied' ? 'Access Denied' : status === 'loading' ? 'Checking Access' : 'Login Required'
  const body =
    message ??
    (status === 'permission_denied'
      ? 'Your account does not have permission to view this content.'
      : status === 'loading'
        ? 'Verifying your session with the server.'
        : 'Please sign in to continue.')

  return (
    <div className="p-7">
      <div className="max-w-xl bg-bg-card border border-border rounded-card shadow-card p-6">
        <h1 className="text-[22px] font-bold text-text-base">{title}</h1>
        <p className="text-[13px] text-wp-muted mt-2">{body}</p>
      </div>
    </div>
  )
}

export function RequirePermission({
  permission,
  adminOnly = false,
  children,
}: {
  permission?: string
  adminOnly?: boolean
  children: ReactNode
}) {
  const { user, status } = useAuth()
  if (status !== 'authenticated') return <AccessState status={status} />
  if (!user) return <AccessState status="login_required" />
  if (adminOnly && !user.is_admin) return <AccessState status="permission_denied" />
  if (permission && !effectiveHasPerm(user, permission)) {
    return <AccessState status="permission_denied" />
  }
  return <>{children}</>
}
