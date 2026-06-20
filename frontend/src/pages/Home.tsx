import { useCallback, useEffect, useState } from 'react'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  ArcElement,
  Tooltip,
  Legend,
} from 'chart.js'
import { Bar } from 'react-chartjs-2'
import { useAuth } from '../auth'

ChartJS.register(CategoryScale, LinearScale, BarElement, ArcElement, Tooltip, Legend)

// ─── Types ────────────────────────────────────────────────────────────────────

interface SheetCoverage {
  total_cache: number
  sheet_products: number
  not_covered: number
  coverage_pct: number
}

interface CacheStock {
  in_stock: number
  out_of_stock: number
}

interface SyncPoint {
  date: string
  count: number
}

interface RecentLog {
  username: string
  action: string
  timestamp: string
}

interface DashboardData {
  total_syncs: number
  sync_chart: SyncPoint[]
  recent_logs: RecentLog[]
  sheet_coverage: SheetCoverage | null
  cache_stock: CacheStock | null
}

interface DailyChange {
  date: string
  became_instock: number
  became_outofstock: number
  price_updated: number
  stock_updated: number
}

interface DailyChanges {
  days: number
  data: DailyChange[]
}

interface CurrencyData {
  base: string
  usd_to_irr: number | null
  eur_to_irr: number | null
  last_updated: string
  cached?: boolean
  stale?: boolean
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmtDate(iso: string) {
  try {
    return new Date(iso + 'T00:00:00').toLocaleDateString('en', { month: 'short', day: 'numeric' })
  } catch { return iso }
}

function fmtTs(iso: string) {
  try {
    return new Date(iso).toLocaleString('en', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch { return iso }
}

function fmtNum(n: number) {
  return n.toLocaleString('en')
}

function fmtRate(r: number | null | undefined) {
  if (!r) return '—'
  return r.toLocaleString('en', { maximumFractionDigits: 0 })
}

const ACTION_CLS: Record<string, string> = {
  login:  'bg-[#dbeafe] text-[#2563eb]',
  fetch:  'bg-[#dcfce7] text-[#16a34a]',
  apply:  'bg-[#ede9fe] text-[#7c3aed]',
}
function actionCls(action: string) {
  return ACTION_CLS[action] ?? 'bg-bg-base text-wp-muted'
}

// ─── Calendar card ────────────────────────────────────────────────────────────

function CalendarCard() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000)
    return () => clearInterval(id)
  }, [])

  const weekday = now.toLocaleDateString('en', { weekday: 'long' })
  const dateStr = now.toLocaleDateString('en', { month: 'long', day: 'numeric', year: 'numeric' })
  const timeStr = now.toLocaleTimeString('en', { hour: '2-digit', minute: '2-digit' })

  return (
    <div className="bg-bg-card border border-border rounded-card shadow-card p-[22px] flex flex-col justify-between min-h-[140px]">
      <div className="flex items-center gap-2">
        <svg viewBox="0 0 24 24" className="w-4 h-4 text-accent flex-shrink-0" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
        </svg>
        <span className="text-[11.5px] uppercase tracking-[.7px] text-wp-muted font-semibold">Today</span>
      </div>
      <div>
        <div className="text-[13px] text-wp-muted">{weekday}</div>
        <div className="text-[22px] font-bold text-text-base mt-0.5 leading-tight">{dateStr}</div>
        <div className="text-[13px] text-wp-muted mt-1">{timeStr}</div>
      </div>
    </div>
  )
}

// ─── Currency card ────────────────────────────────────────────────────────────

function CurrencyCard({ data, loading, error }: { data: CurrencyData | null; loading: boolean; error: string | null }) {
  return (
    <div className="bg-bg-card border border-border rounded-card shadow-card p-[22px] flex flex-col justify-between min-h-[140px]">
      <div className="flex items-center gap-2">
        <svg viewBox="0 0 24 24" className="w-4 h-4 text-accent flex-shrink-0" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
        <span className="text-[11.5px] uppercase tracking-[.7px] text-wp-muted font-semibold">Exchange Rates</span>
      </div>
      {loading ? (
        <div className="text-[13px] text-wp-muted">Loading…</div>
      ) : error ? (
        <div className="text-[12px] text-wp-red">{error}</div>
      ) : data ? (
        <div className="flex flex-col gap-2 mt-2">
          <div className="flex items-center justify-between gap-3">
            <span className="text-[13px] text-wp-muted">1 USD</span>
            <span className="text-[16px] font-bold text-text-base" lang="en">{fmtRate(data.usd_to_irr)} <span className="text-[11px] font-normal text-wp-muted">IRR</span></span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-[13px] text-wp-muted">1 EUR</span>
            <span className="text-[16px] font-bold text-text-base" lang="en">{fmtRate(data.eur_to_irr)} <span className="text-[11px] font-normal text-wp-muted">IRR</span></span>
          </div>
          {data.stale && <div className="text-[10px] text-wp-muted">Stale data — service unavailable</div>}
          {data.last_updated && !data.stale && (
            <div className="text-[10px] text-wp-muted truncate">Updated: {data.last_updated.slice(0, 16)}</div>
          )}
        </div>
      ) : (
        <div className="text-[13px] text-wp-muted">No data</div>
      )}
    </div>
  )
}

