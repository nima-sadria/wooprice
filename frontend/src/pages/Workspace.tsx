import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { AccessState, useAuth } from '../auth'
import { useSSEStream, type SSEErrorReason } from '../hooks/useSSEStream'
import { fmtPrice } from '../utils/price'

// ── Types ─────────────────────────────────────────────────────────────────────

type CacheOp = 'full' | 'light' | 'deep'
type LogLevel = 'info' | 'ok' | 'warn' | 'error'
type StepStatus = 'idle' | 'running' | 'done' | 'error'

interface LogEntry { id: number; ts: string; msg: string; level: LogLevel }

interface SheetMeta {
  current: { etag: string | null; last_modified: string | null; content_length: number | null; checked_at: string }
  cached: Record<string, unknown> | null
  is_fresh: boolean
}

interface PreviewRow {
  product_id: number; product_name: string; sku: string
  old_price: string; new_price: string; sale_price: string
  stock_status: string; stock_quantity: number | null
  categories: Array<{ id: number; name: string }>
  parent_id: number; row_color: string | null
  last_price_updated: string | null; wc_date_modified: string | null
  changed: boolean; found_in_wc: boolean
  change_status?: string; price_changed?: boolean; stock_changed?: boolean
}

interface PreviewSummary {
  job_id: number; total: number; changed_count: number; unchanged_count: number
  new_count: number; invalid_count: number; price_changed_count: number
  stock_changed_count: number; missing_image_count: number
}

interface FilterStats {
  filter_mode: string; sheet_rows_scanned: number; rows_matched: number
  rows_skipped: number; rows_no_cache: number; wc_lookups: number; cache_hits: number
}

interface DupWarning {
  product_id: number; prev_sheet: string; final_sheet: string; prev_price: string; final_price: string
}

interface WcCategory { id: number; name: string; parent: number }

// WS-C types
interface DryRunError { type: string; product_id: number; name: string; value?: string }
interface DryRunWarning { type: string; product_id?: number; name?: string; value?: string; change?: string }

interface DryRunResult {
  job_id: number
  dry_run_scope: number[]
  dry_run_status: 'passed' | 'passed_with_warnings' | 'blocked'
  products_to_update: number
  critical_errors: DryRunError[]
  warnings: DryRunWarning[]
  validation?: Array<{ level: string; rule: string; product_id?: number; message?: string }>
}

interface ApplyItemEvent {
  product_id: number; product_name: string; sku: string
  status: string; old_price: string; new_price: string; error: string
  completed: number; total: number; percentage: number
}

interface ApplyDoneEvent { job_id: number; updated: number; failed: number; skipped: number }

// ── Constants ─────────────────────────────────────────────────────────────────

const OP_LABEL: Record<CacheOp, string> = {
  full: 'Full Product Cache Refresh', light: 'Light Cache Refresh', deep: 'Deep Variation Sync',
}
const OP_ENDPOINT: Record<CacheOp, string> = {
  full: '/api/fetch/full', light: '/api/fetch/light', deep: '/api/fetch/deep-variations',
}
const LOG_COLOR: Record<LogLevel, string> = {
  info: 'text-wp-muted', ok: 'text-[#16a34a]', warn: 'text-[#b45309]', error: 'text-[#dc2626]',
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
  cacheOp: CacheOp | null; cacheRunning: boolean; cacheSseUrl: string | null
  cacheLog: LogEntry[]; _logSeq: number
  // Sheet meta
  sheetLoading: boolean; sheetMeta: SheetMeta | null; sheetError: string | null; sheetPolling: boolean
  // Preview stream
  previewPhase: 'idle' | 'streaming' | 'ready' | 'error'
  previewSseUrl: string | null; previewError: string | null
  stepExcel: StepStatus; stepWC: StepStatus; stepCalc: StepStatus
  stepExcelMsg: string; stepWCMsg: string; stepCalcMsg: string
  // Preview data
  previewRows: PreviewRow[]; previewSummary: PreviewSummary | null
  filterStats: FilterStats | null; duplicateWarnings: DupWarning[]
  // Pagination + selection
  previewPage: number; previewSelection: Set<number>
  // Filters + categories
  filterSearch: string; filterCatIds: number[]
  categories: WcCategory[]; catLoading: boolean; catError: string | null
  // WS-C: Dry Run
  dryRunPhase: 'idle' | 'running' | 'done' | 'failed'
  dryRunError: string | null; dryRunResult: DryRunResult | null; dryRunInvalidated: boolean
  // WS-C: Apply
  applyPhase: 'idle' | 'streaming' | 'done' | 'error'
  applySseUrl: string | null; applyError: string | null; applyStalePreview: boolean
  applyTotal: number; applyCompleted: number; applyItems: ApplyItemEvent[]; applyDone: ApplyDoneEvent | null
  // WS-C: Writeback
  writebackPhase: 'idle' | 'pending' | 'done' | 'error'; writebackMsg: string
  // WS-C: Cancel job
  cancelPhase: 'idle' | 'pending' | 'done' | 'error'; jobCancelled: boolean
  // WS-C: Page-level rollback advisory
  rollbackAdvisory: boolean
}

const INITIAL: WorkspaceState = {
  cacheOp: null, cacheRunning: false, cacheSseUrl: null, cacheLog: [], _logSeq: 0,
  sheetLoading: false, sheetMeta: null, sheetError: null, sheetPolling: false,
  previewPhase: 'idle', previewSseUrl: null, previewError: null,
  stepExcel: 'idle', stepWC: 'idle', stepCalc: 'idle',
  stepExcelMsg: '', stepWCMsg: '', stepCalcMsg: '',
  previewRows: [], previewSummary: null, filterStats: null, duplicateWarnings: [],
  previewPage: 0, previewSelection: new Set(),
  filterSearch: '', filterCatIds: [],
  categories: [], catLoading: false, catError: null,
  dryRunPhase: 'idle', dryRunError: null, dryRunResult: null, dryRunInvalidated: false,
  applyPhase: 'idle', applySseUrl: null, applyError: null, applyStalePreview: false,
  applyTotal: 0, applyCompleted: 0, applyItems: [], applyDone: null,
  writebackPhase: 'idle', writebackMsg: '',
  cancelPhase: 'idle', jobCancelled: false,
  rollbackAdvisory: false,
}

// ── Actions ───────────────────────────────────────────────────────────────────

type Action =
  | { type: 'CACHE_START'; op: CacheOp; url: string }
  | { type: 'CACHE_LOG'; msg: string; level: LogLevel }
  | { type: 'CACHE_DONE' }
  | { type: 'CACHE_ERROR'; message: string }
  | { type: 'SHEET_LOADING' }
  | { type: 'SHEET_LOADED'; meta: SheetMeta }
  | { type: 'SHEET_ERROR'; message: string }
  | { type: 'SHEET_POLL_START' }
  | { type: 'SHEET_POLL_STOP' }
  | { type: 'PREVIEW_START'; url: string }
  | { type: 'PREVIEW_STEP'; which: 'excel' | 'wc' | 'calc'; status: StepStatus; msg: string }
  | { type: 'PREVIEW_DUP_WARNING'; warnings: DupWarning[] }
  | { type: 'PREVIEW_READY'; rows: PreviewRow[]; summary: PreviewSummary; filterStats: FilterStats; dupWarnings: DupWarning[] }
  | { type: 'PREVIEW_ERROR'; message: string }
  | { type: 'PREVIEW_PAGE'; page: number }
  | { type: 'PREVIEW_TOGGLE'; id: number }
  | { type: 'PREVIEW_SELECT_PAGE'; ids: number[] }
  | { type: 'PREVIEW_DESELECT_PAGE'; ids: number[] }
  | { type: 'PREVIEW_CLEAR_SELECTION' }
  | { type: 'FILTER_SEARCH'; value: string }
  | { type: 'FILTER_CAT_TOGGLE'; id: number }
  | { type: 'FILTER_CLEAR' }
  | { type: 'CAT_LOADING' }
  | { type: 'CAT_LOADED'; categories: WcCategory[] }
  | { type: 'CAT_ERROR'; message: string }
  // WS-C
  | { type: 'DRY_RUN_START' }
  | { type: 'DRY_RUN_DONE'; result: DryRunResult }
  | { type: 'DRY_RUN_FAILED'; message: string }
  | { type: 'DRY_RUN_INVALIDATE' }
  | { type: 'DRY_RUN_CLEARED_BY_SERVER' }
  | { type: 'APPLY_START'; url: string }
  | { type: 'APPLY_META'; total: number }
  | { type: 'APPLY_ITEM'; item: ApplyItemEvent }
  | { type: 'APPLY_DONE'; done: ApplyDoneEvent }
  | { type: 'APPLY_ERROR'; message: string; stalePreview?: boolean }
  | { type: 'WRITEBACK_START' }
  | { type: 'WRITEBACK_DONE'; message: string }
  | { type: 'WRITEBACK_ERROR'; message: string }
  | { type: 'CANCEL_START' }
  | { type: 'CANCEL_DONE' }
  | { type: 'CANCEL_ERROR'; message: string }
  | { type: 'ROW_PATCH'; pid: number; patch: Partial<PreviewRow> }
  | { type: 'ROLLBACK_ADVISORY' }

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
function buildApplySseUrl(jobId: number, scope: number[]): string {
  const token = localStorage.getItem('wp_token') ?? ''
  let url = `/api/sync/${jobId}/apply-stream?token=${encodeURIComponent(token)}`
  scope.forEach(id => { url += `&sid=${id}` })
  return url
}
function fmtLastModified(s: string | null | undefined): string {
  if (!s) return '—'
  try {
    return new Date(s).toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch { return s }
}

// ── Reducer helper ────────────────────────────────────────────────────────────

// Returns s with dryRunInvalidated=true only when a dry run has completed
function invalidateDryRun(s: WorkspaceState): WorkspaceState {
  return s.dryRunPhase === 'done' ? { ...s, dryRunInvalidated: true } : s
}

// WS-C state reset used when a new preview fetch starts
const WS_C_RESET: Partial<WorkspaceState> = {
  dryRunPhase: 'idle', dryRunError: null, dryRunResult: null, dryRunInvalidated: false,
  applyPhase: 'idle', applySseUrl: null, applyError: null, applyStalePreview: false,
  applyTotal: 0, applyCompleted: 0, applyItems: [], applyDone: null,
  writebackPhase: 'idle', writebackMsg: '',
  cancelPhase: 'idle', jobCancelled: false,
  rollbackAdvisory: false,
}

// ── Reducer ───────────────────────────────────────────────────────────────────

function reducer(s: WorkspaceState, a: Action): WorkspaceState {
  switch (a.type) {
    case 'CACHE_START':
      return { ...s, cacheOp: a.op, cacheRunning: true, cacheSseUrl: a.url,
        cacheLog: [{ id: 0, ts: nowTime(), msg: OP_LABEL[a.op] + ' started…', level: 'info' }], _logSeq: 1 }
    case 'CACHE_LOG': {
      const entry: LogEntry = { id: s._logSeq, ts: nowTime(), msg: a.msg, level: a.level }
      return { ...s, cacheLog: [...s.cacheLog, entry], _logSeq: s._logSeq + 1 }
    }
    case 'CACHE_DONE':
      return { ...s, cacheRunning: false, cacheSseUrl: null }
    case 'CACHE_ERROR': {
      if (!s.cacheRunning) return s
      const e: LogEntry = { id: s._logSeq, ts: nowTime(), msg: a.message, level: 'error' }
      return { ...s, cacheRunning: false, cacheSseUrl: null, cacheLog: [...s.cacheLog, e], _logSeq: s._logSeq + 1 }
    }
    case 'SHEET_LOADING':
      return { ...s, sheetLoading: true, sheetError: null }
    case 'SHEET_LOADED':
      return { ...s, sheetLoading: false, sheetMeta: a.meta, sheetError: null }
    case 'SHEET_ERROR':
      return { ...s, sheetLoading: false, sheetMeta: null, sheetError: a.message }
    case 'SHEET_POLL_START':
      return { ...s, sheetPolling: true }
    case 'SHEET_POLL_STOP':
      return { ...s, sheetPolling: false }

    case 'PREVIEW_START':
      return {
        ...s, ...WS_C_RESET,
        previewPhase: 'streaming', previewSseUrl: a.url, previewError: null,
        stepExcel: 'idle', stepWC: 'idle', stepCalc: 'idle',
        stepExcelMsg: '', stepWCMsg: '', stepCalcMsg: '',
        previewRows: [], previewSummary: null, filterStats: null,
        duplicateWarnings: [], previewPage: 0, previewSelection: new Set(),
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
        ...s, previewPhase: 'ready',
        previewSseUrl: null,
        stepExcel: 'done', stepWC: 'done', stepCalc: 'done',
        previewRows: a.rows, previewSummary: a.summary,
        filterStats: a.filterStats, duplicateWarnings: a.dupWarnings,
      }
    case 'PREVIEW_ERROR':
      if (s.previewPhase === 'ready') return s
      return { ...s, previewPhase: 'error', previewSseUrl: null, previewError: a.message }

    case 'PREVIEW_PAGE':
      return { ...s, previewPage: a.page }
    case 'PREVIEW_TOGGLE': {
      const next = new Set(s.previewSelection)
      if (next.has(a.id)) next.delete(a.id); else next.add(a.id)
      return invalidateDryRun({ ...s, previewSelection: next })
    }
    case 'PREVIEW_SELECT_PAGE': {
      const next = new Set(s.previewSelection)
      a.ids.forEach(id => next.add(id))
      return invalidateDryRun({ ...s, previewSelection: next })
    }
    case 'PREVIEW_DESELECT_PAGE': {
      const next = new Set(s.previewSelection)
      a.ids.forEach(id => next.delete(id))
      return invalidateDryRun({ ...s, previewSelection: next })
    }
    case 'PREVIEW_CLEAR_SELECTION':
      return invalidateDryRun({ ...s, previewSelection: new Set() })

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

    // WS-C: Dry Run
    case 'DRY_RUN_START':
      return { ...s, dryRunPhase: 'running', dryRunError: null, dryRunResult: null, dryRunInvalidated: false }
    case 'DRY_RUN_DONE':
      return { ...s, dryRunPhase: 'done', dryRunResult: a.result, dryRunInvalidated: false }
    case 'DRY_RUN_FAILED':
      return { ...s, dryRunPhase: 'failed', dryRunError: a.message }
    case 'DRY_RUN_INVALIDATE':
      return { ...s, dryRunInvalidated: true }
    case 'DRY_RUN_CLEARED_BY_SERVER':
      return { ...s, dryRunPhase: 'idle', dryRunResult: null, dryRunInvalidated: false }

    // WS-C: Apply
    case 'APPLY_START':
      return { ...s, applyPhase: 'streaming', applySseUrl: a.url, applyError: null,
        applyStalePreview: false, applyTotal: 0, applyCompleted: 0, applyItems: [], applyDone: null }
    case 'APPLY_META':
      return { ...s, applyTotal: a.total }
    case 'APPLY_ITEM':
      return { ...s, applyItems: [...s.applyItems, a.item], applyTotal: a.item.total, applyCompleted: a.item.completed }
    case 'APPLY_DONE':
      return { ...s, applyPhase: 'done', applySseUrl: null, applyDone: a.done }
    case 'APPLY_ERROR':
      if (s.applyPhase === 'done' || s.applyPhase === 'error') return s
      return { ...s, applyPhase: 'error', applySseUrl: null, applyError: a.message, applyStalePreview: a.stalePreview === true }

    // WS-C: Writeback
    case 'WRITEBACK_START':
      return { ...s, writebackPhase: 'pending', writebackMsg: '' }
    case 'WRITEBACK_DONE':
      return { ...s, writebackPhase: 'done', writebackMsg: a.message }
    case 'WRITEBACK_ERROR':
      return { ...s, writebackPhase: 'error', writebackMsg: a.message }

    // WS-C: Cancel
    case 'CANCEL_START':
      return { ...s, cancelPhase: 'pending' }
    case 'CANCEL_DONE':
      return { ...s, cancelPhase: 'done', jobCancelled: true }
    case 'CANCEL_ERROR':
      return { ...s, cancelPhase: 'error', writebackMsg: a.message }

    // WS-C: Row patch
    case 'ROW_PATCH':
      return { ...s, previewRows: s.previewRows.map(r => r.product_id === a.pid ? { ...r, ...a.patch } : r) }

    // WS-C: Rollback advisory
    case 'ROLLBACK_ADVISORY':
      return { ...s, rollbackAdvisory: true }

    default:
      return s
  }
}

// ── SpreadsheetStatus ─────────────────────────────────────────────────────────

interface SpreadsheetStatusProps {
  loading: boolean; meta: SheetMeta | null; error: string | null
  polling: boolean; canFetch: boolean
  onCheck: () => void; onStartPoll: () => void; onStopPoll: () => void
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
              <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
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
                {etag && <span className="text-[11px] font-mono text-wp-muted">ETag: {etag}…</span>}
                {meta.current.last_modified && <span className="text-[11px] text-wp-muted">{fmtLastModified(meta.current.last_modified)}</span>}
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
            <button onClick={onCheck} disabled={loading || polling}
              className="px-3 py-1.5 text-[12px] border border-border rounded-lg text-wp-muted hover:text-text-base hover:border-accent transition-colors disabled:opacity-50">
              {loading ? 'Checking…' : 'Check freshness'}
            </button>
            {meta && !polling && (
              <button onClick={onStartPoll} title="Poll every 2 s for up to 30 s"
                className="px-3 py-1.5 text-[12px] border border-border rounded-lg text-wp-muted hover:text-text-base hover:border-accent transition-colors">
                Wait for update
              </button>
            )}
            {polling && (
              <button onClick={onStopPoll}
                className="px-3 py-1.5 text-[12px] border border-[#f59e0b] text-[#b45309] rounded-lg hover:bg-[#fef3c7] transition-colors">
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
          Use <em>Wait for update</em> to poll until a new save is detected, then run Fetch Preview.
        </p>
      )}
    </div>
  )
}

