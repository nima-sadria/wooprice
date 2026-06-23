import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../auth'
import { fmtPrice } from '../utils/price'
import { readPageSize, writePageSize } from '../utils/pageSize'

// ── Types ─────────────────────────────────────────────────────────────────────

interface Product {
  wc_id: number
  name: string
  sku: string
  price: string
  regular_price: string
  sale_price: string
  stock_status: string
  stock_quantity: number | null
  categories: { id: number; name: string }[]
  product_type: string
  parent_id: number
  last_synced_at: string | null
  image_url: string | null
  image_source: string
}

interface Category {
  id: number
  name: string
}

interface ApiPage {
  page: number
  limit: number
  total: number
  total_pages: number
  items: Product[]
}

type SortValue = 'newest' | 'oldest' | 'name_asc' | 'name_desc'
type StockFilter = '' | 'instock' | 'outofstock'
type PriceFilter = '' | 'has_price' | 'no_price'
type TypeFilter = '' | 'simple' | 'variable' | 'variation'

// ── Constants ─────────────────────────────────────────────────────────────────

const SORT_OPTIONS: { value: SortValue; label: string }[] = [
  { value: 'newest', label: 'Newest First' },
  { value: 'oldest', label: 'Oldest First' },
  { value: 'name_asc', label: 'Name A→Z' },
  { value: 'name_desc', label: 'Name Z→A' },
]

const PAGE_SIZES = [10, 20, 30, 40, 50]

const STOCK_OPTS: { value: StockFilter; label: string }[] = [
  { value: '', label: 'All Stock' },
  { value: 'instock', label: 'In Stock' },
  { value: 'outofstock', label: 'Out of Stock' },
]

const PRICE_OPTS: { value: PriceFilter; label: string }[] = [
  { value: '', label: 'All Prices' },
  { value: 'has_price', label: 'Has Price' },
  { value: 'no_price', label: 'No Price' },
]

const TYPE_OPTS: { value: TypeFilter; label: string }[] = [
  { value: '', label: 'All Types' },
  { value: 'simple', label: 'Simple' },
  { value: 'variable', label: 'Variable' },
  { value: 'variation', label: 'Variation' },
]

