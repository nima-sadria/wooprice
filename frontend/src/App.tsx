import type { ReactNode } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, RequirePermission, AccessState, useAuth } from './auth'
import { DirectionProvider } from './direction'
import AppShell from './components/AppShell'
import Home from './pages/Home'
import Workspace from './pages/Workspace'
import Analytics from './pages/Analytics'
import Audit from './pages/Audit'
import Logs from './pages/Logs'
import Settings from './pages/Settings'
import Admin from './pages/Admin'
import Login from './pages/Login'

// Redirects unauthenticated users to /login and shows a loading screen while
// the auth state is being resolved. Must be rendered inside AuthProvider.
function AuthGuard({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  if (status === 'loading') {
    return (
      <div className="min-h-screen bg-bg-base flex items-center justify-center">
        <span className="text-[13px] text-wp-muted">Loading…</span>
      </div>
    )
  }
  if (status === 'login_required') return <Navigate to="/login" replace />
  if (status === 'permission_denied') return <AccessState status="permission_denied" />
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
              <Route path="/workspace" element={<Workspace />} />
              <Route
                path="/analytics"
                element={<RequirePermission permission="can_access_site"><Analytics /></RequirePermission>}
              />
              <Route path="/audit" element={<RequirePermission permission="can_view_logs"><Audit /></RequirePermission>} />
              <Route path="/logs" element={<RequirePermission permission="can_view_logs"><Logs /></RequirePermission>} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/admin" element={<RequirePermission adminOnly><Admin /></RequirePermission>} />
            </Route>
          </Routes>
        </AuthProvider>
      </DirectionProvider>
    </BrowserRouter>
  )
}
