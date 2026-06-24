// Row eligibility for auto-selection after Preview completes.
// Pure function — no React deps, independently testable.
//
// Returns true for rows that represent actual changes (changed, new).
// Hard error rows (invalid, missing_from_wc_cache) and unchanged rows are excluded.
// Dry Run and Apply safety gates are NOT bypassed — they remain the sole arbiters
// of what is actually applied. Auto-selection only sets the initial selection state.

export interface PreviewRowEligibilityInput {
  changed: boolean
  change_status?: string
}

export function isAutoSelectEligible(row: PreviewRowEligibilityInput): boolean {
  const status = row.change_status ?? (row.changed ? 'changed' : 'unchanged')
  return status === 'changed' || status === 'new'
}
