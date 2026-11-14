import { useCallback, useEffect, useState } from 'react'
import { IconAdjustmentsHorizontal, IconCalendarWeek, IconChartLine, IconHistory, IconShieldLock } from '@tabler/icons-react'
import { api } from './api'
import { AdminView } from './AdminView'
import { HistoryView } from './HistoryView'
import { LoadingScreen } from './LoadingScreen'
import { OneRepFlow } from './OneRepFlow'
import { ProfileForm } from './ProfileForm'
import { ProgramView } from './ProgramView'
import { ProgressView } from './ProgressView'
import { WorkoutView } from './WorkoutView'
import type { Me, Template, WorkoutSession } from './types'

type Tab = 'today' | 'progress' | 'history' | 'program' | 'admin'
export const phaseText = { light: 'Лёгкая', medium: 'Средняя', heavy: 'Тяжёлая', accumulation: 'Накопление', deload: 'Лёгкая', manual: 'Обычная' }
export const formatWeight = (weight: number) => weight.toLocaleString('ru-RU', { maximumFractionDigits: 2 })
export function countWord(count: number, one: string, few: string, many: string) {
  const lastTwo = count % 100
  if (lastTwo >= 11 && lastTwo <= 14) return many
  const last = count % 10
  return last === 1 ? one : last >= 2 && last <= 4 ? few : many
}
const icons = {
  today: <IconCalendarWeek aria-hidden="true" stroke={1.7} />,
  progress: <IconChartLine aria-hidden="true" stroke={1.7} />,
  history: <IconHistory aria-hidden="true" stroke={1.7} />,
  program: <IconAdjustmentsHorizontal aria-hidden="true" stroke={1.7} />,
  admin: <IconShieldLock aria-hidden="true" stroke={1.7} />,
}
export function ProgramPanel({ templates, loadedAt, error, onRetry, run, canEditCatalog, onTemplateDeleted, onTemplateReordered }: {
  templates: Template[]; loadedAt: string | null; error: string; onRetry: () => void
  run: (action: () => Promise<unknown>) => Promise<void>; canEditCatalog: boolean
  onTemplateDeleted?: (id: string) => void; onTemplateReordered?: (template: Template) => void
}) {
  return <>
    {error && <div className="emptyCard" role="status"><h2>{loadedAt ? 'Не удалось обновить программу' : 'Программа не загрузилась'}</h2><p>{loadedAt ? `Показана последняя загруженная версия: ${new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(loadedAt))}.` : 'Проверьте соединение и повторите загрузку.'}</p><button className="outlineButton" onClick={onRetry}>Повторить загрузку</button></div>}
    {loadedAt ? <ProgramView templates={templates} run={run} canEditCatalog={canEditCatalog} onTemplateDeleted={onTemplateDeleted} onTemplateReordered={onTemplateReordered} /> : !error && <div className="emptyCard">Загружаем программу…</div>}
  </>
}
export default function App() {
  const [tab, setTab] = useState<Tab>('today')
  const [me, setMe] = useState<Me | null>(null)
  const [templates, setTemplates] = useState<Template[]>([])
  const [programLoadedAt, setProgramLoadedAt] = useState<string | null>(null)
  const [programError, setProgramError] = useState('')
  const [selected, setSelected] = useState<WorkoutSession | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editingProfile, setEditingProfile] = useState(false)
  const [flowActive, setFlowActive] = useState(false)
  const refresh = useCallback(async () => {
    const profile = await api.me()
    setMe(profile)
    if (!profile.profile_complete) return
    try {
      const program = await api.templates()
      setTemplates(program)
      setProgramLoadedAt(new Date().toISOString())
      setProgramError('')
    } catch (err) { setProgramError((err as Error).message) }
  }, [])
  useEffect(() => {
    refresh().then(async () => {
      const id = new URLSearchParams(window.location.search).get('session')
      if (id) try { setSelected(await api.session(id)) } catch { /* old link */ }
    }).catch(err => setError((err as Error).message)).finally(() => setLoading(false))
  }, [refresh])
  useEffect(() => {
    const color = '#08090b'
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', color)
    document.documentElement.style.backgroundColor = color
    document.body.style.backgroundColor = color
    window.Telegram?.WebApp?.setHeaderColor?.(color)
    window.Telegram?.WebApp?.setBackgroundColor?.(color)
  }, [])
  const run = async (action: () => Promise<unknown>) => {
    setError('')
    try { await action(); await refresh() } catch (err) { setError((err as Error).message) }
  }
  const retry = () => { setError(''); void refresh().catch(err => setError((err as Error).message)) }
  if (loading) return <LoadingScreen />
  if (!me?.profile_complete) return <div className="appShell"><main className="page">{me
    ? <ProfileForm profile={me} onSaved={profile => { setMe(profile); void refresh() }} />
    : <div className="emptyCard" role="alert"><h2>Профиль не загрузился</h2><p>{error}</p><button onClick={retry}>Повторить загрузку</button></div>
  }</main></div>
  return <div className={`appShell ${selected ? 'isWorkout' : ''}`}>
    {error && <div className="errorToast" role="alert"><span>{error}</span><button onClick={() => setError('')} aria-label="Закрыть">×</button></div>}
    <main className="page">
      {selected ? <WorkoutView session={selected} onChange={setSelected} onBack={() => setSelected(null)} onComplete={() => { setSelected(null); setTab('history') }} onError={setError} />
        : tab === 'today' ? <>
          {programError && <div className="oneRepNotice" role="alert">Не удалось загрузить программу: {programError}<button onClick={retry}>Повторить</button></div>}
          {programLoadedAt ? <OneRepFlow templates={templates} onProgram={() => setTab('program')} onActiveChange={setFlowActive} /> : <div className="emptyCard">Загружаем тренировки…</div>}
        </> : tab === 'program' ? <>
          <div className="profileShortcut"><span>{me.display_name}{me.age !== null ? ` · ${me.age} лет` : ''}</span><button type="button" className="textButton" onClick={() => setEditingProfile(!editingProfile)}>{editingProfile ? 'Свернуть анкету' : 'Изменить анкету'}</button></div>
          {editingProfile && <ProfileForm profile={me} onSaved={profile => { setMe(profile); setEditingProfile(false) }} onClose={() => setEditingProfile(false)} />}
          <ProgramPanel templates={templates} loadedAt={programLoadedAt} error={programError} onRetry={retry} run={run} canEditCatalog={me.is_admin}
            onTemplateDeleted={id => setTemplates(items => items.filter(item => item.id !== id))}
            onTemplateReordered={template => setTemplates(items => items.map(item => item.id === template.id ? template : item))} />
        </> : tab === 'progress' ? <ProgressView /> : tab === 'admin' && me.is_admin ? <AdminView /> : <HistoryView />}
    </main>
    {!selected && !flowActive && <nav className="bottomNav" aria-label="Навигация">
      {(['today', 'progress', 'history', 'program', ...(me.is_admin ? ['admin'] : [])] as Tab[]).map(name => <button key={name} className={tab === name ? 'active' : ''} onClick={() => setTab(name)}>{icons[name]}{{ today: 'Тренировка', progress: 'Прогресс', history: 'История', program: 'Программа', admin: 'Админ' }[name]}</button>)}
    </nav>}
  </div>
}
