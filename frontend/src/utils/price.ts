/** Format price as integer with thousands separators and no decimals.
 *  "150000.00" → "150,000"  |  "100000" → "100,000"  |  null/empty → "—" */
export function fmtPrice(p: string | null | undefined): string {
  if (!p || p.trim() === '') return '—'
  const n = parseFloat(p)
  if (isNaN(n)) return p
  return Math.trunc(n).toLocaleString('en')
}

/** Round per emergency price formula:
 *  price ≤ 20,000,000 → nearest 10,000; price > 20,000,000 → nearest 50,000 */
export function emergencyRound(price: number): number {
  const unit = price > 20_000_000 ? 50_000 : 10_000
  return Math.round(price / unit) * unit
}

/** Compute new price from an emergency operation + value, then round. */
export function applyEmergencyOp(
  oldPrice: number,
  operation: 'pct_increase' | 'pct_decrease' | 'fixed_increase' | 'fixed_decrease',
  value: number,
): number {
  let raw: number
  switch (operation) {
    case 'pct_increase':  raw = oldPrice * (1 + value / 100); break
    case 'pct_decrease':  raw = oldPrice * (1 - value / 100); break
    case 'fixed_increase': raw = oldPrice + value; break
    case 'fixed_decrease': raw = oldPrice - value; break
    default: raw = oldPrice
  }
  return raw <= 0 ? 0 : emergencyRound(raw)
}
