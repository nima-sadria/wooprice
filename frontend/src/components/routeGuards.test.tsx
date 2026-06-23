// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import React from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { AuthContext, RequirePermission } from '../auth'
import type { AuthContextValue, AuthUser } from '../auth'
import Sidebar from './Sidebar'

// ─── Test infrastructure ─────────────────────────────────────────────────────

function makeUser(overrides: Partial<AuthUser> = {}): AuthUser {
  return {
    username: 'testuser',
    role: 'user',
    is_admin: false,
    is_super_admin: false,
    permissions: {
      can_access_site: true,
      can_fetch: true,
      can_apply: true,
      can_edit_price: true,
      can_edit_stock: true,
      can_view_logs: false,
      can_view_settings: false,
    },
    ...overrides,
  }
}

function makeAuth(user: AuthUser | null, status: AuthContextValue['status'] = 'authenticated'): AuthContextValue {
  return {
    user,
    status,
    refreshUser: async () => {},
    clearAuth: () => {},
    authFetch: async () => new Response('', { status: 200 }),
  }
}

// Denied: can_access_site=false and all other relevant perms false
const deniedUser = makeUser({
  permissions: {
    can_access_site: false,
    can_fetch: false,
    can_apply: false,
    can_edit_price: false,
    can_edit_stock: false,
    can_view_logs: false,
    can_view_settings: false,
  },
})
// Allowed: can_access_site=true + can_fetch=true (default makeUser)
const allowedUser = makeUser()
// Allowed with elevated permissions for /settings, /audit, /logs
const logsUser = makeUser({ permissions: { ...allowedUser.permissions, can_view_logs: true } as Record<string, boolean> })
const settingsUser = makeUser({ permissions: { ...allowedUser.permissions, can_view_settings: true } as Record<string, boolean> })
// Admin and super admin bypass all permission checks
const adminUser = makeUser({ is_admin: true, permissions: { can_access_site: false, can_fetch: false, can_view_logs: false, can_view_settings: false } })
const superUser = makeUser({ is_super_admin: true, permissions: { can_access_site: false, can_fetch: false, can_view_logs: false, can_view_settings: false } })

let container: HTMLDivElement
let root: ReturnType<typeof createRoot>

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

function renderAuth(ui: React.ReactElement, authValue: AuthContextValue) {
  act(() => {
    root.render(
      <AuthContext.Provider value={authValue}>
        {ui}
      </AuthContext.Provider>
    )
  })
  return container
}

// ─── Mini-app: route guard matrix ────────────────────────────────────────────
// Mirrors the actual route config in App.tsx without pulling in full page components.

function RouteMatrix({ initialPath }: { initialPath: string }) {
  return (
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/home" element={<RequirePermission permission="can_access_site"><span>home-page</span></RequirePermission>} />
        <Route path="/workspace" element={<RequirePermission permission="can_fetch"><span>workspace-page</span></RequirePermission>} />
        <Route path="/products" element={<RequirePermission permission="can_fetch"><span>products-page</span></RequirePermission>} />
        <Route path="/analytics" element={<RequirePermission permission="can_access_site"><span>analytics-page</span></RequirePermission>} />
        <Route path="/audit" element={<RequirePermission permission="can_view_logs"><span>audit-page</span></RequirePermission>} />
        <Route path="/logs" element={<RequirePermission permission="can_view_logs"><span>logs-page</span></RequirePermission>} />
        <Route path="/settings" element={<RequirePermission permission="can_view_settings"><span>settings-page</span></RequirePermission>} />
        <Route path="/admin" element={<RequirePermission adminOnly><span>admin-page</span></RequirePermission>} />
      </Routes>
    </MemoryRouter>
  )
}

// ─── RequirePermission — direct render ───────────────────────────────────────

