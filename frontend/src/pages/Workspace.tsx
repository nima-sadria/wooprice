import { useCallback, useEffect, useReducer, useRef } from 'react'
import { AccessState, useAuth } from '../auth'
import { useSSEStream, type SSEErrorReason } from '../hooks/useSSEStream'

// ── Types ─────────────────────────────────────────────────────────────────────

type CacheOp = 'full' | 'light' | 'deep'
type LogLevel = 'info' | 'ok' | 'warn' | 'error'
type StepStatus = 'idle' | 'running' | 'done' | 'error'

interface LogEntry {
  id: number
  ts: string
  msg: string
  level: LogLevel
}

interface SheetMeta {
  current: {
    etag: string | null
    last_modified: string | null
    content_length: number | null
    checked_at: string
  }
  cached: Record<string, unknown> | null
  is_fresh: boolean
}

interface PreviewRow {
  product_id: number
  product_name: string
  sku: string
  old_price: string
  new_price: string
  sale_price: string
  stock_status: string
  stock_quantity: number | null
  categories: Array<{ id: number; name: string }>
  parent_id: number
  row_color: string | null
  last_price_updated: string | null
  wc_date_modified: string | null
  changed: boolean
  found_in_wc: boolean
  change_status?: string
  price_changed?: boolean
  stock_changed?: boolean
}

interface PreviewSummary {
  job_id: number
  total: number
  changed_count: number
  unchanged_count: number
  new_count: number
  invalid_count: number
  price_changed_count: number
  stock_changed_count: number
  missing_image_count: number
}

interface FilterStats {
  filter_mode: string
  sheet_rows_scanned: number
  rows_matched: number
  rows_skipped: number
  rows_no_cache: number
  wc_lookups: number
  cache_hits: number
}

interface DupWarning {
  product_id: number
  prev_sheet: string
  final_sheet: string
  prev_price: string
  final_price: string
}

interface WcCategory {
  id: number
  name: string
  parent: number
}

// ── Constants ─────────────────────────────────────────────────────────────────

const OP_LABEL: Record<CacheOp, string> = {
  full:  'Full Product Cache Refresh',
  light: 'Light Cache Refresh',
  deep:  'Deep Variation Sync',
}

const OP_ENDPOINT: Record<CacheOp, string> = {
  full:  '/api/fetch/full',
  light: '/api/fetch/light',
  deep:  '/api/fetch/deep-variations',
}

const LOG_COLOR: Record<LogLevel, string> = {
  info:  'text-wp-muted',
  ok:    'text-[#16a34a]',
  warn:  'text-[#b45309]',
  error: 'text-[#dc2626]',
}

const ROWS_PER_PAGE = 50

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  changed:               { label: 'Changed',     cls: 'bg-amber-100 text-amber-800' },
  new:                   { label: 'New',          cls: 'bg-green-100 text-green-800' },
  unchanged:             { label: 'Unchanged',    cls: 'bg-gray-100 text-gray-500' },
  invalid:               { label: 'Invalid',      cls: 'bg-red-100 text-red-700' },
  missing_from_wc_cache: { label: 'Not in Cache', cls: 'bg-orange-100 text-orange-700' },
}

// ── State ─────────────────────────────────────────────────────────────────────

interface WorkspaceState {
  // Cache refresh
  cacheOp: CacheOp | null
  cacheRunning: boolean
  cacheSseUrl: string | null
  cacheLog: LogEntry[]
  _logSeq: number
  // Sheet meta
  sheetLoading: boolean
  sheetMeta: SheetMeta | null
  sheetError: string | null
  sheetPolling: boolean
  // Preview stream
  previewPhase: 'idle' | 'streaming' | 'ready' | 'error'
  previewSseUrl: string | null
  previewError: string | null
  stepExcel: StepStatus
  stepWC: StepStatus
  stepCalc: StepStatus
  stepExcelMsg: string
  stepWCMsg: string
  stepCalcMsg: string
  // Preview data
  previewRows: PreviewRow[]
  previewSummary: PreviewSummary | null
  filterStats: FilterStats | null
  duplicateWarnings: DupWarning[]
  // Pagination
  previewPage: number
  // Selection (Set of product_id)
  previewSelection: Set<number>
  // Filters
  filterSearch: string
  filterCatIds: number[]
  // Categories
  categories: WcCategory[]
  catLoading: boolean
  catError: string | null
}

const INITIAL: WorkspaceState = {
  cacheOp: null,
  cacheRunning: false,
  cacheSseUrl: null,
  cacheLog: [],
  _logSeq: 0,
  sheetLoading: false,
  sheetMeta: null,
  sheetError: null,
  sheetPolling: false,
  previewPhase: 'idle',
  previewSseUrl: null,
  previewError: null,
  stepExcel: 'idle',
  stepWC: 'idle',
  stepCalc: 'idle',
  stepExcelMsg: '',
  stepWCMsg: '',
  stepCalcMsg: '',
  previewRows: [],
  previewSummary: null,
  filterStats: null,
  duplicateWarnings: [],
  previewPage: 0,
  previewSelection: new Set(),
  filterSearch: '',
  filterCatIds: [],
  categories: [],
  catLoading: false,
  catError: null,
}

// ── Actions ───────────────────────────────────────────────────────────────────

type Action =
  // Cache
  | { type: 'CACHE_START'; op: CacheOp; url: string }
  | { type: 'CACHE_LOG'; msg: string; level: LogLevel }
  | { type: 'CACHE_DONE' }
  | { type: 'CACHE_ERROR'; message: string }
  // Sheet
  | { type: 'SHEET_LOADING' }
  | { type: 'SHEET_LOADED'; meta: SheetMeta }
  | { type: 'SHEET_ERROR'; message: string }
  | { type: 'SHEET_POLL_START' }
  | { type: 'SHEET_POLL_STOP' }
  // Preview stream
  | { type: 'PREVIEW_START'; url: string }
  | { type: 'PREVIEW_STEP'; which: 'excel' | 'wc' | 'calc'; status: StepStatus; msg: string }
  | { type: 'PREVIEW_DUP_WARNING'; warnings: DupWarning[] }
  | { type: 'PREVIEW_READY'; rows: PreviewRow[]; summary: PreviewSummary; filterStats: FilterStats; dupWarnings: DupWarning[] }
  | { type: 'PREVIEW_ERROR'; message: string }
  // Pagination
  | { type: 'PREVIEW_PAGE'; page: number }
  // Selection
  | { type: 'PREVIEW_TOGGLE'; id: number }
  | { type: 'PREVIEW_SELECT_PAGE'; ids: number[] }
  | { type: 'PREVIEW_CLEAR_SELECTION' }
  // Filters
  | { type: 'FILTER_SEARCH'; value: string }
  | { type: 'FILTER_CAT_TOGGLE'; id: number }
  | { type: 'FILTER_CLEAR' }
  // Categories
  | { type: 'CAT_LOADING' }
  | { type: 'CAT_LOADED'; categories: WcCategory[] }
  | { type: 'CAT_ERROR'; message: string }

