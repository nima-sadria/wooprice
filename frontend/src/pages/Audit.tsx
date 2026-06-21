import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../auth'
import { fmtPrice } from '../utils/price'

// ── Types ──────────────────────────────────────────────────────────────────────

interface AuditRow {
  id: number
  product_id: number
  name: string
  sku: string
  brand_name: string
  old_price: string | null
  new_price: string | null
  old_stock_status: string | null
  new_stock_status: string | null
  changed_at: string | null
  username: string | null
  source: string | null
  job_id: number | null
  batch_id: number | null
  rollback_of_id: number | null
}

interface AuditResponse {
  changes: AuditRow[]
  total: number
}

interface UndoState {
  pending: number | null    // change_id being confirmed
  loading: boolean
  error: string | null
  done: Set<number>
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const SOURCE_BADGE: Record<string, { label: string; cls: string }> = {
  apply:       { label: 'Sheet Apply',   cls: 'bg-blue-100 text-blue-800' },
  direct_edit: { label: 'Direct Edit',  cls: 'bg-purple-100 text-purple-800' },
  emergency:   { label: 'Emergency',    cls: 'bg-orange-100 text-orange-700' },
  rollback:    { label: 'Rollback',     cls: 'bg-amber-100 text-amber-800' },
  undo:        { label: 'Undo',         cls: 'bg-gray-100 text-gray-600' },
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return '—'
  try {
    return new Date(s).toLocaleString('en-GB', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return s }
}

function stockLabel(s: string | null): string {
  if (s === 'instock')     return 'In Stock'
  if (s === 'outofstock')  return 'Out of Stock'
  if (s === 'onbackorder') return 'Backorder'
  return s || '—'
}

// ── Audit Page ────────────────────────────────────────────────────────────────

export default function AuditPage() {
  const { authFetch, user } = useAuth()
  const isAdmin = user?.is_admin === true

  // Filters
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [sourceFilter, setSourceFilter] = useState('')
  const [brandFilter, setBrandFilter] = useState('')
  const [skuFilter, setSkuFilter] = useState('')
  const [nameFilter, setNameFilter] = useState('')

  // Results
  const [rows, setRows] = useState<AuditRow[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const PAGE_SIZE = 100

  // Undo
  const [undo, setUndo] = useState<UndoState>({ pending: null, loading: false, error: null, done: new Set() })

  const fetchRef = useRef(0)

  const doFetch = useCallback(async (pg: number) => {
    setLoading(true)
    setError(null)
    const seq = ++fetchRef.current
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset_id: String(pg * PAGE_SIZE) })
    if (fromDate)     params.set('from_date', fromDate)
    if (toDate)       params.set('to_date', toDate)
    if (sourceFilter) params.set('source', sourceFilter)
    if (brandFilter)  params.set('brand_name', brandFilter)
    if (skuFilter)    params.set('sku', skuFilter)
    if (nameFilter)   params.set('product_name', nameFilter)
    try {
      const r = await authFetch(`/api/audit/history?${params}`)
      if (seq !== fetchRef.current) return
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json() as AuditResponse
      setRows(data.changes)
      setTotal(data.total)
      setPage(pg)
    } catch (e) {
      if (seq !== fetchRef.current) return
      setError(e instanceof Error ? e.message : 'Failed to load audit history')
    } finally {
      if (seq === fetchRef.current) setLoading(false)
    }
  }, [authFetch, fromDate, toDate, sourceFilter, brandFilter, skuFilter, nameFilter])

  useEffect(() => { void doFetch(0) }, []) // initial load

  const handleSearch = () => void doFetch(0)

  const handleUndo = async (changeId: number) => {
    if (!isAdmin) return
    setUndo(s => ({ ...s, pending: changeId, error: null }))
  }

  const confirmUndo = async () => {
    const changeId = undo.pending
    if (changeId === null) return
    setUndo(s => ({ ...s, loading: true, error: null }))
    try {
      const r = await authFetch('/api/audit/undo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ change_id: changeId, confirm: true }),
      })
      const data = await r.json() as { undone: number; failed: number; results: { id: number; success: boolean; error_message?: string }[] }
      if (!r.ok) {
        const msg = (data as unknown as { detail: string }).detail ?? `HTTP ${r.status}`
        throw new Error(msg)
      }
      if (data.failed > 0) {
        const res = data.results[0]
        throw new Error(res?.error_message ?? 'Undo failed')
      }
      setUndo(s => ({ ...s, pending: null, loading: false, done: new Set([...s.done, changeId]) }))
      void doFetch(page)
    } catch (e) {
      setUndo(s => ({ ...s, loading: false, error: e instanceof Error ? e.message : 'Undo failed', pending: null }))
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div>
        <h1 className="text-[20px] font-bold text-text-base">Audit History</h1>
        <p className="text-[13px] text-wp-muted mt-0.5">All product changes — Apply, Direct Edit, Emergency, Rollback, Undo</p>
      </div>

      {/* Filters */}
      <div className="bg-bg-card border border-border rounded-lg p-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
          <div>
            <label className="block text-[11px] font-medium text-wp-muted mb-1">From date</label>
            <input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)}
              className="w-full px-3 py-2 text-[13px] border border-border rounded-lg bg-bg-base text-text-base focus:outline-none focus:border-accent" />
          </div>
          <div>
            <label className="block text-[11px] font-medium text-wp-muted mb-1">To date</label>
            <input type="date" value={toDate} onChange={e => setToDate(e.target.value)}
              className="w-full px-3 py-2 text-[13px] border border-border rounded-lg bg-bg-base text-text-base focus:outline-none focus:border-accent" />
          </div>
          <div>
            <label className="block text-[11px] font-medium text-wp-muted mb-1">Source</label>
            <select value={sourceFilter} onChange={e => setSourceFilter(e.target.value)}
              className="w-full px-3 py-2 text-[13px] border border-border rounded-lg bg-bg-base text-text-base focus:outline-none focus:border-accent">
              <option value="">All sources</option>
              <option value="apply">Sheet Apply</option>
              <option value="direct_edit">Direct Edit</option>
              <option value="emergency">Emergency</option>
              <option value="rollback">Rollback</option>
              <option value="undo">Undo</option>
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-medium text-wp-muted mb-1">Brand</label>
            <input type="text" value={brandFilter} onChange={e => setBrandFilter(e.target.value)}
              placeholder="Brand name…"
              className="w-full px-3 py-2 text-[13px] border border-border rounded-lg bg-bg-base text-text-base focus:outline-none focus:border-accent placeholder:text-wp-muted" />
          </div>
          <div>
            <label className="block text-[11px] font-medium text-wp-muted mb-1">SKU</label>
            <input type="text" value={skuFilter} onChange={e => setSkuFilter(e.target.value)}
              placeholder="SKU…"
              className="w-full px-3 py-2 text-[13px] border border-border rounded-lg bg-bg-base text-text-base focus:outline-none focus:border-accent placeholder:text-wp-muted" />
          </div>
          <div>
            <label className="block text-[11px] font-medium text-wp-muted mb-1">Product name</label>
            <input type="text" value={nameFilter} onChange={e => setNameFilter(e.target.value)}
              placeholder="Product name…"
              className="w-full px-3 py-2 text-[13px] border border-border rounded-lg bg-bg-base text-text-base focus:outline-none focus:border-accent placeholder:text-wp-muted" />
          </div>
        </div>
        <div className="flex items-center gap-2 mt-3">
          <button onClick={handleSearch} disabled={loading}
            className="px-4 py-1.5 text-[13px] bg-accent text-white rounded-lg hover:bg-accent/90 disabled:opacity-50 transition-colors">
            {loading ? 'Loading…' : 'Search'}
          </button>
          <button onClick={() => { setFromDate(''); setToDate(''); setSourceFilter(''); setBrandFilter(''); setSkuFilter(''); setNameFilter('') }}
            className="px-3 py-1.5 text-[12px] border border-border rounded-lg text-wp-muted hover:text-text-base transition-colors">
            Clear
          </button>
          {total > 0 && <span className="text-[12px] text-wp-muted">{total} records</span>}
        </div>
      </div>