const QUALITY_OPTS = [
  { key: 'missing_sku', label: 'Missing SKU' },
  { key: 'missing_image', label: 'Missing Image' },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function stockBadge(s: string) {
  if (s === 'instock') return { cls: 'bg-green-100 text-green-700', label: 'In Stock' }
  if (s === 'outofstock') return { cls: 'bg-red-100 text-red-700', label: 'Out of Stock' }
  if (s === 'onbackorder') return { cls: 'bg-amber-100 text-amber-700', label: 'Backorder' }
  return { cls: 'bg-gray-100 text-gray-600', label: s }
}

function typeCls(t: string) {
  if (t === 'simple') return 'bg-blue-100 text-blue-700'
  if (t === 'variable') return 'bg-purple-100 text-purple-700'
  if (t === 'variation') return 'bg-indigo-100 text-indigo-700'
  return 'bg-gray-100 text-gray-600'
}

function relTime(iso: string | null): string {
  if (!iso) return '—'
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

// ── CategoryPicker ─────────────────────────────────────────────────────────────

interface CatPickerProps {
  all: Category[]
  selected: number[]
  onChange: (ids: number[]) => void
}

function CategoryPicker({ all, selected, onChange }: CatPickerProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setSearch('')
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const filtered = useMemo(
    () => search.trim() ? all.filter(c => c.name.toLowerCase().includes(search.toLowerCase())) : all,
    [all, search],
  )

  const selSet = useMemo(() => new Set(selected), [selected])

  function toggle(id: number) {
    onChange(selSet.has(id) ? selected.filter(x => x !== id) : [...selected, id])
  }

  const selCats = useMemo(() => all.filter(c => selSet.has(c.id)), [all, selSet])

  return (
    <div ref={ref} className="relative flex-shrink-0">
      <button
        type="button"
        onClick={() => { setOpen(o => !o); setTimeout(() => inputRef.current?.focus(), 50) }}
        className={[
          'flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-[13px] font-medium transition-colors whitespace-nowrap',
          open || selected.length > 0
            ? 'border-accent text-accent bg-accent/5'
            : 'border-border text-wp-muted bg-bg-card hover:border-accent/40 hover:text-text-base',
        ].join(' ')}
      >
        <svg viewBox="0 0 24 24" className="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M4 6h16M7 12h10M10 18h4" />
        </svg>
        {selected.length > 0 ? `${selected.length} Categor${selected.length === 1 ? 'y' : 'ies'}` : 'Category'}
        {selected.length > 0 && (
          <span
            role="button"
            tabIndex={0}
            onKeyDown={e => e.key === 'Enter' && onChange([])}
            onClick={e => { e.stopPropagation(); onChange([]) }}
            className="ml-0.5 w-4 h-4 flex items-center justify-center rounded-full hover:bg-accent/20"
          >
            <svg viewBox="0 0 24 24" className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth="3"><path d="M18 6 6 18M6 6l12 12" /></svg>
          </span>
        )}
      </button>

      {open && (
        <div className="absolute top-full mt-1 left-0 z-50 w-72 bg-bg-card border border-border rounded-xl shadow-xl overflow-hidden">
          <div className="p-2 border-b border-border">
            <div className="flex items-center gap-2 px-2 py-1.5 bg-bg-base rounded-lg">
              <svg viewBox="0 0 24 24" className="w-3.5 h-3.5 text-wp-muted flex-shrink-0" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
              </svg>
              <input
                ref={inputRef}
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search categories…"
                className="flex-1 bg-transparent text-[13px] text-text-base placeholder:text-wp-muted outline-none"
              />
              {search && (
                <button onClick={() => setSearch('')} className="text-wp-muted hover:text-text-base">
                  <svg viewBox="0 0 24 24" className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth="3"><path d="M18 6 6 18M6 6l12 12" /></svg>
                </button>
              )}
            </div>
          </div>

          <div className="max-h-60 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <p className="text-center text-[12px] text-wp-muted py-5">No categories found</p>
            ) : filtered.map(cat => (
              <button
                key={cat.id}
                type="button"
                onClick={() => toggle(cat.id)}
                className="w-full flex items-center gap-2.5 px-3 py-1.5 text-[13px] text-text-base hover:bg-bg-base transition-colors text-left"
              >
                <span className={[
                  'w-4 h-4 rounded flex items-center justify-center border flex-shrink-0 transition-colors',
                  selSet.has(cat.id) ? 'bg-accent border-accent' : 'border-border bg-bg-card',
                ].join(' ')}>
                  {selSet.has(cat.id) && (
                    <svg viewBox="0 0 24 24" className="w-2.5 h-2.5 text-white" fill="none" stroke="currentColor" strokeWidth="3.5"><polyline points="20 6 9 17 4 12" /></svg>
                  )}
                </span>
                <span className="truncate">{cat.name}</span>
              </button>
            ))}
          </div>

          {selected.length > 0 && (
            <div className="border-t border-border px-3 py-2 flex items-center justify-between">
              <span className="text-[12px] text-wp-muted">{selected.length} selected</span>
              <button onClick={() => { onChange([]); setOpen(false) }} className="text-[12px] text-accent hover:underline">
                Clear all
              </button>
            </div>
          )}
        </div>
      )}

      {selCats.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1.5">
          {selCats.map(cat => (
            <span key={cat.id} className="inline-flex items-center gap-1 px-2 py-0.5 bg-accent/10 text-accent text-[11px] rounded-full">
              {cat.name}
              <button onClick={() => toggle(cat.id)} className="hover:text-accent/60">
                <svg viewBox="0 0 24 24" className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth="3"><path d="M18 6 6 18M6 6l12 12" /></svg>
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Chip ──────────────────────────────────────────────────────────────────────

function Chip({ label, onRemove, amber }: { label: string; onRemove: () => void; amber?: boolean }) {
  return (
    <span className={[
      'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium',
      amber ? 'bg-amber-100 text-amber-700' : 'bg-accent/10 text-accent',
    ].join(' ')}>
      {label}
      <button onClick={onRemove} className="hover:opacity-60">
        <svg viewBox="0 0 24 24" className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth="3"><path d="M18 6 6 18M6 6l12 12" /></svg>
      </button>
    </span>
  )
}

// ── Skeleton row ──────────────────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <tr className="border-b border-border/50">
      <td className="px-3 py-2.5"><div className="w-9 h-9 bg-border/40 rounded-lg animate-pulse" /></td>
      <td className="px-3 py-2.5">
        <div className="h-3.5 bg-border/40 rounded animate-pulse w-36 mb-1.5" />
        <div className="h-2.5 bg-border/30 rounded animate-pulse w-20" />
      </td>
      <td className="px-3 py-2.5"><div className="h-3 bg-border/40 rounded animate-pulse w-10" /></td>
      <td className="px-3 py-2.5"><div className="h-5 bg-border/40 rounded animate-pulse w-16" /></td>
      <td className="px-3 py-2.5"><div className="h-5 bg-border/40 rounded animate-pulse w-20" /></td>
      <td className="px-3 py-2.5"><div className="h-3 bg-border/40 rounded animate-pulse w-20" /></td>
      <td className="px-3 py-2.5"><div className="h-3 bg-border/40 rounded animate-pulse w-24" /></td>
      <td className="px-3 py-2.5"><div className="h-3 bg-border/40 rounded animate-pulse w-12" /></td>
    </tr>
  )
}

// ── Product row ───────────────────────────────────────────────────────────────

function ProductRow({ p }: { p: Product }) {
  const stock = stockBadge(p.stock_status)
  return (
    <tr className="border-b border-border/50 hover:bg-bg-base/60 transition-colors">
      <td className="px-3 py-2">
        <div className="w-9 h-9 rounded-lg bg-bg-base border border-border overflow-hidden flex-shrink-0 flex items-center justify-center">
          <img
            src={`/api/products/${p.wc_id}/thumb?size=40`}
            alt=""
            className="w-full h-full object-cover"
            loading="lazy"
            onError={e => {
              const el = e.currentTarget
              el.style.display = 'none'
              const parent = el.parentElement
              if (parent && !parent.querySelector('svg')) {
                parent.innerHTML = '<svg viewBox="0 0 24 24" class="w-5 h-5 text-border" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>'
              }
            }}
          />
        </div>
      </td>

      <td className="px-3 py-2 min-w-0 max-w-[240px]">
        <div className="font-medium text-text-base text-[13px] truncate" title={p.name}>{p.name || '—'}</div>
        {p.sku && <div className="text-[11px] text-wp-muted font-mono mt-0.5 truncate">{p.sku}</div>}
      </td>

      <td className="px-3 py-2">
        <span className="text-[12px] text-wp-muted font-mono">{p.wc_id}</span>
      </td>

      <td className="px-3 py-2">
        <span className={['text-[11px] px-1.5 py-0.5 rounded-md font-medium capitalize', typeCls(p.product_type)].join(' ')}>
          {p.product_type}
        </span>
      </td>

      <td className="px-3 py-2">
        <span className={['text-[11px] px-1.5 py-0.5 rounded-md font-medium', stock.cls].join(' ')}>
          {stock.label}
        </span>
        {p.stock_quantity != null && (
          <div className="text-[11px] text-wp-muted mt-0.5">Qty: {p.stock_quantity}</div>
        )}
      </td>

      <td className="px-3 py-2">
        {p.price ? (
          <span className="text-[13px] font-medium text-text-base">{fmtPrice(p.price)}</span>
        ) : (
          <span className="text-[13px] text-wp-muted">—</span>
        )}
        {p.sale_price && p.sale_price !== p.regular_price && p.regular_price && (
          <div className="text-[11px] text-wp-muted line-through mt-0.5">{fmtPrice(p.regular_price)}</div>
        )}
      </td>

      <td className="px-3 py-2 max-w-[160px]">
        <div className="flex flex-wrap gap-0.5">
          {p.categories.slice(0, 2).map(c => (
            <span key={c.id} className="text-[11px] px-1.5 py-0.5 bg-bg-base border border-border rounded-md text-wp-muted whitespace-nowrap">
              {c.name}
            </span>
          ))}
          {p.categories.length > 2 && (
            <span className="text-[11px] text-wp-muted px-0.5">+{p.categories.length - 2}</span>
          )}
          {p.categories.length === 0 && <span className="text-[12px] text-wp-muted">—</span>}
        </div>
      </td>

      <td className="px-3 py-2 whitespace-nowrap">
        <span className="text-[12px] text-wp-muted">{relTime(p.last_synced_at)}</span>
      </td>
    </tr>
  )
}

// ── Pagination ────────────────────────────────────────────────────────────────

function Pagination({ page, totalPages, onPage }: { page: number; totalPages: number; onPage: (p: number) => void }) {
  if (totalPages <= 1) return null

  const pages: (number | '…')[] = []
  if (totalPages <= 7) {
    for (let i = 1; i <= totalPages; i++) pages.push(i)
  } else {
    pages.push(1)
    if (page > 3) pages.push('…')
    for (let i = Math.max(2, page - 1); i <= Math.min(totalPages - 1, page + 1); i++) pages.push(i)
    if (page < totalPages - 2) pages.push('…')
    pages.push(totalPages)
  }

  const btnBase = 'w-7 h-7 flex items-center justify-center rounded-lg text-[12px] font-medium border transition-colors'

  return (
    <div className="flex items-center gap-1">
      <button
        onClick={() => onPage(page - 1)} disabled={page === 1}
        className={[btnBase, 'border-border text-wp-muted hover:border-accent hover:text-accent disabled:opacity-30 disabled:cursor-not-allowed'].join(' ')}
      >
        <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="m15 18-6-6 6-6" /></svg>
      </button>
      {pages.map((p, i) =>
        p === '…' ? (
          <span key={`e${i}`} className="w-6 text-center text-[12px] text-wp-muted">…</span>
        ) : (
          <button
            key={p}
            onClick={() => onPage(p as number)}
            className={[
              btnBase,
              p === page ? 'bg-accent text-white border-accent' : 'border-border text-wp-muted hover:border-accent hover:text-accent',
            ].join(' ')}
          >
            {p}
          </button>
        )
      )}
      <button
        onClick={() => onPage(page + 1)} disabled={page === totalPages}
        className={[btnBase, 'border-border text-wp-muted hover:border-accent hover:text-accent disabled:opacity-30 disabled:cursor-not-allowed'].join(' ')}
      >
        <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="m9 18 6-6-6-6" /></svg>
      </button>
    </div>
  )
}

// ── MiniSelect ────────────────────────────────────────────────────────────────

function MiniSelect<T extends string>({ value, onChange, options }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: string }[]
}) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value as T)}
      className="px-2.5 py-1.5 rounded-lg border border-border bg-bg-card text-[13px] text-text-base focus:outline-none focus:border-accent transition-colors cursor-pointer"
    >
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )
}

