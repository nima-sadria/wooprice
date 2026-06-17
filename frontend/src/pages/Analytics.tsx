import { useCallback, useEffect, useMemo, useState } from 'react'
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

function productId(row: ProductRow) {
  return row.wc_id ?? row.product_id ?? 0
}

function productName(row: ProductRow) {
  return row.name || row.product_name || 'Unnamed product'
}

function price(row: ProductRow) {
  return row.final_price || row.new_price || '-'
}

function topRows(rows: CoverageRow[], limit = 6) {
  return rows.slice(0, limit)
}

const chartText = '#8E97A7'
const chartGrid = '#E8EAED'

export default function Analytics() {
  const { user, authFetch } = useAuth()
  const [data, setData] = useState<AnalyticsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [accessState, setAccessState] = useState<'login_required' | 'permission_denied' | null>(null)
  const [modal, setModal] = useState<ModalState>(null)
  const [trendWindow, setTrendWindow] = useState<7 | 30>(30)

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
    const freshPct = total ? Math.max(0, Math.round(((total - staleCount) / total) * 1000) / 10) : 0
    return { updatedToday, staleCount, total, freshPct }
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
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-[22px] font-bold text-text-base">Analytics</h1>
          <p className="text-[13px] text-wp-muted mt-0.5">Catalog coverage, freshness, and pricing movement</p>
        </div>
        <button
          onClick={() => { void load() }}
          disabled={loading}
          className="px-[18px] py-[9px] rounded-lg border-[1.5px] border-border bg-bg-card text-text-base text-[13px] font-medium hover:border-accent hover:text-accent transition-colors disabled:opacity-40"
        >
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-[#fee2e2] border border-[#ef4444]/30 rounded-card px-4 py-3 text-[13px] text-[#dc2626]">
          {error}
        </div>
      )}

      {loading && !data ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-[116px] rounded-card border border-border bg-bg-card shadow-card animate-pulse" />
          ))}
        </div>
      ) : data && totals ? (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
            <Kpi title="Total Products" value={fmt(totals.total)} tone="blue" />
            <Kpi title="Updated Today" value={fmt(data.adminOverview?.updated_products_today ?? totals.updatedToday)} tone="green" />
            <Kpi title="Stale Products" value={fmt(totals.staleCount)} tone="orange" />
            <Kpi title="Brand Coverage" value={pct(data.brands.coverage_percent)} tone="purple" />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-[320px_1fr] gap-4">
            <section className="bg-bg-card border border-border rounded-card shadow-card p-5">
              <SectionTitle title="Catalog Freshness" action={`${pct(totals.freshPct)} fresh`} />
              <div className="flex items-center justify-center py-4">
                <div
                  className="w-[190px] h-[190px] rounded-full flex items-center justify-center"
                  style={{ background: `conic-gradient(#22c55e ${totals.freshPct * 3.6}deg, #E8EAED 0deg)` }}
                >
                  <div className="w-[132px] h-[132px] rounded-full bg-bg-card flex flex-col items-center justify-center border border-border">
                    <div className="text-[34px] font-bold text-text-base">{pct(totals.freshPct)}</div>
                    <div className="text-[12px] text-wp-muted">fresh catalog</div>
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-2 text-center">
                <MiniStat label="3-5 days" value={data.staleness.counts.stale_3_5} onClick={() => setModal({ title: 'Stale 3-5 Days', rows: data.staleness.stale_3_5 })} />
                <MiniStat label="5+ days" value={data.staleness.counts.stale_5_plus} onClick={() => setModal({ title: 'Stale 5+ Days', rows: data.staleness.stale_5_plus })} />
                <MiniStat label="Never" value={data.staleness.counts.never_updated} onClick={() => setModal({ title: 'Never Updated', rows: data.staleness.never_updated })} />
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

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <CoveragePanel
              title="Top Category Coverage"
              rows={topRows(data.categories.categories)}
              nameKey="category_name"
              onOpen={row => setModal({ title: row.category_name || 'Category Products', rows: row.products_not_updated })}
            />
            <CoveragePanel
              title="Top Brand Coverage"
              rows={topRows(data.brands.brands.concat(data.brands.unknown_brand ? [data.brands.unknown_brand] : []))}
              nameKey="brand_name"
              onOpen={row => setModal({ title: row.brand_name || 'Brand Products', rows: row.products_not_updated })}
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <StaleCard title="In Stock, No Price" count={data.issues.in_stock_no_price.length} rows={data.issues.in_stock_no_price} onOpen={setModal} />
            <StaleCard title="Priced, Out of Stock" count={data.issues.has_price_out_of_stock.length} rows={data.issues.has_price_out_of_stock} onOpen={setModal} />
            <StaleCard title="Legacy Stale Items" count={data.issues.stale_products.length} rows={data.issues.stale_products} onOpen={setModal} />
          </div>

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
      )}

      {modal && <DrilldownModal modal={modal} onClose={() => setModal(null)} />}
    </div>
  )
}

