import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuth } from '../auth'

type ConnectorHealthStatus =
  | 'healthy'
  | 'warning'
  | 'error'
  | 'disabled'
  | 'degraded'
  | 'authentication_failed'
  | 'rate_limited'
  | 'timeout'

interface ConnectorCapabilities {
  read_products: boolean
  read_categories: boolean
  read_inventory: boolean
  read_orders: boolean
  write_prices: boolean
  write_inventory: boolean
  webhook: boolean
  polling: boolean
  oauth: boolean
  api_key: boolean
}

interface ConnectorDefinition {
  connector: {
    identity: {
      id: string
      name: string
      type: string
      version: string
      enabled: boolean
      read_only: boolean
    }
    capabilities: ConnectorCapabilities
    status: ConnectorHealthStatus
    runtime_write_blocked: boolean
    capability_authorizes_write: false
  }
  settings_schema: Array<{
    key: string
    label: string
    required: boolean
    secret: boolean
  }>
  diagnostics_contract: {
    checks: Array<{
      name: string
      category: string
    }>
  }
}

interface ConnectorInstance {
  connector: ConnectorDefinition['connector']
  settings: Array<{
    key: string
    value: unknown
    secret: boolean
    configured: boolean
  }>
  created_at: string | null
  updated_at: string | null
}

interface ConnectorRegistryResponse {
  items: ConnectorDefinition[]
  runtime_write_blocked: boolean
}

interface ConnectorListResponse {
  items: ConnectorInstance[]
  runtime_write_blocked: boolean
}

const CAPABILITY_LABELS: Array<[keyof ConnectorCapabilities, string]> = [
  ['read_products', 'Read products'],
  ['read_categories', 'Read categories'],
  ['read_inventory', 'Read inventory'],
  ['read_orders', 'Read orders'],
  ['write_prices', 'Write prices'],
  ['write_inventory', 'Write inventory'],
  ['webhook', 'Webhook'],
  ['polling', 'Polling'],
  ['oauth', 'OAuth'],
  ['api_key', 'API key'],
]

function CapabilityBadge({ enabled, label }: { enabled: boolean; label: string }) {
  return (
    <span
      className={[
        'inline-flex items-center rounded px-2 py-1 text-[11px] font-medium border',
        enabled
          ? 'bg-accent/10 text-accent border-accent/20'
          : 'bg-bg-base text-wp-muted border-border',
      ].join(' ')}
    >
      {label}
    </span>
  )
}

