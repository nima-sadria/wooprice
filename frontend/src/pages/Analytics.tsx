import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { fmtPrice } from '../utils/price'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  Tooltip,
  Legend,
} from 'chart.js'
import { Bar, Line } from 'react-chartjs-2'
import { AccessState, useAuth } from '../auth'

ChartJS.register(CategoryScale, LinearScale, BarElement, LineElement, PointElement, Tooltip, Legend)

interface ProductRow {
  wc_id?: number
  product_id?: number
  name?: string
  product_name?: string
  sku?: string
  stock_status?: string
  final_price?: string
  new_price?: string
  last_applied?: string | null
  updated_today?: boolean
}

interface CoverageRow {
  category_id?: number
  brand_id?: number | null
  category_name?: string
  brand_name?: string
  total: number
  updated_today: number
  update_pct: number
  products_updated: ProductRow[]
  products_not_updated: ProductRow[]
}

interface SellerIssues {
  in_stock_no_price: ProductRow[]
  has_price_out_of_stock: ProductRow[]
  stale_products: ProductRow[]
}

interface SellerCategories {
  categories: CoverageRow[]
}

interface SellerBrands {
  total_products: number
  brand_count: number
  coverage_percent: number
  brands: CoverageRow[]
  unknown_brand: CoverageRow
}

interface SellerStaleness {
  stale_3_5: ProductRow[]
  stale_5_plus: ProductRow[]
  never_updated: ProductRow[]
  counts: {
    stale_3_5: number
    stale_5_plus: number
    never_updated: number
  }
}

interface AdminOverview {
  total_products: number
  updated_products_today: number
  apply_count_today: number
  rollback_count_today: number
  price_changes_today: number
  out_of_stock: number
  missing_image: number
  missing_price: number
}

interface TrendPoint {
  date: string
  updated_products: number
  apply_jobs: number
  rollback_jobs: number
  changed_products: number
}

interface AdminTrend {
  days: number
  data: TrendPoint[]
}

interface Movement {
  product_id: number
  old_price: string
  new_price: string
  delta_pct: number
  name: string
  sku: string
}

interface AdminMovements {
  increases: Movement[]
  decreases: Movement[]
}

interface AnalyticsData {
  issues: SellerIssues
  categories: SellerCategories
  brands: SellerBrands
  staleness: SellerStaleness
  adminOverview: AdminOverview | null
  trend7: AdminTrend | null
  trend30: AdminTrend | null
  movements: AdminMovements | null
}

type ModalState =
  | { title: string; rows: ProductRow[] }
  | { title: string; rows: Movement[]; movement: true }
  | null

type Severity = 'ok' | 'warning' | 'critical'
type TabId = 'overview' | 'changes'

interface ChangeRecord {
  id: number
  product_id: number
  name: string
  sku: string
  brand_name: string
  old_price: string | null
  new_price: string | null
  old_stock_status: string | null
  new_stock_status: string | null
  old_stock_quantity: number | null
  new_stock_quantity: number | null
  changed_at: string | null
  username: string | null
  job_id: number | null
}

class ApiStatusError extends Error {
  status: number
  constructor(status: number) {
    super(`HTTP ${status}`)
    this.status = status
  }
}

async function readJson<T>(r: Response): Promise<T> {
  if (r.status === 401 || r.status === 403) throw new ApiStatusError(r.status)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return (await r.json()) as T
}

function pct(n: number) {
  return `${Math.round(n * 10) / 10}%`
}

function fmt(n: number | undefined) {
  return (n ?? 0).toLocaleString('en')
}

function getSeverity(count: number, total: number): Severity {
  if (total === 0 || count === 0) return 'ok'
  const ratio = count / total
  if (ratio >= 0.05) return 'critical'
  if (ratio >= 0.01) return 'warning'
  return 'ok'
}

function coverageFill(updatePct: number): string {
  if (updatePct < 20) return 'bg-[#ef4444]'
  if (updatePct < 60) return 'bg-[#f59e0b]'
  return 'bg-accent'
}

