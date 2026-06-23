import type { ReactNode } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, RequirePermission, AccessState, useAuth } from './auth'
import { DirectionProvider } from './direction'
import AppShell from './components/AppShell'
import Home from './pages/Home'
import Workspace from './pages/Workspace'
import Products from './pages/Products'
import Analytics from './pages/Analytics'
import Audit from './pages/Audit'
import Logs from './pages/Logs'
import Settings from './pages/Settings'
import Admin from './pages/Admin'
import Login from './pages/Login'

function MaintenanceOverlay({ message }: { message?: string }) {
  const { clearAuth } = useAuth()
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-base/95 backdrop-blur-sm">
      <div className="max-w-md w-full mx-4 bg-bg-card border border-border rounded-card shadow-card p-8 text-center">
        <div className="w-14 h-14 rounded-full bg-amber-100 flex items-center justify-center mx-auto mb-4">
          <svg viewBox="0 0 24 24" className="w-7 h-7 text-amber-600" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
        </div>
        <h2 className="text-[18px] font-bold text-text-base mb-2">Maintenance Mode</h2>
        <p className="text-[13px] text-wp-muted mb-6">
          {message || 'WooPrice is temporarily in maintenance mode. Please try again later.'}
        </p>
        <button
          onClick={() => { clearAuth() }}
          className="px-5 py-2 rounded-lg bg-accent text-white text-[13px] font-medium hover:bg-accent/90 transition-colors"
        >
          Sign out
        </button>
      </div>
    </div>
  )
}

// Redirects unauthenticated users to /login and shows a loading screen while
// the auth state is being resolved. Must be rendered inside AuthProvider.
function AuthGuard({ children }: { children: ReactNode }) {
  const { status, user } = useAuth()
  if (status === 'loading') {
    return (
      <div className="min-h-screen bg-bg-base flex items-center justify-center">
        <span className="text-[13px] text-wp-muted">Loading…</span>
      </div>
    )
  }
  if (status === 'login_required') return <Navigate to="/login" replace />
  if (status === 'permission_denied') return <AccessState status="permission_denied" />
  // Maintenance mode: only super admins (SUPER_ADMIN_USERS) bypass the overlay.
  if (user?.maintenance?.enabled && !user.is_super_admin) {
    return <MaintenanceOverlay message={user.maintenance.message} />
  }
  return <>{children}</>
}

// Prevents authenticated users from seeing the login page.
// Shows loading screen while auth state resolves to avoid a form flash.
function GuestOnly({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  if (status === 'loading') {
    return (
      <div className="min-h-screen bg-bg-base flex items-center justify-center">
        <span className="text-[13px] text-wp-muted">Loading…</span>
      </div>
    )
  }
  if (status === 'authenticated') return <Navigate to="/home" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <DirectionProvider>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<GuestOnly><Login /></GuestOnly>} />
            <Route path="/" element={<Navigate to="/home" replace />} />
            <Route element={<AuthGuard><AppShell /></AuthGuard>}>
              <Route path="/home" element={<Home />} />
              <Route path="/workspace" element={<RequirePermission permission="can_fetch"><Workspace /></RequirePermission>} />
              <Route path="/products" element={<RequirePermission permission="can_fetch"><Products /></RequirePermission>} />
              <Route
                path="/analytics"
                element={<RequirePermission permission="can_access_site"><Analytics /></RequirePermission>}
              />
              <Route path="/audit" element={<RequirePermission permission="can_view_logs"><Audit /></RequirePermission>} />
              <Route path="/logs" element={<RequirePermission permission="can_view_logs"><Logs /></RequirePermission>} />
              <Route path="/settings" element={<RequirePermission permission="can_view_settings"><Settings /></RequirePermission>} />
              <Route path="/admin" element={<RequirePermission adminOnly><Admin /></RequirePermission>} />
            </Route>
          </Routes>
        </AuthProvider>
      </DirectionProvider>
    </BrowserRouter>
  )
}