function ConnectorCard({ definition }: { definition: ConnectorDefinition }) {
  const { connector, settings_schema, diagnostics_contract } = definition
  const writeAdvertised = connector.capabilities.write_prices || connector.capabilities.write_inventory

  return (
    <div className="bg-bg-card border border-border rounded-card shadow-card p-[22px]">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-[16px] font-semibold text-text-base">{connector.identity.name}</h2>
            <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full uppercase tracking-wide bg-border/60 text-wp-muted">
              {connector.status.replace(/_/g, ' ')}
            </span>
          </div>
          <p className="text-[12px] text-wp-muted mt-0.5">
            {connector.identity.type} / v{connector.identity.version}
          </p>
        </div>
        <div className="text-end text-[11px] text-wp-muted">
          <div>{connector.identity.read_only ? 'Read-only instance baseline' : 'Writable capability advertised'}</div>
          <div>{connector.identity.enabled ? 'Enabled' : 'Not enabled'}</div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {CAPABILITY_LABELS.map(([key, label]) => (
          <CapabilityBadge key={key} label={label} enabled={connector.capabilities[key]} />
        ))}
      </div>

      {writeAdvertised && (
        <div className="mt-4 border border-wp-yellow/30 bg-wp-yellow/10 rounded-card px-3 py-2 text-[12px] text-text-base">
          This connector advertises write capability, but FlowHub Beta blocks all writes through the Safety Layer and Write Guard.
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4 text-[12px]">
        <div>
          <p className="text-[11px] uppercase tracking-[.7px] text-wp-muted font-semibold mb-2">Settings Contract</p>
          <div className="flex flex-col gap-1.5">
            {settings_schema.map(setting => (
              <div key={setting.key} className="flex items-center justify-between gap-3">
                <span className="text-text-base">{setting.label}</span>
                <span className="text-wp-muted">{setting.secret ? 'secret' : setting.required ? 'required' : 'optional'}</span>
              </div>
            ))}
          </div>
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-[.7px] text-wp-muted font-semibold mb-2">Diagnostics Contract</p>
          <div className="flex flex-col gap-1.5">
            {diagnostics_contract.checks.map(check => (
              <div key={check.name} className="flex items-center justify-between gap-3">
                <span className="text-text-base">{check.name.replace(/_/g, ' ')}</span>
                <span className="text-wp-muted">{check.category}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function IntegrationPlatform() {
  const { authFetch } = useAuth()
  const [registry, setRegistry] = useState<ConnectorDefinition[]>([])
  const [connectors, setConnectors] = useState<ConnectorInstance[]>([])
  const [runtimeWriteBlocked, setRuntimeWriteBlocked] = useState(true)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [registryResponse, connectorResponse] = await Promise.all([
        authFetch('/api/v2/integrations/registry'),
        authFetch('/api/v2/integrations/connectors'),
      ])
      if (!registryResponse.ok) throw new Error(`Registry request failed (${registryResponse.status})`)
      if (!connectorResponse.ok) throw new Error(`Connector request failed (${connectorResponse.status})`)
      const registryData = await registryResponse.json() as ConnectorRegistryResponse
      const connectorData = await connectorResponse.json() as ConnectorListResponse
      setRegistry(registryData.items)
      setConnectors(connectorData.items)
      setRuntimeWriteBlocked(registryData.runtime_write_blocked && connectorData.runtime_write_blocked)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load integrations')
    } finally {
      setLoading(false)
    }
  }, [authFetch])

  useEffect(() => {
    void load()
  }, [load])

  const advertisedWrites = useMemo(() => {
    return registry.filter(
      item => item.connector.capabilities.write_prices || item.connector.capabilities.write_inventory,
    ).length
  }, [registry])

  return (
    <div className="p-4 sm:p-7 flex flex-col gap-5 max-w-5xl">
      <div>
        <h1 className="text-[22px] font-bold text-text-base">Integration Platform</h1>
        <p className="text-[13px] text-wp-muted mt-0.5">
          Connector registry, capability metadata, status contracts, and diagnostics baseline
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-bg-card border border-border rounded-card shadow-card p-[18px]">
          <p className="text-[11px] uppercase tracking-[.7px] text-wp-muted font-semibold mb-1">Registry</p>
          <div className="text-[20px] font-bold text-text-base">{loading ? '...' : registry.length}</div>
        </div>
        <div className="bg-bg-card border border-border rounded-card shadow-card p-[18px]">
          <p className="text-[11px] uppercase tracking-[.7px] text-wp-muted font-semibold mb-1">Instances</p>
          <div className="text-[20px] font-bold text-text-base">{loading ? '...' : connectors.length}</div>
        </div>
        <div className="bg-bg-card border border-border rounded-card shadow-card p-[18px]">
          <p className="text-[11px] uppercase tracking-[.7px] text-wp-muted font-semibold mb-1">Write Guard</p>
          <div className="text-[20px] font-bold text-wp-green">
            {runtimeWriteBlocked ? 'Blocked' : 'Open'}
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-wp-red/10 border border-wp-red/30 rounded-card p-4 text-[13px] text-wp-red">
          {error}
        </div>
      )}

      <div className="bg-bg-card border border-border rounded-card shadow-card p-[18px]">
        <div className="flex items-start gap-3">
          <span className="w-2 h-2 rounded-full bg-wp-green mt-1.5 flex-shrink-0" />
          <div>
            <p className="text-[13px] font-semibold text-text-base">Read-only safety preserved</p>
            <p className="text-[12px] text-wp-muted mt-0.5">
              {advertisedWrites} connector type{advertisedWrites === 1 ? '' : 's'} advertise write capabilities as metadata.
              Capability detection remains separate from authorization, and no write execution routes are exposed.
            </p>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-4">
        {registry.map(definition => (
          <ConnectorCard key={definition.connector.identity.id} definition={definition} />
        ))}
      </div>
    </div>
  )
}
