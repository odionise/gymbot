type Transport = {
  fetcher?: typeof fetch
  sleep?: (milliseconds: number) => Promise<void>
}

// Allow observed tunnel reconnects of up to 20 seconds, including Cloudflare 530.
// Pauses total 23 seconds; persistent failures remain visible after five attempts.
// Writes are never replayed:
// a failed response does not tell us whether a set/result was already saved.
// GET /sessions/today can create plans, but is idempotent for template + date.
export async function fetchApi(input: RequestInfo | URL, options: RequestInit = {}, transport: Transport = {}): Promise<Response> {
  const fetcher = transport.fetcher ?? globalThis.fetch.bind(globalThis)
  const sleep = transport.sleep ?? (milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)))
  const method = options.method ?? (input instanceof Request ? input.method : 'GET')
  const delays = method.toUpperCase() === 'GET' ? [1000, 3000, 7000, 12000] : []
  for (let attempt = 0; ; attempt++) {
    const response = await fetcher(input, options)
    if (![502, 503, 504, 530].includes(response.status) || attempt >= delays.length || options.signal?.aborted) return response
    try { await response.body?.cancel() } catch { /* broken gateway streams can already be closed */ }
    await sleep(delays[attempt])
  }
}
