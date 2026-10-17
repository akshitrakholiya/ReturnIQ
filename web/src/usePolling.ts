import { useEffect, useRef, useState } from 'react'

/** Calls `fn` now and every `ms` until `stop(result)` is true. Returns the latest result/error. */
export function usePolling<T>(fn: () => Promise<T>, stop: (v: T) => boolean, ms = 2500, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fnRef = useRef(fn)
  fnRef.current = fn
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    const tick = async () => {
      try {
        const v = await fnRef.current()
        if (!alive) return
        setData(v); setError(null)
        if (stop(v)) return
      } catch (e) {
        if (!alive) return
        setError(e instanceof Error ? e.message : String(e))
      }
      timer = setTimeout(tick, ms)
    }
    tick()
    return () => { alive = false; clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return { data, error, setData }
}