describe('RequirePermission — direct render', () => {
  it('renders children when permission is granted', () => {
    const c = renderAuth(
      <MemoryRouter>
        <RequirePermission permission="can_access_site">
          <span>protected</span>
        </RequirePermission>
      </MemoryRouter>,
      makeAuth(allowedUser)
    )
    expect(c.textContent).toContain('protected')
  })

  it('shows Access Denied when permission is missing', () => {
    const c = renderAuth(
      <MemoryRouter>
        <RequirePermission permission="can_access_site">
          <span>protected</span>
        </RequirePermission>
      </MemoryRouter>,
      makeAuth(deniedUser)
    )
    expect(c.textContent).not.toContain('protected')
    expect(c.textContent).toContain('Access Denied')
  })

  it('admin bypasses permission check', () => {
    const c = renderAuth(
      <MemoryRouter>
        <RequirePermission permission="can_access_site">
          <span>protected</span>
        </RequirePermission>
      </MemoryRouter>,
      makeAuth(adminUser)
    )
    expect(c.textContent).toContain('protected')
  })

  it('super admin bypasses permission check', () => {
    const c = renderAuth(
      <MemoryRouter>
        <RequirePermission permission="can_view_settings">
          <span>settings</span>
        </RequirePermission>
      </MemoryRouter>,
      makeAuth(superUser)
    )
    expect(c.textContent).toContain('settings')
  })

  it('enforces can_access_site gate before specific permission (can_fetch denied)', () => {
    const user = makeUser({ permissions: { can_access_site: false, can_fetch: true } })
    const c = renderAuth(
      <MemoryRouter>
        <RequirePermission permission="can_fetch">
          <span>workspace</span>
        </RequirePermission>
      </MemoryRouter>,
      makeAuth(user)
    )
    expect(c.textContent).not.toContain('workspace')
    expect(c.textContent).toContain('Access Denied')
  })

  it('adminOnly denies regular users', () => {
    const c = renderAuth(
      <MemoryRouter>
        <RequirePermission adminOnly>
          <span>admin-only</span>
        </RequirePermission>
      </MemoryRouter>,
      makeAuth(allowedUser)
    )
    expect(c.textContent).not.toContain('admin-only')
  })

  it('adminOnly allows admin users', () => {
    const c = renderAuth(
      <MemoryRouter>
        <RequirePermission adminOnly>
          <span>admin-only</span>
        </RequirePermission>
      </MemoryRouter>,
      makeAuth(adminUser)
    )
    expect(c.textContent).toContain('admin-only')
  })
})

// ─── Router — /home route guard ───────────────────────────────────────────────

describe('Router — /home', () => {
  it('renders Home for allowed user (can_access_site=true)', () => {
    const c = renderAuth(<RouteMatrix initialPath="/home" />, makeAuth(allowedUser))
    expect(c.textContent).toContain('home-page')
  })

  it('shows Access Denied for denied user (can_access_site=false)', () => {
    const c = renderAuth(<RouteMatrix initialPath="/home" />, makeAuth(deniedUser))
    expect(c.textContent).not.toContain('home-page')
    expect(c.textContent).toContain('Access Denied')
  })

  it('renders Home for admin regardless of permissions', () => {
    const c = renderAuth(<RouteMatrix initialPath="/home" />, makeAuth(adminUser))
    expect(c.textContent).toContain('home-page')
  })

  it('renders Home for super admin regardless of permissions', () => {
    const c = renderAuth(<RouteMatrix initialPath="/home" />, makeAuth(superUser))
    expect(c.textContent).toContain('home-page')
  })
})

// ─── Router — /workspace ──────────────────────────────────────────────────────

describe('Router — /workspace', () => {
  it('renders Workspace for user with can_access_site=true and can_fetch=true', () => {
    const c = renderAuth(<RouteMatrix initialPath="/workspace" />, makeAuth(allowedUser))
    expect(c.textContent).toContain('workspace-page')
  })

  it('shows Access Denied when can_access_site=false (even if can_fetch=true)', () => {
    const user = makeUser({ permissions: { can_access_site: false, can_fetch: true } })
    const c = renderAuth(<RouteMatrix initialPath="/workspace" />, makeAuth(user))
    expect(c.textContent).not.toContain('workspace-page')
    expect(c.textContent).toContain('Access Denied')
  })

  it('renders Workspace for admin', () => {
    const c = renderAuth(<RouteMatrix initialPath="/workspace" />, makeAuth(adminUser))
    expect(c.textContent).toContain('workspace-page')
  })

  it('renders Workspace for super admin', () => {
    const c = renderAuth(<RouteMatrix initialPath="/workspace" />, makeAuth(superUser))
    expect(c.textContent).toContain('workspace-page')
  })
})

// ─── Router — /products ───────────────────────────────────────────────────────

