import assert from 'node:assert/strict'
import test from 'node:test'
import { createSerialQueue } from '../src/asyncQueue.ts'

test('overlapping saves run once in order and cannot publish an older snapshot last', async () => {
  const enqueue = createSerialQueue()
  let release
  const held = new Promise(resolve => { release = resolve })
  const events = []
  const first = enqueue(async () => { events.push('save 1'); await held; events.push('snapshot 1') })
  const second = enqueue(async () => { events.push('save 2'); events.push('snapshot 2') })
  await Promise.resolve()
  assert.deepEqual(events, ['save 1'])
  release()
  await Promise.all([first, second])
  assert.deepEqual(events, ['save 1', 'snapshot 1', 'save 2', 'snapshot 2'])
})

test('a failed save is not replayed and does not block the next explicit action', async () => {
  const enqueue = createSerialQueue()
  let failedCalls = 0
  const failed = enqueue(async () => { failedCalls++; throw new Error('synthetic connection failure') })
  const next = enqueue(async () => 'next action confirmed')
  await assert.rejects(failed, /synthetic connection failure/)
  assert.equal(await next, 'next action confirmed')
  assert.equal(failedCalls, 1)
})
