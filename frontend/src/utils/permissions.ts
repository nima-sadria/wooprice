export interface PermissionsUser {
  is_admin: boolean
  is_super_admin: boolean
  permissions?: Record<string, boolean>
}

// Mirrors backend _enforce_permission gate order:
// admin/super bypass all checks; for regular users can_access_site is the global gate
// before any specific permission.
export function effectiveHasPerm(user: PermissionsUser | null, perm: string): boolean {
  if (!user) return false
  if (user.is_admin || user.is_super_admin) return true
  if (!user.permissions?.['can_access_site']) return false
  return user.permissions?.[perm] === true
}