describe('Router — /products', () => {
  it('renders Products for allowed user', () => {
    const c = renderAuth(<RouteMatrix initialPath="/products" />, makeAuth(allowedUser))
    expect(c.textContent).toContain('products-page')
  })

  it('shows Access Denied for denied user', () => {
    const c = renderAuth(<RouteMatrix initialPath="/products" />, makeAuth(deniedUser))
    expect(c.textContent).not.toContain('products-page')
    expect(c.textContent).toContain('Access Denied')
  })

  it('renders Products for admin', () => {
    const c = renderAuth(<RouteMatrix initialPath="/products" />, makeAuth(adminUser))
    expect(c.textContent).toContain('products-page')
  })

  it('renders Products for super admin', () => {
    const c = renderAuth(<RouteMatrix initialPath="/products" />, makeAuth(superUser))
    expect(c.textContent).toContain('products-page')
  })
})

// ─── Router — /settings ───────────────────────────────────────────────────────

describe('Router — /settings', () => {
  it('renders Settings for user with can_view_settings=true', () => {
    const c = renderAuth(<RouteMatrix initialPath="/settings" />, makeAuth(settingsUser))
    expect(c.textContent).toContain('settings-page')
  })

  it('shows Access Denied for user without can_view_settings', () => {
    const c = renderAuth(<RouteMatrix initialPath="/settings" />, makeAuth(allowedUser))
    expect(c.textContent).not.toContain('settings-page')
    expect(c.textContent).toContain('Access Denied')
  })

  it('shows Access Denied when can_access_site=false (even if can_view_settings=true)', () => {
    const user = makeUser({ permissions: { can_access_site: false, can_view_settings: true } })
    const c = renderAuth(<RouteMatrix initialPath="/settings" />, makeAuth(user))
    expect(c.textContent).not.toContain('settings-page')
    expect(c.textContent).toContain('Access Denied')
  })

  it('renders Settings for admin', () => {
    const c = renderAuth(<RouteMatrix initialPath="/settings" />, makeAuth(adminUser))
    expect(c.textContent).toContain('settings-page')
  })

  it('renders Settings for super admin', () => {
    const c = renderAuth(<RouteMatrix initialPath="/settings" />, makeAuth(superUser))
    expect(c.textContent).toContain('settings-page')
  })
})

// ─── Router — /audit ─────────────────────────────────────────────────────────

describe('Router — /audit', () => {
  it('renders Audit for user with can_view_logs=true', () => {
    const c = renderAuth(<RouteMatrix initialPath="/audit" />, makeAuth(logsUser))
    expect(c.textContent).toContain('audit-page')
  })

  it('shows Access Denied for user without can_view_logs', () => {
    const c = renderAuth(<RouteMatrix initialPath="/audit" />, makeAuth(allowedUser))
    expect(c.textContent).not.toContain('audit-page')
    expect(c.textContent).toContain('Access Denied')
  })

  it('shows Access Denied when can_access_site=false (even if can_view_logs=true)', () => {
    const user = makeUser({ permissions: { can_access_site: false, can_view_logs: true } })
    const c = renderAuth(<RouteMatrix initialPath="/audit" />, makeAuth(user))
    expect(c.textContent).not.toContain('audit-page')
    expect(c.textContent).toContain('Access Denied')
  })

  it('renders Audit for admin', () => {
    const c = renderAuth(<RouteMatrix initialPath="/audit" />, makeAuth(adminUser))
    expect(c.textContent).toContain('audit-page')
  })

  it('renders Audit for super admin', () => {
    const c = renderAuth(<RouteMatrix initialPath="/audit" />, makeAuth(superUser))
    expect(c.textContent).toContain('audit-page')
  })
})

// ─── Router — /logs ───────────────────────────────────────────────────────────

describe('Router — /logs', () => {
  it('renders Logs for user with can_view_logs=true', () => {
    const c = renderAuth(<RouteMatrix initialPath="/logs" />, makeAuth(logsUser))
    expect(c.textContent).toContain('logs-page')
  })

  it('shows Access Denied for user without can_view_logs', () => {
    const c = renderAuth(<RouteMatrix initialPath="/logs" />, makeAuth(allowedUser))
    expect(c.textContent).not.toContain('logs-page')
    expect(c.textContent).toContain('Access Denied')
  })

  it('renders Logs for admin', () => {
    const c = renderAuth(<RouteMatrix initialPath="/logs" />, makeAuth(adminUser))
    expect(c.textContent).toContain('logs-page')
  })

  it('renders Logs for super admin', () => {
    const c = renderAuth(<RouteMatrix initialPath="/logs" />, makeAuth(superUser))
    expect(c.textContent).toContain('logs-page')
  })
})

// ─── Sidebar — nav visibility ─────────────────────────────────────────────────

