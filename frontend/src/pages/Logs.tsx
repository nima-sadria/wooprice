import { Fragment, useState, useMemo, useEffect, useCallback } from 'react'
import { useAuth } from '../auth'

interface AuditEntry {
  id: number
  username: string
  action: string
  timestamp: string
  ip_address: string | null
  job_id: number | null
  detail: Record<string, unknown> | null
}

interface Job {
  id: number
  created_at: string
  completed_at: string | null
  status: 'preview' | 'running' | 'completed' | 'failed' | 'cancelled'
  total_count: number
  updated_count: number
  failed_count: number
  skipped_count: number
  changed_count: number | null
  unchanged_count: number | null
  new_count: number | null
  invalid_count: number | null
  dry_run_status: string | null
}

type Tab = 'audit' | 'history'

function fmtDate(s: string | null | undefined): string {
  if (!s) return '—'
  try {
    return new Date(s).toLocaleString('en-GB', {
      day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return s
  }
}

const ACTION_COLORS: Record<string, { bg: string; text: string }> = {
  login:                         { bg: 'bg-[#dbeafe]', text: 'text-[#2563eb]' },
  fetch:                         { bg: 'bg-[#dcfce7]', text: 'text-[#16a34a]' },
  apply_started:                 { bg: 'bg-[#ede9fe]', text: 'text-[#7c3aed]' },
  apply_confirmed_after_dry_run: { bg: 'bg-[#ede9fe]', text: 'text-[#7c3aed]' },
  apply_blocked_by_dry_run:      { bg: 'bg-[#fee2e2]', text: 'text-[#dc2626]' },
  rollback_started:              { bg: 'bg-[#fef3c7]', text: 'text-[#b45309]' },
  rollback_completed:            { bg: 'bg-[#fef3c7]', text: 'text-[#b45309]' },
  rollback_failed:               { bg: 'bg-[#fee2e2]', text: 'text-[#dc2626]' },
  update_price:                  { bg: 'bg-[#e0e7ff]', text: 'text-[#4f46e5]' },
  update_stock:                  { bg: 'bg-[#e0e7ff]', text: 'text-[#4f46e5]' },
  permission_denied:             { bg: 'bg-[#fee2e2]', text: 'text-[#dc2626]' },
  writeback:                     { bg: 'bg-[#dcfce7]', text: 'text-[#16a34a]' },
}

function ActionBadge({ action }: { action: string }) {
  const c = ACTION_COLORS[action] ?? { bg: 'bg-bg-base', text: 'text-wp-muted' }
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-[11px] font-semibold ${c.bg} ${c.text}`}>
      {action.replace(/_/g, ' ')}
    </span>
  )
}

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  completed: { bg: 'bg-[#dcfce7]', text: 'text-[#16a34a]' },
  running:   { bg: 'bg-[#dbeafe]', text: 'text-[#2563eb]' },
  preview:   { bg: 'bg-[#fef9c3]', text: 'text-[#b45309]' },
  failed:    { bg: 'bg-[#fee2e2]', text: 'text-[#dc2626]' },
  cancelled: { bg: 'bg-bg-base',   text: 'text-wp-muted' },
}

function StatusBadge({ status }: { status: string }) {
  const c = STATUS_COLORS[status] ?? { bg: 'bg-bg-base', text: 'text-wp-muted' }
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-[11px] font-semibold ${c.bg} ${c.text}`}>
      {status}
    </span>
  )
}

type RollbackOutcome = { succeeded: number; failed: number } | { error: string }

const PAGE_SIZE = 25

