import assert from 'node:assert/strict'
import { before, after, test } from 'node:test'
import { fileURLToPath } from 'node:url'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

let vite
let ProgramPanel
let HistoryEntry
let VolumeGraph
before(async () => {
  vite = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    configFile: false, envDir: false, plugins: [react()], appType: 'custom',
    define: { 'import.meta.env.VITE_DEV_TELEGRAM_ID': '""' },
    server: { middlewareMode: true, watch: null, hmr: false },
  })
  ;({ ProgramPanel } = await vite.ssrLoadModule('/src/App.tsx'))
  ;({ HistoryEntry } = await vite.ssrLoadModule('/src/HistoryView.tsx'))
  ;({ VolumeGraph } = await vite.ssrLoadModule('/src/ProgressCharts.tsx'))
})
after(async () => { await vite?.close() })

const template = (id, name) => ({ id, name, muscle_group: 'Грудь', weekday: 0, send_time: '09:00', exercises: [] })
const render = props => renderToStaticMarkup(React.createElement(ProgramPanel, {
  templates: [], loadedAt: null, error: '', onRetry: () => {}, run: async () => {}, ...props,
}))

test('initial failure does not render a new-program form as if the program were empty', () => {
  const html = render({ error: 'Ошибка 502' })
  assert.match(html, /Программа не загрузилась/)
  assert.match(html, /Повторить загрузку/)
  assert.doesNotMatch(html, /<form|Новая тренировка|Название тренировки/)
})

test('unknown loading state is distinct from a confirmed empty program', () => {
  const html = render({})
  assert.match(html, /Загружаем программу/)
  assert.doesNotMatch(html, /<form|Новая тренировка/)
})

test('confirmed empty program still offers the existing editor', () => {
  const html = render({ loadedAt: '2026-11-03T06:00:00Z' })
  assert.match(html, /<form/)
  assert.match(html, /Новая тренировка/)
})

test('failed refresh retains both cached days with their load timestamp', () => {
  const html = render({
    loadedAt: '2026-11-03T06:00:00Z', error: 'Ошибка 502',
    templates: [template('synthetic-a', 'День A'), template('synthetic-b', 'День B')],
  })
  assert.match(html, /Не удалось обновить программу/)
  assert.match(html, /Показана последняя загруженная версия/)
  assert.match(html, /03\.11\.2026/)
  assert.match(html, /День A/)
  assert.match(html, /День B/)
})

const historySession = {
  id: 'synthetic-session', template_name: 'ДЕМО — День A', muscle_group: 'Грудь',
  scheduled_date: '2026-10-26', actual_date: '2026-11-02', phase: 'accumulation',
  exercises: [{ id: 'synthetic-exercise', name: 'ДЕМО — Жим', kind: 'strength',
    skipped: false, recommendation: null,
    results: [{ set_index: -1, weight: 20, reps: 10, rir_reported: null, is_working: false },
      { set_index: 1, weight: 80, reps: 8, rir_reported: 2, is_working: true }] }],
}

test('history separates actual completion date, planned date, warmup and working RIR', () => {
  const html = renderToStaticMarkup(React.createElement(HistoryEntry, {
    session: historySession, expanded: true, onToggle: () => {},
  }))
  assert.match(html, /2 ноября 2026/)
  assert.match(html, /По плану: <!-- -->26 октября 2026|По плану: 26 октября 2026/)
  assert.match(html, /Разминка 1: 20 кг × 10/)
  assert.match(html, /Подход 1: 80 кг × 8, ПДО 2/)
})

test('unknown historical completion date is not presented as the planned date', () => {
  const html = renderToStaticMarkup(React.createElement(HistoryEntry, {
    session: { ...historySession, actual_date: null }, expanded: false, onToggle: () => {},
  }))
  assert.match(html, /Дата выполнения неизвестна/)
  assert.match(html, /По плану:/)
})

test('overall volume chart has no invented shared muscle target', () => {
  const html = renderToStaticMarkup(React.createElement(VolumeGraph, {
    allMuscles: true, rows: [{ week_start: '2026-10-26', group: 'Все мышцы', phase: 'accumulation',
      working_sets: 2, hard_sets: 1, target_low: null, target_high: null }],
  }))
  assert.match(html, /каждый рабочий подход один раз/)
  assert.doesNotMatch(html, /class="plotTarget"|NaN|Infinity/)
})