// ── Helpers ───────────────────────────────────────────────────────────────────

function nowTime(): string {
  return new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function buildSseUrl(path: string): string {
  const token = localStorage.getItem('wp_token') ?? ''
  return `${path}?token=${encodeURIComponent(token)}`
}

function buildPreviewSseUrl(search: string, catIds: number[]): string {
  const token = localStorage.getItem('wp_token') ?? ''
  let url = `/api/preview/stream?token=${encodeURIComponent(token)}`
  if (search.trim()) url += `&pre_search=${encodeURIComponent(search.trim())}`
  catIds.forEach(id => { url += `&pre_cat=${id}` })
  return url
}

function fmtLastModified(s: string | null | undefined): string {
  if (!s) return '—'
  try {
    return new Date(s).toLocaleString('en-GB', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return s
  }
}

// ── Reducer ───────────────────────────────────────────────────────────────────

function reducer(s: WorkspaceState, a: Action): WorkspaceState {
  switch (a.type) {
    case 'CACHE_START':
      return {
        ...s,
        cacheOp: a.op,
        cacheRunning: true,
        cacheSseUrl: a.url,
        // Only clears on explicit new start — log persists across re-renders otherwise
        cacheLog: [{ id: 0, ts: nowTime(), msg: OP_LABEL[a.op] + ' started…', level: 'info' }],
        _logSeq: 1,
      }
    case 'CACHE_LOG': {
      const entry: LogEntry = { id: s._logSeq, ts: nowTime(), msg: a.msg, level: a.level }
      return { ...s, cacheLog: [...s.cacheLog, entry], _logSeq: s._logSeq + 1 }
    }
    case 'CACHE_DONE':
      return { ...s, cacheRunning: false, cacheSseUrl: null }
    case 'CACHE_ERROR': {
      const errEntry: LogEntry = { id: s._logSeq, ts: nowTime(), msg: a.message, level: 'error' }
      return { ...s, cacheRunning: false, cacheSseUrl: null, cacheLog: [...s.cacheLog, errEntry], _logSeq: s._logSeq + 1 }
    }
    case 'SHEET_LOADING':
      return { ...s, sheetLoading: true, sheetError: null }
    case 'SHEET_LOADED':
      return { ...s, sheetLoading: false, sheetMeta: a.meta, sheetError: null }
    case 'SHEET_ERROR':
      // Clear stale meta so the UI never shows old freshness data alongside a new error
      return { ...s, sheetLoading: false, sheetMeta: null, sheetError: a.message }
    case 'SHEET_POLL_START':
      return { ...s, sheetPolling: true }
    case 'SHEET_POLL_STOP':
      return { ...s, sheetPolling: false }

    case 'PREVIEW_START':
      return {
        ...s,
        previewPhase: 'streaming',
        previewSseUrl: a.url,
        previewError: null,
        stepExcel: 'idle',
        stepWC: 'idle',
        stepCalc: 'idle',
        stepExcelMsg: '',
        stepWCMsg: '',
        stepCalcMsg: '',
        previewRows: [],
        previewSummary: null,
        filterStats: null,
        duplicateWarnings: [],
        previewPage: 0,
        previewSelection: new Set(),
      }
    case 'PREVIEW_STEP':
      return {
        ...s,
        stepExcel:    a.which === 'excel' ? a.status : s.stepExcel,
        stepWC:       a.which === 'wc'    ? a.status : s.stepWC,
        stepCalc:     a.which === 'calc'  ? a.status : s.stepCalc,
        stepExcelMsg: a.which === 'excel' && a.msg ? a.msg : s.stepExcelMsg,
        stepWCMsg:    a.which === 'wc'    && a.msg ? a.msg : s.stepWCMsg,
        stepCalcMsg:  a.which === 'calc'  && a.msg ? a.msg : s.stepCalcMsg,
      }
    case 'PREVIEW_DUP_WARNING':
      return { ...s, duplicateWarnings: a.warnings }
    case 'PREVIEW_READY':
      return {
        ...s,
        previewPhase: 'ready',
        previewSseUrl: null,   // URL → null causes useSSEStream cleanup, dropping any queued onerror
        stepExcel: 'done',
        stepWC: 'done',
        stepCalc: 'done',
        previewRows: a.rows,
        previewSummary: a.summary,
        filterStats: a.filterStats,
        duplicateWarnings: a.dupWarnings,
      }
    case 'PREVIEW_ERROR':
      // Spurious onerror fires when server closes the connection after preview.done —
      // the generation guard can't stop it in time if the re-render hasn't flushed yet.
      if (s.previewPhase === 'ready') return s
      return { ...s, previewPhase: 'error', previewSseUrl: null, previewError: a.message }

    case 'PREVIEW_PAGE':
      return { ...s, previewPage: a.page }
    case 'PREVIEW_TOGGLE': {
      const next = new Set(s.previewSelection)
      if (next.has(a.id)) next.delete(a.id)
      else next.add(a.id)
      return { ...s, previewSelection: next }
    }
    case 'PREVIEW_SELECT_PAGE': {
      const next = new Set(s.previewSelection)
      a.ids.forEach(id => next.add(id))
      return { ...s, previewSelection: next }
    }
    case 'PREVIEW_CLEAR_SELECTION':
      return { ...s, previewSelection: new Set() }

    case 'FILTER_SEARCH':
      return { ...s, filterSearch: a.value }
    case 'FILTER_CAT_TOGGLE': {
      const has = s.filterCatIds.includes(a.id)
      return { ...s, filterCatIds: has ? s.filterCatIds.filter(x => x !== a.id) : [...s.filterCatIds, a.id] }
    }
    case 'FILTER_CLEAR':
      return { ...s, filterSearch: '', filterCatIds: [] }

    case 'CAT_LOADING':
      return { ...s, catLoading: true, catError: null }
    case 'CAT_LOADED':
      return { ...s, catLoading: false, categories: a.categories }
    case 'CAT_ERROR':
      return { ...s, catLoading: false, catError: a.message }

    default:
      return s
  }
}

// ── SpreadsheetStatus ─────────────────────────────────────────────────────────

interface SpreadsheetStatusProps {
  loading: boolean
  meta: SheetMeta | null
  error: string | null
  polling: boolean
  onCheck: () => void
  onStartPoll: () => void
  onStopPoll: () => void
  canFetch: boolean
}

function SpreadsheetStatus({ loading, meta, error, polling, onCheck, onStartPoll, onStopPoll, canFetch }: SpreadsheetStatusProps) {
  const etag = meta?.current.etag?.replace(/^"|"$/g, '').slice(0, 16)

  return (
    <div className="bg-bg-card border border-border rounded-lg p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-lg bg-accent/10 flex items-center justify-center flex-shrink-0 mt-0.5">
            <svg viewBox="0 0 24 24" fill="none" stroke="#4880FF" strokeWidth="2" className="w-[18px] h-[18px]">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
            </svg>
          </div>
          <div>
            <div className="font-semibold text-[14px] text-text-base">Spreadsheet Status</div>
            {meta ? (
              <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-0.5">
                <span className="flex items-center gap-1.5 text-[12px] text-wp-muted">
                  <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${meta.is_fresh ? 'bg-[#16a34a]' : 'bg-[#f59e0b]'}`} />
                  {meta.is_fresh ? 'Fresh' : 'May have changed'}
                </span>
                {etag && (
                  <span className="text-[11px] font-mono text-wp-muted">ETag: {etag}…</span>
                )}
                {meta.current.last_modified && (
                  <span className="text-[11px] text-wp-muted">{fmtLastModified(meta.current.last_modified)}</span>
                )}
              </div>
            ) : error ? (
              <div className="text-[12px] text-[#dc2626] mt-0.5">{error}</div>
            ) : (
              <div className="text-[12px] text-wp-muted mt-0.5">Not checked</div>
            )}
          </div>
        </div>

        {canFetch && (
          <div className="flex flex-wrap items-center gap-2 flex-shrink-0">
            <button
              onClick={onCheck}
              disabled={loading || polling}
              className="px-3 py-1.5 text-[12px] border border-border rounded-lg text-wp-muted hover:text-text-base hover:border-accent transition-colors disabled:opacity-50"
            >
              {loading ? 'Checking…' : 'Check freshness'}
            </button>
            {meta && !polling && (
              <button
                onClick={onStartPoll}
                title="Poll every 2 s for up to 30 s until Nextcloud registers a new save"
                className="px-3 py-1.5 text-[12px] border border-border rounded-lg text-wp-muted hover:text-text-base hover:border-accent transition-colors"
              >
                Wait for update
              </button>
            )}
            {polling && (
              <button
                onClick={onStopPoll}
                className="px-3 py-1.5 text-[12px] border border-[#f59e0b] text-[#b45309] rounded-lg hover:bg-[#fef3c7] transition-colors"
              >
                Stop waiting…
              </button>
            )}
          </div>
        )}
      </div>

      {meta && (
        <p className="mt-3 pt-3 border-t border-border text-[11px] text-wp-muted leading-relaxed">
          <span className="font-medium text-[#b45309]">ONLYOFFICE note: </span>
          Edits may not be committed to Nextcloud/WebDAV storage immediately.
          The status above reflects what Nextcloud currently exposes — not what ONLYOFFICE holds in memory.
          Use <em>Wait for update</em> to poll until a new save is detected, then run Fetch Preview.
        </p>
      )}
    </div>
  )
}

// ── CacheRefreshPanel ─────────────────────────────────────────────────────────

interface CacheRefreshPanelProps {
  op: CacheOp | null
  running: boolean
  log: LogEntry[]
}

function CacheRefreshPanel({ op, running, log }: CacheRefreshPanelProps) {
  const logEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [log.length])

  const lastLevel = log[log.length - 1]?.level
  const panelStatus = running ? 'running' : lastLevel === 'error' ? 'error' : 'done'

  return (
    <div className="bg-bg-card border border-border rounded-lg p-4">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div className="flex flex-wrap items-baseline gap-2 min-w-0">
          <span className="font-semibold text-[14px] text-text-base">
            {op ? OP_LABEL[op] : 'Cache Refresh'}
          </span>
          {op && (
            <span className="font-mono text-[11px] text-wp-muted">GET {OP_ENDPOINT[op]}</span>
          )}
        </div>

        {panelStatus === 'running' && (
          <span className="flex items-center gap-1.5 text-[12px] text-[#2563eb] flex-shrink-0">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-3.5 h-3.5 animate-spin">
              <path d="M21 12a9 9 0 1 1-6.219-8.56" />
            </svg>
            Running…
          </span>
        )}
        {panelStatus === 'done' && (
          <span className="flex items-center gap-1.5 text-[12px] text-[#16a34a] flex-shrink-0">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-3.5 h-3.5">
              <polyline points="20 6 9 17 4 12" />
            </svg>
            Done
          </span>
        )}
        {panelStatus === 'error' && (
          <span className="flex items-center gap-1.5 text-[12px] text-[#dc2626] flex-shrink-0">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-3.5 h-3.5">
              <circle cx="12" cy="12" r="10" />
              <line x1="15" y1="9" x2="9" y2="15" />
              <line x1="9" y1="9" x2="15" y2="15" />
            </svg>
            Failed
          </span>
        )}
      </div>

      <div className="bg-bg-base border border-border rounded-lg p-3 max-h-[200px] overflow-y-auto font-mono text-[12px] leading-[1.6]">
        {log.map(entry => (
          <div key={entry.id} className="flex gap-3">
            <span className="text-wp-muted flex-shrink-0 tabular-nums select-none">{entry.ts}</span>
            <span className={LOG_COLOR[entry.level]}>{entry.msg}</span>
          </div>
        ))}
        <div ref={logEndRef} />
      </div>
    </div>
  )
}

// ── PreFetchFilters ───────────────────────────────────────────────────────────

interface PreFetchFiltersProps {
  search: string
  catIds: number[]
  categories: WcCategory[]
  catLoading: boolean
  disabled: boolean
  onSearchChange: (v: string) => void
  onCatToggle: (id: number) => void
  onClearFilters: () => void
}

function PreFetchFilters({ search, catIds, categories, catLoading, disabled, onSearchChange, onCatToggle, onClearFilters }: PreFetchFiltersProps) {
  const topLevel = categories.filter(c => c.parent === 0)
  const byParent: Record<number, WcCategory[]> = {}
  categories.forEach(c => { if (c.parent !== 0) (byParent[c.parent] ??= []).push(c) })

  // Orphaned categories whose parent is not in the list
  const parentIds = new Set(categories.map(c => c.id))
  const orphaned = categories.filter(c => c.parent !== 0 && !parentIds.has(c.parent))

  const hasFilters = search.trim() !== '' || catIds.length > 0

  return (
    <div className="bg-bg-card border border-border rounded-lg p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-md bg-accent/10 flex items-center justify-center flex-shrink-0">
            <svg viewBox="0 0 24 24" fill="none" stroke="#4880FF" strokeWidth="2" className="w-[14px] h-[14px]">
              <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
            </svg>
          </div>
          <span className="font-semibold text-[14px] text-text-base">Pre-Fetch Filters</span>
        </div>
        {hasFilters && (
          <button
            onClick={onClearFilters}
            disabled={disabled}
            className="text-[12px] text-wp-muted hover:text-[#dc2626] transition-colors disabled:opacity-50"
          >
            Clear All
          </button>
        )}
      </div>

      <div className="mb-3">
        <input
          type="text"
          value={search}
          onChange={e => onSearchChange(e.target.value)}
          disabled={disabled}
          placeholder="Search by name or SKU…"
          className="w-full px-3 py-2 text-[13px] border border-border rounded-lg bg-bg-base text-text-base placeholder:text-wp-muted focus:outline-none focus:border-accent disabled:opacity-50"
        />
      </div>

      <div>
        <div className="text-[12px] font-medium text-wp-muted mb-1.5">Categories</div>
        {catLoading ? (
          <div className="text-[12px] text-wp-muted py-2">Loading categories…</div>
        ) : categories.length === 0 ? (
          <div className="text-[12px] text-wp-muted py-2">{catLoading ? '' : 'No categories available'}</div>
        ) : (
          <div className="border border-border rounded-lg max-h-[160px] overflow-y-auto">
            {topLevel.map(cat => (
              <div key={cat.id}>
                <label className={`flex items-center gap-2 px-3 py-1.5 hover:bg-bg-base select-none ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}>
                  <input
                    type="checkbox"
                    checked={catIds.includes(cat.id)}
                    onChange={() => !disabled && onCatToggle(cat.id)}
                    disabled={disabled}
                    className="rounded accent-accent"
                  />
                  <span className="text-[13px] text-text-base">{cat.name}</span>
                </label>
                {(byParent[cat.id] ?? []).map(child => (
                  <label key={child.id} className={`flex items-center gap-2 ps-7 pe-3 py-1.5 hover:bg-bg-base select-none border-t border-border/40 ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}>
                    <input
                      type="checkbox"
                      checked={catIds.includes(child.id)}
                      onChange={() => !disabled && onCatToggle(child.id)}
                      disabled={disabled}
                      className="rounded accent-accent"
                    />
                    <span className="text-[12px] text-text-base">{child.name}</span>
                  </label>
                ))}
              </div>
            ))}
            {orphaned.map(cat => (
              <label key={cat.id} className={`flex items-center gap-2 px-3 py-1.5 hover:bg-bg-base select-none ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}>
                <input
                  type="checkbox"
                  checked={catIds.includes(cat.id)}
                  onChange={() => !disabled && onCatToggle(cat.id)}
                  disabled={disabled}
                  className="rounded accent-accent"
                />
                <span className="text-[13px] text-text-base">{cat.name}</span>
              </label>
            ))}
          </div>
        )}
      </div>

      {catIds.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-2.5">
          {catIds.map(id => {
            const cat = categories.find(c => c.id === id)
            if (!cat) return null
            return (
              <span key={id} className="flex items-center gap-1 px-2 py-0.5 bg-accent/10 text-accent text-[12px] rounded-full">
                {cat.name}
                {!disabled && (
                  <button
                    onClick={() => onCatToggle(id)}
                    className="leading-none hover:text-accent/60 ms-0.5"
                    aria-label={`Remove ${cat.name}`}
                  >
                    ×
                  </button>
                )}
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── PreviewSteps ──────────────────────────────────────────────────────────────

function StepIndicator({ label, status, msg }: { label: string; status: StepStatus; msg: string }) {
  return (
    <div className="flex items-start gap-2 min-w-0">
      <div className="mt-0.5 flex-shrink-0">
        {status === 'running' && (
          <svg viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2.5" className="w-4 h-4 animate-spin">
            <path d="M21 12a9 9 0 1 1-6.219-8.56" />
          </svg>
        )}
        {status === 'done' && (
          <svg viewBox="0 0 24 24" fill="none" stroke="#16a34a" strokeWidth="2.5" className="w-4 h-4">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        )}
        {status === 'error' && (
          <svg viewBox="0 0 24 24" fill="none" stroke="#dc2626" strokeWidth="2.5" className="w-4 h-4">
            <circle cx="12" cy="12" r="10" />
            <line x1="15" y1="9" x2="9" y2="15" />
            <line x1="9" y1="9" x2="15" y2="15" />
          </svg>
        )}
        {status === 'idle' && (
          <span className="block w-4 h-4 rounded-full border-2 border-border" />
        )}
      </div>
      <div className="min-w-0">
        <div className={`text-[13px] font-medium ${status === 'idle' ? 'text-wp-muted' : 'text-text-base'}`}>{label}</div>
        {msg && <div className="text-[11px] text-wp-muted truncate mt-0.5">{msg}</div>}
      </div>
    </div>
  )
}

interface PreviewStepsProps {
  phase: WorkspaceState['previewPhase']
  stepExcel: StepStatus
  stepWC: StepStatus
  stepCalc: StepStatus
  stepExcelMsg: string
  stepWCMsg: string
  stepCalcMsg: string
  previewError: string | null
  onRetry: () => void
}

function PreviewSteps({ phase, stepExcel, stepWC, stepCalc, stepExcelMsg, stepWCMsg, stepCalcMsg, previewError, onRetry }: PreviewStepsProps) {
  return (
    <div className="bg-bg-card border border-border rounded-lg p-4">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <span className="font-semibold text-[14px] text-text-base">Fetch Preview</span>
        {phase === 'streaming' && (
          <span className="flex items-center gap-1.5 text-[12px] text-[#2563eb]">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-3.5 h-3.5 animate-spin">
              <path d="M21 12a9 9 0 1 1-6.219-8.56" />
            </svg>
            Processing…
          </span>
        )}
        {phase === 'ready' && (
          <span className="flex items-center gap-1.5 text-[12px] text-[#16a34a]">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-3.5 h-3.5">
              <polyline points="20 6 9 17 4 12" />
            </svg>
            Ready
          </span>
        )}
        {phase === 'error' && (
          <button
            onClick={onRetry}
            className="flex items-center gap-1.5 text-[12px] text-[#dc2626] border border-[#dc2626] rounded-lg px-2.5 py-1 hover:bg-red-50 transition-colors"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5">
              <polyline points="23 4 23 10 17 10" />
              <polyline points="1 20 1 14 7 14" />
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
            </svg>
            Retry
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StepIndicator label="Excel / Spreadsheet" status={stepExcel} msg={stepExcelMsg} />
        <StepIndicator label="WooCommerce / Cache" status={stepWC} msg={stepWCMsg} />
        <StepIndicator label="Calculate Changes" status={stepCalc} msg={stepCalcMsg} />
      </div>

      {phase === 'error' && previewError && (
        <div className="mt-3 pt-3 border-t border-border text-[12px] text-[#dc2626]">
          {previewError}
        </div>
      )}
    </div>
  )
}

// ── FilterStatsBar ────────────────────────────────────────────────────────────

interface FilterStatsBarProps {
  stats: FilterStats
  summary: PreviewSummary
}

function FilterStatsBar({ stats, summary }: FilterStatsBarProps) {
  return (
    <div className="bg-bg-card border border-border rounded-lg px-4 py-3">
      <div className="flex flex-wrap gap-x-6 gap-y-1.5">
        <span className="text-[13px]">
          <span className="text-wp-muted">Total: </span>
          <span className="font-semibold text-text-base">{summary.total}</span>
        </span>
        <span className="text-[13px]">
          <span className="text-wp-muted">Changed: </span>
          <span className="font-semibold text-[#b45309]">{summary.changed_count}</span>
        </span>
        <span className="text-[13px]">
          <span className="text-wp-muted">New: </span>
          <span className="font-semibold text-[#16a34a]">{summary.new_count}</span>
        </span>
        <span className="text-[13px]">
          <span className="text-wp-muted">Unchanged: </span>
          <span className="font-semibold text-text-base">{summary.unchanged_count}</span>
        </span>
        {summary.invalid_count > 0 && (
          <span className="text-[13px]">
            <span className="text-wp-muted">Invalid: </span>
            <span className="font-semibold text-[#dc2626]">{summary.invalid_count}</span>
          </span>
        )}
        {stats.filter_mode === 'filtered' && (
          <span className="text-[13px]">
            <span className="text-wp-muted">Filtered from </span>
            <span className="font-semibold text-text-base">{stats.sheet_rows_scanned}</span>
            <span className="text-wp-muted"> sheet rows</span>
          </span>
        )}
        <span className="text-[13px]">
          <span className="text-wp-muted">Cache hits: </span>
          <span className="font-semibold text-text-base">{stats.cache_hits}</span>
        </span>
        {stats.wc_lookups > 0 && (
          <span className="text-[13px]">
            <span className="text-wp-muted">WC lookups: </span>
            <span className="font-semibold text-text-base">{stats.wc_lookups}</span>
          </span>
        )}
      </div>
    </div>
  )
}

// ── DuplicateWarningBox ───────────────────────────────────────────────────────

interface DuplicateWarningBoxProps {
  warnings: DupWarning[]
}

function DuplicateWarningBox({ warnings }: DuplicateWarningBoxProps) {
  if (warnings.length === 0) return null
  return (
    <div className="border border-[#f59e0b] rounded-lg p-4 bg-[#fffbeb]">
      <div className="flex items-start gap-3">
        <svg viewBox="0 0 24 24" fill="none" stroke="#b45309" strokeWidth="2" className="w-5 h-5 flex-shrink-0 mt-0.5">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
          <line x1="12" y1="9" x2="12" y2="13" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
        <div className="min-w-0">
          <div className="font-semibold text-[13px] text-[#b45309] mb-1.5">
            {warnings.length} duplicate product ID{warnings.length !== 1 ? 's' : ''} detected — last sheet wins
          </div>
          <div className="space-y-0.5 max-h-[120px] overflow-y-auto">
            {warnings.map((w, i) => (
              <div key={i} className="text-[12px] text-[#92400e]">
                ID {w.product_id}:{' '}
                <span className="font-mono">{w.prev_sheet}</span> ({w.prev_price})
                {' → '}
                <span className="font-mono">{w.final_sheet}</span> ({w.final_price})
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── PreviewTable ──────────────────────────────────────────────────────────────

interface PreviewTableProps {
  rows: PreviewRow[]
  page: number
  selection: Set<number>
  onPageChange: (p: number) => void
  onToggleSelect: (id: number) => void
  onSelectPage: (ids: number[]) => void
  onClearSelection: () => void
}

function PreviewTable({ rows, page, selection, onPageChange, onToggleSelect, onSelectPage, onClearSelection }: PreviewTableProps) {
  const totalPages = Math.max(1, Math.ceil(rows.length / ROWS_PER_PAGE))
  const currentRows = rows.slice(page * ROWS_PER_PAGE, (page + 1) * ROWS_PER_PAGE)
  const currentIds = currentRows.map(r => r.product_id)
  const allPageSelected = currentIds.length > 0 && currentIds.every(id => selection.has(id))

  return (
    <div className="bg-bg-card border border-border rounded-lg overflow-hidden">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-b border-border">
        <div className="flex items-center gap-3">
          <span className="font-semibold text-[14px] text-text-base">Preview</span>
          <span className="text-[13px] text-wp-muted">{rows.length} rows</span>
          {selection.size > 0 && (
            <span className="text-[12px] text-accent font-medium">{selection.size} selected</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {selection.size > 0 && (
            <button
              onClick={onClearSelection}
              className="text-[12px] text-wp-muted hover:text-text-base transition-colors"
            >
              Clear selection
            </button>
          )}
          <button
            onClick={() => allPageSelected ? onClearSelection() : onSelectPage(currentIds)}
            className="px-2.5 py-1 text-[12px] border border-border rounded-lg text-wp-muted hover:text-text-base hover:border-accent transition-colors"
          >
            {allPageSelected ? 'Deselect page' : 'Select page'}
          </button>
          {/* Pagination controls */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => onPageChange(page - 1)}
              disabled={page === 0}
              className="w-7 h-7 flex items-center justify-center rounded border border-border text-wp-muted hover:text-text-base disabled:opacity-40 transition-colors text-[14px]"
            >
              ‹
            </button>
            <span className="text-[12px] text-wp-muted tabular-nums px-1.5">
              {page + 1} / {totalPages}
            </span>
            <button
              onClick={() => onPageChange(page + 1)}
              disabled={page >= totalPages - 1}
              className="w-7 h-7 flex items-center justify-center rounded border border-border text-wp-muted hover:text-text-base disabled:opacity-40 transition-colors text-[14px]"
            >
              ›
            </button>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-[13px] border-collapse">
          <thead>
            <tr className="bg-bg-base">
              <th className="w-10 px-3 py-2.5 border-b border-border text-start">
                <input
                  type="checkbox"
                  checked={allPageSelected}
                  onChange={() => allPageSelected ? onClearSelection() : onSelectPage(currentIds)}
                  className="rounded accent-accent"
                />
              </th>
              <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide w-14">Image</th>
              <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">Product</th>
              <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">Status</th>
              <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">Old Price</th>
              <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">New Price</th>
              <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">Stock</th>
            </tr>
          </thead>
          <tbody>
            {currentRows.map(row => {
              const statusKey = row.change_status ?? (row.changed ? 'changed' : 'unchanged')
              const badge = STATUS_BADGE[statusKey] ?? STATUS_BADGE.unchanged
              const isSelected = selection.has(row.product_id)
              const newPriceColor =
                row.change_status === 'changed' ? 'text-[#b45309] font-semibold' :
                row.change_status === 'new'     ? 'text-[#16a34a] font-semibold' :
                row.change_status === 'invalid' || row.change_status === 'missing_from_wc_cache'
                                                ? 'text-[#dc2626]' :
                'text-text-base'

              return (
                <tr
                  key={row.product_id}
                  onClick={() => onToggleSelect(row.product_id)}
                  className={`border-b border-border cursor-pointer transition-colors ${isSelected ? 'bg-accent/5' : 'hover:bg-bg-base'}`}
                >
                  <td className="px-3 py-2.5" onClick={e => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => onToggleSelect(row.product_id)}
                      className="rounded accent-accent"
                    />
                  </td>
                  <td className="px-3 py-2.5">
                    <img
                      src={`/api/products/${row.product_id}/thumb?size=96`}
                      alt=""
                      loading="lazy"
                      width={40}
                      height={40}
                      className="w-10 h-10 object-cover rounded bg-bg-base"
                      onError={e => { (e.currentTarget as HTMLImageElement).style.visibility = 'hidden' }}
                    />
                  </td>
                  <td className="px-3 py-2.5 max-w-[220px]">
                    <div className="font-medium text-text-base truncate" title={row.product_name}>
                      {row.product_name || `#${row.product_id}`}
                    </div>
                    {row.sku && (
                      <div className="text-[11px] font-mono text-wp-muted">{row.sku}</div>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${badge.cls}`}>
                      {badge.label}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 font-mono text-wp-muted">
                    {row.old_price || '—'}
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={`font-mono ${newPriceColor}`}>
                      {row.new_price || '—'}
                    </span>
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={`text-[12px] ${row.stock_status === 'instock' ? 'text-[#16a34a]' : row.stock_status === 'outofstock' ? 'text-[#dc2626]' : 'text-wp-muted'}`}>
                      {row.stock_status === 'instock' ? 'In Stock' :
                       row.stock_status === 'outofstock' ? 'Out of Stock' :
                       row.stock_status || '—'}
                    </span>
                    {row.stock_quantity != null && (
                      <span className="ms-1 text-[11px] text-wp-muted">({row.stock_quantity})</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Bottom pagination — only rendered when there are multiple pages */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 px-4 py-3 border-t border-border">
          <button
            onClick={() => onPageChange(0)}
            disabled={page === 0}
            className="px-2 py-1 text-[12px] border border-border rounded text-wp-muted hover:text-text-base disabled:opacity-40 transition-colors"
          >
            «
          </button>
          <button
            onClick={() => onPageChange(page - 1)}
            disabled={page === 0}
            className="px-2.5 py-1 text-[12px] border border-border rounded text-wp-muted hover:text-text-base disabled:opacity-40 transition-colors"
          >
            ‹ Prev
          </button>
          <span className="text-[12px] text-wp-muted tabular-nums">
            Page {page + 1} of {totalPages} &middot; {rows.length} rows
          </span>
          <button
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages - 1}
            className="px-2.5 py-1 text-[12px] border border-border rounded text-wp-muted hover:text-text-base disabled:opacity-40 transition-colors"
          >
            Next ›
          </button>
          <button
            onClick={() => onPageChange(totalPages - 1)}
            disabled={page >= totalPages - 1}
            className="px-2 py-1 text-[12px] border border-border rounded text-wp-muted hover:text-text-base disabled:opacity-40 transition-colors"
          >
            »
          </button>
        </div>
      )}
    </div>
  )
}

// ── Workspace ─────────────────────────────────────────────────────────────────

export default function Workspace() {
  const { authFetch, user, status } = useAuth()
  const [state, dispatch] = useReducer(reducer, INITIAL)
  const pollInitialEtagRef = useRef<string | null>(null)

  // ── Cache SSE handlers ─────────────────────────────────────────────────────

  const handleCacheMessage = useCallback((raw: unknown) => {
    const ev = raw as Record<string, unknown>
    const msg = String(ev.msg ?? ev.error ?? '')

    if (ev.status === 'error' || ev.step === 'error' || ev.error) {
      if (msg) dispatch({ type: 'CACHE_LOG', msg, level: 'error' })
      dispatch({ type: 'CACHE_ERROR', message: msg || 'Refresh failed — see server logs.' })
    } else if (ev.step === 'done') {
      if (msg) dispatch({ type: 'CACHE_LOG', msg, level: 'ok' })
      dispatch({ type: 'CACHE_DONE' })
    } else if (msg) {
      const level: LogLevel = ev.status === 'warning' ? 'warn' : 'info'
      dispatch({ type: 'CACHE_LOG', msg, level })
    }
  }, [])

  const handleCacheError = useCallback((reason: SSEErrorReason) => {
    const message =
      reason === 'connection_lost'
        ? 'Connection lost — try the refresh again.'
        : 'Stream data was truncated or corrupted — try the refresh again.'
    dispatch({ type: 'CACHE_ERROR', message })
  }, [])

  useSSEStream(state.cacheSseUrl, handleCacheMessage, handleCacheError)

  // ── Preview SSE handlers ───────────────────────────────────────────────────

  const handlePreviewMessage = useCallback((raw: unknown) => {
    const ev = raw as Record<string, unknown>
    const step = String(ev.step ?? '')
    const sstatus = String(ev.status ?? '')
    const msg = String(ev.msg ?? '')

    if (sstatus === 'error') {
      dispatch({ type: 'PREVIEW_ERROR', message: msg || 'Preview failed.' })
      return
    }

    if (step === 'excel' && sstatus === 'warning' && ev.duplicate_warnings) {
      dispatch({ type: 'PREVIEW_DUP_WARNING', warnings: ev.duplicate_warnings as DupWarning[] })
      return
    }

    if (step === 'excel' || step === 'wc' || step === 'calc') {
      dispatch({ type: 'PREVIEW_STEP', which: step as 'excel' | 'wc' | 'calc', status: sstatus as StepStatus, msg })
      return
    }

    if (step === 'preview' && sstatus === 'done') {
      dispatch({
        type: 'PREVIEW_READY',
        rows: (ev.items as PreviewRow[]) ?? [],
        summary: {
          job_id:               Number(ev.job_id),
          total:                Number(ev.total),
          changed_count:        Number(ev.changed_count),
          unchanged_count:      Number(ev.unchanged_count),
          new_count:            Number(ev.new_count),
          invalid_count:        Number(ev.invalid_count),
          price_changed_count:  Number(ev.price_changed_count),
          stock_changed_count:  Number(ev.stock_changed_count),
          missing_image_count:  Number(ev.missing_image_count),
        },
        filterStats: ev.filter_stats as FilterStats,
        dupWarnings: (ev.duplicate_warnings as DupWarning[]) ?? [],
      })
    }
  }, [])

  const handlePreviewError = useCallback((reason: SSEErrorReason) => {
    const message =
      reason === 'parse_error'
        ? 'Preview data was incomplete — this may be a proxy configuration issue.'
        : 'Preview connection lost.'
    dispatch({ type: 'PREVIEW_ERROR', message })
  }, [])

  useSSEStream(state.previewSseUrl, handlePreviewMessage, handlePreviewError)

  // ── Sheet meta ─────────────────────────────────────────────────────────────

  const checkSheetMeta = useCallback(async () => {
    dispatch({ type: 'SHEET_LOADING' })
    try {
      const r = await authFetch('/api/spreadsheet/meta')
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const meta = (await r.json()) as SheetMeta
      dispatch({ type: 'SHEET_LOADED', meta })
    } catch (e) {
      dispatch({ type: 'SHEET_ERROR', message: e instanceof Error ? e.message : 'Failed to check spreadsheet' })
    }
  }, [authFetch])

  const startPoll = useCallback(() => {
    pollInitialEtagRef.current = state.sheetMeta?.current.etag ?? null
    dispatch({ type: 'SHEET_POLL_START' })
  }, [state.sheetMeta])

  useEffect(() => {
    if (!state.sheetPolling) return
    const initialEtag = pollInitialEtagRef.current
    let remaining = 15 // 15 × 2 s = 30 s max

    const tick = async () => {
      if (remaining <= 0) {
        dispatch({ type: 'SHEET_POLL_STOP' })
        return
      }
      remaining--
      try {
        const r = await authFetch('/api/spreadsheet/meta')
        if (!r.ok) return
        const meta = (await r.json()) as SheetMeta
        dispatch({ type: 'SHEET_LOADED', meta })
        if (meta.current.etag !== initialEtag) dispatch({ type: 'SHEET_POLL_STOP' })
      } catch {
        // ignore individual poll failures
      }
    }

    const id = setInterval(() => { void tick() }, 2000)
    return () => clearInterval(id)
  }, [state.sheetPolling, authFetch])

  // ── Categories (fetch on mount) ────────────────────────────────────────────

  useEffect(() => {
    dispatch({ type: 'CAT_LOADING' })
    authFetch('/api/categories')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() as Promise<WcCategory[]> })
      .then(cats => dispatch({ type: 'CAT_LOADED', categories: cats }))
      .catch((e: unknown) => dispatch({ type: 'CAT_ERROR', message: String(e) }))
  }, [authFetch])

  // ── Cache refresh trigger ──────────────────────────────────────────────────

  const startCacheRefresh = useCallback((op: CacheOp) => {
    if (state.cacheRunning) return
    dispatch({ type: 'CACHE_START', op, url: buildSseUrl(OP_ENDPOINT[op]) })
  }, [state.cacheRunning])

  // ── Preview fetch trigger ──────────────────────────────────────────────────

  const startPreviewFetch = useCallback(() => {
    if (state.previewPhase === 'streaming') return
    dispatch({ type: 'PREVIEW_START', url: buildPreviewSseUrl(state.filterSearch, state.filterCatIds) })
  }, [state.previewPhase, state.filterSearch, state.filterCatIds])

  // ── Auth gate (after all hooks) ────────────────────────────────────────────

  if (status !== 'authenticated') return <AccessState status={status} />

  const canFetch = user?.is_admin === true || user?.permissions?.can_fetch === true
  const isAdmin = user?.is_admin === true

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="p-6 space-y-4">

      {/* Page header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-text-base">Workspace</h1>
          <p className="text-[13px] text-wp-muted mt-0.5">Fetch, review, and apply price updates</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {canFetch && (
            <>
              <button
                onClick={() => startCacheRefresh('light')}
                disabled={state.cacheRunning}
                title="Fetch only products modified since the last full sync (GET /api/fetch/light)"
                className="px-3 py-1.5 text-[13px] border border-border rounded-lg text-wp-muted hover:text-text-base hover:border-accent transition-colors disabled:opacity-50"
              >
                Light Refresh
              </button>

              <button
                onClick={() => startCacheRefresh('full')}
                disabled={state.cacheRunning}
                title="Fetch all top-level products + images from WooCommerce (GET /api/fetch/full)"
                className="flex items-center gap-2 px-3 py-1.5 text-[13px] border border-border rounded-lg text-wp-muted hover:text-text-base hover:border-accent transition-colors disabled:opacity-50"
              >
                <svg
                  viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                  className={`w-3.5 h-3.5 ${state.cacheRunning && state.cacheOp === 'full' ? 'animate-spin' : ''}`}
                >
                  <polyline points="23 4 23 10 17 10" />
                  <polyline points="1 20 1 14 7 14" />
                  <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
                </svg>
                Full Refresh
              </button>
            </>
          )}

          {isAdmin && (
            <button
              onClick={() => startCacheRefresh('deep')}
              disabled={state.cacheRunning}
              title="Sync ALL variations for ALL variable parents — may take 40–60 min (GET /api/fetch/deep-variations)"
              className="px-3 py-1.5 text-[13px] border border-[#f59e0b] text-[#b45309] rounded-lg hover:bg-[#fef3c7] transition-colors disabled:opacity-50"
            >
              ● Deep Sync
            </button>
          )}

          {canFetch && (
            <button
              onClick={startPreviewFetch}
              disabled={state.cacheRunning || state.previewPhase === 'streaming'}
              title="Run preview: download spreadsheet, compare with WooCommerce cache, calculate changes"
              className="flex items-center gap-2 px-4 py-1.5 text-[13px] bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors disabled:opacity-50"
            >
              {state.previewPhase === 'streaming' && (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-3.5 h-3.5 animate-spin">
                  <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                </svg>
              )}
              Fetch Preview →
            </button>
          )}
        </div>
      </div>

      {/* Spreadsheet status card */}
      <SpreadsheetStatus
        loading={state.sheetLoading}
        meta={state.sheetMeta}
        error={state.sheetError}
        polling={state.sheetPolling}
        onCheck={() => { void checkSheetMeta() }}
        onStartPoll={startPoll}
        onStopPoll={() => dispatch({ type: 'SHEET_POLL_STOP' })}
        canFetch={canFetch}
      />

      {/* Pre-fetch filters */}
      {canFetch && (
        <PreFetchFilters
          search={state.filterSearch}
          catIds={state.filterCatIds}
          categories={state.categories}
          catLoading={state.catLoading}
          disabled={state.previewPhase === 'streaming'}
          onSearchChange={v => dispatch({ type: 'FILTER_SEARCH', value: v })}
          onCatToggle={id => dispatch({ type: 'FILTER_CAT_TOGGLE', id })}
          onClearFilters={() => dispatch({ type: 'FILTER_CLEAR' })}
        />
      )}

      {/* Preview progress steps */}
      {state.previewPhase !== 'idle' && (
        <PreviewSteps
          phase={state.previewPhase}
          stepExcel={state.stepExcel}
          stepWC={state.stepWC}
          stepCalc={state.stepCalc}
          stepExcelMsg={state.stepExcelMsg}
          stepWCMsg={state.stepWCMsg}
          stepCalcMsg={state.stepCalcMsg}
          previewError={state.previewError}
          onRetry={startPreviewFetch}
        />
      )}

      {/* Filter stats bar */}
      {state.previewPhase === 'ready' && state.filterStats && state.previewSummary && (
        <FilterStatsBar stats={state.filterStats} summary={state.previewSummary} />
      )}

      {/* Duplicate product warnings */}
      {state.duplicateWarnings.length > 0 && state.previewPhase !== 'idle' && (
        <DuplicateWarningBox warnings={state.duplicateWarnings} />
      )}

      {/* Preview table — read-only, 50/page */}
      {state.previewPhase === 'ready' && state.previewRows.length > 0 && (
        <PreviewTable
          rows={state.previewRows}
          page={state.previewPage}
          selection={state.previewSelection}
          onPageChange={p => dispatch({ type: 'PREVIEW_PAGE', page: p })}
          onToggleSelect={id => dispatch({ type: 'PREVIEW_TOGGLE', id })}
          onSelectPage={ids => dispatch({ type: 'PREVIEW_SELECT_PAGE', ids })}
          onClearSelection={() => dispatch({ type: 'PREVIEW_CLEAR_SELECTION' })}
        />
      )}

      {/* Cache refresh log — persists until user starts a new operation */}
      {state.cacheLog.length > 0 && (
        <CacheRefreshPanel
          op={state.cacheOp}
          running={state.cacheRunning}
          log={state.cacheLog}
        />
      )}

    </div>
  )
}