export default function Logs() {
  const { authFetch, user } = useAuth()
  const isAdmin = user?.is_admin ?? false

  const [tab, setTab] = useState<Tab>('audit')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [auditLogs, setAuditLogs] = useState<AuditEntry[]>([])
  const [jobs, setJobs] = useState<Job[]>([])

  // Audit tab state
  const [search, setSearch] = useState('')
  const [actionFilter, setActionFilter] = useState('all')
  const [auditPage, setAuditPage] = useState(1)

  // History tab state
  const [expandedJob, setExpandedJob] = useState<number | null>(null)
  const [rollbackConfirm, setRollbackConfirm] = useState<number | null>(null)
  const [rollbackLoading, setRollbackLoading] = useState(false)
  const [rollbackResults, setRollbackResults] = useState<Record<number, RollbackOutcome>>({})
  const [writebackLoading, setWritebackLoading] = useState<number | null>(null)
  const [writebackResults, setWritebackResults] = useState<Record<number, 'ok' | 'error'>>({})

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const [logsRes, jobsRes] = await Promise.all([
        authFetch('/api/audit-logs?limit=200'),
        authFetch('/api/jobs?limit=50'),
      ])
      if (!logsRes.ok) throw new Error(`Audit logs: HTTP ${logsRes.status}`)
      if (!jobsRes.ok) throw new Error(`Jobs: HTTP ${jobsRes.status}`)
      const [logsData, jobsData] = await Promise.all([logsRes.json(), jobsRes.json()])
      setAuditLogs(logsData as AuditEntry[])
      setJobs(jobsData as Job[])
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'Failed to load logs')
    } finally {
      setLoading(false)
    }
  }, [authFetch])

  useEffect(() => { void load() }, [load])

  // Audit filtering
  const actionTypes = useMemo(() => {
    const seen = new Set(auditLogs.map(l => l.action))
    return ['all', ...Array.from(seen).sort()]
  }, [auditLogs])

  const filteredAudit = useMemo(() => {
    const q = search.trim().toLowerCase()
    return auditLogs.filter(l => {
      const matchSearch = !q || l.username.toLowerCase().includes(q) || l.action.toLowerCase().includes(q)
      const matchAction = actionFilter === 'all' || l.action === actionFilter
      return matchSearch && matchAction
    })
  }, [auditLogs, search, actionFilter])

  const totalAuditPages = Math.max(1, Math.ceil(filteredAudit.length / PAGE_SIZE))
  const pagedAudit = filteredAudit.slice((auditPage - 1) * PAGE_SIZE, auditPage * PAGE_SIZE)

  useEffect(() => { setAuditPage(1) }, [search, actionFilter])

  async function doRollback(jobId: number) {
    setRollbackLoading(true)
    try {
      const r = await authFetch(`/api/rollback/job/${jobId}`, { method: 'POST' })
      const data = await r.json() as { succeeded?: number; failed?: number; detail?: string }
      if (!r.ok) {
        setRollbackResults(prev => ({ ...prev, [jobId]: { error: data.detail ?? 'Rollback failed' } }))
      } else {
        setRollbackResults(prev => ({
          ...prev,
          [jobId]: { succeeded: data.succeeded ?? 0, failed: data.failed ?? 0 },
        }))
        void load()
      }
    } catch {
      setRollbackResults(prev => ({ ...prev, [jobId]: { error: 'Network error' } }))
    } finally {
      setRollbackLoading(false)
      setRollbackConfirm(null)
    }
  }

  async function doWriteback(jobId: number) {
    setWritebackLoading(jobId)
    try {
      const r = await authFetch(`/api/jobs/${jobId}/writeback`, { method: 'POST' })
      setWritebackResults(prev => ({ ...prev, [jobId]: r.ok ? 'ok' : 'error' }))
    } catch {
      setWritebackResults(prev => ({ ...prev, [jobId]: 'error' }))
    } finally {
      setWritebackLoading(null)
    }
  }

  function paginationPages(current: number, total: number): number[] {
    const pages: number[] = []
    const start = Math.max(1, Math.min(current - 2, total - 4))
    for (let i = start; i <= Math.min(total, start + 4); i++) pages.push(i)
    return pages
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Page header */}
      <div className="flex items-start justify-between mb-5">
        <div>
          <h1 className="text-[20px] font-bold text-text-base">Logs</h1>
          <p className="text-[13px] text-wp-muted mt-0.5">Audit trail and sync history</p>
        </div>
        <button
          onClick={() => void load()}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-1.5 text-[13px] border border-border rounded-lg text-wp-muted hover:text-text-base hover:border-accent transition-colors disabled:opacity-50"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
            className={`w-3.5 h-3.5 flex-shrink-0 ${loading ? 'animate-spin' : ''}`}>
            <polyline points="23 4 23 10 17 10" />
            <polyline points="1 20 1 14 7 14" />
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
          </svg>
          Refresh
        </button>
      </div>

      {loadError && (
        <div className="mb-4 px-4 py-3 bg-[#fee2e2] border border-[#fca5a5] rounded-lg text-[13px] text-[#dc2626]">
          {loadError}
        </div>
      )}

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-border mb-5">
        {(['audit', 'history'] as Tab[]).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={[
              'px-4 py-2 text-[13px] font-medium border-b-2 -mb-px transition-colors',
              tab === t
                ? 'border-accent text-accent'
                : 'border-transparent text-wp-muted hover:text-text-base',
            ].join(' ')}
          >
            {t === 'audit' ? 'Audit Log' : 'Sync History'}
          </button>
        ))}
      </div>

      {/* ── Audit Log tab ── */}
      {tab === 'audit' && (
        <div>
          <div className="flex flex-wrap items-center gap-3 mb-4">
            <div className="relative flex-1 min-w-[200px]">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                className="absolute start-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-wp-muted pointer-events-none">
                <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
              </svg>
              <input
                type="text"
                placeholder="Search user or action…"
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-full ps-9 pe-3 py-1.5 text-[13px] bg-bg-base border border-border rounded-lg text-text-base placeholder:text-wp-muted focus:outline-none focus:border-accent"
              />
            </div>
            <select
              value={actionFilter}
              onChange={e => setActionFilter(e.target.value)}
              className="px-3 py-1.5 text-[13px] bg-bg-base border border-border rounded-lg text-text-base focus:outline-none focus:border-accent"
            >
              {actionTypes.map(a => (
                <option key={a} value={a}>
                  {a === 'all' ? 'All actions' : a.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
            <span className="text-[12px] text-wp-muted whitespace-nowrap">
              {filteredAudit.length === auditLogs.length
                ? `${auditLogs.length} entries`
                : `${filteredAudit.length} of ${auditLogs.length}`}
            </span>
          </div>

          {loading ? (
            <div className="py-16 text-center text-[13px] text-wp-muted">Loading…</div>
          ) : pagedAudit.length === 0 ? (
            <div className="py-16 text-center text-[13px] text-wp-muted">No entries match your search.</div>
          ) : (
            <div className="rounded-lg border border-border overflow-hidden">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="bg-bg-base border-b border-border">
                    <th className="text-start px-4 py-2.5 font-semibold text-[11px] uppercase tracking-wider text-wp-muted">User</th>
                    <th className="text-start px-4 py-2.5 font-semibold text-[11px] uppercase tracking-wider text-wp-muted">Action</th>
                    <th className="text-start px-4 py-2.5 font-semibold text-[11px] uppercase tracking-wider text-wp-muted">Date / Time</th>
                    <th className="text-start px-4 py-2.5 font-semibold text-[11px] uppercase tracking-wider text-wp-muted hidden sm:table-cell">IP</th>
                    <th className="text-start px-4 py-2.5 font-semibold text-[11px] uppercase tracking-wider text-wp-muted hidden md:table-cell">Job</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {pagedAudit.map(l => (
                    <tr key={l.id} className="bg-bg-card hover:bg-bg-base transition-colors">
                      <td className="px-4 py-2.5 font-medium text-text-base">{l.username}</td>
                      <td className="px-4 py-2.5"><ActionBadge action={l.action} /></td>
                      <td className="px-4 py-2.5 text-wp-muted tabular-nums">{fmtDate(l.timestamp)}</td>
                      <td className="px-4 py-2.5 text-wp-muted text-[12px] hidden sm:table-cell">{l.ip_address ?? '—'}</td>
                      <td className="px-4 py-2.5 text-wp-muted text-[12px] hidden md:table-cell">
                        {l.job_id ? `#${l.job_id}` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {totalAuditPages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <span className="text-[12px] text-wp-muted">Page {auditPage} of {totalAuditPages}</span>
              <div className="flex items-center gap-1">
                <button
                  disabled={auditPage === 1}
                  onClick={() => setAuditPage(p => p - 1)}
                  className="px-2.5 py-1 text-[12px] border border-border rounded text-wp-muted hover:text-text-base disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  ‹ Prev
                </button>
                {paginationPages(auditPage, totalAuditPages).map(p => (
                  <button
                    key={p}
                    onClick={() => setAuditPage(p)}
                    className={[
                      'px-2.5 py-1 text-[12px] border rounded transition-colors',
                      p === auditPage
                        ? 'border-accent bg-accent text-white'
                        : 'border-border text-wp-muted hover:text-text-base',
                    ].join(' ')}
                  >
                    {p}
                  </button>
                ))}
                <button
                  disabled={auditPage === totalAuditPages}
                  onClick={() => setAuditPage(p => p + 1)}
                  className="px-2.5 py-1 text-[12px] border border-border rounded text-wp-muted hover:text-text-base disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Next ›
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Sync History tab ── */}
      {tab === 'history' && (
        <div>
          {loading ? (
            <div className="py-16 text-center text-[13px] text-wp-muted">Loading…</div>
          ) : jobs.length === 0 ? (
            <div className="py-16 text-center text-[13px] text-wp-muted">No sync jobs found.</div>
          ) : (
            <div className="rounded-lg border border-border overflow-hidden">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="bg-bg-base border-b border-border">
                    <th className="text-start px-4 py-2.5 font-semibold text-[11px] uppercase tracking-wider text-wp-muted w-16">#</th>
                    <th className="text-start px-4 py-2.5 font-semibold text-[11px] uppercase tracking-wider text-wp-muted">Started</th>
                    <th className="text-start px-4 py-2.5 font-semibold text-[11px] uppercase tracking-wider text-wp-muted">Status</th>
                    <th className="text-start px-4 py-2.5 font-semibold text-[11px] uppercase tracking-wider text-wp-muted">Results</th>
                    <th className="w-10"></th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map(j => {
                    const isExpanded = expandedJob === j.id
                    const rbResult = rollbackResults[j.id]
                    const wbResult = writebackResults[j.id]
                    return (
                      <Fragment key={j.id}>
                        <tr
                          className="bg-bg-card hover:bg-bg-base transition-colors border-b border-border cursor-pointer"
                          onClick={() => setExpandedJob(isExpanded ? null : j.id)}
                        >
                          <td className="px-4 py-2.5 text-wp-muted font-mono text-[12px]">#{j.id}</td>
                          <td className="px-4 py-2.5 text-wp-muted tabular-nums">{fmtDate(j.created_at)}</td>
                          <td className="px-4 py-2.5"><StatusBadge status={j.status} /></td>
                          <td className="px-4 py-2.5">
                            <span className="text-[#16a34a] font-medium">{j.updated_count} ↑</span>
                            {j.failed_count > 0 && (
                              <span className="text-[#dc2626] font-medium ms-2">{j.failed_count} ✕</span>
                            )}
                            {j.skipped_count > 0 && (
                              <span className="text-wp-muted ms-2">{j.skipped_count} –</span>
                            )}
                          </td>
                          <td className="px-4 py-2.5">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                              className={`w-3.5 h-3.5 text-wp-muted transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`}>
                              <path d="m6 9 6 6 6-6" />
                            </svg>
                          </td>
                        </tr>

                        {isExpanded && (
                          <tr className="border-b border-border">
                            <td colSpan={5} className="px-5 py-4 bg-bg-base">
                              {/* Counts */}
                              <div className="flex flex-wrap gap-x-5 gap-y-1 mb-4 text-[12px]">
                                <span className="text-wp-muted">Changed <b className="text-text-base">{j.changed_count ?? 0}</b></span>
                                <span className="text-wp-muted">Unchanged <b className="text-text-base">{j.unchanged_count ?? 0}</b></span>
                                <span className="text-wp-muted">New <b className="text-text-base">{j.new_count ?? 0}</b></span>
                                <span className="text-wp-muted">Invalid <b className="text-text-base">{j.invalid_count ?? 0}</b></span>
                                <span className="text-wp-muted">Skipped <b className="text-text-base">{j.skipped_count}</b></span>
                                {j.completed_at && (
                                  <span className="text-wp-muted">Completed <b className="text-text-base">{fmtDate(j.completed_at)}</b></span>
                                )}
                                {j.dry_run_status && (
                                  <span className="text-wp-muted">Dry run <b className="text-text-base">{j.dry_run_status}</b></span>
                                )}
                              </div>

                              {/* Feedback */}
                              {rbResult && (
                                <div className={`mb-3 px-3 py-2 rounded text-[12px] ${
                                  'error' in rbResult
                                    ? 'bg-[#fee2e2] text-[#dc2626]'
                                    : 'bg-[#dcfce7] text-[#16a34a]'
                                }`}>
                                  {'error' in rbResult
                                    ? `Rollback failed: ${rbResult.error}`
                                    : `Rollback complete — ${rbResult.succeeded} restored, ${rbResult.failed} failed`}
                                </div>
                              )}
                              {wbResult && (
                                <div className={`mb-3 px-3 py-2 rounded text-[12px] ${
                                  wbResult === 'ok' ? 'bg-[#dcfce7] text-[#16a34a]' : 'bg-[#fee2e2] text-[#dc2626]'
                                }`}>
                                  {wbResult === 'ok' ? 'Written back to spreadsheet.' : 'Writeback failed.'}
                                </div>
                              )}

                              {/* Actions */}
                              <div className="flex flex-wrap items-center gap-2">
                                {j.status === 'completed' && (
                                  <button
                                    onClick={e => { e.stopPropagation(); void doWriteback(j.id) }}
                                    disabled={writebackLoading === j.id}
                                    className="px-3 py-1.5 text-[12px] border border-border rounded-lg text-wp-muted hover:text-text-base hover:border-accent transition-colors disabled:opacity-50"
                                  >
                                    {writebackLoading === j.id ? 'Writing…' : 'Write Back to Sheet'}
                                  </button>
                                )}

                                {isAdmin && j.status === 'completed' && j.updated_count > 0 && (
                                  rollbackConfirm === j.id ? (
                                    <div className="flex flex-wrap items-center gap-2">
                                      <span className="text-[12px] text-[#b45309]">
                                        Roll back all {j.updated_count} changes?
                                      </span>
                                      <button
                                        onClick={e => { e.stopPropagation(); void doRollback(j.id) }}
                                        disabled={rollbackLoading}
                                        className="px-3 py-1.5 text-[12px] bg-[#dc2626] text-white rounded-lg hover:bg-[#b91c1c] transition-colors disabled:opacity-50"
                                      >
                                        {rollbackLoading ? 'Rolling back…' : 'Confirm Rollback'}
                                      </button>
                                      <button
                                        onClick={e => { e.stopPropagation(); setRollbackConfirm(null) }}
                                        className="px-3 py-1.5 text-[12px] border border-border rounded-lg text-wp-muted hover:text-text-base transition-colors"
                                      >
                                        Cancel
                                      </button>
                                    </div>
                                  ) : (
                                    <button
                                      onClick={e => { e.stopPropagation(); setRollbackConfirm(j.id) }}
                                      className="px-3 py-1.5 text-[12px] border border-[#fca5a5] text-[#b45309] rounded-lg hover:bg-[#fee2e2] transition-colors"
                                    >
                                      Rollback Job
                                    </button>
                                  )
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