      {/* Undo error */}
      {undo.error && (
        <div className="bg-[#fef2f2] border border-[#fca5a5] rounded-lg px-4 py-3 text-[13px] text-[#dc2626]">
          Undo failed: {undo.error}
        </div>
      )}

      {/* Undo confirmation modal */}
      {undo.pending !== null && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div className="bg-bg-card border border-border rounded-xl p-6 max-w-sm w-full shadow-xl">
            <h2 className="font-bold text-[15px] text-text-base mb-2">Confirm Undo</h2>
            <p className="text-[13px] text-wp-muted mb-4">
              This will restore the previous price/stock for this product in WooCommerce and create an audit record. Are you sure?
            </p>
            <div className="flex gap-2 justify-end">
              <button onClick={() => setUndo(s => ({ ...s, pending: null }))} disabled={undo.loading}
                className="px-3 py-1.5 text-[13px] border border-border rounded-lg text-wp-muted hover:text-text-base disabled:opacity-50">
                Cancel
              </button>
              <button onClick={() => void confirmUndo()} disabled={undo.loading}
                className="px-4 py-1.5 text-[13px] bg-[#dc2626] text-white rounded-lg hover:bg-[#b91c1c] disabled:opacity-50">
                {undo.loading ? 'Undoing…' : 'Confirm Undo'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-[#fef2f2] border border-[#fca5a5] rounded-lg px-4 py-3 text-[13px] text-[#dc2626]">{error}</div>
      )}

      {/* Table */}
      {!error && (
        <div className="bg-bg-card border border-border rounded-lg overflow-hidden">
          {/* Pagination bar */}
          {totalPages > 1 && (
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border">
              <button onClick={() => void doFetch(page - 1)} disabled={page === 0 || loading}
                className="px-2.5 py-1 text-[12px] border border-border rounded text-wp-muted hover:text-text-base disabled:opacity-40">‹ Prev</button>
              <span className="text-[12px] text-wp-muted">{page + 1} / {totalPages}</span>
              <button onClick={() => void doFetch(page + 1)} disabled={page >= totalPages - 1 || loading}
                className="px-2.5 py-1 text-[12px] border border-border rounded text-wp-muted hover:text-text-base disabled:opacity-40">Next ›</button>
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="w-full text-[13px] border-collapse">
              <thead>
                <tr className="bg-bg-base">
                  <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">When</th>
                  <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">Product</th>
                  <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">Source</th>
                  <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">Price change</th>
                  <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">Stock change</th>
                  <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">User</th>
                  {isAdmin && <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide w-20">Action</th>}
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && !loading && (
                  <tr>
                    <td colSpan={isAdmin ? 7 : 6} className="px-4 py-8 text-center text-[13px] text-wp-muted">
                      No records found
                    </td>
                  </tr>
                )}
                {loading && rows.length === 0 && (
                  <tr>
                    <td colSpan={isAdmin ? 7 : 6} className="px-4 py-8 text-center text-[13px] text-wp-muted">Loading…</td>
                  </tr>
                )}
                {rows.map(row => {
                  const badge = SOURCE_BADGE[row.source ?? ''] ?? { label: row.source ?? '?', cls: 'bg-gray-100 text-gray-600' }
                  const priceChanged = row.old_price !== row.new_price && (row.old_price || row.new_price)
                  const stockChanged = row.old_stock_status !== row.new_stock_status && (row.old_stock_status || row.new_stock_status)
                  const isDone = undo.done.has(row.id)

                  return (
                    <tr key={row.id} className={`border-b border-border hover:bg-bg-base transition-colors ${isDone ? 'opacity-40' : ''}`}>
                      <td className="px-3 py-2.5 text-[12px] text-wp-muted whitespace-nowrap">{fmtDate(row.changed_at)}</td>
                      <td className="px-3 py-2.5 max-w-[200px]">
                        <div className="font-medium text-text-base truncate" title={row.name}>{row.name || `#${row.product_id}`}</div>
                        {row.sku && <div className="text-[11px] font-mono text-wp-muted">{row.sku}</div>}
                        {row.brand_name && <div className="text-[11px] text-wp-muted">{row.brand_name}</div>}
                      </td>
                      <td className="px-3 py-2.5">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${badge.cls}`}>
                          {badge.label}
                        </span>
                        {row.batch_id && <div className="text-[11px] text-wp-muted mt-0.5">batch #{row.batch_id}</div>}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-[12px]">
                        {priceChanged ? (
                          <span className="text-[#b45309]">
                            {fmtPrice(row.old_price)} → {fmtPrice(row.new_price)}
                          </span>
                        ) : <span className="text-wp-muted">—</span>}
                      </td>
                      <td className="px-3 py-2.5 text-[12px]">
                        {stockChanged ? (
                          <span className="text-[#b45309]">
                            {stockLabel(row.old_stock_status)} → {stockLabel(row.new_stock_status)}
                          </span>
                        ) : <span className="text-wp-muted">—</span>}
                      </td>
                      <td className="px-3 py-2.5 text-[12px] text-wp-muted">{row.username || '—'}</td>
                      {isAdmin && (
                        <td className="px-3 py-2.5">
                          {isDone ? (
                            <span className="text-[11px] text-[#16a34a]">Undone</span>
                          ) : row.source === 'undo' || row.source === 'rollback' ? (
                            <span className="text-[11px] text-wp-muted">—</span>
                          ) : (
                            <button onClick={() => handleUndo(row.id)}
                              className="px-2 py-1 text-[11px] border border-[#f87171] text-[#dc2626] rounded hover:bg-red-50 transition-colors">
                              Undo
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
