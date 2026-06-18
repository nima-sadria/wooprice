import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, RequirePermission } from './auth'
import { DirectionProvider } from './direction'
import AppShell from './components/AppShell'
import Home from './pages/Home'
import Workspace from './pages/Workspace'
import Analytics from './pages/Analytics'
import Logs from './pages/Logs'
import Settings from './pages/Settings'
import Admin from './pages/Admin'

export default function App() {
  return (
    <BrowserRouter>
      <DirectionProvider>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<Navigate to="/home" replace />} />
            <Route element={<AppShell />}>
              <Route path="/home" element={<Home />} />
              <Route path="/workspace" element={<Workspace />} />
              <Route
                path="/analytics"
                element={<RequirePermission permission="can_access_site"><Analytics /></RequirePermission>}
              />
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