// ─── Stat card ────────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  tone = 'default',
}: {
  label: string
  value: string | number
  sub?: string
  tone?: 'default' | 'green' | 'red' | 'blue' | 'orange'
}) {
  const tones = {
    default: 'text-text-base',
    green:   'text-[#16a34a]',
    red:     'text-[#dc2626]',
    blue:    'text-accent',
    orange:  'text-[#ea580c]',
  }
  return (
    <div className="bg-bg-card border border-border rounded-card shadow-card p-[22px]">
      <div className="text-[12px] text-wp-muted mb-1">{label}</div>
      <div className={['text-[28px] font-bold leading-tight', tones[tone]].join(' ')} lang="en">
        {typeof value === 'number' ? fmtNum(value) : value}
      </div>
      {sub && <div className="text-[11px] text-wp-muted mt-1">{sub}</div>}
    </div>
  )
}

// ─── Bar chart options ────────────────────────────────────────────────────────

const CHART_OPTS = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      position: 'bottom' as const,
      labels: { color: '#8E97A7', font: { size: 11 }, boxWidth: 12, padding: 16 },
    },
  },
  scales: {
    x: { grid: { color: '#E8EAED' }, ticks: { color: '#8E97A7', maxRotation: 0 } },
    y: { grid: { color: '#E8EAED' }, ticks: { color: '#8E97A7', precision: 0 }, beginAtZero: true },
  },
} as const

// ─── Main component ───────────────────────────────────────────────────────────

