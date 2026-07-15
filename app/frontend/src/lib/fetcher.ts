import type { ApiResponse } from "@/lib/contracts"

/** Error carrying the HTTP status so callers can special-case 403/404 etc. */
export class ApiError extends Error {
  status: number
  body: unknown
  constructor(message: string, status: number, body: unknown) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.body = body
  }
}

/**
 * Fetch a JSON endpoint and unwrap the standard `{ data, meta }` envelope,
 * returning just the `data` payload typed as `T`. All API paths are relative
 * (`/api/...`) so the same code works behind the Vite dev proxy and when the
 * SPA is served by FastAPI in production.
 */
export async function fetchData<T>(path: string): Promise<T> {
  const res = await fetch(path, {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  })

  if (!res.ok) {
    let body: unknown = null
    try {
      body = await res.json()
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(
      `Request to ${path} failed with ${res.status}`,
      res.status,
      body,
    )
  }

  const json = (await res.json()) as ApiResponse<T>
  return json.data
}

/** Raw fetch of the envelope (data + provenance meta) when meta is needed. */
export async function fetchEnvelope<T>(path: string): Promise<ApiResponse<T>> {
  const res = await fetch(path, {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  })
  if (!res.ok) {
    throw new ApiError(
      `Request to ${path} failed with ${res.status}`,
      res.status,
      null,
    )
  }
  return (await res.json()) as ApiResponse<T>
}

/** Build a query string, dropping null/undefined/empty values. */
export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const usp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "") continue
    usp.set(k, String(v))
  }
  const s = usp.toString()
  return s ? `?${s}` : ""
}
