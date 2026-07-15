import { useEffect, useState } from "react"
import { ApiError, fetchData } from "@/lib/fetcher"

export interface ApiState<T> {
  data: T | null
  loading: boolean
  error: ApiError | Error | null
}

/**
 * Minimal data-fetching hook for the `{ data, meta }` envelope. Refetches when
 * `path` changes (e.g. domain key or reporting period), and guards against
 * setting state after unmount / stale responses.
 */
export function useApi<T>(path: string | null): ApiState<T> {
  const [state, setState] = useState<ApiState<T>>({
    data: null,
    loading: path !== null,
    error: null,
  })

  useEffect(() => {
    if (!path) {
      setState({ data: null, loading: false, error: null })
      return
    }
    let cancelled = false
    setState((s) => ({ ...s, loading: true, error: null }))
    fetchData<T>(path)
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null })
      })
      .catch((error: ApiError | Error) => {
        if (!cancelled) setState({ data: null, loading: false, error })
      })
    return () => {
      cancelled = true
    }
  }, [path])

  return state
}
