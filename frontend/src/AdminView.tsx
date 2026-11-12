import { useEffect, useState } from 'react'
import { api } from './api'
import { ProgramView } from './ProgramView'
import type { Template } from './types'

type AdminUser = { telegram_id: number; username: string | null; display_name: string | null }

export function AdminView() {
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<AdminUser[]>([])
  const [selected, setSelected] = useState<AdminUser | null>(null)
  const [templates, setTemplates] = useState<Template[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  useEffect(() => () => api.setAdminTarget(null), [])
  useEffect(() => {
    let active = true
    const timer = window.setTimeout(async () => {
      setError(''); setBusy(true)
      try {
        const users = await api.adminUsers(query.trim().replace(/^@/, ''))
        if (active) { setMatches(users); setHasMore(users.length === 50) }
      } catch (err) { if (active) setError((err as Error).message) }
      finally { if (active) setBusy(false) }
    }, query ? 250 : 0)
    return () => { active = false; window.clearTimeout(timer) }
  }, [query])
  const loadMore = async () => {
    setBusy(true); setError('')
    try {
      const users = await api.adminUsers(query.trim().replace(/^@/, ''), matches.length)
      setMatches(previous => [...previous, ...users]); setHasMore(users.length === 50)
    } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }
  const open = async (user: AdminUser) => {
    setError('')
    api.setAdminTarget(user.telegram_id)
    try { setTemplates(await api.templates()); setSelected(user) }
    catch (err) { api.setAdminTarget(null); setError((err as Error).message) }
  }
  const leave = () => { api.setAdminTarget(null); setSelected(null); setTemplates([]); setError('') }
  const run = async (action: () => Promise<unknown>) => {
    setError('')
    try { await action() }
    catch (err) { setError((err as Error).message); return }
    try { setTemplates(await api.templates()) }
    catch (err) { setError(`Изменение сохранено, но список не обновился: ${(err as Error).message}`) }
  }
  return <section className="adminView">
    {selected ? <>
      <button className="backButton" type="button" onClick={leave}>← <span>К списку</span></button>
      <span className="adminEyebrow">Программа пользователя</span>
      <h1>{selected.username ? `@${selected.username}` : selected.display_name || `ID ${selected.telegram_id}`}</h1>
      {selected.display_name && <p className="intro">{selected.display_name}</p>}
      {error && <p className="adminError" role="alert">{error}</p>}
      <ProgramView templates={templates} run={run} canEditCatalog onTemplateDeleted={id => setTemplates(items => items.filter(item => item.id !== id))} onTemplateReordered={template => setTemplates(items => items.map(item => item.id === template.id ? template : item))} />
    </> : <>
      <span className="adminEyebrow">Управление программами</span>
      <h1>Пользователи</h1>
      <p className="intro">Все пользователи бота. Поиск по username или имени.</p>
      <div className="adminSearch"><label className="field"><span>Поиск пользователя</span><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="@username или имя" autoComplete="off" /></label></div>
      {error && <p className="adminError" role="alert">{error}</p>}
      <div className="adminMatches">{matches.map(user => <button type="button" key={user.telegram_id} onClick={() => open(user)}><span><strong>{user.username ? `@${user.username}` : user.display_name || `ID ${user.telegram_id}`}</strong><small>{user.username ? user.display_name : `Telegram ID ${user.telegram_id}`}</small></span><span aria-hidden="true">→</span></button>)}</div>
      {!busy && !error && matches.length === 0 && <p className="intro">Пользователи не найдены.</p>}
      {hasMore && <button className="outlineButton" type="button" disabled={busy} onClick={loadMore}>{busy ? 'Загружаем…' : 'Показать ещё'}</button>}
    </>}
  </section>
}
