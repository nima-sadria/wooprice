import { useEffect, useRef } from 'react'

export type SSEErrorReason = 'connection_lost' | 'parse_error'

export function useSSEStream(
  url: string | null,
  onMessage: (data: unknown) => void,
  onError: (reason: SSEErrorReason) => void,
): void {
  const msgRef = useRef(onMessage)
  const errRef = useRef(onError)
  msgRef.current = onMessage
  errRef.current = onError

  // Monotonically incrementing generation counter. Each new EventSource captures
  // the current value; callbacks that see a different value are from a closed or
  // superseded stream and are silently dropped.
  const genRef = useRef(0)

  useEffect(() => {
    if (!url) return

    const gen = ++genRef.current
    const source = new EventSource(url)

    source.onmessage = (e: MessageEvent) => {
      if (gen !== genRef.current) return  // stale — superseded or already closed
      let data: unknown
      try {
        data = JSON.parse(String(e.data))
      } catch {
        source.close()
        genRef.current++  // reject any further queued messages from this source
        errRef.current('parse_error')
        return
      }
      msgRef.current(data)
    }

    source.onerror = () => {
      if (gen !== genRef.current) return  // stale
      source.close()
      genRef.current++  // reject queued onmessage handlers before calling errRef
      errRef.current('connection_lost')
    }

    return () => {
      source.close()
      genRef.current++  // invalidate on URL change or unmount
    }
  }, [url])
}