function timeAgo(date: Date): string {
  const mins = Math.floor((Date.now() - date.getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins === 1) return '1 min ago'
  return `${mins} min ago`
}

function productId(row: ProductRow) {
  return row.wc_id ?? row.product_id ?? 0
}

function productName(row: ProductRow) {
  return row.name || row.product_name || 'Unnamed product'
}

function price(row: ProductRow) {
  return fmtPrice(row.final_price || row.new_price)
}

function topRows(rows: CoverageRow[], limit = 6) {
  return rows.slice(0, limit)
}

const SEVERITY_STYLES: Record<Severity, { card: string; badge: string; label: string }> = {
  critical: {
    card: 'border-[#ef4444] bg-[#fef2f2] hover:border-[#dc2626]',
    badge: 'bg-[#fee2e2] text-[#dc2626]',
    label: 'Critical',
  },
  warning: {
    card: 'border-[#f59e0b] bg-[#fffbeb] hover:border-[#d97706]',
    badge: 'bg-[#fef9c3] text-[#b45309]',
    label: 'Warning',
  },
  ok: {
    card: 'border-border bg-bg-card hover:border-accent',
    badge: 'bg-[#dcfce7] text-[#16a34a]',
    label: 'OK',
  },
}

const chartText = '#8E97A7'
const chartGrid = '#E8EAED'

export default function Analytics() {
  const { user, authFetch } = useAuth()
  const [tab, setTab] = useState<TabId>('overview')
  const [data, setData] = useState<AnalyticsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [accessState, setAccessState] = useState<'login_required' | 'permission_denied' | null>(null)
  const [modal, setModal] = useState<ModalState>(null)
  const [trendWindow, setTrendWindow] = useState<7 | 30>(30)
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    setAccessState(null)
    try {
      const [issues, categories, brands, staleness] = await Promise.all([
        authFetch('/api/analytics').then(readJson<SellerIssues>),
        authFetch('/api/analytics/seller/categories').then(readJson<SellerCategories>),
        authFetch('/api/analytics/seller/brands').then(readJson<SellerBrands>),
        authFetch('/api/analytics/seller/staleness').then(readJson<SellerStaleness>),
      ])

      let adminOverview: AdminOverview | null = null
      let trend7: AdminTrend | null = null
      let trend30: AdminTrend | null = null
      let movements: AdminMovements | null = null

      if (user?.is_admin) {
        ;[adminOverview, trend7, trend30, movements] = await Promise.all([
          authFetch('/api/analytics/admin/overview').then(readJson<AdminOverview>),
          authFetch('/api/analytics/admin/trend?days=7').then(readJson<AdminTrend>),
          authFetch('/api/analytics/admin/trend?days=30').then(readJson<AdminTrend>),
          authFetch('/api/analytics/admin/top-movements').then(readJson<AdminMovements>),
        ])
      }

      setData({ issues, categories, brands, staleness, adminOverview, trend7, trend30, movements })
      setRefreshedAt(new Date())
    } catch (e) {
      setData(null)
      if (e instanceof ApiStatusError) {
        setAccessState(e.status === 401 ? 'login_required' : 'permission_denied')
      } else {
        setError(e instanceof Error ? e.message : 'Failed to load analytics')
      }
    } finally {
      setLoading(false)
    }
  }, [authFetch, user?.is_admin])

  useEffect(() => { void load() }, [load])

  const totals = useMemo(() => {
    if (!data) return null
    const unknown = data.brands.unknown_brand
    const updatedToday = data.brands.brands.reduce((sum, row) => sum + row.updated_today, 0) + (unknown?.updated_today ?? 0)
    const staleCount = data.staleness.counts.stale_3_5 + data.staleness.counts.stale_5_plus + data.staleness.counts.never_updated
    const total = data.adminOverview?.total_products ?? data.brands.total_products
    const freshPct = total ? Math.round(((total - staleCount) / total) * 1000) / 10 : 0
    return { updatedToday, staleCount, total, freshPct }
  }, [data])

  // Deduplicated list of products updated today (across all categories)
  const allUpdatedToday = useMemo(() => {
    if (!data) return []
    const seen = new Set<number>()
    return data.categories.categories.flatMap(c => c.products_updated).filter(p => {
      const id = productId(p)
      if (seen.has(id)) return false
      seen.add(id)
      return true
    })
  }, [data])

  if (accessState) return <AccessState status={accessState} />

  const trendData = trendWindow === 7 ? (data?.trend7 ?? data?.trend30) : (data?.trend30 ?? data?.trend7)
  const trendChart = trendData
    ? {
        labels: trendData.data.map(d => d.date.slice(5)),
        datasets: [
          {
            label: 'Updated',
            data: trendData.data.map(d => d.updated_products),
            borderColor: '#4880FF',
            backgroundColor: 'rgba(72, 128, 255, .14)',
            tension: 0.3,
          },
          {
            label: 'Changed',
            data: trendData.data.map(d => d.changed_products),
            borderColor: '#22c55e',
            backgroundColor: 'rgba(34, 197, 94, .14)',
            tension: 0.3,
          },
        ],
      }
    : null

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { labels: { color: chartText, font: { size: 11 } } } },
    scales: {
      x: { grid: { color: chartGrid }, ticks: { color: chartText } },
      y: { grid: { color: chartGrid }, ticks: { color: chartText, precision: 0 }, beginAtZero: true },
    },
  } as const

  return (
    <div className="p-4 sm:p-7 flex flex-col gap-5">
      {/* Page header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-[22px] font-bold text-text-base">Analytics</h1>
          <p className="text-[13px] text-wp-muted mt-0.5">Catalog coverage, freshness, and pricing movement</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {/* Tab switcher */}
          <div className="flex bg-bg-base border border-border rounded-lg p-0.5">
            {(['overview', 'changes'] as TabId[]).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={[
                  'px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors',
                  tab === t ? 'bg-bg-card text-accent shadow-card' : 'text-wp-muted hover:text-text-base',
                ].join(' ')}
              >
                {t === 'overview' ? 'Overview' : 'Apply History'}
              </button>
            ))}
          </div>
          {tab === 'overview' && (
            <>
              {refreshedAt && !loading && (
                <span className="text-[12px] text-wp-muted">
                  Updated {timeAgo(refreshedAt)}
                </span>
              )}
              <button
                onClick={() => { void load() }}
                disabled={loading}
                className="flex items-center gap-2 px-[18px] py-[9px] rounded-lg border-[1.5px] border-border bg-bg-card text-text-base text-[13px] font-medium hover:border-accent hover:text-accent transition-colors disabled:opacity-40"
              >
                {loading && (
                  <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <path d="M21 12a9 9 0 1 1-6.219-8.56" strokeLinecap="round" />
                  </svg>
                )}
                {loading ? 'Loading…' : 'Refresh'}
              </button>
            </>
          )}
        </div>
      </div>

      {tab === 'changes' && <ChangeHistoryTab authFetch={authFetch} isAdmin={user?.is_admin ?? false} />}

      {tab === 'overview' && error && (
        <div className="bg-[#fee2e2] border border-[#ef4444]/30 rounded-card px-4 py-3 text-[13px] text-[#dc2626]">
          {error}
        </div>
      )}

      {tab === 'overview' && (
        loading && !data ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-[116px] rounded-card border border-border bg-bg-card shadow-card animate-pulse" />
          ))}
        </div>
      ) : data && totals ? (
        <>
          {/* KPI cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
            <Kpi
              title="Total Products"
              value={fmt(totals.total)}
              tone="blue"
              icon={
                <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
                  <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
                  <line x1="12" y1="22.08" x2="12" y2="12" />
                </svg>
              }
            />
            <Kpi
              title="Updated Today"
              value={fmt(data.adminOverview?.updated_products_today ?? totals.updatedToday)}
              tone="green"
              icon={
                <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
                  <polyline points="17 6 23 6 23 12" />
                </svg>
              }
              onClick={allUpdatedToday.length > 0
                ? () => setModal({ title: 'Updated Today', rows: allUpdatedToday })
                : undefined}
            />
            <Kpi
              title="Stale Products"
              value={fmt(totals.staleCount)}
              tone="orange"
              icon={
                <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
              }
              onClick={totals.staleCount > 0
                ? () => setModal({ title: 'All Stale Products', rows: [...data.staleness.stale_3_5, ...data.staleness.stale_5_plus, ...data.staleness.never_updated] })
                : undefined}
            />
            <Kpi
              title="Brand Coverage"
              value={pct(data.brands.coverage_percent)}
              tone="purple"
              icon={
                <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                </svg>
              }
            />
          </div>

          {/* Apply Recency gauge + trend chart */}
          <div className="grid grid-cols-1 xl:grid-cols-[320px_1fr] gap-4">
            <section className="bg-bg-card border border-border rounded-card shadow-card p-5">
              <SectionTitle title="Apply Recency" action={`${pct(totals.freshPct)} applied 0-3 days`} />
              <div className="flex items-center justify-center py-4">
                <div
                  className="w-[190px] h-[190px] rounded-full flex items-center justify-center"
                  style={{ background: `conic-gradient(#22c55e ${Math.max(0, totals.freshPct) * 3.6}deg, #E8EAED 0deg)` }}
                >
                  <div className="w-[132px] h-[132px] rounded-full bg-bg-card flex flex-col items-center justify-center border border-border">
                    <div className="text-[34px] font-bold text-text-base">{pct(totals.freshPct)}</div>
                    <div className="text-[12px] text-wp-muted">applied 0-3d</div>
                  </div>
                </div>
              </div>
              <div className="text-[11px] text-wp-muted text-center mb-2">Top-level products Applied within 3 days</div>
              <div className="grid grid-cols-3 gap-2 text-center">
                <MiniStat label="3-5 days" value={data.staleness.counts.stale_3_5} onClick={() => setModal({ title: 'Applied 3-5 Days Ago', rows: data.staleness.stale_3_5 })} />
                <MiniStat label="5+ days" value={data.staleness.counts.stale_5_plus} onClick={() => setModal({ title: 'Applied 5+ Days Ago', rows: data.staleness.stale_5_plus })} />
                <MiniStat label="Never" value={data.staleness.counts.never_updated} onClick={() => setModal({ title: 'Never Applied', rows: data.staleness.never_updated })} />
              </div>
            </section>

            <section className="bg-bg-card border border-border rounded-card shadow-card p-5 min-h-[310px]">
              <div className="flex items-center justify-between gap-3 mb-4">
                <SectionTitle title={trendChart ? `${trendData?.days ?? trendWindow}-Day Trend` : 'Seller Analytics'} action={user?.is_admin ? 'Admin verified' : 'Seller view'} />
                {user?.is_admin && (
                  <div className="flex bg-bg-base border border-border rounded-lg p-0.5">
                    {[7, 30].map(days => (
                      <button
                        key={days}
                        onClick={() => setTrendWindow(days as 7 | 30)}
                        className={[
                          'px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors',
                          trendWindow === days ? 'bg-bg-card text-accent shadow-card' : 'text-wp-muted hover:text-text-base',
                        ].join(' ')}
                      >
                        {days}d
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div className="h-[245px]">
                {trendChart ? (
                  <Line data={trendChart} options={chartOptions} />
                ) : (
                  <Bar
                    data={{
                      labels: topRows(data.categories.categories).map(c => c.category_name || 'Category'),
                      datasets: [{ label: 'Updated today', data: topRows(data.categories.categories).map(c => c.updated_today), backgroundColor: 'rgba(72, 128, 255, .65)' }],
                    }}
                    options={chartOptions}
                  />
                )}
              </div>
            </section>
          </div>

          {/* Coverage panels */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <CoveragePanel
              title="Applied Today by Category"
              rows={topRows(data.categories.categories)}
              nameKey="category_name"
              onOpen={row => setModal({ title: row.category_name || 'Category Products', rows: row.products_not_updated })}
            />
            <CoveragePanel
              title="Applied Today by Brand"
              rows={topRows(data.brands.brands.concat(data.brands.unknown_brand ? [data.brands.unknown_brand] : []))}
              nameKey="brand_name"
              onOpen={row => setModal({ title: row.brand_name || 'Brand Products', rows: row.products_not_updated })}
            />
          </div>

          {/* Business issue cards */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <StaleCard title="In Stock, No Price" count={data.issues.in_stock_no_price.length} rows={data.issues.in_stock_no_price} total={totals.total} onOpen={setModal} />
            <StaleCard title="Priced, Out of Stock" count={data.issues.has_price_out_of_stock.length} rows={data.issues.has_price_out_of_stock} total={totals.total} onOpen={setModal} />
          </div>

          {/* Diagnostics */}
          <div>
            <div className="text-[11px] font-semibold text-wp-muted uppercase tracking-wide mb-2">Diagnostics</div>
            <div className="grid grid-cols-1 lg:grid-cols-1 gap-4">
              <StaleCard title="Not Updated via WC (7d+)" count={data.issues.stale_products.length} rows={data.issues.stale_products} total={totals.total} onOpen={setModal} />
            </div>
          </div>

          {/* Price movement panels (admin) */}
          {user?.is_admin && data.movements && (
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              <MovementPanel title="Biggest Increases" rows={data.movements.increases} onOpen={() => setModal({ title: 'Biggest Increases', rows: data.movements?.increases ?? [], movement: true })} />
              <MovementPanel title="Biggest Decreases" rows={data.movements.decreases} onOpen={() => setModal({ title: 'Biggest Decreases', rows: data.movements?.decreases ?? [], movement: true })} />
            </div>
          )}
        </>
      ) : (
        <div className="bg-bg-card border border-border rounded-card shadow-card p-6 text-[13px] text-wp-muted">
          No analytics data available.
        </div>
      )
      )}

      {modal && <DrilldownModal modal={modal} onClose={() => setModal(null)} />}
    </div>
  )
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function Kpi({
  title,
  value,
  tone,
  icon,
  onClick,
}: {
  title: string
  value: string
  tone: 'blue' | 'green' | 'orange' | 'purple'
  icon: ReactNode
  onClick?: () => void
}) {
  const tones = {
    blue:   'bg-[#dbeafe] text-[#2563eb]',
    green:  'bg-[#dcfce7] text-[#16a34a]',
    orange: 'bg-[#ffedd5] text-[#ea580c]',
    purple: 'bg-[#ede9fe] text-[#7c3aed]',
  }
  const base = 'bg-bg-card border border-border rounded-card shadow-card p-5 flex items-center justify-between gap-4 w-full text-left'
  const inner = (
    <>
      <div className="min-w-0">
        <div className="text-[12px] text-wp-muted">{title}</div>
        <div className="text-[28px] leading-tight font-bold text-text-base mt-1 truncate">{value}</div>
        {onClick && <div className="text-[11px] text-wp-muted mt-1">Tap to review ↗</div>}
      </div>
      <div className={['w-11 h-11 rounded-lg flex items-center justify-center flex-shrink-0', tones[tone]].join(' ')}>
        {icon}
      </div>
    </>
  )

  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={`${base} hover:border-accent hover:shadow-md transition-all cursor-pointer`}>
        {inner}
      </button>
    )
  }
  return <div className={base}>{inner}</div>
}

function SectionTitle({ title, action }: { title: string; action?: string }) {
  return (
    <div className="flex items-center justify-between gap-3 mb-4">
      <h2 className="text-[15px] font-bold text-text-base">{title}</h2>
      {action && <span className="text-[11px] text-wp-muted bg-bg-base border border-border rounded px-2 py-1">{action}</span>}
    </div>
  )
}

function MiniStat({ label, value, onClick }: { label: string; value: number; onClick: () => void }) {
  return (
    <button onClick={onClick} className="bg-bg-base border border-border rounded-lg p-3 hover:border-accent transition-colors">
      <div className="text-[18px] font-bold text-text-base">{fmt(value)}</div>
      <div className="text-[11px] text-wp-muted">{label}</div>
    </button>
  )
}

function CoveragePanel({
  title,
  rows,
  nameKey,
  onOpen,
}: {
  title: string
  rows: CoverageRow[]
  nameKey: 'category_name' | 'brand_name'
  onOpen: (row: CoverageRow) => void
}) {
  return (
    <section className="bg-bg-card border border-border rounded-card shadow-card p-5">
      <SectionTitle title={title} action="not updated drill-down" />
      <div className="flex flex-col gap-3">
        {rows.length ? rows.map(row => (
          <button key={`${nameKey}-${row[nameKey] ?? 'unknown'}`} onClick={() => onOpen(row)} className="text-left group">
            <div className="flex items-center justify-between gap-3 text-[12.5px] mb-1">
              <span className="font-medium text-text-base truncate">{row[nameKey] || 'Unknown'}</span>
              <span className="text-wp-muted">{fmt(row.updated_today)} / {fmt(row.total)}</span>
            </div>
            <div className="h-2 rounded-full bg-bg-base overflow-hidden">
              <div
                className={['h-full rounded-full transition-colors', coverageFill(row.update_pct)].join(' ')}
                style={{ width: `${Math.min(row.update_pct, 100)}%` }}
              />
            </div>
          </button>
        )) : <div className="text-[13px] text-wp-muted py-6 text-center">No coverage data</div>}
      </div>
    </section>
  )
}

function StaleCard({
  title,
  count,
  rows,
  total,
  onOpen,
}: {
  title: string
  count: number
  rows: ProductRow[]
  total: number
  onOpen: (modal: ModalState) => void
}) {
  const sev = getSeverity(count, total)
  const style = SEVERITY_STYLES[sev]
  const ratioPct = total > 0 ? Math.round((count / total) * 100) : 0

  return (
    <button
      onClick={() => onOpen({ title, rows })}
      className={['rounded-card border shadow-card p-5 text-left transition-all', style.card].join(' ')}
    >
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="text-[12px] text-wp-muted font-medium">{title}</div>
        <span className={['text-[10px] font-bold px-2 py-0.5 rounded-full', style.badge].join(' ')}>
          {style.label}
        </span>
      </div>
      <div className="text-[30px] leading-tight font-bold text-text-base">{fmt(count)}</div>
      <div className="text-[11px] text-wp-muted mt-2">
        {count === 0
          ? 'No issues found'
          : `${ratioPct}% of catalog · tap to review`}
      </div>
    </button>
  )
}

function MovementPanel({ title, rows, onOpen }: { title: string; rows: Movement[]; onOpen: () => void }) {
  const isIncrease = title.toLowerCase().includes('increase')
  return (
    <section className="bg-bg-card border border-border rounded-card shadow-card p-5">
      <SectionTitle title={title} action="admin only" />
      <div className="flex flex-col gap-2">
        {rows.slice(0, 5).map(row => (
          <div key={`${title}-${row.product_id}`} className="flex items-center gap-3 bg-bg-base border border-border rounded-lg px-3 py-2">
            <div className="min-w-0 flex-1">
              <div className="text-[13px] font-medium text-text-base truncate">{row.name || `Product ${row.product_id}`}</div>
              <div className="text-[11px] text-wp-muted font-mono">
                {fmtPrice(row.old_price)} → {fmtPrice(row.new_price)}
              </div>
            </div>
            <div className={[
              'flex items-center gap-1 text-[12px] font-bold px-2 py-0.5 rounded-full flex-shrink-0',
              isIncrease ? 'bg-[#dcfce7] text-[#16a34a]' : 'bg-[#fee2e2] text-[#dc2626]',
            ].join(' ')}>
              <svg viewBox="0 0 24 24" className={['w-3 h-3', isIncrease ? '' : 'rotate-180'].join(' ')} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <polyline points="18 15 12 9 6 15" />
              </svg>
              {pct(Math.abs(row.delta_pct))}
            </div>
          </div>
        ))}
        <button onClick={onOpen} className="mt-1 text-[12px] text-accent hover:text-accent-hover font-medium text-left">
          Open drill-down
        </button>
      </div>
    </section>
  )
}

function DrilldownModal({ modal, onClose }: { modal: NonNullable<ModalState>; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-end sm:items-center justify-center p-0 sm:p-6" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        className="bg-bg-card border border-border rounded-t-card sm:rounded-card shadow-card w-full max-w-5xl max-h-[86vh] overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-border">
          <div>
            <h2 id="modal-title" className="text-[16px] font-bold text-text-base">{modal.title}</h2>
            <p className="text-[12px] text-wp-muted">{fmt(modal.rows.length)} rows</p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="w-8 h-8 rounded border border-border text-wp-muted hover:text-text-base hover:bg-bg-base flex items-center justify-center"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-4 h-4">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="overflow-auto max-h-[70vh]">
          {'movement' in modal ? <MovementTable rows={modal.rows as Movement[]} /> : <ProductTable rows={modal.rows as ProductRow[]} />}
        </div>
      </div>
    </div>
  )
}

function ProductTable({ rows }: { rows: ProductRow[] }) {
  return (
    <table className="w-full text-[12.5px]">
      <thead className="bg-bg-base text-wp-muted sticky top-0">
        <tr>
          <th className="text-left font-medium px-4 py-3">ID</th>
          <th className="text-left font-medium px-4 py-3">Product</th>
          <th className="text-left font-medium px-4 py-3">SKU</th>
          <th className="text-left font-medium px-4 py-3">Stock</th>
          <th className="text-left font-medium px-4 py-3">Price</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={`${productId(row)}-${i}`} className="border-t border-border">
            <td className="px-4 py-3 text-wp-muted">{productId(row) || '-'}</td>
            <td className="px-4 py-3 text-text-base min-w-[220px]">{productName(row)}</td>
            <td className="px-4 py-3 text-wp-muted">{row.sku || '-'}</td>
            <td className="px-4 py-3 text-wp-muted">{row.stock_status || '-'}</td>
            <td className="px-4 py-3 text-wp-muted">{price(row)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function MovementTable({ rows }: { rows: Movement[] }) {
  return (
    <table className="w-full text-[12.5px]">
      <thead className="bg-bg-base text-wp-muted sticky top-0">
        <tr>
          <th className="text-left font-medium px-4 py-3">ID</th>
          <th className="text-left font-medium px-4 py-3">Product</th>
          <th className="text-left font-medium px-4 py-3">Old Price</th>
          <th className="text-left font-medium px-4 py-3">New Price</th>
          <th className="text-left font-medium px-4 py-3">Change</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(row => (
          <tr key={row.product_id} className="border-t border-border">
            <td className="px-4 py-3 text-wp-muted">{row.product_id}</td>
            <td className="px-4 py-3 text-text-base min-w-[220px]">{row.name || '-'}</td>
            <td className="px-4 py-3 text-wp-muted font-mono">{fmtPrice(row.old_price)}</td>
            <td className="px-4 py-3 text-wp-muted font-mono">{fmtPrice(row.new_price)}</td>
            <td className={['px-4 py-3 font-bold', row.delta_pct > 0 ? 'text-[#16a34a]' : 'text-[#dc2626]'].join(' ')}>
              {row.delta_pct > 0 ? '+' : ''}{pct(row.delta_pct)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ─── Apply History Tab ────────────────────────────────────────────────────────

type AuthFetchFn = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

function FilterField({
  label,
  type = 'text',
  value,
  onChange,
  placeholder,
}: {
  label: string
  type?: 'text' | 'date'
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  return (
    <div>
      <label className="block text-[12px] text-wp-muted mb-1">{label}</label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full border border-border rounded-lg px-3 py-2 text-[13px] bg-bg-base text-text-base focus:outline-none focus:border-accent placeholder:text-wp-muted"
      />
    </div>
  )
}

function ChangeHistoryTab({ authFetch, isAdmin }: { authFetch: AuthFetchFn; isAdmin: boolean }) {
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [brandName, setBrandName] = useState('')
  const [sku, setSku] = useState('')
  const [productName, setProductName] = useState('')
  const [changeType, setChangeType] = useState('')
  const [results, setResults] = useState<ChangeRecord[] | null>(null)
  const [loadingQ, setLoadingQ] = useState(false)
  const [errorQ, setErrorQ] = useState<string | null>(null)

  async function applyFilters() {
    setLoadingQ(true)
    setErrorQ(null)
    const p = new URLSearchParams({ limit: '200' })
    if (fromDate) p.set('from_date', fromDate)
    if (toDate) p.set('to_date', toDate)
    if (brandName.trim()) p.set('brand_name', brandName.trim())
    if (sku.trim()) p.set('sku', sku.trim())
    if (productName.trim()) p.set('product_name', productName.trim())
    if (changeType) p.set('change_type', changeType)
    try {
      const r = await authFetch(`/api/analytics/change-log?${p}`)
      if (r.status === 403) {
        setErrorQ('You do not have permission to view change history.')
        return
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json() as { changes: ChangeRecord[]; total: number }
      setResults(data.changes)
    } catch (e) {
      setErrorQ(e instanceof Error ? e.message : 'Failed to load change history')
    } finally {
      setLoadingQ(false)
    }
  }

  function reset() {
    setFromDate('')
    setToDate('')
    setBrandName('')
    setSku('')
    setProductName('')
    setChangeType('')
    setResults(null)
    setErrorQ(null)
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Filter panel */}
      <div className="bg-bg-card border border-border rounded-card shadow-card p-5">
        <p className="text-[13px] font-semibold text-text-base mb-4">Filter Apply History</p>
        <p className="text-[11px] text-wp-muted -mt-2 mb-3">Shows confirmed Apply operations only — direct edits and rollbacks are separate flows.</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <FilterField label="From Date" type="date" value={fromDate} onChange={setFromDate} />
          <FilterField label="To Date" type="date" value={toDate} onChange={setToDate} />
          <FilterField label="Brand" placeholder="e.g. Samsung" value={brandName} onChange={setBrandName} />
          <FilterField label="SKU" placeholder="Exact or partial SKU" value={sku} onChange={setSku} />
          <FilterField label="Product Name" placeholder="Search name…" value={productName} onChange={setProductName} />
          <div>
            <label className="block text-[12px] text-wp-muted mb-1">Change Type</label>
            <select
              value={changeType}
              onChange={e => setChangeType(e.target.value)}
              className="w-full border border-border rounded-lg px-3 py-2 text-[13px] bg-bg-base text-text-base focus:outline-none focus:border-accent"
            >
              <option value="">All types</option>
              <option value="price_update">Price Updated</option>
              <option value="stock_in">Became In-Stock</option>
              <option value="stock_out">Became Out-of-Stock</option>
              <option value="stock_updated">Stock Changed</option>
            </select>
          </div>
        </div>
        <div className="flex gap-2 mt-4">
          <button
            onClick={() => { void applyFilters() }}
            disabled={loadingQ}
            className="px-4 py-2 bg-accent text-white text-[13px] font-semibold rounded-lg hover:bg-accent-hover transition-colors disabled:opacity-50"
          >
            {loadingQ ? 'Loading…' : 'Apply Filters'}
          </button>
          <button
            onClick={reset}
            className="px-4 py-2 border border-border text-[13px] text-wp-muted rounded-lg hover:border-accent hover:text-accent transition-colors"
          >
            Reset
          </button>
        </div>
        {!isAdmin && (
          <p className="text-[11px] text-wp-muted mt-3">Requires <code>can_view_logs</code> permission.</p>
        )}
      </div>

      {/* Error */}
      {errorQ && (
        <div className="bg-[#fee2e2] border border-[#ef4444]/30 rounded-card px-4 py-3 text-[13px] text-[#dc2626]">
          {errorQ}
        </div>
      )}

      {/* Results table */}
      {results !== null && (
        <div className="bg-bg-card border border-border rounded-card shadow-card overflow-hidden">
          <div className="px-5 py-3 border-b border-border flex items-center gap-3">
            <span className="text-[14px] font-bold text-text-base">Results</span>
            <span className="text-[12px] text-wp-muted">{results.length.toLocaleString('en')} records</span>
          </div>
          {results.length === 0 ? (
            <div className="text-center text-[13px] text-wp-muted py-8">No changes match the selected filters.</div>
          ) : (
            <div className="overflow-x-auto max-h-[560px] overflow-y-auto">
              <table className="w-full text-[12.5px]">
                <thead className="bg-bg-base text-wp-muted sticky top-0">
                  <tr>
                    <th className="text-left font-medium px-4 py-3 whitespace-nowrap">Date</th>
                    <th className="text-left font-medium px-4 py-3">Product</th>
                    <th className="text-left font-medium px-4 py-3">Brand</th>
                    <th className="text-left font-medium px-4 py-3 whitespace-nowrap">Old Price</th>
                    <th className="text-left font-medium px-4 py-3 whitespace-nowrap">New Price</th>
                    <th className="text-left font-medium px-4 py-3 whitespace-nowrap">Stock</th>
                    <th className="text-left font-medium px-4 py-3">User</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map(r => (
                    <tr key={r.id} className="border-t border-border hover:bg-bg-base transition-colors">
                      <td className="px-4 py-2.5 text-wp-muted whitespace-nowrap">
                        {r.changed_at ? r.changed_at.slice(0, 16).replace('T', ' ') : '—'}
                      </td>
                      <td className="px-4 py-2.5 min-w-[180px]">
                        <div className="text-text-base font-medium truncate max-w-[200px]">
                          {r.name || `#${r.product_id}`}
                        </div>
                        {r.sku && <div className="text-[11px] text-wp-muted">{r.sku}</div>}
                      </td>
                      <td className="px-4 py-2.5 text-wp-muted">{r.brand_name || '—'}</td>
                      <td className="px-4 py-2.5 font-mono text-wp-muted">{fmtPrice(r.old_price)}</td>
                      <td className={[
                        'px-4 py-2.5 font-mono font-medium',
                        r.old_price !== r.new_price && r.old_price && r.new_price ? 'text-accent' : 'text-wp-muted',
                      ].join(' ')}>
                        {fmtPrice(r.new_price)}
                      </td>
                      <td className="px-4 py-2.5 whitespace-nowrap">
                        {r.old_stock_status !== r.new_stock_status ? (
                          <span className={[
                            'text-[11px] px-2 py-0.5 rounded-full font-medium',
                            r.new_stock_status === 'instock'
                              ? 'bg-[#dcfce7] text-[#16a34a]'
                              : 'bg-[#fee2e2] text-[#dc2626]',
                          ].join(' ')}>
                            {r.old_stock_status} → {r.new_stock_status}
                          </span>
                        ) : (
                          <span className="text-wp-muted">{r.new_stock_status || '—'}</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-wp-muted">{r.username || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