export default function Home() {
  const { authFetch } = useAuth()

  const [dashboard, setDashboard] = useState<DashboardData | null>(null)
  const [dailyChanges, setDailyChanges] = useState<DailyChanges | null>(null)
  const [currency, setCurrency] = useState<CurrencyData | null>(null)

  const [loadingDash, setLoadingDash] = useState(true)
  const [loadingChanges, setLoadingChanges] = useState(true)
  const [loadingCurrency, setLoadingCurrency] = useState(true)

  const [errorDash, setErrorDash] = useState<string | null>(null)
  const [errorCurrency, setErrorCurrency] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoadingDash(true)
    setLoadingChanges(true)
    setLoadingCurrency(true)
    setErrorDash(null)
    setErrorCurrency(null)

    // Dashboard + daily changes in parallel
    const [dashRes, changesRes] = await Promise.allSettled([
      authFetch('/api/dashboard'),
      authFetch('/api/analytics/daily-changes?days=30'),
    ])

    if (dashRes.status === 'fulfilled') {
      const r = dashRes.value
      if (r.ok) {
        setDashboard(await r.json() as DashboardData)
      } else {
        setErrorDash(`Dashboard error (HTTP ${r.status})`)
      }
    } else {
      setErrorDash('Failed to load dashboard')
    }
    setLoadingDash(false)

    if (changesRes.status === 'fulfilled' && changesRes.value.ok) {
      setDailyChanges(await changesRes.value.json() as DailyChanges)
    }
    setLoadingChanges(false)

    // Currency — best-effort, shown even if auth fetch fails
    try {
      const r = await fetch('/api/currency')
      if (r.ok) {
        setCurrency(await r.json() as CurrencyData)
      } else {
        setErrorCurrency('Rate unavailable')
      }
    } catch {
      setErrorCurrency('Network error')
    }
    setLoadingCurrency(false)
  }, [authFetch])

  useEffect(() => { void load() }, [load])

  // Build 4-color bar chart data
  const changeChartData = dailyChanges
    ? {
        labels: dailyChanges.data.map(d => fmtDate(d.date)),
        datasets: [
          {
            label: 'Became In-Stock',
            data: dailyChanges.data.map(d => d.became_instock),
            backgroundColor: '#22c55e',
            borderRadius: 3,
          },
          {
            label: 'Became Out-of-Stock',
            data: dailyChanges.data.map(d => d.became_outofstock),
            backgroundColor: '#ef4444',
            borderRadius: 3,
          },
          {
            label: 'Price Updated',
            data: dailyChanges.data.map(d => d.price_updated),
            backgroundColor: '#4880FF',
            borderRadius: 3,
          },
          {
            label: 'Stock Updated',
            data: dailyChanges.data.map(d => d.stock_updated),
            backgroundColor: '#f59e0b',
            borderRadius: 3,
          },
        ],
      }
    : null

  const cov = dashboard?.sheet_coverage
  const stk = dashboard?.cache_stock

  return (
    <div className="p-4 sm:p-7 flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-[22px] font-bold text-text-base">Dashboard</h1>
          <p className="text-[13px] text-wp-muted mt-0.5">Overview and recent activity</p>
        </div>
        <button
          onClick={() => { void load() }}
          disabled={loadingDash}
          className="px-[18px] py-[9px] rounded-lg border-[1.5px] border-border bg-bg-card text-text-base text-[13px] font-medium hover:border-accent hover:text-accent transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Refresh
        </button>
      </div>

      {errorDash && (
        <div className="bg-[#fee2e2] border border-[#ef4444]/30 rounded-lg px-4 py-3 text-[13px] text-[#dc2626]">
          {errorDash}
        </div>
      )}

      {/* Row 1: Calendar + Currency */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <CalendarCard />
        <CurrencyCard data={currency} loading={loadingCurrency} error={errorCurrency} />
      </div>

      {/* Row 2: Sheet coverage (4 cards) */}
      <div className="grid grid-cols-2 min-[900px]:grid-cols-4 gap-4">
        {loadingDash && !dashboard
          ? Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="bg-bg-card border border-border rounded-card shadow-card p-[22px] animate-pulse h-[88px]" />
            ))
          : cov
            ? <>
                <StatCard label="WC Products" value={cov.total_cache} sub="top-level in cache" />
                <StatCard label="Sheet Covered" value={cov.sheet_products} tone="blue" sub="in latest job" />
                <StatCard label="Not Covered" value={cov.not_covered} tone={cov.not_covered > 0 ? 'orange' : 'default'} />
                <StatCard label="Coverage" value={`${cov.coverage_pct}%`} tone={cov.coverage_pct >= 80 ? 'green' : cov.coverage_pct >= 50 ? 'orange' : 'red'} />
              </>
            : Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="bg-bg-card border border-border rounded-card shadow-card p-[22px] h-[88px]" />
              ))
        }
      </div>

      {/* Row 3: Stock summary (2 cards) */}
      <div className="grid grid-cols-2 gap-4">
        {loadingDash && !dashboard
          ? Array.from({ length: 2 }).map((_, i) => (
              <div key={i} className="bg-bg-card border border-border rounded-card shadow-card p-[22px] animate-pulse h-[88px]" />
            ))
          : stk
            ? <>
                <StatCard label="In Stock" value={stk.in_stock} tone="green" sub="top-level products" />
                <StatCard label="Out of Stock" value={stk.out_of_stock} tone="red" sub="top-level products" />
              </>
            : Array.from({ length: 2 }).map((_, i) => (
                <div key={i} className="bg-bg-card border border-border rounded-card shadow-card p-[22px] h-[88px]" />
              ))
        }
      </div>

      {/* Row 4: Daily update bar chart (4 colors) */}
      <div className="bg-bg-card border border-border rounded-card shadow-card p-[22px]">
        <p className="text-[11.5px] uppercase tracking-[.7px] text-wp-muted mb-4 font-semibold">
          Daily Product Changes — Last 30 Days
        </p>
        <div className="relative h-[240px]">
          {loadingChanges && !dailyChanges ? (
            <div className="flex items-center justify-center h-full text-[13px] text-wp-muted animate-pulse">
              Loading chart…
            </div>
          ) : changeChartData ? (
            <Bar data={changeChartData} options={CHART_OPTS} />
          ) : (
            <div className="flex items-center justify-center h-full text-[13px] text-wp-muted">
              No change data yet
            </div>
          )}
        </div>
      </div>

      {/* Recent activity */}
      <div className="bg-bg-card border border-border rounded-card shadow-card p-[22px]">
        <p className="text-[11.5px] uppercase tracking-[.7px] text-wp-muted mb-4 font-semibold">
          Recent Activity
        </p>
        {loadingDash && !dashboard ? (
          <div className="text-center text-[13px] text-wp-muted py-5">Loading…</div>
        ) : dashboard && dashboard.recent_logs.length > 0 ? (
          <div className="flex flex-col gap-1.5 max-h-[260px] overflow-y-auto">
            {dashboard.recent_logs.map((log, i) => (
              <div
                key={i}
                className="flex items-center gap-2.5 px-3.5 py-2 rounded-lg bg-bg-base text-[12.5px] border border-border"
              >
                <span className={['px-2 py-0.5 rounded text-[11px] font-semibold min-w-[50px] text-center', actionCls(log.action)].join(' ')}>
                  {log.action}
                </span>
                <span className="text-text-base">{log.username}</span>
                <span className="ml-auto text-[11px] text-wp-muted whitespace-nowrap">
                  {fmtTs(log.timestamp)}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center text-[13px] text-wp-muted py-5">No recent activity</div>
        )}
      </div>
    </div>
  )
}
