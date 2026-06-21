import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../auth'

// ── Types ──────────────────────────────────────────────────────────────────────

interface UserPermissions {
  can_access_site: boolean
  can_fetch: boolean
  can_apply: boolean
  can_edit_price: boolean
  can_edit_stock: boolean
  can_view_logs: boolean
  can_view_settings: boolean
}

interface AppUser {
  id: number
  username: string
  display_name: string | null
  email: string | null
  is_active: boolean
  is_admin: boolean
  permission_version: number
  notes: string | null
  created_at: string | null
  updated_at: string | null
  permissions: UserPermissions
}

interface MaintenanceState {
  enabled: boolean
  message: string
}

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

// ── Permission labels ──────────────────────────────────────────────────────────

const PERM_LABELS: Record<keyof UserPermissions, string> = {
  can_access_site:   'Access Site',
  can_fetch:         'Fetch/Sync',
  can_apply:         'Apply Changes',
  can_edit_price:    'Edit Prices',
  can_edit_stock:    'Edit Stock',
  can_view_logs:     'View Logs',
  can_view_settings: 'View Settings',
}

const PERM_KEYS = Object.keys(PERM_LABELS) as (keyof UserPermissions)[]

// ── Small components ───────────────────────────────────────────────────────────

function Toggle({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => !disabled && onChange(!checked)}
      className={[
        'relative inline-flex h-5 w-9 items-center rounded-full transition-colors flex-shrink-0',
        checked ? 'bg-accent' : 'bg-border',
        disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer',
      ].join(' ')}
    >
      <span
        className={[
          'inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform',
          checked ? 'translate-x-4' : 'translate-x-1',
        ].join(' ')}
      />
    </button>
  )
}

function StatusBadge({ status }: { status: SaveStatus }) {
  if (status === 'idle') return null
  const map = {
    saving: { text: 'Saving…', cls: 'text-wp-muted' },
    saved:  { text: 'Saved', cls: 'text-green-600' },
    error:  { text: 'Save failed', cls: 'text-wp-red' },
  } as const
  const { text, cls } = map[status]
  return <span className={`text-[11px] font-medium ${cls}`}>{text}</span>
}

// ── User row ───────────────────────────────────────────────────────────────────

