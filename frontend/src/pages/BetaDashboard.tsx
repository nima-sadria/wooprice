import { useEffect, useState } from 'react'
import { useAuth } from '../auth'

interface HealthData {
  status: string
  env: string
  version: string
}

type Indicator = 'ok' | 'error' | 'loading'

function StatusCard({ label, value, indicator }: { label: string; value: string; indicator: Indicator }) {
  const dot =
    indicator === 'ok'
      ? 'bg-[#22c55e]'
      : indicator === 'error'
        ? 'bg-[#ef4444]'
        : 'bg-[#f59e0b] animate-pulse'
  return (
    <div className="bg-bg-card border border-border rounded-card shadow-card p-[22px]">
      <div className="flex items-center gap-2 mb-2">
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dot}`} />
        <span className="text-[11.5px] uppercase tracking-[.7px] text-wp-muted font-semibold">{label}</span>
      </div>
      <div className="text-[15px] font-bold text-text-base">{value}</div>
    </div>
  )
}

export default function BetaDashboard() {
  const { user } = useAuth()
  const [health, setHealth] = useState<HealthData | null>(null)
  const [healthError, setHealthError] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/health')
      .then(r => r.json() as Promise<HealthData>)
      .then(data => { setHealth(data); setLoading(false) })
      .catch(() => { setHealthError(true); setLoading(false) })
  }, [])

  const backendIndicator: Indicator = loading ? 'loading' : healthError ? 'error' : 'ok'
  const dbIndicator: Indicator = loading ? 'loading' : healthError ? 'error' : 'ok'
  const cpIndicator: Indicator = loading ? 'loading' : healthError ? 'error' : 'ok'

  const initial = user?.username?.[0]?.toUpperCase() ?? '?'

  return (
    <div className="p-4 sm:p-7 flex flex-col gap-5 max-w-2xl">
      {/* Header */}
      <div>
        <h1 className="text-[22px] font-bold text-text-base">Dashboard</h1>
        <p className="text-[13px] text-wp-muted mt-0.5">WooPrice Beta — System Overview</p>
      </div>

      {/* Logged-in user */}
      <div className="bg-bg-card border border-border rounded-card shadow-card p-[22px]">
        <p className="text-[11.5px] uppercase tracking-[.7px] text-wp-muted mb-3 font-semibold">
          Logged In
        </p>
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-accent/10 flex items-center justify-center flex-shrink-0">
            <span className="text-accent font-bold text-[14px]">{initial}</span>
          </div>
          <div>
            <div className="text-[15px] font-semibold text-text-base">{user?.username ?? '—'}</div>
            <div className="text-[12px] text-wp-muted capitalize">{user?.role ?? '—'}</div>
          </div>
        </div>
      </div>

      {/* Status grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatusCard label="Environment" value="Beta" indicator="ok" />
        <StatusCard
          label="Backend"
          value={health ? `v${health.version}` : loading ? 'Checking…' : 'Unavailable'}
          indicator={backendIndicator}
        />
        <StatusCard
          label="Database"
          value={dbIndicator === 'ok' ? 'Connected' : dbIndicator === 'loading' ? 'Checking…' : 'Unavailable'}
          indicator={dbIndicator}
        />
        <StatusCard
          label="Control Plane"
          value={cpIndicator === 'ok' ? 'Running' : cpIndicator === 'loading' ? 'Checking…' : 'Unavailable'}
          indicator={cpIndicator}
        />
      </div>

      {/* Next step prompt */}
      <div className="bg-bg-card border border-accent/30 rounded-card shadow-card p-[22px] flex items-start gap-3">
        <div className="w-2 h-2 rounded-full bg-accent mt-1.5 flex-shrink-0" />
        <div>
          <p className="text-[14px] font-semibold text-text-base">Connect your first source.</p>
          <p className="text-[12px] text-wp-muted mt-1">
            Source management is available in a future Beta phase.
          </p>
        </div>
      </div>

      {/* Beta notice */}
      <p className="text-[11px] text-wp-muted">
        WooPrice Beta &mdash; authentication foundation only. Business features arrive in later phases.
      </p>
    </div>
  )
}
