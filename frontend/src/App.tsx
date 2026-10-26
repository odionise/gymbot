import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { HistoryView } from './HistoryView'
import { ProgramView } from './ProgramView'
import { ProgressView } from './ProgressView'
import { WorkoutView } from './WorkoutView'
import { IconAdjustmentsHorizontal, IconCalendarWeek, IconChartLine, IconHistory } from '@tabler/icons-react'
import type { Me, Template, WorkoutSession } from './types'

type Tab = 'today' | 'progress' | 'history' | 'program'
const weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
export const phaseText = { light: 'Лёгкая', medium: 'Средняя', heavy: 'Тяжёлая' }
export const formatWeight = (weight: number) => weight.toLocaleString('ru-RU', { maximumFractionDigits: 2 })
export function countWord(count: number, one: string, few: string, many: string) {
  const lastTwo = count % 100
  if (lastTwo >= 11 && lastTwo <= 14) return many
  const last = count % 10
  return last === 1 ? one : last >= 2 && last <= 4 ? few : many
}

function NavIcon({ name }: { name: Tab }) {
  const icons: Record<Tab, React.ReactNode> = {
    today: <IconCalendarWeek aria-hidden="true" stroke={1.7} />,
    progress: <IconChartLine aria-hidden="true" stroke={1.7} />,
    history: <IconHistory aria-hidden="true" stroke={1.7} />,
    program: <IconAdjustmentsHorizontal aria-hidden="true" stroke={1.7} />,
  }
  return icons[name]
}

