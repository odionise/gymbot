import { useEffect, useState, type FormEvent } from 'react'
import { api } from './api'
import { ProgramView } from './ProgramView'
import type { Template } from './types'

type AdminUser = { telegram_id: number; username: string; display_name: string | null }

export function AdminView() {
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<AdminUser[]>([])
  const [selected, setSelected] = useState<AdminUser | null>(null)
  const [templates, setTemplates] = useState<Template[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => () => api.setAdminTarget(null), [])
  const search = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    setBusy(true)
    try { setMatches(await api.adminUsers(query.trim().replace(/^@/, ''))) }
    catch (err) { setError((err as Error).message) }
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
      <button className="backButton" type="button" onClick={leave}>← <span>К поиску</span></button>
      <span className="adminEyebrow">Программа пользователя</span>
      <h1>@{selected.username}</h1>
      {selected.display_name && <p className="intro">{selected.display_name}</p>}
      {error && <p className="adminError" role="alert">{error}</p>}
      <ProgramView templates={templates} run={run} />
    </> : <>
      <span className="adminEyebrow">Управление программами</span>
      <h1>Пользователи</h1>
      <p className="intro">Найдите пользователя по Telegram username и откройте его программу.</p>
      <form className="adminSearch" onSubmit={search}><label className="field"><span>Telegram username</span><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="@username" autoComplete="off" /></label><button className="primaryButton" type="submit" disabled={busy || query.trim().replace(/^@/, '').length < 3}>Найти</button></form>
      {error && <p className="adminError" role="alert">{error}</p>}
      <div className="adminMatches">{matches.map(user => <button type="button" key={user.telegram_id} onClick={() => open(user)}><span><strong>@{user.username}</strong>{user.display_name && <small>{user.display_name}</small>}</span><span aria-hidden="true">→</span></button>)}</div>
    </>}
  </section>
}
