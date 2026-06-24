import { describe, it, expect } from 'vitest'
import { isAutoSelectEligible, type PreviewRowEligibilityInput } from './previewEligibility'

// Helper to build minimal row fixtures
function row(changed: boolean, change_status?: string): PreviewRowEligibilityInput {
  return { changed, change_status }
}

// ── Scenario 1: Changed rows auto-selected after Preview ─────────────────────
describe('Scenario 1 — changed rows are auto-selected', () => {
  it('selects a row with change_status="changed"', () => {
    expect(isAutoSelectEligible(row(true, 'changed'))).toBe(true)
  })

  it('selects a changed row when change_status is absent (changed=true fallback)', () => {
    expect(isAutoSelectEligible(row(true))).toBe(true)
  })
})

// ── Scenario 2: Warning-only changed rows auto-selected ──────────────────────
// At preview time there is no separate per-row warning status. Rows that will
// trigger dry-run warnings arrive as change_status='changed' or 'new'.
// They must be auto-selected so the user can proceed to Dry Run without
// manually re-selecting every row.
describe('Scenario 2 — warning-only changed rows are auto-selected', () => {
  it('selects a row with change_status="new" (new product, may trigger dry-run warnings)', () => {
    expect(isAutoSelectEligible(row(true, 'new'))).toBe(true)
  })

  it('selects a changed row regardless of downstream dry-run warning potential', () => {
    // Auto-selection does not evaluate dry-run outcome — only status classification.
    expect(isAutoSelectEligible(row(true, 'changed'))).toBe(true)
  })
})

// ── Scenario 3: Hard error rows not auto-selected ────────────────────────────
describe('Scenario 3 — hard error and blocking rows are NOT auto-selected', () => {
  it('does not select a row with change_status="invalid"', () => {
    expect(isAutoSelectEligible(row(true, 'invalid'))).toBe(false)
  })

  it('does not select a row with change_status="missing_from_wc_cache"', () => {
    expect(isAutoSelectEligible(row(false, 'missing_from_wc_cache'))).toBe(false)
  })

  it('does not select an unchanged row', () => {
    expect(isAutoSelectEligible(row(false, 'unchanged'))).toBe(false)
  })

  it('does not select an unchanged row when change_status is absent (changed=false fallback)', () => {
    expect(isAutoSelectEligible(row(false))).toBe(false)
  })

  it('does not select a row with an unrecognised future status (safe default = excluded)', () => {
    expect(isAutoSelectEligible(row(true, 'some_future_status'))).toBe(false)
  })
})

// ── Scenario 4: Mixed result — only eligible rows selected ───────────────────
describe('Scenario 4 — mixed preview result selects only eligible rows', () => {
  type RowWithId = PreviewRowEligibilityInput & { product_id: number }

  it('selects changed and new rows; excludes unchanged, invalid, and cache-missing rows', () => {
    const rows: RowWithId[] = [
      { changed: true,  change_status: 'changed',               product_id: 10 },
      { changed: true,  change_status: 'new',                   product_id: 20 },
      { changed: false, change_status: 'unchanged',             product_id: 30 },
      { changed: true,  change_status: 'invalid',               product_id: 40 },
      { changed: false, change_status: 'missing_from_wc_cache', product_id: 50 },
    ]
    const selected = rows.filter(isAutoSelectEligible).map(r => r.product_id)
    expect(selected).toEqual([10, 20])
  })

  it('returns empty list when all rows are unchanged or errored', () => {
    const rows: RowWithId[] = [
      { changed: false, change_status: 'unchanged',  product_id: 1 },
      { changed: true,  change_status: 'invalid',    product_id: 2 },
    ]
    expect(rows.filter(isAutoSelectEligible)).toHaveLength(0)
  })

  it('selects all rows when every row is eligible', () => {
    const rows: RowWithId[] = [
      { changed: true, change_status: 'changed', product_id: 1 },
      { changed: true, change_status: 'new',     product_id: 2 },
    ]
    const selected = rows.filter(isAutoSelectEligible).map(r => r.product_id)
    expect(selected).toEqual([1, 2])
  })
})

// ── Scenario 5: Existing protections remain intact ───────────────────────────
// isAutoSelectEligible classifies INITIAL selection only. Dry Run and Apply
// gating are untouched — this function has no access to and makes no decision
// about those code paths.
describe('Scenario 5 — eligibility function does not bypass safety protections', () => {
  it('does not grant apply eligibility — function only classifies initial selection', () => {
    // A row marked eligible here still goes through Dry Run before Apply is enabled.
    // The function returns a boolean classification; it does not write any state or
    // modify the Dry Run / Apply protection invariants.
    const eligible = isAutoSelectEligible({ changed: true, change_status: 'changed' })
    expect(typeof eligible).toBe('boolean')
    // Eligible = true means the row enters the selection set.
    // It does NOT mean Apply is permitted — Dry Run gating is unchanged.
    expect(eligible).toBe(true)
  })

  it('invalid rows remain ineligible regardless of changed flag', () => {
    expect(isAutoSelectEligible({ changed: true, change_status: 'invalid' })).toBe(false)
  })
})