export default function App() {
  const [tab, setTab] = useState<Tab>('today')
  const [me, setMe] = useState<Me | null>(null)
  const [templates, setTemplates] = useState<Template[]>([])
  const [sessions, setSessions] = useState<WorkoutSession[]>([])
  const [completedToday, setCompletedToday] = useState<WorkoutSession[]>([])
  const [selected, setSelected] = useState<WorkoutSession | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    const [profile, program, today, history] = await Promise.all([api.me(), api.templates(), api.today(), api.history()])
    const dateParts = new Intl.DateTimeFormat('en-US', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone: profile.timezone }).formatToParts(new Date())
    const part = (type: string) => dateParts.find(item => item.type === type)?.value ?? ''
    const localDate = `${part('year')}-${part('month')}-${part('day')}`
    setMe(profile)
    setTemplates(program)
    setSessions(today)
    setCompletedToday(history.filter(item => item.scheduled_date === localDate))
  }, [])

  useEffect(() => {
    refresh().then(async () => {
      const sessionId = new URLSearchParams(window.location.search).get('session')
      if (sessionId) {
        try { setSelected(await api.session(sessionId)) } catch { /* expired deep link */ }
      }
    }).catch((err: Error) => setError(err.message)).finally(() => setLoading(false))
  }, [refresh])

  useEffect(() => {
    const color = '#f5f6f7'
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', color)
    document.documentElement.style.backgroundColor = color
    document.body.style.backgroundColor = color
    window.Telegram?.WebApp?.setHeaderColor?.(color)
    window.Telegram?.WebApp?.setBackgroundColor?.(color)
  }, [selected])

  const run = async (action: () => Promise<unknown>) => {
    setError('')
    try { await action(); await refresh() } catch (err) { setError((err as Error).message) }
  }

  const openSession = async (id: string) => {
    await run(async () => setSelected(await api.session(id)))
  }

  const startSession = async (id: string) => {
    await run(async () => { setSelected(await api.start(id)); setTab('today') })
  }

  if (loading) return <div className="loading"><span className="loadingMark" />Загружаем тренировку<span className="loadingDots">…</span></div>

  const todayLabel = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', weekday: 'long', timeZone: me?.timezone || 'Europe/Moscow' }).format(new Date())
  const completedSets = completedToday.reduce((sum, item) => sum + item.exercises.reduce((count, exercise) => count + exercise.results.length, 0), 0)
  return <div className={`appShell ${selected && selected.status !== 'completed' ? 'isWorkout' : ''}`}>
    {error && <div className="errorToast" role="alert"><span>{error}</span><button onClick={() => setError('')} aria-label="Закрыть сообщение об ошибке">×</button></div>}

    <main className="page">
      {selected && selected.status !== 'completed' ? <WorkoutView
        session={selected}
        onChange={setSelected}
        onBack={() => { setSelected(null); refresh().catch((err: Error) => setError(err.message)) }}
        onComplete={() => { setSelected(null); refresh().catch((err: Error) => setError(err.message)); setTab('history') }}
        onError={setError}
      /> : tab === 'today' ? <>
        <div className="eyebrow">{todayLabel}</div>
        <h1>Сегодня</h1>
        {sessions.length ? <div className="sessionList">{sessions.map(session =>
          <article className="heroSession" key={session.id}>
            <div className="heroTop"><span className="heroKicker">Тренировка по плану</span><span className={`phasePill phase-${session.phase}`}>{phaseText[session.phase]}</span></div>
            <h2 className="heroTitle">{session.template_name}</h2>
            <div className="heroMeta">{session.muscle_group} · {session.exercises.length} {countWord(session.exercises.length, 'упражнение', 'упражнения', 'упражнений')}</div>
            <div className="phaseRail" aria-label={`Фаза цикла: ${phaseText[session.phase]}`}><span className={session.phase === 'light' ? 'current' : ''} /><span className={session.phase === 'medium' ? 'current' : ''} /><span className={session.phase === 'heavy' ? 'current' : ''} /></div>
            <div className="heroExercises">{session.exercises.slice(0, 3).map(item => <div className="heroExercise" key={item.id}><span>{item.name}</span><strong>{formatWeight(item.target_weight)} кг · {item.sets_count} × {item.target_reps}</strong></div>)}{session.exercises.length > 3 && <span className="heroMore">И ещё {session.exercises.length - 3}</span>}</div>
            <button className="heroFooter" onClick={() => openSession(session.id)}><span>{session.status === 'in_progress' ? 'Продолжить тренировку' : 'Начать тренировку'}</span><span aria-hidden="true">→</span></button>
          </article>
        )}</div> : error ? <div className="emptyCard"><div className="emptyIcon">!</div><span className="emptyOverline">Данные недоступны</span><h2>План не загрузился.</h2><p>Проверьте соединение и попробуйте ещё раз.</p><button className="outlineButton" onClick={() => { setError(''); refresh().catch((err: Error) => setError(err.message)) }}>Повторить загрузку</button></div> : completedToday.length ? <div className="completedSession"><div className="completedTop"><span>Тренировка завершена</span><span className="completedSymbol" aria-hidden="true">✓</span></div><h2>{completedToday.map(item => item.template_name).join(' · ')}</h2><p>{completedSets} {countWord(completedSets, 'записанный подход', 'записанных подхода', 'записанных подходов')}</p><button onClick={() => setTab('history')}>Посмотреть результаты <span aria-hidden="true">→</span></button></div> : <div className="emptyCard"><div className="emptyIcon">—</div><span className="emptyOverline">Пауза в расписании</span><h2>Сегодня без зала.</h2><p>Восстановление — часть плана. Можно открыть тренировку вручную.</p></div>}
        <div className="sectionHead"><h2>Ваши тренировки</h2><span>{templates.length}</span></div>
        {templates.length ? <div className="templateList">{templates.map((template, index) =>
          <div className="templateMini" key={template.id}>
            <span className="templateOrder">{index + 1}</span>
            <div className="templateDetails"><strong>{template.name}</strong><small>{completedToday.some(item => item.template_id === template.id) ? 'Завершено сегодня' : `${weekdays[template.weekday]} · ${template.send_time} · далее ${phaseText[template.next_phase].toLowerCase()}`}</small></div>
            <button className="roundButton" onClick={() => completedToday.some(item => item.template_id === template.id) ? setTab('history') : startSession(template.id)} aria-label={completedToday.some(item => item.template_id === template.id) ? `Результаты ${template.name}` : `Начать ${template.name}`}>{completedToday.some(item => item.template_id === template.id) ? '✓' : '→'}</button>
          </div>
        )}</div> : <button className="primaryButton" onClick={() => setTab('program')}>Создать программу <span>↗</span></button>}
        {me && !me.has_started_bot && <p className="hint">Чтобы получать сообщения, сначала отправьте боту команду /start.</p>}
      </> : tab === 'program' ? <ProgramView templates={templates} me={me} refresh={refresh} run={run} />
        : tab === 'progress' ? <ProgressView />
          : <HistoryView />}
    </main>

    {!selected && <nav className="bottomNav" aria-label="Навигация">
      <button className={tab === 'today' ? 'active' : ''} onClick={() => setTab('today')}><NavIcon name="today" />Сегодня</button>
      <button className={tab === 'progress' ? 'active' : ''} onClick={() => setTab('progress')}><NavIcon name="progress" />Прогресс</button>
      <button className={tab === 'history' ? 'active' : ''} onClick={() => setTab('history')}><NavIcon name="history" />История</button>
      <button className={tab === 'program' ? 'active' : ''} onClick={() => setTab('program')}><NavIcon name="program" />Программа</button>
    </nav>}
  </div>
}
