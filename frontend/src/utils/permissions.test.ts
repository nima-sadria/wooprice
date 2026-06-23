// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { effectiveHasPerm } from './permissions'
import type { PermissionsUser } from './permissions'

function makeUser(overrides: Partial<PermissionsUser> & { permissions?: Record<string, boolean> } = {}): PermissionsUser {
  return {
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

describe('effectiveHasPerm — can_access_site gate', () => {
  it('denies can_fetch when can_access_site=false even if can_fetch=true', () => {
    const user = makeUser({ permissions: { can_access_site: false, can_fetch: true } })
    expect(effectiveHasPerm(user, 'can_fetch')).toBe(false)
  })

  it('denies can_view_settings when can_access_site=false even if can_view_settings=true', () => {
    const user = makeUser({ permissions: { can_access_site: false, can_view_settings: true } })
    expect(effectiveHasPerm(user, 'can_view_settings')).toBe(false)
  })

  it('denies can_view_logs when can_access_site=false even if can_view_logs=true', () => {
    const user = makeUser({ permissions: { can_access_site: false, can_view_logs: true } })
    expect(effectiveHasPerm(user, 'can_view_logs')).toBe(false)
  })

  it('allows can_fetch when can_access_site=true and can_fetch=true', () => {
    const user = makeUser({ permissions: { can_access_site: true, can_fetch: true } })
    expect(effectiveHasPerm(user, 'can_fetch')).toBe(true)
  })

  it('denies can_fetch when can_access_site=true but can_fetch=false', () => {
    const user = makeUser({ permissions: { can_access_site: true, can_fetch: false } })
    expect(effectiveHasPerm(user, 'can_fetch')).toBe(false)
  })

  it('denies can_access_site itself when can_access_site=false', () => {
    const user = makeUser({ permissions: { can_access_site: false } })
    expect(effectiveHasPerm(user, 'can_access_site')).toBe(false)
  })
})

describe('effectiveHasPerm — admin bypass', () => {
  it('allows any permission when is_admin=true regardless of can_access_site', () => {
    const user = makeUser({ is_admin: true, permissions: { can_access_site: false, can_fetch: false } })
    expect(effectiveHasPerm(user, 'can_fetch')).toBe(true)
    expect(effectiveHasPerm(user, 'can_view_settings')).toBe(true)
    expect(effectiveHasPerm(user, 'can_view_logs')).toBe(true)
    expect(effectiveHasPerm(user, 'can_access_site')).toBe(true)
  })

  it('allows any permission when is_super_admin=true regardless of can_access_site', () => {
    const user = makeUser({ is_super_admin: true, permissions: { can_access_site: false, can_fetch: false } })
    expect(effectiveHasPerm(user, 'can_fetch')).toBe(true)
    expect(effectiveHasPerm(user, 'can_view_logs')).toBe(true)
  })
})

describe('effectiveHasPerm — null user', () => {
  it('returns false for null user regardless of permission', () => {
    expect(effectiveHasPerm(null, 'can_fetch')).toBe(false)
    expect(effectiveHasPerm(null, 'can_access_site')).toBe(false)
    expect(effectiveHasPerm(null, 'can_view_logs')).toBe(false)
  })
})

describe('effectiveHasPerm — sidebar visibility', () => {
  it('Dashboard link hidden when can_access_site=false', () => {
    const user = makeUser({ permissions: { can_access_site: false } })
    expect(effectiveHasPerm(user, 'can_access_site')).toBe(false)
  })

  it('Dashboard link shown when can_access_site=true', () => {
    const user = makeUser({ permissions: { can_access_site: true } })
    expect(effectiveHasPerm(user, 'can_access_site')).toBe(true)
  })

  it('Workspace/Products hidden when can_access_site=false even if can_fetch=true', () => {
    const user = makeUser({ permissions: { can_access_site: false, can_fetch: true } })
    expect(effectiveHasPerm(user, 'can_fetch')).toBe(false)
  })

  it('Settings hidden when can_access_site=false even if can_view_settings=true', () => {
    const user = makeUser({ permissions: { can_access_site: false, can_view_settings: true } })
    expect(effectiveHasPerm(user, 'can_view_settings')).toBe(false)
  })
})

describe('effectiveHasPerm — route guard scenarios', () => {
  it('Products route denied when can_access_site=false + can_fetch=true', () => {
    const user = makeUser({ permissions: { can_access_site: false, can_fetch: true } })
    expect(effectiveHasPerm(user, 'can_fetch')).toBe(false)
  })

  it('Workspace route denied when can_access_site=false + can_fetch=true', () => {
    const user = makeUser({ permissions: { can_access_site: false, can_fetch: true } })
    expect(effectiveHasPerm(user, 'can_fetch')).toBe(false)
  })

  it('Analytics route denied when can_access_site=false', () => {
    const user = makeUser({ permissions: { can_access_site: false } })
    expect(effectiveHasPerm(user, 'can_access_site')).toBe(false)
  })

  it('Audit/Logs route denied when can_access_site=false + can_view_logs=true', () => {
    const user = makeUser({ permissions: { can_access_site: false, can_view_logs: true } })
    expect(effectiveHasPerm(user, 'can_view_logs')).toBe(false)
  })

  it('Admin route bypasses gate for is_admin users', () => {
    // Admin route uses adminOnly prop — effectiveHasPerm not involved, but
    // verify admin bypass holds for all other perms too
    const user = makeUser({ is_admin: true, permissions: { can_access_site: false } })
    expect(effectiveHasPerm(user, 'can_view_logs')).toBe(true)
  })
})
