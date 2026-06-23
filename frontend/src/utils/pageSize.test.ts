// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from 'vitest'
import { readPageSize, writePageSize } from './pageSize'

const KEY = 'wooprice.products.page_size'

describe('readPageSize', () => {
  beforeEach(() => sessionStorage.clear())

  it('defaults to 10 when storage is missing', () => {
    expect(readPageSize()).toBe(10)
  })

  it('restores 20 when 20 is stored', () => {
    sessionStorage.setItem(KEY, '20')
    expect(readPageSize()).toBe(20)
  })

  it('restores 50 when 50 is stored', () => {
    sessionStorage.setItem(KEY, '50')
    expect(readPageSize()).toBe(50)
  })

  it('falls back to 10 for invalid stored value (non-numeric)', () => {
    sessionStorage.setItem(KEY, 'banana')
    expect(readPageSize()).toBe(10)
  })

  it('ignores unsupported stored value (not in allowed set)', () => {
    sessionStorage.setItem(KEY, '99')
    expect(readPageSize()).toBe(10)
  })

  it('preserves selection after writePageSize (remount simulation)', () => {
    writePageSize(30)
    expect(readPageSize()).toBe(30)
  })
})