// ── Products page ─────────────────────────────────────────────────────────────

export default function Products() {
  const { authFetch, user } = useAuth()

  // Filter state
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [stockFilter, setStockFilter] = useState<StockFilter>('')
  const [priceFilter, setPriceFilter] = useState<PriceFilter>('')
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('')
  const [categoryIds, setCategoryIds] = useState<number[]>([])
  const [qualityFilter, setQualityFilter] = useState('')

  // Controls
  const [page, setPage] = useState(1)
  const [limit, setLimit] = useState(readPageSize)
  const [sort, setSort] = useState<SortValue>('newest')

  // Data
  const [products, setProducts] = useState<Product[]>([])
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [categories, setCategories] = useState<Category[]>([])

  // Debounce search input — 350 ms
  useEffect(() => {
    const t = setTimeout(() => { setDebouncedSearch(search); setPage(1) }, 350)
    return () => clearTimeout(t)
  }, [search])

  // Reset page when any filter or control changes
  useEffect(() => { setPage(1) }, [stockFilter, priceFilter, typeFilter, categoryIds, qualityFilter, sort, limit])

  // Fetch category list once on mount
  useEffect(() => {
    authFetch('/api/products/categories')
      .then(r => r.ok ? r.json() : [])
      .then((d: Category[]) => setCategories(d))
      .catch(() => {})
  }, [authFetch])

  // Build query string (memoised so fetch effect only fires when it changes)
  const qs = useMemo(() => {
    const p = new URLSearchParams()
    p.set('page', String(page))
    p.set('limit', String(limit))
    p.set('sort', sort)
    if (debouncedSearch) p.set('search', debouncedSearch)
    if (stockFilter) p.set('stock_status', stockFilter)
    if (priceFilter) p.set('price_status', priceFilter)
    if (typeFilter) p.set('product_type', typeFilter)
    if (qualityFilter) p.set('quality_filter', qualityFilter)
    categoryIds.forEach(id => p.append('category_ids', String(id)))
    return p.toString()
  }, [page, limit, sort, debouncedSearch, stockFilter, priceFilter, typeFilter, qualityFilter, categoryIds])

  // Fetch products
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    authFetch(`/api/products?${qs}`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() as Promise<ApiPage> })
      .then(d => { if (!cancelled) { setProducts(d.items); setTotal(d.total); setTotalPages(d.total_pages); setLoading(false) } })
      .catch(e => { if (!cancelled) { setError(String(e.message ?? e)); setLoading(false) } })
    return () => { cancelled = true }
  }, [authFetch, qs])

  const clearCatIds = useCallback(() => setCategoryIds([]), [])

  function clearAll() {
    setSearch(''); setDebouncedSearch('')
    setStockFilter(''); setPriceFilter(''); setTypeFilter('')
    setCategoryIds([]); setQualityFilter(''); setPage(1)
  }

  const hasFilters = !!(debouncedSearch || stockFilter || priceFilter || typeFilter || categoryIds.length || qualityFilter)

  const start = total === 0 ? 0 : (page - 1) * limit + 1
  const end = Math.min(page * limit, total)

  if (!user?.permissions?.can_fetch) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <p className="text-[14px] text-wp-muted">You don't have permission to view products.</p>
      </div>
    )
  }

  return (
    <div className="min-h-full bg-bg-base">
      <div className="max-w-screen-2xl mx-auto px-5 py-5">

        {/* ── Page header ── */}
        <div className="flex items-center gap-3 mb-4">
          <div className="w-9 h-9 rounded-xl bg-accent/10 flex items-center justify-center flex-shrink-0">
            <svg viewBox="0 0 24 24" className="w-5 h-5 text-accent" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="3" width="20" height="14" rx="2" />
              <path d="M8 21h8M12 17v4" />
            </svg>
          </div>
          <div>
            <h1 className="text-[20px] font-bold text-text-base leading-tight">Products</h1>
            <p className="text-[12px] text-wp-muted">
              {total > 0 ? `${total.toLocaleString()} cached products` : 'Browse and filter your WooCommerce product cache'}
            </p>
          </div>
        </div>

        {/* ── Filter bar ── */}
        <div className="bg-bg-card border border-border rounded-xl p-3 mb-4 space-y-2">

          {/* Row 1: controls */}
          <div className="flex flex-wrap items-center gap-2">

            {/* Search */}
            <div className="relative">
              <svg viewBox="0 0 24 24" className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-wp-muted pointer-events-none" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
              </svg>
              <input
                type="text"
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search name or SKU…"
                className="pl-8 pr-8 py-1.5 w-52 rounded-lg border border-border bg-bg-base text-[13px] placeholder:text-wp-muted focus:outline-none focus:border-accent transition-colors"
              />
              {search && (
                <button onClick={() => setSearch('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-wp-muted hover:text-text-base">
                  <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M18 6 6 18M6 6l12 12" /></svg>
                </button>
              )}
            </div>

            {/* Dropdowns */}
            <MiniSelect value={typeFilter} onChange={setTypeFilter} options={TYPE_OPTS} />
            <MiniSelect value={stockFilter} onChange={setStockFilter} options={STOCK_OPTS} />
            <MiniSelect value={priceFilter} onChange={setPriceFilter} options={PRICE_OPTS} />

            {/* Category multi-select */}
            <CategoryPicker all={categories} selected={categoryIds} onChange={setCategoryIds} />

            {/* Separator */}
            <div className="h-7 w-px bg-border mx-1 hidden sm:block" />

            {/* Quality filters */}
            {QUALITY_OPTS.map(q => (
              <button
                key={q.key}
                onClick={() => setQualityFilter(qualityFilter === q.key ? '' : q.key)}
                title={q.key === 'missing_sku' ? 'Products with no SKU' : 'Products with no image'}
                className={[
                  'flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-[12px] font-medium transition-colors',
                  qualityFilter === q.key
                    ? 'bg-amber-50 border-amber-400 text-amber-700'
                    : 'border-border text-wp-muted hover:border-amber-400 hover:text-amber-700 bg-bg-card',
                ].join(' ')}
              >
                <svg viewBox="0 0 24 24" className="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                  <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
                {q.label}
              </button>
            ))}

            {/* Right side: sort + page size */}
            <div className="flex items-center gap-2 ml-auto">
              <MiniSelect value={sort} onChange={setSort} options={SORT_OPTIONS} />
              <select
                value={limit}
                onChange={e => { const n = Number(e.target.value); setLimit(n); writePageSize(n) }}
                className="px-2.5 py-1.5 rounded-lg border border-border bg-bg-card text-[13px] text-text-base focus:outline-none focus:border-accent transition-colors cursor-pointer"
              >
                {PAGE_SIZES.map(n => <option key={n} value={n}>{n} / page</option>)}
              </select>
            </div>
          </div>

          {/* Row 2: active filter chips */}
          {hasFilters && (
            <div className="flex flex-wrap items-center gap-1.5 pt-1.5 border-t border-border">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-wp-muted mr-1">Filters:</span>
              {debouncedSearch && <Chip label={`"${debouncedSearch}"`} onRemove={() => setSearch('')} />}
              {typeFilter && <Chip label={TYPE_OPTS.find(o => o.value === typeFilter)?.label ?? typeFilter} onRemove={() => setTypeFilter('')} />}
              {stockFilter && <Chip label={STOCK_OPTS.find(o => o.value === stockFilter)?.label ?? stockFilter} onRemove={() => setStockFilter('')} />}
              {priceFilter && <Chip label={PRICE_OPTS.find(o => o.value === priceFilter)?.label ?? priceFilter} onRemove={() => setPriceFilter('')} />}
              {categoryIds.length > 0 && (
                <Chip label={`${categoryIds.length} categor${categoryIds.length === 1 ? 'y' : 'ies'}`} onRemove={clearCatIds} />
              )}
              {qualityFilter && (
                <Chip label={QUALITY_OPTS.find(q => q.key === qualityFilter)?.label ?? qualityFilter} onRemove={() => setQualityFilter('')} amber />
              )}
              <button onClick={clearAll} className="ml-auto text-[12px] text-wp-muted hover:text-wp-red transition-colors">
                Clear all
              </button>
            </div>
          )}
        </div>

        {/* ── Table card ── */}
        <div className="bg-bg-card border border-border rounded-xl overflow-hidden">

          {/* Table toolbar */}
          <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-bg-base/30">
            <span className="text-[12px] text-wp-muted">
              {loading ? 'Loading…' : total === 0 ? 'No products found' : `Showing ${start}–${end} of ${total.toLocaleString()}`}
            </span>
            <Pagination page={page} totalPages={totalPages} onPage={setPage} />
          </div>

          {error && (
            <div className="px-4 py-3 text-[13px] text-wp-red bg-wp-red/5 border-b border-border">
              Failed to load products: {error}
            </div>
          )}

          {/* Table */}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[780px]">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-wp-muted uppercase tracking-wide w-12"></th>
                  <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-wp-muted uppercase tracking-wide">Product</th>
                  <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-wp-muted uppercase tracking-wide w-16">ID</th>
                  <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-wp-muted uppercase tracking-wide w-22">Type</th>
                  <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-wp-muted uppercase tracking-wide w-28">Stock</th>
                  <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-wp-muted uppercase tracking-wide w-28">Price</th>
                  <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-wp-muted uppercase tracking-wide">Categories</th>
                  <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-wp-muted uppercase tracking-wide w-20">Synced</th>
                </tr>
              </thead>
              <tbody className={loading ? 'opacity-40 pointer-events-none' : ''}>
                {loading && products.length === 0
                  ? Array.from({ length: limit }).map((_, i) => <SkeletonRow key={i} />)
                  : products.length === 0
                    ? (
                      <tr>
                        <td colSpan={8} className="px-4 py-14 text-center text-[13px] text-wp-muted">
                          {hasFilters
                            ? 'No products match the current filters.'
                            : 'Product cache is empty. Run a Full Refresh from the Workspace first.'}
                        </td>
                      </tr>
                    )
                    : products.map(p => <ProductRow key={p.wc_id} p={p} />)
                }
              </tbody>
            </table>
          </div>

          {/* Bottom pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-2 border-t border-border">
              <span className="text-[12px] text-wp-muted">{start}–{end} of {total.toLocaleString()}</span>
              <Pagination page={page} totalPages={totalPages} onPage={setPage} />
            </div>
          )}
        </div>

      </div>
    </div>
  )
}
