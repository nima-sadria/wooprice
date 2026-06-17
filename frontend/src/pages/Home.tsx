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
import { Bar, Doughnut } from 'react-chartjs-2'
import { useAuth } from '../auth'

ChartJS.register(CategoryScale, LinearScale, BarElement, ArcElement, Tooltip, Legend)

interface ProductStats {
  total: number
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
  product_stats: ProductStats
  sync_chart: SyncPoint[]
  recent_logs: RecentLog[]
}

function fmtDate(iso: string) {
  try {
    const d = new Date(iso + 'T00:00:00')
    return d.toLocaleDateString('en', { month: 'short', day: 'numeric' })
  } catch {
    return iso
  }
}

function fmtTs(iso: string) {
  try {
    const d = new Date(iso)
    return d.toLocaleString('en', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

const ACTION_CLS: Record<string, string> = {
  login: 'bg-[#dbeafe] text-[#2563eb]',
  fetch: 'bg-[#dcfce7] text-[#16a34a]',
  apply: 'bg-[#ede9fe] text-[#7c3aed]',
}

function actionCls(action: string) {
  return ACTION_CLS[action] ?? 'bg-bg-base text-wp-muted'
}

const BAR_OPTS = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: { legend: { display: false } },
  scales: {
    x: { grid: { color: '#E8EAED' }, ticks: { color: '#8E97A7' } },
    y: {
      grid: { color: '#E8EAED' },
      ticks: { color: '#8E97A7', precision: 0 },
      beginAtZero: true,
    },
  },
} as const

const DONUT_OPTS = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      position: 'bottom' as const,
      labels: { color: '#8E97A7', font: { size: 11 } },
    },
  },
} as const

export default function Home() {
  const { authFetch } = useAuth()
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await authFetch('/api/dashboard')
      if (r.status === 401 || r.status === 403) {
        setData(null)
        setError(r.status === 401 ? 'Login required. Please sign in via the main interface.' : 'Access denied.')
        return
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setData((await r.json()) as DashboardData)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load dashboard')
    } finally {
      setLoading(false)
    }
  }, [authFetch])

  useEffect(() => { void load() }, [load])

  const statCards = data
    ? [
        {
          val: data.total_syncs.toLocaleString('en'),
          label: 'Total Syncs',
          icon: '/static/icons/icons8-total-syncs-96.png',
        },
        {
          val: data.product_stats.total.toLocaleString('en'),
          label: 'Products',
          icon: '/static/icons/icons8-product-96.png',
        },
        {
          val: data.product_stats.in_stock.toLocaleString('en'),
          label: 'In Stock',
          icon: '/static/icons/icons8-in-stock-96.png',
        },
        {
          val: data.product_stats.out_of_stock.toLocaleString('en'),
          label: 'Out of Stock',
          icon: '/static/icons/icons8-out-of-stock-96.png',
        },
      ]
    : null

  const barData = data
    ? {
        labels: data.sync_chart.map(d => fmtDate(d.date)),
        datasets: [
          {
            data: data.sync_chart.map(d => d.count),
            backgroundColor: 'rgba(72, 128, 255, 0.55)',
            borderRadius: 4,
          },
        ],
      }
    : null

  const donutData = data
    ? {
        labels: ['In Stock', 'Out of Stock'],
        datasets: [
          {
            data: [data.product_stats.in_stock, data.product_stats.out_of_stock],
            backgroundColor: ['#22c55e', '#ef4444'],
            borderWidth: 0,
          },
        ],
      }
    : null

  return (
    <div className="p-7 flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-[22px] font-bold text-text-base">Dashboard</h1>
          <p className="text-[13px] text-wp-muted mt-0.5">Overview and recent activity</p>
        </div>
        <button
          onClick={() => { void load() }}
          disabled={loading}
          className="px-[18px] py-[9px] rounded-lg border-[1.5px] border-border bg-bg-card text-text-base text-[13px] font-medium hover:border-accent hover:text-accent transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Refresh
        </button>
      </div>

      {/* Error banner */}
      {error && (
        <div className="bg-[#fee2e2] border border-[#ef4444]/30 rounded-lg px-4 py-3 text-[13px] text-[#dc2626]">
          {error}
        </div>
      )}

      {/* Stat cards */}
      <div className="grid grid-cols-1 min-[480px]:grid-cols-2 min-[1100px]:grid-cols-4 gap-4">
        {loading && !data
          ? Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="bg-bg-card border border-border rounded-card shadow-card p-[22px] animate-pulse h-[90px]" />
            ))
          : statCards?.map(card => (
              <div
                key={card.label}
                className="bg-bg-card border border-border rounded-card shadow-card p-[22px] flex items-center justify-between gap-4"
              >
                <div className="flex-1 min-w-0">
                  <div className="text-[30px] font-bold text-text-base leading-none mb-1" lang="en">
                    {card.val}
                  </div>
                  <div className="text-[12.5px] text-wp-muted">{card.label}</div>
                </div>
                <div className="w-[60px] h-[60px] flex items-center justify-center flex-shrink-0">
                  <img src={card.icon} alt={card.label} className="w-[60px] h-[60px] object-contain" />
                </div>
              </div>
            ))}
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-bg-card border border-border rounded-card shadow-card p-[22px]">
          <p className="text-[11.5px] uppercase tracking-[.7px] text-wp-muted mb-4 font-semibold">
            Sync Activity — Last 30 Days
          </p>
          <div className="relative h-[190px]">
            {barData && barData.labels.length > 0 ? (
              <Bar data={barData} options={BAR_OPTS} />
            ) : (
              <div className="flex items-center justify-center h-full text-[13px] text-wp-muted">
                {loading ? 'Loading…' : 'No data'}
              </div>
            )}
          </div>
        </div>

        <div className="bg-bg-card border border-border rounded-card shadow-card p-[22px]">
          <p className="text-[11.5px] uppercase tracking-[.7px] text-wp-muted mb-4 font-semibold">
            Stock Distribution
          </p>
          <div className="relative h-[190px]">
            {donutData && (donutData.datasets[0].data[0] + donutData.datasets[0].data[1] > 0) ? (
              <Doughnut data={donutData} options={DONUT_OPTS} />
            ) : (
              <div className="flex items-center justify-center h-full text-[13px] text-wp-muted">
                {loading ? 'Loading…' : 'No data'}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Recent activity */}
      <div className="bg-bg-card border border-border rounded-card shadow-card p-[22px]">
        <p className="text-[11.5px] uppercase tracking-[.7px] text-wp-muted mb-4 font-semibold">
          Recent Activity
        </p>
        {loading && !data ? (
          <div className="text-center text-[13px] text-wp-muted py-5">Loading…</div>
        ) : data && data.recent_logs.length > 0 ? (
          <div className="flex flex-col gap-1.5 max-h-[260px] overflow-y-auto">
            {data.recent_logs.map((log, i) => (
              <div
                key={i}
                className="flex items-center gap-2.5 px-3.5 py-2 rounded-lg bg-bg-base text-[12.5px] border border-border"
              >
                <span
                  className={[
                    'px-2 py-0.5 rounded text-[11px] font-semibold min-w-[50px] text-center',
                    actionCls(log.action),
                  ].join(' ')}
                >
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
