type Transport = {
  fetcher?: typeof fetch
  sleep?: (milliseconds: number) => Promise<void>
}

// Recover short gateway interruptions during loading. Writes are never replayed:
// a failed response does not tell us whether a set/result was already saved.
// GET /sessions/today can create plans, but is idempotent for template + date.
export async function fetchApi(input: RequestInfo | URL, options: RequestInit = {}, transport: Transport = {}): Promise<Response> {
  const fetcher = transport.fetcher ?? globalThis.fetch.bind(globalThis)
  const sleep = transport.sleep ?? (milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)))
  const method = options.method ?? (input instanceof Request ? input.method : 'GET')
  const delays = method.toUpperCase() === 'GET' ? [600, 1400, 3000] : []
  for (let attempt = 0; ; attempt++) {
    const response = await fetcher(input, options)
    if (![502, 503, 504].includes(response.status) || attempt >= delays.length || options.signal?.aborted) return response
    try { await response.body?.cancel() } catch { /* broken gateway streams can already be closed */ }
    await sleep(delays[attempt])
  }
}