function UserRow({
  user,
  superAdmins,
  onUpdate,
}: {
  user: AppUser
  superAdmins: string[]
  onUpdate: (username: string, patch: Partial<AppUser & UserPermissions>) => Promise<void>
}) {
  const isSuperAdmin = superAdmins.includes(user.username)
  const [expanded, setExpanded] = useState(false)
  const [draft, setDraft] = useState<UserPermissions>({ ...user.permissions })
  const [isAdmin, setIsAdmin] = useState(user.is_admin)
  const [isActive, setIsActive] = useState(user.is_active)
  const [status, setStatus] = useState<SaveStatus>('idle')
  const [errorMsg, setErrorMsg] = useState('')

  async function save() {
    setStatus('saving')
    setErrorMsg('')
    try {
      await onUpdate(user.username, {
        is_active: isActive,
        is_admin: isAdmin,
        ...draft,
      })
      setStatus('saved')
      setTimeout(() => setStatus('idle'), 2500)
    } catch (e: unknown) {
      setStatus('error')
      setErrorMsg(e instanceof Error ? e.message : 'Unknown error')
    }
  }

  const dirty = JSON.stringify(draft) !== JSON.stringify(user.permissions)
    || isAdmin !== user.is_admin
    || isActive !== user.is_active

  return (
    <div className="border border-border rounded-lg overflow-hidden mb-2">
      {/* Header row */}
      <button
        type="button"
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-bg-base/50 transition-colors"
      >
        <div className="w-8 h-8 rounded-full bg-accent/10 flex items-center justify-center text-accent text-[11px] font-bold flex-shrink-0">
          {user.username.slice(0, 2).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-semibold text-text-base">{user.username}</span>
            {isSuperAdmin && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-accent/10 text-accent">SUPER ADMIN</span>
            )}
            {user.is_admin && !isSuperAdmin && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-purple-100 text-purple-700">ADMIN</span>
            )}
            {!user.is_active && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-wp-red/10 text-wp-red">DISABLED</span>
            )}
          </div>
          {user.display_name && (
            <div className="text-[11px] text-wp-muted truncate">{user.display_name}</div>
          )}
        </div>
        <svg
          viewBox="0 0 24 24"
          className={`w-4 h-4 text-wp-muted transition-transform flex-shrink-0 ${expanded ? 'rotate-180' : ''}`}
          fill="none" stroke="currentColor" strokeWidth="2"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {/* Expanded permission editor */}
      {expanded && (
        <div className="border-t border-border px-4 py-3 bg-bg-base/30">
          {isSuperAdmin ? (
            <p className="text-[12px] text-wp-muted">
              Super admin — full access is always granted. Permissions cannot be changed here.
              Configure via the <code className="font-mono">SUPER_ADMIN_USERS</code> environment variable.
            </p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-x-6 gap-y-2 mb-4">
                {/* Active / Admin toggles */}
                <label className="flex items-center justify-between gap-2">
                  <span className="text-[12px] text-text-base font-medium">Account Active</span>
                  <Toggle checked={isActive} onChange={setIsActive} />
                </label>
                <label className="flex items-center justify-between gap-2">
                  <span className="text-[12px] text-text-base font-medium">DB Admin</span>
                  <Toggle checked={isAdmin} onChange={setIsAdmin} />
                </label>
                {/* Permission toggles */}
                {PERM_KEYS.map(key => (
                  <label key={key} className="flex items-center justify-between gap-2">
                    <span className="text-[12px] text-text-base">{PERM_LABELS[key]}</span>
                    <Toggle
                      checked={isAdmin ? true : draft[key]}
                      onChange={v => setDraft(d => ({ ...d, [key]: v }))}
                      disabled={isAdmin}
                    />
                  </label>
                ))}
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={save}
                  disabled={!dirty || status === 'saving'}
                  className="px-3 py-1.5 rounded-lg bg-accent text-white text-[12px] font-medium hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  Save
                </button>
                <StatusBadge status={status} />
                {errorMsg && <span className="text-[11px] text-wp-red">{errorMsg}</span>}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main Admin page ────────────────────────────────────────────────────────────

export default function Admin() {
  const { authFetch, user: currentUser } = useAuth()
  const isSuperAdmin = currentUser?.is_super_admin === true

  const [users, setUsers] = useState<AppUser[]>([])
  const [superAdmins, setSuperAdmins] = useState<string[]>([])
  const [loadingUsers, setLoadingUsers] = useState(true)
  const [usersError, setUsersError] = useState('')

  const [maintenance, setMaintenance] = useState<MaintenanceState>({ enabled: false, message: '' })
  const [maintMessage, setMaintMessage] = useState('')
  const [maintStatus, setMaintStatus] = useState<SaveStatus>('idle')
  const [maintError, setMaintError] = useState('')

  // ── Load users ──────────────────────────────────────────────────────────────

  const loadUsers = useCallback(async () => {
    setLoadingUsers(true)
    setUsersError('')
    try {
      const [usersRes, settingsRes] = await Promise.all([
        authFetch('/api/admin/app-users'),
        authFetch('/api/settings'),
      ])
      if (!usersRes.ok) throw new Error(`Users: HTTP ${usersRes.status}`)
      const data = (await usersRes.json()) as AppUser[]
      setUsers(data)
      if (settingsRes.ok) {
        const s = await settingsRes.json() as { super_admin_users?: string }
        const list = (s.super_admin_users || '')
          .split(',').map(u => u.trim()).filter(Boolean)
        setSuperAdmins(list)
      }
    } catch (e: unknown) {
      setUsersError(e instanceof Error ? e.message : 'Failed to load users')
    } finally {
      setLoadingUsers(false)
    }
  }, [authFetch])

  // ── Load maintenance state ──────────────────────────────────────────────────

  const loadMaintenance = useCallback(async () => {
    if (!isSuperAdmin) return
    try {
      const r = await authFetch('/api/admin/maintenance')
      if (r.ok) {
        const d = await r.json() as MaintenanceState
        setMaintenance(d)
        setMaintMessage(d.message)
      }
    } catch { /* best-effort */ }
  }, [authFetch, isSuperAdmin])

  useEffect(() => {
    void loadUsers()
    void loadMaintenance()
  }, [loadUsers, loadMaintenance])

  // ── Update a user's permissions ─────────────────────────────────────────────

  const updateUser = useCallback(async (username: string, patch: Record<string, unknown>) => {
    const r = await authFetch(`/api/admin/app-users/${username}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (!r.ok) {
      const body = await r.json().catch(() => ({})) as { detail?: string }
      throw new Error(body.detail ?? `HTTP ${r.status}`)
    }
    const updated = (await r.json()) as AppUser
    setUsers(prev => prev.map(u => u.username === username ? updated : u))
  }, [authFetch])

  // ── Toggle maintenance mode ─────────────────────────────────────────────────

  async function toggleMaintenance(enable: boolean) {
    setMaintStatus('saving')
    setMaintError('')
    try {
      const r = await authFetch('/api/admin/maintenance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: enable, message: maintMessage }),
      })
      if (!r.ok) {
        const body = await r.json().catch(() => ({})) as { detail?: string }
        throw new Error(body.detail ?? `HTTP ${r.status}`)
      }
      const d = await r.json() as MaintenanceState
      setMaintenance(d)
      setMaintMessage(d.message)
      setMaintStatus('saved')
      setTimeout(() => setMaintStatus('idle'), 2500)
    } catch (e: unknown) {
      setMaintStatus('error')
      setMaintError(e instanceof Error ? e.message : 'Unknown error')
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="p-7 max-w-3xl">
      <h1 className="text-[22px] font-bold text-text-base">Admin</h1>
      <p className="text-[13px] text-wp-muted mt-0.5 mb-6">User permissions and maintenance settings</p>

      {/* ── Maintenance Mode ── */}
      {isSuperAdmin && (
        <section className="mb-8">
          <h2 className="text-[15px] font-semibold text-text-base mb-3">Maintenance Mode</h2>
          <div className="bg-bg-card border border-border rounded-card p-4 shadow-card">
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="text-[13px] font-medium text-text-base">
                  {maintenance.enabled ? 'Maintenance is ON' : 'Maintenance is OFF'}
                </div>
                <div className="text-[11px] text-wp-muted mt-0.5">
                  {maintenance.enabled
                    ? 'Normal users see a maintenance screen. Super admins have full access.'
                    : 'All users have normal access.'}
                </div>
              </div>
              <div className={`px-3 py-1 rounded-full text-[11px] font-bold ${
                maintenance.enabled
                  ? 'bg-wp-red/10 text-wp-red'
                  : 'bg-green-100 text-green-700'
              }`}>
                {maintenance.enabled ? 'ACTIVE' : 'INACTIVE'}
              </div>
            </div>

            <div className="mb-3">
              <label className="block text-[12px] font-medium text-text-base mb-1">
                Message shown to users (optional)
              </label>
              <textarea
                value={maintMessage}
                onChange={e => setMaintMessage(e.target.value)}
                placeholder="WooPrice is temporarily in maintenance mode. Please try again later."
                rows={2}
                className="w-full text-[12px] px-3 py-2 border border-border rounded-lg bg-bg-base text-text-base resize-none focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </div>

            <div className="flex items-center gap-3">
              {maintenance.enabled ? (
                <button
                  onClick={() => void toggleMaintenance(false)}
                  disabled={maintStatus === 'saving'}
                  className="px-3 py-1.5 rounded-lg bg-green-600 text-white text-[12px] font-medium hover:bg-green-700 disabled:opacity-50 transition-colors"
                >
                  Disable Maintenance
                </button>
              ) : (
                <button
                  onClick={() => void toggleMaintenance(true)}
                  disabled={maintStatus === 'saving'}
                  className="px-3 py-1.5 rounded-lg bg-wp-red text-white text-[12px] font-medium hover:bg-wp-red/90 disabled:opacity-50 transition-colors"
                >
                  Enable Maintenance
                </button>
              )}
              <StatusBadge status={maintStatus} />
              {maintError && <span className="text-[11px] text-wp-red">{maintError}</span>}
            </div>
          </div>
        </section>
      )}

      {/* ── User Management ── */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-[15px] font-semibold text-text-base">Users</h2>
          <button
            onClick={() => void loadUsers()}
            className="text-[12px] text-accent hover:underline"
          >
            Refresh
          </button>
        </div>

        {loadingUsers && (
          <p className="text-[12px] text-wp-muted">Loading users…</p>
        )}
        {usersError && (
          <div className="text-[12px] text-wp-red bg-wp-red/5 border border-wp-red/20 rounded-lg px-3 py-2 mb-3">
            {usersError}
          </div>
        )}

        {!loadingUsers && users.length === 0 && !usersError && (
          <p className="text-[12px] text-wp-muted">No users found in database.</p>
        )}

        {users.map(u => (
          <UserRow
            key={u.username}
            user={u}
            superAdmins={superAdmins}
            onUpdate={updateUser}
          />
        ))}

        {superAdmins.length > 0 && (
          <div className="mt-4 p-3 bg-accent/5 border border-accent/20 rounded-lg">
            <p className="text-[11px] text-wp-muted">
              <span className="font-semibold text-accent">Super admins</span> ({superAdmins.join(', ')}) always have
              full access regardless of database rows. Configured via{' '}
              <code className="font-mono">SUPER_ADMIN_USERS</code>.
            </p>
          </div>
        )}
      </section>
    </div>
  )
}