function Kpi({ title, value, tone }: { title: string; value: string; tone: 'blue' | 'green' | 'orange' | 'purple' }) {
  const tones = {
    blue: 'bg-[#dbeafe] text-[#2563eb]',
    green: 'bg-[#dcfce7] text-[#16a34a]',
    orange: 'bg-[#ffedd5] text-[#ea580c]',
    purple: 'bg-[#ede9fe] text-[#7c3aed]',
  }
  return (
    <div className="bg-bg-card border border-border rounded-card shadow-card p-5 flex items-center justify-between gap-4">
      <div className="min-w-0">
        <div className="text-[12px] text-wp-muted">{title}</div>
        <div className="text-[28px] leading-tight font-bold text-text-base mt-1 truncate">{value}</div>
      </div>
      <div className={['w-11 h-11 rounded-lg flex items-center justify-center font-bold text-[16px]', tones[tone]].join(' ')}>
        {title.slice(0, 1)}
      </div>
    </div>
  )
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
              <div className="h-full rounded-full bg-accent group-hover:bg-accent-hover transition-colors" style={{ width: `${Math.min(row.update_pct, 100)}%` }} />
            </div>
          </button>
        )) : <div className="text-[13px] text-wp-muted py-6 text-center">No coverage data</div>}
      </div>
    </section>
  )
}

function StaleCard({ title, count, rows, onOpen }: { title: string; count: number; rows: ProductRow[]; onOpen: (modal: ModalState) => void }) {
  return (
    <button onClick={() => onOpen({ title, rows })} className="bg-bg-card border border-border rounded-card shadow-card p-5 text-left hover:border-accent transition-colors">
      <div className="text-[12px] text-wp-muted">{title}</div>
      <div className="text-[30px] leading-tight font-bold text-text-base mt-1">{fmt(count)}</div>
      <div className="text-[12px] text-wp-muted mt-2">Open product list</div>
    </button>
  )
}

function MovementPanel({ title, rows, onOpen }: { title: string; rows: Movement[]; onOpen: () => void }) {
  return (
    <section className="bg-bg-card border border-border rounded-card shadow-card p-5">
      <SectionTitle title={title} action="admin only" />
      <div className="flex flex-col gap-2">
        {rows.slice(0, 5).map(row => (
          <div key={`${title}-${row.product_id}`} className="flex items-center gap-3 bg-bg-base border border-border rounded-lg px-3 py-2">
            <div className="min-w-0 flex-1">
              <div className="text-[13px] font-medium text-text-base truncate">{row.name || `Product ${row.product_id}`}</div>
              <div className="text-[11px] text-wp-muted">{row.old_price} → {row.new_price}</div>
            </div>
            <div className={['text-[13px] font-bold', row.delta_pct > 0 ? 'text-[#16a34a]' : 'text-[#dc2626]'].join(' ')}>
              {pct(row.delta_pct)}
            </div>
          </div>
        ))}
        <button onClick={onOpen} className="mt-1 text-[12px] text-accent hover:text-accent-hover font-medium text-left">Open drill-down</button>
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
          <th className="text-left font-medium px-4 py-3">Old</th>
          <th className="text-left font-medium px-4 py-3">New</th>
          <th className="text-left font-medium px-4 py-3">Change</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(row => (
          <tr key={row.product_id} className="border-t border-border">
            <td className="px-4 py-3 text-wp-muted">{row.product_id}</td>
            <td className="px-4 py-3 text-text-base min-w-[220px]">{row.name || '-'}</td>
            <td className="px-4 py-3 text-wp-muted">{row.old_price}</td>
            <td className="px-4 py-3 text-wp-muted">{row.new_price}</td>
            <td className={['px-4 py-3 font-bold', row.delta_pct > 0 ? 'text-[#16a34a]' : 'text-[#dc2626]'].join(' ')}>{pct(row.delta_pct)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
