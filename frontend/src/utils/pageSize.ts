const KEY = 'wooprice.products.page_size'
const ALLOWED: readonly number[] = [10, 20, 30, 40, 50]
const DEFAULT = 10

export function readPageSize(): number {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (raw === null) return DEFAULT
    const n = Number(raw)
    if (ALLOWED.includes(n)) return n
    return DEFAULT
  } catch {
    return DEFAULT
  }
}

export function writePageSize(n: number): void {
  try {
    sessionStorage.setItem(KEY, String(n))
  } catch {
    // Silently ignore quota/private-browsing errors.
  }
}
