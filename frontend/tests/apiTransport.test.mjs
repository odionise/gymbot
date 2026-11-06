import assert from 'node:assert/strict'
import test from 'node:test'
import { fetchApi } from '../src/apiTransport.ts'

test('Cloudflare 530 recovers after a 20-second tunnel reconnection', async () => {
  let elapsed = 0
  let calls = 0
  const result = await fetchApi('/api/templates', {}, {
    fetcher: async () => {
      calls++
      return new Response(elapsed < 20000 ? 'error code: 1033' : '[{"name":"Day A"}]', {
        status: elapsed < 20000 ? 530 : 200,
      })
    },
    sleep: async delay => { elapsed += delay },
  })
  assert.equal(result.status, 200)
  assert.deepEqual(await result.json(), [{ name: 'Day A' }])
  assert.equal(calls, 5)
  assert.equal(elapsed, 23000)
})

test('persistent Cloudflare 530 stops after the bounded retry window', async () => {
  let calls = 0
  let elapsed = 0
  const result = await fetchApi('/api/templates', {}, {
    fetcher: async () => { calls++; return new Response('error code: 1033', { status: 530 }) },
    sleep: async delay => { elapsed += delay },
  })
  assert.equal(result.status, 530)
  assert.equal(await result.text(), 'error code: 1033')
  assert.equal(calls, 5)
  assert.equal(elapsed, 23000)
})

test('gateway interruptions are retried and the successful response is preserved', async () => {
  const statuses = [502, 503, 504, 530, 200]
  const delays = []
  const options = { headers: { Authorization: 'tma synthetic-test-payload' } }
  let calls = 0
  const result = await fetchApi('/api/templates', options, {
    fetcher: async (input, actualOptions) => {
      assert.equal(input, '/api/templates')
      assert.equal(actualOptions, options)
      return new Response(JSON.stringify([{ name: 'Day A' }, { name: 'Day B' }]), { status: statuses[calls++] })
    }, sleep: async delay => { delays.push(delay) },
  })
  assert.equal(result.status, 200)
  assert.equal((await result.json()).length, 2)
  assert.equal(calls, 5)
  assert.deepEqual(delays, [1000, 3000, 7000, 12000])
})

test('persistent gateway failure is bounded and returned as an error response', async () => {
  let calls = 0
  const result = await fetchApi('/api/templates', {}, {
    fetcher: async () => { calls++; return new Response('gateway unavailable', { status: 502 }) },
    sleep: async () => {},
  })
  assert.equal(calls, 5)
  assert.equal(result.status, 502)
  assert.equal(await result.text(), 'gateway unavailable')
})

for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
  for (const status of [502, 530]) {
    test(`${method} is never replayed after HTTP ${status}`, async () => {
      let calls = 0
      const result = await fetchApi('/api/session-exercises/synthetic/sets/1', { method, body: '{}' }, {
        fetcher: async () => { calls++; return new Response('', { status }) },
        sleep: async () => assert.fail('A write must not be retried'),
      })
      assert.equal(result.status, status)
      assert.equal(calls, 1)
    })
  }
}

for (const status of [400, 401, 403, 404, 422, 500]) {
  test(`HTTP ${status} is not retried`, async () => {
    let calls = 0
    const result = await fetchApi('/api/me', {}, {
      fetcher: async () => { calls++; return new Response('', { status }) },
      sleep: async () => assert.fail('Only transient gateway responses should be retried'),
    })
    assert.equal(result.status, status)
    assert.equal(calls, 1)
  })
}

test('a POST carried by a Request object is not replayed after Cloudflare 530', async () => {
  let calls = 0
  const request = new Request('http://127.0.0.1/api/sets', { method: 'POST', body: '{}' })
  const response = await fetchApi(request, {}, {
    fetcher: async () => { calls++; return new Response('', { status: 530 }) },
    sleep: async () => assert.fail('Request-object writes must not be replayed'),
  })
  assert.equal(response.status, 530)
  assert.equal(calls, 1)
})

test('five concurrent startup loads recover only the interrupted request', async () => {
  const paths = ['/me', '/templates', '/sessions/today', '/sessions', '/next-week']
  const calls = new Map()
  const responses = await Promise.all(paths.map(path => fetchApi('/api' + path, {}, {
    fetcher: async input => {
      const count = (calls.get(input) ?? 0) + 1
      calls.set(input, count)
      return new Response('{}', { status: input === '/api/templates' && count === 1 ? 502 : 200 })
    }, sleep: async () => {},
  })))
  assert.ok(responses.every(response => response.status === 200))
  assert.deepEqual([...calls.values()].sort(), [1, 1, 1, 1, 2])
})

test('network rejection and an aborted request are not replayed', async () => {
  let calls = 0
  await assert.rejects(fetchApi('/api/me', {}, {
    fetcher: async () => { calls++; throw new TypeError('synthetic network failure') },
    sleep: async () => assert.fail('Network rejection must propagate'),
  }), /synthetic network failure/)
  assert.equal(calls, 1)
  const controller = new AbortController()
  controller.abort()
  const result = await fetchApi('/api/me', { signal: controller.signal }, {
    fetcher: async () => new Response('', { status: 502 }),
    sleep: async () => assert.fail('An aborted request must not be retried'),
  })
  assert.equal(result.status, 502)
})