// ── CacheRefreshPanel ─────────────────────────────────────────────────────────

interface CacheRefreshPanelProps { op: CacheOp | null; running: boolean; log: LogEntry[] }
function CacheRefreshPanel({ op, running, log }: CacheRefreshPanelProps) {
  const logEndRef = useRef<HTMLDivElement>(null)
  useEffect(() => { logEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [log.length])
  const lastLevel = log[log.length - 1]?.level
  const panelStatus = running ? 'running' : lastLevel === 'error' ? 'error' : 'done'
  return (
    <div className="bg-bg-card border border-border rounded-lg p-4">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div className="flex flex-wrap items-baseline gap-2 min-w-0">
          <span className="font-semibold text-[14px] text-text-base">{op ? OP_LABEL[op] : 'Cache Refresh'}</span>
          {op && <span className="font-mono text-[11px] text-wp-muted">GET {OP_ENDPOINT[op]}</span>}
        </div>
        {panelStatus === 'running' && (
          <span className="flex items-center gap-1.5 text-[12px] text-[#2563eb] flex-shrink-0">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-3.5 h-3.5 animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
            Running…
          </span>
        )}
        {panelStatus === 'done' && (
          <span className="flex items-center gap-1.5 text-[12px] text-[#16a34a] flex-shrink-0">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-3.5 h-3.5"><polyline points="20 6 9 17 4 12" /></svg>
            Done
          </span>
        )}
        {panelStatus === 'error' && (
          <span className="flex items-center gap-1.5 text-[12px] text-[#dc2626] flex-shrink-0">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-3.5 h-3.5"><circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" /></svg>
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
  search: string; catIds: number[]; categories: WcCategory[]
  catLoading: boolean; catError: string | null; disabled: boolean
  onSearchChange: (v: string) => void; onCatToggle: (id: number) => void; onClearFilters: () => void
}
function PreFetchFilters({ search, catIds, categories, catLoading, catError, disabled, onSearchChange, onCatToggle, onClearFilters }: PreFetchFiltersProps) {
  const topLevel = categories.filter(c => c.parent === 0)
  const byParent: Record<number, WcCategory[]> = {}
  categories.forEach(c => { if (c.parent !== 0) (byParent[c.parent] ??= []).push(c) })
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
          <button onClick={onClearFilters} disabled={disabled}
            className="text-[12px] text-wp-muted hover:text-[#dc2626] transition-colors disabled:opacity-50">
            Clear All
          </button>
        )}
      </div>
      <div className="mb-3">
        <input type="text" value={search} onChange={e => onSearchChange(e.target.value)}
          disabled={disabled} placeholder="Search by name or SKU…"
          className="w-full px-3 py-2 text-[13px] border border-border rounded-lg bg-bg-base text-text-base placeholder:text-wp-muted focus:outline-none focus:border-accent disabled:opacity-50" />
      </div>
      <div>
        <div className="text-[12px] font-medium text-wp-muted mb-1.5">Categories</div>
        {catLoading ? (
          <div className="text-[12px] text-wp-muted py-2">Loading categories…</div>
        ) : catError ? (
          <div className="text-[12px] text-[#dc2626] py-2">Failed to load categories: {catError}</div>
        ) : categories.length === 0 ? (
          <div className="text-[12px] text-wp-muted py-2">No categories available</div>
        ) : (
          <div className="border border-border rounded-lg max-h-[160px] overflow-y-auto">
            {topLevel.map(cat => (
              <div key={cat.id}>
                <label className={`flex items-center gap-2 px-3 py-1.5 hover:bg-bg-base select-none ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}>
                  <input type="checkbox" checked={catIds.includes(cat.id)} onChange={() => !disabled && onCatToggle(cat.id)}
                    disabled={disabled} className="rounded accent-accent" />
                  <span className="text-[13px] text-text-base">{cat.name}</span>
                </label>
                {(byParent[cat.id] ?? []).map(child => (
                  <label key={child.id} className={`flex items-center gap-2 ps-7 pe-3 py-1.5 hover:bg-bg-base select-none border-t border-border/40 ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}>
                    <input type="checkbox" checked={catIds.includes(child.id)} onChange={() => !disabled && onCatToggle(child.id)}
                      disabled={disabled} className="rounded accent-accent" />
                    <span className="text-[12px] text-text-base">{child.name}</span>
                  </label>
                ))}
              </div>
            ))}
            {orphaned.map(cat => (
              <label key={cat.id} className={`flex items-center gap-2 px-3 py-1.5 hover:bg-bg-base select-none ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}>
                <input type="checkbox" checked={catIds.includes(cat.id)} onChange={() => !disabled && onCatToggle(cat.id)}
                  disabled={disabled} className="rounded accent-accent" />
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
                  <button onClick={() => onCatToggle(id)} className="leading-none hover:text-accent/60 ms-0.5" aria-label={`Remove ${cat.name}`}>×</button>
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
        {status === 'running' && <svg viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2.5" className="w-4 h-4 animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>}
        {status === 'done' && <svg viewBox="0 0 24 24" fill="none" stroke="#16a34a" strokeWidth="2.5" className="w-4 h-4"><polyline points="20 6 9 17 4 12" /></svg>}
        {status === 'error' && <svg viewBox="0 0 24 24" fill="none" stroke="#dc2626" strokeWidth="2.5" className="w-4 h-4"><circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" /></svg>}
        {status === 'idle' && <span className="block w-4 h-4 rounded-full border-2 border-border" />}
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
  stepExcel: StepStatus; stepWC: StepStatus; stepCalc: StepStatus
  stepExcelMsg: string; stepWCMsg: string; stepCalcMsg: string
  previewError: string | null; onRetry: () => void
}
function PreviewSteps({ phase, stepExcel, stepWC, stepCalc, stepExcelMsg, stepWCMsg, stepCalcMsg, previewError, onRetry }: PreviewStepsProps) {
  return (
    <div className="bg-bg-card border border-border rounded-lg p-4">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <span className="font-semibold text-[14px] text-text-base">Fetch Preview</span>
        {phase === 'streaming' && (
          <span className="flex items-center gap-1.5 text-[12px] text-[#2563eb]">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-3.5 h-3.5 animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
            Processing…
          </span>
        )}
        {phase === 'ready' && (
          <span className="flex items-center gap-1.5 text-[12px] text-[#16a34a]">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-3.5 h-3.5"><polyline points="20 6 9 17 4 12" /></svg>
            Ready
          </span>
        )}
        {phase === 'error' && (
          <button onClick={onRetry} className="flex items-center gap-1.5 text-[12px] text-[#dc2626] border border-[#dc2626] rounded-lg px-2.5 py-1 hover:bg-red-50 transition-colors">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5"><polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" /><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" /></svg>
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
        <div className="mt-3 pt-3 border-t border-border text-[12px] text-[#dc2626]">{previewError}</div>
      )}
    </div>
  )
}

// ── FilterStatsBar ────────────────────────────────────────────────────────────

function FilterStatsBar({ stats, summary }: { stats: FilterStats; summary: PreviewSummary }) {
  return (
    <div className="bg-bg-card border border-border rounded-lg px-4 py-3">
      <div className="flex flex-wrap gap-x-6 gap-y-1.5">
        <span className="text-[13px]"><span className="text-wp-muted">Total: </span><span className="font-semibold text-text-base">{summary.total}</span></span>
        <span className="text-[13px]"><span className="text-wp-muted">Changed: </span><span className="font-semibold text-[#b45309]">{summary.changed_count}</span></span>
        <span className="text-[13px]"><span className="text-wp-muted">New: </span><span className="font-semibold text-[#16a34a]">{summary.new_count}</span></span>
        <span className="text-[13px]"><span className="text-wp-muted">Unchanged: </span><span className="font-semibold text-text-base">{summary.unchanged_count}</span></span>
        {summary.invalid_count > 0 && (
          <span className="text-[13px]"><span className="text-wp-muted">Invalid: </span><span className="font-semibold text-[#dc2626]">{summary.invalid_count}</span></span>
        )}
        {stats.filter_mode === 'filtered' && (
          <span className="text-[13px]"><span className="text-wp-muted">Filtered from </span><span className="font-semibold text-text-base">{stats.sheet_rows_scanned}</span><span className="text-wp-muted"> sheet rows</span></span>
        )}
        <span className="text-[13px]"><span className="text-wp-muted">Cache hits: </span><span className="font-semibold text-text-base">{stats.cache_hits}</span></span>
        {stats.wc_lookups > 0 && (
          <span className="text-[13px]"><span className="text-wp-muted">WC lookups: </span><span className="font-semibold text-text-base">{stats.wc_lookups}</span></span>
        )}
      </div>
    </div>
  )
}

// ── DuplicateWarningBox ───────────────────────────────────────────────────────

function DuplicateWarningBox({ warnings }: { warnings: DupWarning[] }) {
  if (warnings.length === 0) return null
  return (
    <div className="border border-[#f59e0b] rounded-lg p-4 bg-[#fffbeb]">
      <div className="flex items-start gap-3">
        <svg viewBox="0 0 24 24" fill="none" stroke="#b45309" strokeWidth="2" className="w-5 h-5 flex-shrink-0 mt-0.5">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
          <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
        <div className="min-w-0">
          <div className="font-semibold text-[13px] text-[#b45309] mb-1.5">
            {warnings.length} duplicate product ID{warnings.length !== 1 ? 's' : ''} detected — last sheet wins
          </div>
          <div className="space-y-0.5 max-h-[120px] overflow-y-auto">
            {warnings.map((w, i) => (
              <div key={i} className="text-[12px] text-[#92400e]">
                ID {w.product_id}: <span className="font-mono">{w.prev_sheet}</span> ({w.prev_price}){' → '}
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
  canEditPrice: boolean
  canEditStock: boolean
  canRollback: boolean
  editsDisabled: boolean
  onPageChange: (p: number) => void
  onToggleSelect: (id: number) => void
  onSelectPage: (ids: number[]) => void
  onDeselectPage: (ids: number[]) => void
  onClearSelection: () => void
  onSavePrice: (pid: number, parentId: number, newPrice: string) => Promise<void>
  onSaveStock: (pid: number, parentId: number, stockStatus: string, qty: number | null) => Promise<void>
  onRollback: (pid: number) => Promise<void>
}

function PreviewTable({
  rows, page, selection, canEditPrice, canEditStock, canRollback, editsDisabled,
  onPageChange, onToggleSelect, onSelectPage, onDeselectPage, onClearSelection,
  onSavePrice, onSaveStock, onRollback,
}: PreviewTableProps) {
  const totalPages = Math.max(1, Math.ceil(rows.length / ROWS_PER_PAGE))
  const currentRows = rows.slice(page * ROWS_PER_PAGE, (page + 1) * ROWS_PER_PAGE)
  const currentIds = currentRows.map(r => r.product_id)
  const allPageSelected = currentIds.length > 0 && currentIds.every(id => selection.has(id))

  // Local inline-edit state
  type ActiveEdit = { pid: number; field: 'price' | 'stock'; value: string; stockQty: string }
  const [activeEdit, setActiveEdit] = useState<ActiveEdit | null>(null)
  const [saving, setSaving] = useState<Record<number, boolean>>({})
  const [saveError, setSaveError] = useState<Record<number, string>>({})
  const [saveDone, setSaveDone] = useState<Record<number, boolean>>({})

  // Local rollback state
  const [rbPending, setRbPending] = useState<Record<number, boolean>>({})
  const [rbDone, setRbDone] = useState<Record<number, boolean>>({})
  const [rbError, setRbError] = useState<Record<number, string>>({})

  // Clear active edit on page change
  useEffect(() => {
    setActiveEdit(null)
    setSaveError({})
    setSaveDone({})
  }, [page])

  const startEdit = (pid: number, field: 'price' | 'stock', row: PreviewRow, e: React.MouseEvent) => {
    e.stopPropagation()
    if (editsDisabled || saving[pid]) return
    if (field === 'price') setActiveEdit({ pid, field, value: row.new_price, stockQty: '' })
    else setActiveEdit({ pid, field, value: row.stock_status || 'instock', stockQty: row.stock_quantity != null ? String(row.stock_quantity) : '' })
  }

  const cancelEdit = () => setActiveEdit(null)

  const commitEdit = async () => {
    if (!activeEdit || saving[activeEdit.pid]) return
    const { pid, field, value, stockQty } = activeEdit
    const row = rows.find(r => r.product_id === pid)
    if (!row) { cancelEdit(); return }
    setSaving(s => ({ ...s, [pid]: true }))
    setSaveError(s => { const n = { ...s }; delete n[pid]; return n })
    try {
      if (field === 'price') {
        await onSavePrice(pid, row.parent_id, value)
      } else {
        const qty = stockQty.trim() !== '' ? parseInt(stockQty.trim(), 10) : null
        await onSaveStock(pid, row.parent_id, value, qty !== null && !isNaN(qty) ? qty : null)
      }
      setSaving(s => { const n = { ...s }; delete n[pid]; return n })
      setSaveDone(s => ({ ...s, [pid]: true }))
      setActiveEdit(null)
      setTimeout(() => setSaveDone(s => { const n = { ...s }; delete n[pid]; return n }), 2000)
    } catch (err) {
      setSaving(s => { const n = { ...s }; delete n[pid]; return n })
      setSaveError(s => ({ ...s, [pid]: err instanceof Error ? err.message : 'Save failed' }))
    }
  }

  const handleRollback = async (pid: number, e: React.MouseEvent) => {
    e.stopPropagation()
    if (rbPending[pid]) return
    setRbPending(r => ({ ...r, [pid]: true }))
    setRbError(r => { const n = { ...r }; delete n[pid]; return n })
    try {
      await onRollback(pid)
      setRbPending(r => { const n = { ...r }; delete n[pid]; return n })
      setRbDone(r => ({ ...r, [pid]: true }))
    } catch (err) {
      setRbPending(r => { const n = { ...r }; delete n[pid]; return n })
      setRbError(r => ({ ...r, [pid]: err instanceof Error ? err.message : 'Rollback failed' }))
    }
  }

  const hasActions = canEditPrice || canEditStock || canRollback

  return (
    <div className="bg-bg-card border border-border rounded-lg overflow-hidden">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-b border-border">
        <div className="flex items-center gap-3">
          <span className="font-semibold text-[14px] text-text-base">Preview</span>
          <span className="text-[13px] text-wp-muted">{rows.length} rows</span>
          {selection.size > 0 && <span className="text-[12px] text-accent font-medium">{selection.size} selected</span>}
        </div>
        <div className="flex items-center gap-2">
          {selection.size > 0 && (
            <button onClick={onClearSelection} className="text-[12px] text-wp-muted hover:text-text-base transition-colors">
              Clear selection
            </button>
          )}
          <button
            onClick={() => allPageSelected ? onDeselectPage(currentIds) : onSelectPage(currentIds)}
            className="px-2.5 py-1 text-[12px] border border-border rounded-lg text-wp-muted hover:text-text-base hover:border-accent transition-colors"
          >
            {allPageSelected ? 'Deselect page' : 'Select page'}
          </button>
          <div className="flex items-center gap-1">
            <button onClick={() => onPageChange(page - 1)} disabled={page === 0}
              className="w-7 h-7 flex items-center justify-center rounded border border-border text-wp-muted hover:text-text-base disabled:opacity-40 transition-colors text-[14px]">‹</button>
            <span className="text-[12px] text-wp-muted tabular-nums px-1.5">{page + 1} / {totalPages}</span>
            <button onClick={() => onPageChange(page + 1)} disabled={page >= totalPages - 1}
              className="w-7 h-7 flex items-center justify-center rounded border border-border text-wp-muted hover:text-text-base disabled:opacity-40 transition-colors text-[14px]">›</button>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-[13px] border-collapse">
          <thead>
            <tr className="bg-bg-base">
              <th className="w-10 px-3 py-2.5 border-b border-border text-start">
                <input type="checkbox" checked={allPageSelected}
                  onChange={() => allPageSelected ? onDeselectPage(currentIds) : onSelectPage(currentIds)}
                  className="rounded accent-accent" />
              </th>
              <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide w-14">Image</th>
              <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">Product</th>
              <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">Status</th>
              <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">Old Price</th>
              <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">New Price</th>
              <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">Stock</th>
              {hasActions && <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide w-28">Actions</th>}
            </tr>
          </thead>
          <tbody>
            {currentRows.map(row => {
              const statusKey = row.change_status ?? (row.changed ? 'changed' : 'unchanged')
              const badge = STATUS_BADGE[statusKey] ?? STATUS_BADGE.unchanged
              const isSelected = selection.has(row.product_id)
              const pid = row.product_id
              const isEditing = activeEdit?.pid === pid
              const isSaving = saving[pid]
              const isSaved = saveDone[pid]
              const editErr = saveError[pid]
              const newPriceColor =
                row.change_status === 'changed' ? 'text-[#b45309] font-semibold' :
                row.change_status === 'new'     ? 'text-[#16a34a] font-semibold' :
                row.change_status === 'invalid' || row.change_status === 'missing_from_wc_cache' ? 'text-[#dc2626]' :
                'text-text-base'

              return (
                <tr key={pid} onClick={() => onToggleSelect(pid)}
                  className={`border-b border-border cursor-pointer transition-colors ${isSelected ? 'bg-accent/5' : 'hover:bg-bg-base'}`}>
                  <td className="px-3 py-2.5" onClick={e => e.stopPropagation()}>
                    <input type="checkbox" checked={isSelected} onChange={() => onToggleSelect(pid)} className="rounded accent-accent" />
                  </td>
                  <td className="px-3 py-2.5">
                    <img src={`/api/products/${pid}/thumb?size=96`} alt="" loading="lazy" width={40} height={40}
                      className="w-10 h-10 object-cover rounded bg-bg-base"
                      onError={e => { (e.currentTarget as HTMLImageElement).style.visibility = 'hidden' }} />
                  </td>
                  <td className="px-3 py-2.5 max-w-[220px]">
                    <div className="font-medium text-text-base truncate" title={row.product_name}>{row.product_name || `#${pid}`}</div>
                    {row.sku && <div className="text-[11px] font-mono text-wp-muted">{row.sku}</div>}
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${badge.cls}`}>{badge.label}</span>
                  </td>
                  <td className="px-3 py-2.5 font-mono text-wp-muted">{fmtPrice(row.old_price)}</td>

                  {/* New Price — inline edit */}
                  <td className="px-3 py-2.5" onClick={e => e.stopPropagation()}>
                    {isEditing && activeEdit!.field === 'price' ? (
                      <div className="flex flex-col gap-1">
                        <div className="flex items-center gap-1">
                          <input
                            autoFocus type="text" value={activeEdit!.value}
                            onChange={e => setActiveEdit(ae => ae ? { ...ae, value: e.target.value } : ae)}
                            onKeyDown={e => { if (e.key === 'Enter') void commitEdit(); if (e.key === 'Escape') cancelEdit() }}
                            disabled={isSaving}
                            className="w-28 px-2 py-1 text-[12px] font-mono border border-accent rounded bg-bg-base text-text-base focus:outline-none disabled:opacity-50"
                          />
                          <button onClick={() => void commitEdit()} disabled={isSaving}
                            className="px-2 py-1 text-[11px] bg-accent text-white rounded hover:bg-accent/90 disabled:opacity-50">
                            {isSaving ? '…' : 'Save'}
                          </button>
                          <button onClick={cancelEdit} disabled={isSaving}
                            className="px-2 py-1 text-[11px] border border-border rounded text-wp-muted hover:text-text-base">✕</button>
                        </div>
                        {editErr && <div className="text-[11px] text-[#dc2626]">{editErr}</div>}
                      </div>
                    ) : (
                      <div className="flex items-center gap-1.5">
                        <span className={`font-mono ${newPriceColor}`}>{fmtPrice(row.new_price)}</span>
                        {isSaved && <span className="text-[11px] text-[#16a34a]">✓</span>}
                        {canEditPrice && !editsDisabled && (
                          <button onClick={e => startEdit(pid, 'price', row, e)}
                            className="opacity-0 group-hover:opacity-100 hover:opacity-100 text-wp-muted hover:text-accent transition-colors"
                            title="Edit price">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5">
                              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                            </svg>
                          </button>
                        )}
                      </div>
                    )}
                  </td>

                  {/* Stock — inline edit */}
                  <td className="px-3 py-2.5" onClick={e => e.stopPropagation()}>
                    {isEditing && activeEdit!.field === 'stock' ? (
                      <div className="flex flex-col gap-1">
                        <div className="flex items-center gap-1 flex-wrap">
                          <select value={activeEdit!.value}
                            onChange={e => setActiveEdit(ae => ae ? { ...ae, value: e.target.value } : ae)}
                            disabled={isSaving}
                            className="px-2 py-1 text-[12px] border border-accent rounded bg-bg-base text-text-base focus:outline-none disabled:opacity-50">
                            <option value="instock">In Stock</option>
                            <option value="outofstock">Out of Stock</option>
                            <option value="onbackorder">On Backorder</option>
                          </select>
                          <input type="number" min={0} placeholder="Qty"
                            value={activeEdit!.stockQty}
                            onChange={e => setActiveEdit(ae => ae ? { ...ae, stockQty: e.target.value } : ae)}
                            disabled={isSaving}
                            className="w-16 px-2 py-1 text-[12px] border border-border rounded bg-bg-base text-text-base focus:outline-none focus:border-accent disabled:opacity-50"
                          />
                          <button onClick={() => void commitEdit()} disabled={isSaving}
                            className="px-2 py-1 text-[11px] bg-accent text-white rounded hover:bg-accent/90 disabled:opacity-50">
                            {isSaving ? '…' : 'Save'}
                          </button>
                          <button onClick={cancelEdit} disabled={isSaving}
                            className="px-2 py-1 text-[11px] border border-border rounded text-wp-muted hover:text-text-base">✕</button>
                        </div>
                        {editErr && <div className="text-[11px] text-[#dc2626]">{editErr}</div>}
                      </div>
                    ) : (
                      <div className="flex items-center gap-1.5">
                        <div>
                          <span className={`text-[12px] ${row.stock_status === 'instock' ? 'text-[#16a34a]' : row.stock_status === 'outofstock' ? 'text-[#dc2626]' : 'text-wp-muted'}`}>
                            {row.stock_status === 'instock' ? 'In Stock' : row.stock_status === 'outofstock' ? 'Out of Stock' : row.stock_status || '—'}
                          </span>
                          {row.stock_quantity != null && <span className="ms-1 text-[11px] text-wp-muted">({row.stock_quantity})</span>}
                        </div>
                        {canEditStock && !editsDisabled && (
                          <button onClick={e => startEdit(pid, 'stock', row, e)}
                            className="opacity-0 group-hover:opacity-100 hover:opacity-100 text-wp-muted hover:text-accent transition-colors"
                            title="Edit stock">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5">
                              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                            </svg>
                          </button>
                        )}
                      </div>
                    )}
                  </td>

                  {/* Actions column */}
                  {hasActions && (
                    <td className="px-3 py-2.5" onClick={e => e.stopPropagation()}>
                      <div className="flex items-center gap-1.5">
                        {canEditPrice && !editsDisabled && !(isEditing && activeEdit!.field === 'price') && (
                          <button onClick={e => startEdit(pid, 'price', row, e)} title="Edit price"
                            className="px-1.5 py-1 text-[11px] border border-border rounded text-wp-muted hover:text-accent hover:border-accent transition-colors">
                            P
                          </button>
                        )}
                        {canEditStock && !editsDisabled && !(isEditing && activeEdit!.field === 'stock') && (
                          <button onClick={e => startEdit(pid, 'stock', row, e)} title="Edit stock"
                            className="px-1.5 py-1 text-[11px] border border-border rounded text-wp-muted hover:text-accent hover:border-accent transition-colors">
                            S
                          </button>
                        )}
                        {canRollback && (
                          rbDone[pid] ? (
                            <span className="text-[11px] text-[#16a34a]">Rolled back</span>
                          ) : rbPending[pid] ? (
                            <svg viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2.5" className="w-3.5 h-3.5 animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
                          ) : rbError[pid] ? (
                            <span className="text-[11px] text-[#dc2626]" title={rbError[pid]}>Failed</span>
                          ) : (
                            <button onClick={e => void handleRollback(pid, e)} title="Rollback this product"
                              className="px-1.5 py-1 text-[11px] border border-[#f87171] text-[#dc2626] rounded hover:bg-red-50 transition-colors">
                              ↩
                            </button>
                          )
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 px-4 py-3 border-t border-border">
          <button onClick={() => onPageChange(0)} disabled={page === 0}
            className="px-2 py-1 text-[12px] border border-border rounded text-wp-muted hover:text-text-base disabled:opacity-40 transition-colors">«</button>
          <button onClick={() => onPageChange(page - 1)} disabled={page === 0}
            className="px-2.5 py-1 text-[12px] border border-border rounded text-wp-muted hover:text-text-base disabled:opacity-40 transition-colors">‹ Prev</button>
          <span className="text-[12px] text-wp-muted tabular-nums">Page {page + 1} of {totalPages} &middot; {rows.length} rows</span>
          <button onClick={() => onPageChange(page + 1)} disabled={page >= totalPages - 1}
            className="px-2.5 py-1 text-[12px] border border-border rounded text-wp-muted hover:text-text-base disabled:opacity-40 transition-colors">Next ›</button>
          <button onClick={() => onPageChange(totalPages - 1)} disabled={page >= totalPages - 1}
            className="px-2 py-1 text-[12px] border border-border rounded text-wp-muted hover:text-text-base disabled:opacity-40 transition-colors">»</button>
        </div>
      )}
    </div>
  )
}

// ── DryRunPanel ───────────────────────────────────────────────────────────────

interface DryRunPanelProps {
  phase: WorkspaceState['dryRunPhase']
  error: string | null
  result: DryRunResult | null
  invalidated: boolean
}
function DryRunPanel({ phase, error, result, invalidated }: DryRunPanelProps) {
  if (phase === 'idle') return null
  const statusBadge =
    phase === 'running' ? <span className="flex items-center gap-1.5 text-[12px] text-[#2563eb]"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-3.5 h-3.5 animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>Running…</span> :
    phase === 'failed'  ? <span className="text-[12px] text-[#dc2626] font-medium">Failed</span> :
    result?.dry_run_status === 'passed'               ? <span className="px-2 py-0.5 text-[11px] font-medium rounded-full bg-green-100 text-green-800">Passed</span> :
    result?.dry_run_status === 'passed_with_warnings' ? <span className="px-2 py-0.5 text-[11px] font-medium rounded-full bg-amber-100 text-amber-800">Passed with warnings</span> :
    result?.dry_run_status === 'blocked'              ? <span className="px-2 py-0.5 text-[11px] font-medium rounded-full bg-red-100 text-red-700">Blocked</span> :
    null

  return (
    <div className="bg-bg-card border border-border rounded-lg p-4">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-[14px] text-text-base">Dry Run</span>
          {statusBadge}
        </div>
        {invalidated && (
          <span className="flex items-center gap-1.5 text-[12px] text-[#b45309] font-medium">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5 flex-shrink-0"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg>
            Invalidated — re-run before applying
          </span>
        )}
      </div>

      {phase === 'failed' && error && <div className="text-[13px] text-[#dc2626]">{error}</div>}

      {phase === 'done' && result && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-x-6 gap-y-1.5 text-[13px]">
            <span><span className="text-wp-muted">Products to update: </span><span className="font-semibold text-text-base">{result.products_to_update}</span></span>
            {result.critical_errors.length > 0 && <span><span className="text-wp-muted">Critical errors: </span><span className="font-semibold text-[#dc2626]">{result.critical_errors.length}</span></span>}
            {result.warnings.length > 0 && <span><span className="text-wp-muted">Warnings: </span><span className="font-semibold text-[#b45309]">{result.warnings.length}</span></span>}
            <span className="text-[12px] text-wp-muted font-mono">scope: {result.dry_run_scope.length} product{result.dry_run_scope.length !== 1 ? 's' : ''}</span>
          </div>

          {result.critical_errors.length > 0 && (
            <div className="border border-[#fca5a5] rounded-lg p-3 bg-[#fef2f2]">
              <div className="font-medium text-[12px] text-[#dc2626] mb-1.5">Critical Errors — Apply blocked</div>
              <div className="space-y-0.5 max-h-[120px] overflow-y-auto">
                {result.critical_errors.map((e, i) => (
                  <div key={i} className="text-[12px] text-[#b91c1c]">
                    {e.name || `#${e.product_id}`}: {e.type.replace(/_/g, ' ')}{e.value ? ` (${e.value})` : ''}
                  </div>
                ))}
              </div>
            </div>
          )}

          {result.warnings.length > 0 && (
            <div className="border border-[#fde68a] rounded-lg p-3 bg-[#fffbeb]">
              <div className="font-medium text-[12px] text-[#b45309] mb-1.5">Warnings</div>
              <div className="space-y-0.5 max-h-[80px] overflow-y-auto">
                {result.warnings.map((w, i) => (
                  <div key={i} className="text-[12px] text-[#92400e]">
                    {w.name ? `${w.name}: ` : ''}{w.type.replace(/_/g, ' ')}{w.change ? ` (${w.change})` : ''}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── ApplyProgress ─────────────────────────────────────────────────────────────

interface ApplyProgressProps {
  phase: WorkspaceState['applyPhase']
  error: string | null
  stalePreview: boolean
  total: number
  completed: number
  items: ApplyItemEvent[]
  done: ApplyDoneEvent | null
  onRetryPreview: () => void
}
function ApplyProgress({ phase, error, stalePreview, total, completed, items, done, onRetryPreview }: ApplyProgressProps) {
  if (phase === 'idle') return null
  const failedItems = items.filter(i => i.status === 'failed')
  const percentage = total > 0 ? Math.round((completed / total) * 100) : (phase === 'streaming' ? 0 : 100)

  return (
    <div className="bg-bg-card border border-border rounded-lg p-4">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <span className="font-semibold text-[14px] text-text-base">Apply</span>
        {phase === 'streaming' && (
          <span className="flex items-center gap-1.5 text-[12px] text-[#2563eb]">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-3.5 h-3.5 animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
            {completed}/{total}
          </span>
        )}
        {phase === 'done' && (
          <span className="flex items-center gap-1.5 text-[12px] text-[#16a34a]">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-3.5 h-3.5"><polyline points="20 6 9 17 4 12" /></svg>
            Done
          </span>
        )}
        {phase === 'error' && <span className="text-[12px] text-[#dc2626] font-medium">Error</span>}
      </div>

      {phase === 'streaming' && (
        <div className="space-y-1.5">
          <div className="h-2 bg-bg-base rounded-full overflow-hidden border border-border">
            <div className="h-full bg-accent rounded-full transition-all duration-300" style={{ width: `${percentage}%` }} />
          </div>
          <div className="flex justify-between text-[11px] text-wp-muted">
            <span>{completed} / {total} products</span>
            <span>{percentage}%</span>
          </div>
        </div>
      )}

      {phase === 'error' && error && (
        <div className="space-y-2">
          <div className="text-[13px] text-[#dc2626]">{error}</div>
          {stalePreview && (
            <button onClick={onRetryPreview}
              className="flex items-center gap-1.5 text-[12px] text-accent border border-accent rounded-lg px-3 py-1.5 hover:bg-accent/5 transition-colors">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5"><polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" /><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" /></svg>
              Re-run Fetch Preview
            </button>
          )}
        </div>
      )}

      {done && (
        <div className={`flex flex-wrap gap-4 p-3 rounded-lg text-[13px] mt-2 ${done.failed > 0 ? 'bg-[#fef2f2] border border-[#fca5a5]' : 'bg-[#f0fdf4] border border-[#bbf7d0]'}`}>
          <span><span className="text-wp-muted">Updated: </span><span className="font-semibold text-[#16a34a]">{done.updated}</span></span>
          <span><span className="text-wp-muted">Failed: </span><span className={`font-semibold ${done.failed > 0 ? 'text-[#dc2626]' : 'text-text-base'}`}>{done.failed}</span></span>
          <span><span className="text-wp-muted">Skipped: </span><span className="font-semibold text-text-base">{done.skipped}</span></span>
        </div>
      )}

      {failedItems.length > 0 && (
        <div className="mt-3 border border-[#fca5a5] rounded-lg p-3 bg-[#fef2f2] max-h-[160px] overflow-y-auto">
          <div className="font-medium text-[12px] text-[#dc2626] mb-1.5">Failed items</div>
          {failedItems.map(item => (
            <div key={item.product_id} className="text-[12px] text-[#b91c1c]">
              {item.product_name || `#${item.product_id}`}
              {item.sku ? ` (${item.sku})` : ''}: {item.error || 'Unknown error'}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── SyncActionBar ─────────────────────────────────────────────────────────────

interface SyncActionBarProps {
  jobId: number | null
  selectionCount: number
  dryRunPhase: WorkspaceState['dryRunPhase']
  dryRunResult: DryRunResult | null
  dryRunInvalidated: boolean
  applyPhase: WorkspaceState['applyPhase']
  writebackPhase: WorkspaceState['writebackPhase']
  writebackMsg: string
  cancelPhase: WorkspaceState['cancelPhase']
  jobCancelled: boolean
  onDryRun: () => void
  onApply: () => void
  onCancelJob: () => void
  onWriteback: () => void
}
function SyncActionBar({
  jobId, selectionCount, dryRunPhase, dryRunResult, dryRunInvalidated,
  applyPhase, writebackPhase, writebackMsg, cancelPhase, jobCancelled,
  onDryRun, onApply, onCancelJob, onWriteback,
}: SyncActionBarProps) {
  const canRunApply = dryRunPhase === 'done' && dryRunResult !== null &&
    dryRunResult.dry_run_status !== 'blocked' && !dryRunInvalidated

  const applyDisabledReason =
    !dryRunResult                                     ? 'Run Dry Run first' :
    dryRunResult.dry_run_status === 'blocked'         ? 'Dry run has critical errors — blocked' :
    dryRunInvalidated                                 ? 'Re-run Dry Run (selection or data changed)' :
    dryRunPhase !== 'done'                            ? 'Run Dry Run first' :
    null

  const applyDone = applyPhase === 'done'
  const applyRunning = applyPhase === 'streaming'

  return (
    <div className="bg-bg-card border border-border rounded-lg p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-[13px] text-wp-muted">
          {selectionCount > 0
            ? <><span className="font-semibold text-text-base">{selectionCount}</span> products selected for sync</>
            : 'All changed products in scope'}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Cancel Job */}
          {!jobCancelled && !applyDone && !applyRunning && jobId && (
            <button onClick={onCancelJob} disabled={cancelPhase === 'pending'}
              className="px-3 py-1.5 text-[12px] border border-[#f87171] text-[#dc2626] rounded-lg hover:bg-red-50 transition-colors disabled:opacity-50">
              {cancelPhase === 'pending' ? 'Cancelling…' : 'Cancel Job'}
            </button>
          )}
          {jobCancelled && <span className="text-[12px] text-[#dc2626] font-medium">Job cancelled</span>}
          {cancelPhase === 'error' && <span className="text-[12px] text-[#dc2626]">Cancel failed</span>}

          {/* Dry Run */}
          {!jobCancelled && !applyDone && (
            <button onClick={onDryRun} disabled={dryRunPhase === 'running' || !jobId || applyRunning}
              className="px-3 py-1.5 text-[12px] border border-border rounded-lg text-wp-muted hover:text-text-base hover:border-accent transition-colors disabled:opacity-50">
              {dryRunPhase === 'running' ? 'Running…' : 'Dry Run'}
            </button>
          )}

          {/* Apply */}
          {!jobCancelled && !applyDone && (
            <button onClick={onApply}
              disabled={!canRunApply}
              title={applyDisabledReason ?? ''}
              className="px-4 py-1.5 text-[12px] bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors disabled:opacity-50">
              {applyRunning ? (
                <span className="flex items-center gap-1.5">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-3.5 h-3.5 animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
                  Applying…
                </span>
              ) : 'Apply →'}
            </button>
          )}

          {/* Writeback */}
          {applyDone && (
            <button onClick={onWriteback} disabled={writebackPhase === 'pending' || writebackPhase === 'done'}
              className="px-3 py-1.5 text-[12px] border border-border rounded-lg text-wp-muted hover:text-text-base hover:border-accent transition-colors disabled:opacity-50">
              {writebackPhase === 'pending' ? 'Writing…' :
               writebackPhase === 'done'    ? 'Written back ✓' :
               writebackPhase === 'error'   ? 'Writeback failed — retry' :
               'Write back to sheet'}
            </button>
          )}
        </div>
      </div>

      {/* Reason why apply is disabled */}
      {applyDisabledReason && !jobCancelled && !applyDone && (
        <div className="mt-2 text-[11px] text-[#b45309]">{applyDisabledReason}</div>
      )}

      {/* Writeback message */}
      {writebackMsg && (
        <div className={`mt-2 text-[12px] ${writebackPhase === 'error' ? 'text-[#dc2626]' : 'text-[#16a34a]'}`}>{writebackMsg}</div>
      )}
    </div>
  )
}

// ── Product Browser Types ─────────────────────────────────────────────────────

interface CachedProduct {
  wc_id: number; name: string; sku: string; price: string; regular_price: string
  stock_status: string; brand_name: string | null; categories: Array<{ id: number; name: string }>
  last_synced_at: string | null; parent_id: number; product_type: string
}

interface PBFilters {
  name: string; sku: string; brand_name: string; wc_id: string; category_id: string
}

const PB_EMPTY: PBFilters = { name: '', sku: '', brand_name: '', wc_id: '', category_id: '' }

type EmergencyOp = 'pct_increase' | 'pct_decrease' | 'fixed_increase' | 'fixed_decrease'

interface EmergencyPreviewItem {
  id: number; product_id: number; sku: string; product_name: string
  old_price: string | null; new_price: string | null; status: string
}

interface EmergencyState {
  phase: 'idle' | 'building' | 'preview' | 'confirming' | 'applying' | 'done' | 'error'
  op: EmergencyOp
  value: string
  batchId: number | null
  items: EmergencyPreviewItem[]
  error: string | null
  applied: number
  failed: number
  reconcile: number
  stale: number
  confirmed: boolean
}

const EM_INIT: EmergencyState = {
  phase: 'idle', op: 'pct_increase', value: '', batchId: null,
  items: [], error: null, applied: 0, failed: 0, reconcile: 0, stale: 0, confirmed: false,
}

interface AttentionBatch {
  id: number; status: string; created_at: string; created_by: string
  operation: string; value: number; needs_reconcile_count?: number
}

const EMERGENCY_OP_LABEL: Record<EmergencyOp, string> = {
  pct_increase:  '% Increase',
  pct_decrease:  '% Decrease',
  fixed_increase: 'Fixed Increase',
  fixed_decrease: 'Fixed Decrease',
}

// ── ProductBrowser ─────────────────────────────────────────────────────────────

function ProductBrowser({ authFetch }: { authFetch: (url: string, opts?: RequestInit) => Promise<Response> }) {
  const [filters, setFilters] = useState<PBFilters>(PB_EMPTY)
  const [applied, setApplied] = useState<PBFilters>(PB_EMPTY)
  const [products, setProducts] = useState<CachedProduct[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [emergency, setEmergency] = useState<EmergencyState>(EM_INIT)
  const [attentionBatches, setAttentionBatches] = useState<AttentionBatch[] | null>(null)
  const fetchSeq = useRef(0)
  const LIMIT = 50

  const fetchAttention = useCallback(async () => {
    try {
      const r = await authFetch('/api/emergency/pending')
      if (!r.ok) return
      const data = await r.json() as { batches: AttentionBatch[] }
      setAttentionBatches(
        data.batches.filter(b => ['applying', 'needs_reconcile', 'partially_failed'].includes(b.status))
      )
    } catch { /* ignore — attention banner is best-effort */ }
  }, [authFetch])

  useEffect(() => { void fetchAttention() }, [fetchAttention])

  const doFetch = useCallback(async (pg: number, f: PBFilters) => {
    setLoading(true)
    setError(null)
    const seq = ++fetchSeq.current
    const params = new URLSearchParams({ page: String(pg), limit: String(LIMIT) })
    if (f.name)        params.set('name', f.name)
    if (f.sku)         params.set('sku', f.sku)
    if (f.brand_name)  params.set('brand_name', f.brand_name)
    if (f.wc_id)       params.set('wc_id', f.wc_id)
    if (f.category_id) params.set('category_id', f.category_id)
    try {
      const r = await authFetch(`/api/products?${params}`)
      if (seq !== fetchSeq.current) return
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json() as { items: CachedProduct[]; total: number; page: number }
      setProducts(data.items)
      setTotal(data.total)
      setPage(pg)
    } catch (e) {
      if (seq !== fetchSeq.current) return
      setError(e instanceof Error ? e.message : 'Failed to load products')
    } finally {
      if (seq === fetchSeq.current) setLoading(false)
    }
  }, [authFetch])

  useEffect(() => { void doFetch(1, PB_EMPTY) }, [doFetch])

  const handleSearch = () => {
    setApplied(filters)
    void doFetch(1, filters)
  }

  const handleClear = () => {
    setFilters(PB_EMPTY)
    setApplied(PB_EMPTY)
    void doFetch(1, PB_EMPTY)
  }

  // Emergency price handlers
  const handleEmergencyPreview = useCallback(async () => {
    if (!emergency.value || parseFloat(emergency.value) <= 0) {
      setEmergency(s => ({ ...s, error: 'Value must be greater than 0' }))
      return
    }
    setEmergency(s => ({ ...s, phase: 'building', error: null }))
    try {
      const body: Record<string, unknown> = {
        operation: emergency.op,
        value: parseFloat(emergency.value),
      }
      if (applied.brand_name) body.brand_name = applied.brand_name
      if (applied.category_id) body.category_id = parseInt(applied.category_id, 10)
      if (applied.sku) body.sku = applied.sku
      if (applied.wc_id) body.product_ids = [parseInt(applied.wc_id, 10)]
      const r = await authFetch('/api/emergency/preview', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      })
      if (!r.ok) {
        const err = await r.json().catch(() => ({})) as Record<string, unknown>
        throw new Error(String(err.detail ?? `HTTP ${r.status}`))
      }
      const data = await r.json() as { batch_id: number; items: EmergencyPreviewItem[] }
      setEmergency(s => ({ ...s, phase: 'preview', batchId: data.batch_id, items: data.items, error: null }))
    } catch (e) {
      setEmergency(s => ({ ...s, phase: 'idle', error: e instanceof Error ? e.message : 'Preview failed' }))
    }
  }, [authFetch, emergency.op, emergency.value, applied])

  const handleEmergencyCancel = useCallback(async () => {
    const bid = emergency.batchId
    if (bid) {
      try { await authFetch(`/api/emergency/${bid}`, { method: 'DELETE' }) } catch { /* ignore */ }
    }
    setEmergency(EM_INIT)
  }, [authFetch, emergency.batchId])

  const handleEmergencyApply = useCallback(async () => {
    const bid = emergency.batchId
    if (!bid || !emergency.confirmed) return
    setEmergency(s => ({ ...s, phase: 'applying', error: null }))
    try {
      const r = await authFetch(`/api/emergency/${bid}/apply`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: true }),
      })
      if (!r.ok) {
        const err = await r.json().catch(() => ({})) as Record<string, unknown>
        throw new Error(String(err.detail ?? `HTTP ${r.status}`))
      }
      const data = await r.json() as { applied: number; failed: number; reconcile?: number; stale?: number }
      setEmergency(s => ({
        ...s, phase: 'done',
        applied: data.applied, failed: data.failed,
        reconcile: data.reconcile ?? 0, stale: data.stale ?? 0,
      }))
      void fetchAttention()  // re-check for needs_reconcile batches after apply
    } catch (e) {
      setEmergency(s => ({ ...s, phase: 'error', error: e instanceof Error ? e.message : 'Apply failed' }))
    }
  }, [authFetch, emergency.batchId, emergency.confirmed, fetchAttention])

  const totalPages = Math.max(1, Math.ceil(total / LIMIT))
  const pendingItems = emergency.items.filter(i => i.status === 'pending')
  const skippedItems = emergency.items.filter(i => i.status === 'skipped')

  return (
    <div className="space-y-4">
      {/* Filter panel */}
      <div className="bg-bg-card border border-border rounded-lg p-4">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-7 h-7 rounded-md bg-accent/10 flex items-center justify-center flex-shrink-0">
            <svg viewBox="0 0 24 24" fill="none" stroke="#4880FF" strokeWidth="2" className="w-[14px] h-[14px]">
              <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
            </svg>
          </div>
          <span className="font-semibold text-[14px] text-text-base">Product Filters</span>
          {total > 0 && <span className="text-[12px] text-wp-muted ml-auto">{total} products</span>}
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2 mb-3">
          <input type="text" placeholder="WC name…" value={filters.name}
            onChange={e => setFilters(s => ({ ...s, name: e.target.value }))}
            className="px-3 py-2 text-[13px] border border-border rounded-lg bg-bg-base text-text-base placeholder:text-wp-muted focus:outline-none focus:border-accent" />
          <input type="text" placeholder="SKU…" value={filters.sku}
            onChange={e => setFilters(s => ({ ...s, sku: e.target.value }))}
            className="px-3 py-2 text-[13px] border border-border rounded-lg bg-bg-base text-text-base placeholder:text-wp-muted focus:outline-none focus:border-accent" />
          <input type="text" placeholder="Brand…" value={filters.brand_name}
            onChange={e => setFilters(s => ({ ...s, brand_name: e.target.value }))}
            className="px-3 py-2 text-[13px] border border-border rounded-lg bg-bg-base text-text-base placeholder:text-wp-muted focus:outline-none focus:border-accent" />
          <input type="number" placeholder="Product ID…" value={filters.wc_id}
            onChange={e => setFilters(s => ({ ...s, wc_id: e.target.value }))}
            className="px-3 py-2 text-[13px] border border-border rounded-lg bg-bg-base text-text-base placeholder:text-wp-muted focus:outline-none focus:border-accent" />
          <input type="number" placeholder="Category ID…" value={filters.category_id}
            onChange={e => setFilters(s => ({ ...s, category_id: e.target.value }))}
            className="px-3 py-2 text-[13px] border border-border rounded-lg bg-bg-base text-text-base placeholder:text-wp-muted focus:outline-none focus:border-accent" />
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleSearch} disabled={loading}
            className="px-4 py-1.5 text-[13px] bg-accent text-white rounded-lg hover:bg-accent/90 disabled:opacity-50 transition-colors">
            {loading ? 'Loading…' : 'Search'}
          </button>
          <button onClick={handleClear} disabled={loading}
            className="px-3 py-1.5 text-[12px] border border-border rounded-lg text-wp-muted hover:text-text-base transition-colors">
            Clear
          </button>
        </div>
      </div>

      {/* Emergency Attention Banner — shown when any batch needs operator action */}
      {attentionBatches && attentionBatches.length > 0 && (
        <div className="border border-[#fca5a5] rounded-lg p-4 bg-[#fef2f2]">
          <div className="flex items-start gap-3">
            <svg viewBox="0 0 24 24" fill="none" stroke="#dc2626" strokeWidth="2" className="w-5 h-5 flex-shrink-0 mt-0.5">
              <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <div className="flex-1 min-w-0">
              <div className="font-semibold text-[13px] text-[#b91c1c] mb-2">
                {attentionBatches.length} emergency batch{attentionBatches.length !== 1 ? 'es' : ''} require operator attention
              </div>
              <div className="space-y-1.5">
                {attentionBatches.map(b => (
                  <div key={b.id} className="flex flex-wrap items-center gap-2 text-[12px]">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium flex-shrink-0 ${
                      b.status === 'needs_reconcile'  ? 'bg-red-100 text-red-800' :
                      b.status === 'applying'         ? 'bg-orange-100 text-orange-800' :
                      'bg-amber-100 text-amber-800'
                    }`}>{b.status.replace(/_/g, ' ')}</span>
                    <span className="text-[#7f1d1d]">
                      Batch #{b.id} — {b.operation.replace(/_/g, ' ')} {b.value} — by {b.created_by}
                    </span>
                    {(b.needs_reconcile_count ?? 0) > 0 && (
                      <span className="text-[11px] text-[#dc2626] font-medium">
                        {b.needs_reconcile_count} item(s) need reconciliation
                      </span>
                    )}
                  </div>
                ))}
              </div>
              <div className="mt-2 text-[11px] text-[#b91c1c] space-y-0.5">
                <div><strong>needs_reconcile</strong>: WooCommerce was updated but local DB finalization failed — manual verification required.</div>
                <div><strong>applying</strong>: Batch was interrupted mid-apply — inspect items individually.</div>
                <div><strong>partially_failed</strong>: Some items applied, some failed — review the batch.</div>
              </div>
              <button onClick={() => void fetchAttention()}
                className="mt-2 text-[11px] text-[#dc2626] border border-[#f87171] rounded px-2 py-0.5 hover:bg-red-50 transition-colors">
                Refresh
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Emergency Price Panel */}
      <div className="bg-bg-card border border-[#f59e0b] rounded-lg p-4">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-7 h-7 rounded-md bg-[#fef3c7] flex items-center justify-center flex-shrink-0">
            <svg viewBox="0 0 24 24" fill="none" stroke="#b45309" strokeWidth="2" className="w-[14px] h-[14px]">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
          </div>
          <span className="font-semibold text-[14px] text-[#b45309]">Emergency Price Update</span>
          <span className="text-[11px] text-wp-muted ml-1">— applies to filtered products above</span>
        </div>

        {emergency.phase === 'idle' && (
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="block text-[11px] font-medium text-wp-muted mb-1">Operation</label>
              <select value={emergency.op}
                onChange={e => setEmergency(s => ({ ...s, op: e.target.value as EmergencyOp }))}
                className="px-3 py-2 text-[13px] border border-border rounded-lg bg-bg-base text-text-base focus:outline-none focus:border-accent">
                {(Object.keys(EMERGENCY_OP_LABEL) as EmergencyOp[]).map(op => (
                  <option key={op} value={op}>{EMERGENCY_OP_LABEL[op]}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-[11px] font-medium text-wp-muted mb-1">
                {emergency.op.startsWith('pct') ? 'Percent (%)' : 'Fixed Amount'}
              </label>
              <input type="number" min="0" step="any" value={emergency.value}
                onChange={e => setEmergency(s => ({ ...s, value: e.target.value }))}
                placeholder="e.g. 10"
                className="w-32 px-3 py-2 text-[13px] border border-border rounded-lg bg-bg-base text-text-base focus:outline-none focus:border-accent placeholder:text-wp-muted" />
            </div>
            <button onClick={() => void handleEmergencyPreview()} disabled={!emergency.value}
              className="px-4 py-2 text-[13px] border border-[#b45309] text-[#b45309] rounded-lg hover:bg-[#fef3c7] disabled:opacity-50 transition-colors">
              Preview Changes
            </button>
            {emergency.error && <span className="text-[12px] text-[#dc2626]">{emergency.error}</span>}
          </div>
        )}

        {emergency.phase === 'building' && (
          <div className="flex items-center gap-2 text-[13px] text-wp-muted">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-4 h-4 animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
            Computing emergency prices…
          </div>
        )}

        {emergency.phase === 'preview' && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3 text-[13px]">
              <span><span className="text-wp-muted">Operation: </span><span className="font-medium text-text-base">{EMERGENCY_OP_LABEL[emergency.op]} {emergency.value}{emergency.op.startsWith('pct') ? '%' : ''}</span></span>
              <span><span className="text-wp-muted">Products to update: </span><span className="font-semibold text-[#b45309]">{pendingItems.length}</span></span>
              {skippedItems.length > 0 && <span><span className="text-wp-muted">Skipped (no price): </span><span className="text-wp-muted">{skippedItems.length}</span></span>}
            </div>
            <div className="border border-border rounded-lg overflow-hidden max-h-[240px] overflow-y-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="bg-bg-base border-b border-border">
                    <th className="px-3 py-2 text-start font-semibold text-wp-muted uppercase tracking-wide text-[10px]">Product</th>
                    <th className="px-3 py-2 text-start font-semibold text-wp-muted uppercase tracking-wide text-[10px]">Old Price</th>
                    <th className="px-3 py-2 text-start font-semibold text-wp-muted uppercase tracking-wide text-[10px]">New Price</th>
                    <th className="px-3 py-2 text-start font-semibold text-wp-muted uppercase tracking-wide text-[10px]">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {emergency.items.map(item => (
                    <tr key={item.id} className="border-b border-border/50">
                      <td className="px-3 py-1.5">
                        <div className="font-medium text-text-base truncate max-w-[180px]" title={item.product_name}>{item.product_name || `#${item.product_id}`}</div>
                        {item.sku && <div className="text-[11px] font-mono text-wp-muted">{item.sku}</div>}
                      </td>
                      <td className="px-3 py-1.5 font-mono text-wp-muted">{fmtPrice(item.old_price)}</td>
                      <td className="px-3 py-1.5 font-mono font-semibold text-[#b45309]">{item.new_price ? fmtPrice(item.new_price) : '—'}</td>
                      <td className="px-3 py-1.5">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${item.status === 'pending' ? 'bg-amber-100 text-amber-800' : 'bg-gray-100 text-gray-500'}`}>
                          {item.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="border border-[#fca5a5] rounded-lg p-3 bg-[#fef2f2]">
              <p className="text-[12px] text-[#b91c1c] font-medium mb-2">
                This will write {pendingItems.length} new prices directly to WooCommerce without going through the spreadsheet. These prices will be flagged on the Dashboard until the sheet is updated.
              </p>
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input type="checkbox" checked={emergency.confirmed}
                  onChange={e => setEmergency(s => ({ ...s, confirmed: e.target.checked }))}
                  className="rounded accent-accent" />
                <span className="text-[12px] text-[#b91c1c]">I understand this writes to WooCommerce immediately</span>
              </label>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={() => void handleEmergencyApply()} disabled={!emergency.confirmed}
                className="px-4 py-1.5 text-[13px] bg-[#dc2626] text-white rounded-lg hover:bg-[#b91c1c] disabled:opacity-50 transition-colors">
                Apply Emergency Update →
              </button>
              <button onClick={() => void handleEmergencyCancel()}
                className="px-3 py-1.5 text-[12px] border border-border rounded-lg text-wp-muted hover:text-text-base transition-colors">
                Cancel
              </button>
            </div>
          </div>
        )}

        {emergency.phase === 'applying' && (
          <div className="flex items-center gap-2 text-[13px] text-[#dc2626]">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-4 h-4 animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
            Applying emergency prices… Do not close this page.
          </div>
        )}

        {emergency.phase === 'done' && (
          <div className="space-y-2">
            <div className={`flex flex-wrap gap-4 p-3 rounded-lg text-[13px] ${
              emergency.reconcile > 0 ? 'bg-[#fef2f2] border border-[#fca5a5]' :
              emergency.failed > 0    ? 'bg-[#fef2f2] border border-[#fca5a5]' :
              'bg-[#f0fdf4] border border-[#bbf7d0]'
            }`}>
              <span><span className="text-wp-muted">Applied: </span><span className="font-semibold text-[#16a34a]">{emergency.applied}</span></span>
              {emergency.failed > 0 && <span><span className="text-wp-muted">Failed: </span><span className="font-semibold text-[#dc2626]">{emergency.failed}</span></span>}
              {emergency.stale > 0 && <span><span className="text-wp-muted">Stale: </span><span className="font-semibold text-[#b45309]">{emergency.stale}</span></span>}
              {emergency.reconcile > 0 && <span><span className="text-wp-muted">Needs reconcile: </span><span className="font-semibold text-[#dc2626]">{emergency.reconcile}</span></span>}
            </div>
            {emergency.reconcile > 0 && (
              <div className="border border-[#fca5a5] rounded-lg p-3 bg-[#fef2f2] text-[12px] text-[#b91c1c]">
                <strong>{emergency.reconcile} item(s) need manual reconciliation.</strong>{' '}
                WooCommerce was updated but local DB finalization failed. The attention banner above will show these batches until resolved.
              </div>
            )}
            <p className="text-[12px] text-wp-muted">Emergency prices applied. Update the source sheet to re-synchronize.</p>
            <button onClick={() => setEmergency(EM_INIT)}
              className="px-3 py-1.5 text-[12px] border border-border rounded-lg text-wp-muted hover:text-text-base transition-colors">
              Done
            </button>
          </div>
        )}

        {emergency.phase === 'error' && (
          <div className="space-y-2">
            <div className="text-[13px] text-[#dc2626]">{emergency.error}</div>
            <div className="flex gap-2">
              <button onClick={() => setEmergency(s => ({ ...s, phase: 'preview', error: null }))}
                className="px-3 py-1.5 text-[12px] border border-border rounded-lg text-wp-muted hover:text-text-base">Retry</button>
              <button onClick={() => void handleEmergencyCancel()}
                className="px-3 py-1.5 text-[12px] border border-[#f87171] text-[#dc2626] rounded-lg hover:bg-red-50">Cancel</button>
            </div>
          </div>
        )}
      </div>

      {/* Product list */}
      {error && <div className="bg-[#fef2f2] border border-[#fca5a5] rounded-lg px-4 py-3 text-[13px] text-[#dc2626]">{error}</div>}

      {!error && (
        <div className="bg-bg-card border border-border rounded-lg overflow-hidden">
          {totalPages > 1 && (
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border">
              <button onClick={() => void doFetch(page - 1, applied)} disabled={page <= 1 || loading}
                className="px-2.5 py-1 text-[12px] border border-border rounded text-wp-muted hover:text-text-base disabled:opacity-40">‹ Prev</button>
              <span className="text-[12px] text-wp-muted">{page} / {totalPages}</span>
              <button onClick={() => void doFetch(page + 1, applied)} disabled={page >= totalPages || loading}
                className="px-2.5 py-1 text-[12px] border border-border rounded text-wp-muted hover:text-text-base disabled:opacity-40">Next ›</button>
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="w-full text-[13px] border-collapse">
              <thead>
                <tr className="bg-bg-base">
                  <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide w-10">Img</th>
                  <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">Product</th>
                  <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">Brand</th>
                  <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">Price</th>
                  <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">Stock</th>
                  <th className="px-3 py-2.5 border-b border-border text-start text-[11px] font-semibold text-wp-muted uppercase tracking-wide">Synced</th>
                </tr>
              </thead>
              <tbody>
                {loading && products.length === 0 && (
                  <tr><td colSpan={6} className="px-4 py-8 text-center text-[13px] text-wp-muted">Loading…</td></tr>
                )}
                {!loading && products.length === 0 && (
                  <tr><td colSpan={6} className="px-4 py-8 text-center text-[13px] text-wp-muted">No products found</td></tr>
                )}
                {products.map(p => (
                  <tr key={p.wc_id} className="border-b border-border hover:bg-bg-base transition-colors">
                    <td className="px-3 py-2.5">
                      <img src={`/api/products/${p.wc_id}/thumb?size=96`} alt="" loading="lazy" width={36} height={36}
                        className="w-9 h-9 object-cover rounded bg-bg-base"
                        onError={e => { (e.currentTarget as HTMLImageElement).style.visibility = 'hidden' }} />
                    </td>
                    <td className="px-3 py-2.5 max-w-[220px]">
                      <div className="font-medium text-text-base truncate" title={p.name}>{p.name || `#${p.wc_id}`}</div>
                      {p.sku && <div className="text-[11px] font-mono text-wp-muted">{p.sku}</div>}
                      <div className="text-[11px] text-wp-muted">ID: {p.wc_id}</div>
                    </td>
                    <td className="px-3 py-2.5 text-[12px] text-wp-muted">{p.brand_name || '—'}</td>
                    <td className="px-3 py-2.5 font-mono text-[13px]">{fmtPrice(p.price || p.regular_price)}</td>
                    <td className="px-3 py-2.5 text-[12px]">
                      <span className={p.stock_status === 'instock' ? 'text-[#16a34a]' : p.stock_status === 'outofstock' ? 'text-[#dc2626]' : 'text-wp-muted'}>
                        {p.stock_status === 'instock' ? 'In Stock' : p.stock_status === 'outofstock' ? 'Out of Stock' : p.stock_status || '—'}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-[11px] text-wp-muted whitespace-nowrap">
                      {p.last_synced_at ? new Date(p.last_synced_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : 'Never'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Workspace ─────────────────────────────────────────────────────────────────

type WorkspaceTab = 'sheet_sync' | 'product_browser'

export default function Workspace() {
  const { authFetch, user, status } = useAuth()
  const [state, dispatch] = useReducer(reducer, INITIAL)
  const pollInitialEtagRef = useRef<string | null>(null)
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('sheet_sync')

  // ── Cache SSE ──────────────────────────────────────────────────────────────

  const handleCacheMessage = useCallback((raw: unknown) => {
    const ev = raw as Record<string, unknown>
    const msg = String(ev.msg ?? ev.error ?? '')
    if (ev.status === 'error' || ev.step === 'error' || ev.error) {
      if (msg) dispatch({ type: 'CACHE_LOG', msg, level: 'error' })
      dispatch({ type: 'CACHE_ERROR', message: msg || 'Refresh failed.' })
    } else if (ev.step === 'done') {
      if (msg) dispatch({ type: 'CACHE_LOG', msg, level: 'ok' })
      dispatch({ type: 'CACHE_DONE' })
    } else if (msg) {
      dispatch({ type: 'CACHE_LOG', msg, level: ev.status === 'warning' ? 'warn' : 'info' })
    }
  }, [])
  const handleCacheError = useCallback((reason: SSEErrorReason) => {
    dispatch({ type: 'CACHE_ERROR', message: reason === 'connection_lost' ? 'Connection lost — try again.' : 'Stream truncated — try again.' })
  }, [])
  useSSEStream(state.cacheSseUrl, handleCacheMessage, handleCacheError)

  // ── Preview SSE ────────────────────────────────────────────────────────────

  const handlePreviewMessage = useCallback((raw: unknown) => {
    const ev = raw as Record<string, unknown>
    const step = String(ev.step ?? '')
    const sstatus = String(ev.status ?? '')
    const msg = String(ev.msg ?? '')
    if (sstatus === 'error') { dispatch({ type: 'PREVIEW_ERROR', message: msg || 'Preview failed.' }); return }
    if (step === 'excel' && sstatus === 'warning' && ev.duplicate_warnings) {
      dispatch({ type: 'PREVIEW_DUP_WARNING', warnings: ev.duplicate_warnings as DupWarning[] }); return
    }
    if (step === 'excel' || step === 'wc' || step === 'calc') {
      dispatch({ type: 'PREVIEW_STEP', which: step as 'excel' | 'wc' | 'calc', status: sstatus as StepStatus, msg }); return
    }
    if (step === 'preview' && sstatus === 'done') {
      dispatch({
        type: 'PREVIEW_READY',
        rows: (ev.items as PreviewRow[]) ?? [],
        summary: {
          job_id: Number(ev.job_id), total: Number(ev.total),
          changed_count: Number(ev.changed_count), unchanged_count: Number(ev.unchanged_count),
          new_count: Number(ev.new_count), invalid_count: Number(ev.invalid_count),
          price_changed_count: Number(ev.price_changed_count), stock_changed_count: Number(ev.stock_changed_count),
          missing_image_count: Number(ev.missing_image_count),
        },
        filterStats: ev.filter_stats as FilterStats,
        dupWarnings: (ev.duplicate_warnings as DupWarning[]) ?? [],
      })
    }
  }, [])
  const handlePreviewError = useCallback((reason: SSEErrorReason) => {
    dispatch({ type: 'PREVIEW_ERROR', message: reason === 'parse_error'
      ? 'Preview data was incomplete — this may be a proxy configuration issue.'
      : 'Preview connection lost.' })
  }, [])
  useSSEStream(state.previewSseUrl, handlePreviewMessage, handlePreviewError)

  // ── Apply SSE ──────────────────────────────────────────────────────────────

  const handleApplyMessage = useCallback((raw: unknown) => {
    const ev = raw as Record<string, unknown>
    const evType = String(ev.type ?? '')
    if (evType === 'error') {
      dispatch({ type: 'APPLY_ERROR', message: String(ev.msg || 'Apply failed.') }); return
    }
    if (evType === 'stale_preview' || evType === 'freshness_unverifiable') {
      dispatch({ type: 'APPLY_ERROR', message: String(ev.msg || 'Preview is stale — re-run Fetch Preview.'), stalePreview: true }); return
    }
    if (evType === 'dry_run_invalidated') {
      dispatch({ type: 'APPLY_ERROR', message: String(ev.msg || 'Dry run was invalidated — re-run Dry Run before applying.') })
      dispatch({ type: 'DRY_RUN_CLEARED_BY_SERVER' }); return
    }
    if (evType === 'start') { dispatch({ type: 'APPLY_META', total: Number(ev.total) }); return }
    if (evType === 'item') { dispatch({ type: 'APPLY_ITEM', item: ev as unknown as ApplyItemEvent }); return }
    if (evType === 'done') {
      dispatch({ type: 'APPLY_DONE', done: { job_id: Number(ev.job_id), updated: Number(ev.updated), failed: Number(ev.failed), skipped: Number(ev.skipped) } })
    }
  }, [])
  // No retry on apply disconnect — show "check Sync History" message
  const handleApplyError = useCallback((reason: SSEErrorReason) => {
    dispatch({ type: 'APPLY_ERROR', message: reason === 'parse_error'
      ? 'Apply stream data was truncated — check Sync History for actual outcome.'
      : 'Connection lost — check Sync History for actual outcome.' })
  }, [])
  useSSEStream(state.applySseUrl, handleApplyMessage, handleApplyError)

  // ── Sheet meta ─────────────────────────────────────────────────────────────

  const checkSheetMeta = useCallback(async () => {
    dispatch({ type: 'SHEET_LOADING' })
    try {
      const r = await authFetch('/api/spreadsheet/meta')
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      dispatch({ type: 'SHEET_LOADED', meta: (await r.json()) as SheetMeta })
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
    let remaining = 15
    const tick = async () => {
      if (remaining <= 0) { dispatch({ type: 'SHEET_POLL_STOP' }); return }
      remaining--
      try {
        const r = await authFetch('/api/spreadsheet/meta')
        if (!r.ok) return
        const meta = (await r.json()) as SheetMeta
        dispatch({ type: 'SHEET_LOADED', meta })
        if (meta.current.etag !== initialEtag) dispatch({ type: 'SHEET_POLL_STOP' })
      } catch { /* ignore */ }
    }
    const id = setInterval(() => { void tick() }, 2000)
    return () => clearInterval(id)
  }, [state.sheetPolling, authFetch])

  // ── Categories ─────────────────────────────────────────────────────────────

  useEffect(() => {
    dispatch({ type: 'CAT_LOADING' })
    authFetch('/api/categories')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() as Promise<WcCategory[]> })
      .then(cats => dispatch({ type: 'CAT_LOADED', categories: cats }))
      .catch((e: unknown) => dispatch({ type: 'CAT_ERROR', message: String(e) }))
  }, [authFetch])

  // ── Cache refresh ──────────────────────────────────────────────────────────

  const startCacheRefresh = useCallback((op: CacheOp) => {
    if (state.cacheRunning) return
    dispatch({ type: 'CACHE_START', op, url: buildSseUrl(OP_ENDPOINT[op]) })
  }, [state.cacheRunning])

  // ── Preview fetch ──────────────────────────────────────────────────────────

  const startPreviewFetch = useCallback(() => {
    if (state.previewPhase === 'streaming') return
    dispatch({ type: 'PREVIEW_START', url: buildPreviewSseUrl(state.filterSearch, state.filterCatIds) })
  }, [state.previewPhase, state.filterSearch, state.filterCatIds])

  // ── WS-C: Dry Run ──────────────────────────────────────────────────────────

  const runDryRun = useCallback(async () => {
    const jobId = state.previewSummary?.job_id
    if (!jobId || state.dryRunPhase === 'running') return
    dispatch({ type: 'DRY_RUN_START' })
    try {
      const selection = [...state.previewSelection]
      let url = `/api/sync/${jobId}/dry-run`
      if (selection.length > 0) url += '?' + selection.map(id => `sid=${id}`).join('&')
      const r = await authFetch(url, { method: 'POST' })
      if (!r.ok) {
        const err = await r.json().catch(() => ({})) as Record<string, unknown>
        throw new Error(String(err.detail ?? `HTTP ${r.status}`))
      }
      dispatch({ type: 'DRY_RUN_DONE', result: (await r.json()) as DryRunResult })
    } catch (e) {
      dispatch({ type: 'DRY_RUN_FAILED', message: e instanceof Error ? e.message : 'Dry run failed.' })
    }
  }, [authFetch, state.previewSummary, state.previewSelection, state.dryRunPhase])

  // ── WS-C: Apply ────────────────────────────────────────────────────────────

  const startApply = useCallback(() => {
    const jobId = state.previewSummary?.job_id
    if (!jobId || state.applyPhase !== 'idle' || !state.dryRunResult) return
    dispatch({ type: 'APPLY_START', url: buildApplySseUrl(jobId, state.dryRunResult.dry_run_scope) })
  }, [state.previewSummary, state.applyPhase, state.dryRunResult])

  // ── WS-C: Cancel ───────────────────────────────────────────────────────────

  const cancelJob = useCallback(async () => {
    const jobId = state.previewSummary?.job_id
    if (!jobId || state.cancelPhase === 'pending') return
    dispatch({ type: 'CANCEL_START' })
    try {
      const r = await authFetch(`/api/sync/${jobId}`, { method: 'DELETE' })
      if (!r.ok) {
        const err = await r.json().catch(() => ({})) as Record<string, unknown>
        throw new Error(String(err.detail ?? `HTTP ${r.status}`))
      }
      dispatch({ type: 'CANCEL_DONE' })
    } catch (e) {
      dispatch({ type: 'CANCEL_ERROR', message: e instanceof Error ? e.message : 'Cancel failed.' })
    }
  }, [authFetch, state.previewSummary, state.cancelPhase])

  // ── WS-C: Writeback ────────────────────────────────────────────────────────

  const runWriteback = useCallback(async () => {
    const jobId = state.previewSummary?.job_id
    if (!jobId || state.writebackPhase === 'pending') return
    dispatch({ type: 'WRITEBACK_START' })
    try {
      const r = await authFetch(`/api/jobs/${jobId}/writeback`, { method: 'POST' })
      if (!r.ok) {
        const err = await r.json().catch(() => ({})) as Record<string, unknown>
        throw new Error(String(err.detail ?? `HTTP ${r.status}`))
      }
      const data = (await r.json()) as { message: string }
      dispatch({ type: 'WRITEBACK_DONE', message: data.message })
    } catch (e) {
      dispatch({ type: 'WRITEBACK_ERROR', message: e instanceof Error ? e.message : 'Writeback failed.' })
    }
  }, [authFetch, state.previewSummary, state.writebackPhase])

  // ── WS-C: Inline price save ────────────────────────────────────────────────

  const handleSavePrice = useCallback(async (pid: number, parentId: number, newPrice: string) => {
    const jobId = state.previewSummary?.job_id ?? null
    const body: Record<string, unknown> = { new_price: newPrice }
    if (jobId) body.job_id = jobId
    if (parentId) body.parent_id = parentId
    const r = await authFetch(`/api/products/${pid}/price`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    if (!r.ok) {
      const err = await r.json().catch(() => ({})) as Record<string, unknown>
      throw new Error(String(err.detail ?? `HTTP ${r.status}`))
    }
    dispatch({ type: 'ROW_PATCH', pid, patch: { new_price: newPrice } })
    dispatch({ type: 'DRY_RUN_INVALIDATE' })
  }, [authFetch, state.previewSummary])

  // ── WS-C: Inline stock save ────────────────────────────────────────────────

  const handleSaveStock = useCallback(async (pid: number, parentId: number, stockStatus: string, qty: number | null) => {
    const jobId = state.previewSummary?.job_id ?? null
    const body: Record<string, unknown> = { stock_status: stockStatus }
    if (jobId) body.job_id = jobId
    if (parentId) body.parent_id = parentId
    if (qty !== null) body.stock_quantity = qty
    const r = await authFetch(`/api/products/${pid}/stock`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    if (!r.ok) {
      const err = await r.json().catch(() => ({})) as Record<string, unknown>
      throw new Error(String(err.detail ?? `HTTP ${r.status}`))
    }
    const patch: Partial<PreviewRow> = { stock_status: stockStatus }
    if (qty !== null) patch.stock_quantity = qty
    dispatch({ type: 'ROW_PATCH', pid, patch })
    dispatch({ type: 'DRY_RUN_INVALIDATE' })
  }, [authFetch, state.previewSummary])

  // ── WS-C: Rollback ─────────────────────────────────────────────────────────

  const handleRollback = useCallback(async (pid: number) => {
    const r = await authFetch(`/api/rollback/product/${pid}`, { method: 'POST' })
    if (!r.ok) {
      const err = await r.json().catch(() => ({})) as Record<string, unknown>
      throw new Error(String(err.detail ?? `HTTP ${r.status}`))
    }
    const data = (await r.json()) as { restored_price?: string; restored_stock_status?: string }
    const patch: Partial<PreviewRow> = {}
    if (data.restored_price) { patch.new_price = data.restored_price; patch.old_price = data.restored_price }
    if (data.restored_stock_status) patch.stock_status = data.restored_stock_status
    if (Object.keys(patch).length > 0) dispatch({ type: 'ROW_PATCH', pid, patch })
    dispatch({ type: 'DRY_RUN_INVALIDATE' })
    dispatch({ type: 'ROLLBACK_ADVISORY' })
  }, [authFetch])

  // ── Auth gate (after all hooks) ────────────────────────────────────────────

  if (status !== 'authenticated') return <AccessState status={status} />

  const canFetch     = user?.is_admin === true || user?.permissions?.can_fetch === true
  const canApply     = user?.is_admin === true || user?.permissions?.can_apply === true
  const canEditPrice = user?.is_admin === true || user?.permissions?.can_edit_price === true
  const canEditStock = user?.is_admin === true || user?.permissions?.can_edit_stock === true
  const isAdmin      = user?.is_admin === true

  const jobId = state.previewSummary?.job_id ?? null
  const editsDisabled = state.applyPhase === 'done' || state.applyPhase === 'streaming'

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
          {/* Tab switcher */}
          <div className="flex border border-border rounded-lg overflow-hidden text-[12px] font-medium">
            <button onClick={() => setActiveTab('sheet_sync')}
              className={`px-3 py-1.5 transition-colors ${activeTab === 'sheet_sync' ? 'bg-accent text-white' : 'text-wp-muted hover:text-text-base'}`}>
              Sheet Sync
            </button>
            <button onClick={() => setActiveTab('product_browser')}
              className={`px-3 py-1.5 border-l border-border transition-colors ${activeTab === 'product_browser' ? 'bg-accent text-white' : 'text-wp-muted hover:text-text-base'}`}>
              Product Browser
            </button>
          </div>
          {activeTab === 'sheet_sync' && canFetch && (
            <>
              <button onClick={() => startCacheRefresh('light')} disabled={state.cacheRunning}
                title="Fetch only products modified since the last full sync"
                className="px-3 py-1.5 text-[13px] border border-border rounded-lg text-wp-muted hover:text-text-base hover:border-accent transition-colors disabled:opacity-50">
                Light Refresh
              </button>
              <button onClick={() => startCacheRefresh('full')} disabled={state.cacheRunning}
                title="Fetch all top-level products + images from WooCommerce"
                className="flex items-center gap-2 px-3 py-1.5 text-[13px] border border-border rounded-lg text-wp-muted hover:text-text-base hover:border-accent transition-colors disabled:opacity-50">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                  className={`w-3.5 h-3.5 ${state.cacheRunning && state.cacheOp === 'full' ? 'animate-spin' : ''}`}>
                  <polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" />
                  <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
                </svg>
                Full Refresh
              </button>
            </>
          )}
          {activeTab === 'sheet_sync' && isAdmin && (
            <button onClick={() => startCacheRefresh('deep')} disabled={state.cacheRunning}
              title="Sync ALL variations for ALL variable parents"
              className="px-3 py-1.5 text-[13px] border border-[#f59e0b] text-[#b45309] rounded-lg hover:bg-[#fef3c7] transition-colors disabled:opacity-50">
              ● Deep Sync
            </button>
          )}
          {activeTab === 'sheet_sync' && canFetch && (
            <button onClick={startPreviewFetch}
              disabled={state.cacheRunning || state.previewPhase === 'streaming' || state.applyPhase === 'streaming'}
              title="Run preview: download spreadsheet, compare with WooCommerce cache, calculate changes"
              className="flex items-center gap-2 px-4 py-1.5 text-[13px] bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors disabled:opacity-50">
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

      {/* ── Product Browser tab ─────────────────────────────────────────────── */}
      {activeTab === 'product_browser' && (
        <ProductBrowser authFetch={authFetch} />
      )}

      {/* ── Sheet Sync tab ──────────────────────────────────────────────────── */}
      {activeTab === 'sheet_sync' && (<>

      {/* Spreadsheet status */}
      <SpreadsheetStatus
        loading={state.sheetLoading} meta={state.sheetMeta} error={state.sheetError}
        polling={state.sheetPolling} canFetch={canFetch}
        onCheck={() => { void checkSheetMeta() }} onStartPoll={startPoll}
        onStopPoll={() => dispatch({ type: 'SHEET_POLL_STOP' })}
      />

      {/* Pre-fetch filters */}
      {canFetch && (
        <PreFetchFilters
          search={state.filterSearch} catIds={state.filterCatIds}
          categories={state.categories} catLoading={state.catLoading} catError={state.catError}
          disabled={state.previewPhase === 'streaming'}
          onSearchChange={v => dispatch({ type: 'FILTER_SEARCH', value: v })}
          onCatToggle={id => dispatch({ type: 'FILTER_CAT_TOGGLE', id })}
          onClearFilters={() => dispatch({ type: 'FILTER_CLEAR' })}
        />
      )}

      {/* Preview progress steps */}
      {state.previewPhase !== 'idle' && (
        <PreviewSteps
          phase={state.previewPhase} stepExcel={state.stepExcel} stepWC={state.stepWC} stepCalc={state.stepCalc}
          stepExcelMsg={state.stepExcelMsg} stepWCMsg={state.stepWCMsg} stepCalcMsg={state.stepCalcMsg}
          previewError={state.previewError} onRetry={startPreviewFetch}
        />
      )}

      {/* Filter stats */}
      {state.previewPhase === 'ready' && state.filterStats && state.previewSummary && (
        <FilterStatsBar stats={state.filterStats} summary={state.previewSummary} />
      )}

      {/* Duplicate warnings */}
      {state.duplicateWarnings.length > 0 && state.previewPhase !== 'idle' && (
        <DuplicateWarningBox warnings={state.duplicateWarnings} />
      )}

      {/* Rollback advisory */}
      {state.rollbackAdvisory && (
        <div className="border border-[#f59e0b] rounded-lg px-4 py-3 bg-[#fffbeb] text-[13px] text-[#92400e]">
          A rollback changed WooCommerce state. Re-running Fetch Preview is recommended before applying.
        </div>
      )}

      {/* Preview table */}
      {state.previewPhase === 'ready' && state.previewRows.length > 0 && (
        <PreviewTable
          rows={state.previewRows} page={state.previewPage} selection={state.previewSelection}
          canEditPrice={canEditPrice} canEditStock={canEditStock} canRollback={isAdmin}
          editsDisabled={editsDisabled}
          onPageChange={p => dispatch({ type: 'PREVIEW_PAGE', page: p })}
          onToggleSelect={id => dispatch({ type: 'PREVIEW_TOGGLE', id })}
          onSelectPage={ids => dispatch({ type: 'PREVIEW_SELECT_PAGE', ids })}
          onDeselectPage={ids => dispatch({ type: 'PREVIEW_DESELECT_PAGE', ids })}
          onClearSelection={() => dispatch({ type: 'PREVIEW_CLEAR_SELECTION' })}
          onSavePrice={handleSavePrice}
          onSaveStock={handleSaveStock}
          onRollback={handleRollback}
        />
      )}

      {/* Sync action bar — visible when preview is ready and user can apply */}
      {state.previewPhase === 'ready' && canApply && state.applyPhase !== 'streaming' && (
        <SyncActionBar
          jobId={jobId} selectionCount={state.previewSelection.size}
          dryRunPhase={state.dryRunPhase} dryRunResult={state.dryRunResult}
          dryRunInvalidated={state.dryRunInvalidated}
          applyPhase={state.applyPhase}
          writebackPhase={state.writebackPhase} writebackMsg={state.writebackMsg}
          cancelPhase={state.cancelPhase} jobCancelled={state.jobCancelled}
          onDryRun={() => { void runDryRun() }}
          onApply={startApply}
          onCancelJob={() => { void cancelJob() }}
          onWriteback={() => { void runWriteback() }}
        />
      )}

      {/* Apply in-progress action bar (simplified — just show Applying…) */}
      {state.applyPhase === 'streaming' && canApply && (
        <div className="bg-bg-card border border-border rounded-lg p-3 flex items-center gap-3">
          <svg viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2.5" className="w-4 h-4 animate-spin flex-shrink-0"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
          <span className="text-[13px] text-text-base">Applying… Do not close this page.</span>
        </div>
      )}

      {/* Dry run panel */}
      {state.dryRunPhase !== 'idle' && (
        <DryRunPanel phase={state.dryRunPhase} error={state.dryRunError}
          result={state.dryRunResult} invalidated={state.dryRunInvalidated} />
      )}

      {/* Apply progress */}
      {state.applyPhase !== 'idle' && (
        <ApplyProgress
          phase={state.applyPhase} error={state.applyError} stalePreview={state.applyStalePreview}
          total={state.applyTotal} completed={state.applyCompleted}
          items={state.applyItems} done={state.applyDone}
          onRetryPreview={startPreviewFetch}
        />
      )}

      {/* Cache refresh log */}
      {state.cacheLog.length > 0 && (
        <CacheRefreshPanel op={state.cacheOp} running={state.cacheRunning} log={state.cacheLog} />
      )}

      </>)}

    </div>
  )
}
