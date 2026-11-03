import assert from 'node:assert/strict'
import { before, after, test } from 'node:test'
import { fileURLToPath } from 'node:url'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

let vite
let ProgramPanel
before(async () => {
  vite = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    configFile: false, envDir: false, plugins: [react()], appType: 'custom',
    define: { 'import.meta.env.VITE_DEV_TELEGRAM_ID': '""' },
    server: { middlewareMode: true, watch: null, hmr: false },
  })
  ;({ ProgramPanel } = await vite.ssrLoadModule('/src/App.tsx'))
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