function renderSidebar(user: AuthUser | null) {
  return renderAuth(
    <MemoryRouter>
      <Sidebar open collapsed={false} onClose={() => {}} onToggleCollapse={() => {}} user={user} />
    </MemoryRouter>,
    makeAuth(user)
  )
}

describe('Sidebar — denied user (can_access_site=false)', () => {
  it('hides Dashboard link', () => {
    const c = renderSidebar(deniedUser)
    expect(c.querySelector('a[href="/home"]')).toBeNull()
  })

  it('hides Workspace link', () => {
    const c = renderSidebar(deniedUser)
    expect(c.querySelector('a[href="/workspace"]')).toBeNull()
  })

  it('hides Products link', () => {
    const c = renderSidebar(deniedUser)
    expect(c.querySelector('a[href="/products"]')).toBeNull()
  })

  it('hides Analytics link', () => {
    const c = renderSidebar(deniedUser)
    expect(c.querySelector('a[href="/analytics"]')).toBeNull()
  })

  it('hides Audit link', () => {
    const c = renderSidebar(deniedUser)
    expect(c.querySelector('a[href="/audit"]')).toBeNull()
  })

  it('hides Logs link', () => {
    const c = renderSidebar(deniedUser)
    expect(c.querySelector('a[href="/logs"]')).toBeNull()
  })

  it('hides Settings link', () => {
    const c = renderSidebar(deniedUser)
    expect(c.querySelector('a[href="/settings"]')).toBeNull()
  })
})

describe('Sidebar — allowed user (can_access_site=true, can_fetch=true)', () => {
  it('shows Dashboard link', () => {
    const c = renderSidebar(allowedUser)
    expect(c.querySelector('a[href="/home"]')).not.toBeNull()
  })

  it('shows Workspace link', () => {
    const c = renderSidebar(allowedUser)
    expect(c.querySelector('a[href="/workspace"]')).not.toBeNull()
  })

  it('shows Products link', () => {
    const c = renderSidebar(allowedUser)
    expect(c.querySelector('a[href="/products"]')).not.toBeNull()
  })

  it('shows Analytics link', () => {
    const c = renderSidebar(allowedUser)
    expect(c.querySelector('a[href="/analytics"]')).not.toBeNull()
  })

  it('hides Audit link (no can_view_logs)', () => {
    const c = renderSidebar(allowedUser)
    expect(c.querySelector('a[href="/audit"]')).toBeNull()
  })

  it('hides Settings link (no can_view_settings)', () => {
    const c = renderSidebar(allowedUser)
    expect(c.querySelector('a[href="/settings"]')).toBeNull()
  })

  it('hides Admin link (not is_admin)', () => {
    const c = renderSidebar(allowedUser)
    expect(c.querySelector('a[href="/admin"]')).toBeNull()
  })
})

describe('Sidebar — admin user', () => {
  it('shows all nav links', () => {
    const c = renderSidebar(adminUser)
    expect(c.querySelector('a[href="/home"]')).not.toBeNull()
    expect(c.querySelector('a[href="/workspace"]')).not.toBeNull()
    expect(c.querySelector('a[href="/products"]')).not.toBeNull()
    expect(c.querySelector('a[href="/analytics"]')).not.toBeNull()
    expect(c.querySelector('a[href="/audit"]')).not.toBeNull()
    expect(c.querySelector('a[href="/logs"]')).not.toBeNull()
    expect(c.querySelector('a[href="/settings"]')).not.toBeNull()
    expect(c.querySelector('a[href="/admin"]')).not.toBeNull()
  })
})

describe('Sidebar — super admin (is_super_admin=true, is_admin=false)', () => {
  it('shows all permission-gated links', () => {
    const c = renderSidebar(superUser)
    expect(c.querySelector('a[href="/home"]')).not.toBeNull()
    expect(c.querySelector('a[href="/workspace"]')).not.toBeNull()
    expect(c.querySelector('a[href="/products"]')).not.toBeNull()
    expect(c.querySelector('a[href="/analytics"]')).not.toBeNull()
    expect(c.querySelector('a[href="/audit"]')).not.toBeNull()
    expect(c.querySelector('a[href="/logs"]')).not.toBeNull()
    expect(c.querySelector('a[href="/settings"]')).not.toBeNull()
  })

  it('hides Admin link (is_admin=false)', () => {
    // Admin link uses user.is_admin directly, not effectiveHasPerm
    const c = renderSidebar(superUser)
    expect(c.querySelector('a[href="/admin"]')).toBeNull()
  })
})
