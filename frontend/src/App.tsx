import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { HistoryView } from './HistoryView'
import { ProgramView } from './ProgramView'
import { ProgressView } from './ProgressView'
import { WorkoutView } from './WorkoutView'
import { IconAdjustmentsHorizontal, IconCalendarWeek, IconChartLine, IconHistory } from '@tabler/icons-react'
import type { Me, NextWeek, Template, WorkoutSession } from './types'

type Tab = 'today' | 'progress' | 'history' | 'program'
const weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
export const phaseText = { light: 'Лёгкая', medium: 'Средняя', heavy: 'Тяжёлая', accumulation: 'Накопление', deload: 'Легкая неделя' }
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
  const [nextWeek, setNextWeek] = useState<NextWeek | null>(null)
  const [weekMenuOpen, setWeekMenuOpen] = useState(false)

  const refresh = useCallback(async () => {
    const [profile, program, today, history, upcoming] = await Promise.all([api.me(), api.templates(), api.today(), api.history(), api.nextWeek()])
    const dateParts = new Intl.DateTimeFormat('en-US', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone: profile.timezone }).formatToParts(new Date())
    const part = (type: string) => dateParts.find(item => item.type === type)?.value ?? ''
    const localDate = `${part('year')}-${part('month')}-${part('day')}`
    setMe(profile)
    setTemplates(program)
    setSessions(today)
    setCompletedToday(history.filter(item => (item.actual_date ?? item.scheduled_date) === localDate))
    setNextWeek(upcoming)
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
  const completedSets = completedToday.reduce((sum, item) => sum + item.exercises.reduce((count, exercise) => count + (exercise.kind === 'strength' ? exercise.results.length : exercise.actual_duration_minutes ? 1 : 0), 0), 0)
  const upcomingLabel = nextWeek ? new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', timeZone: 'UTC' }).format(new Date(`${nextWeek.week_start}T12:00:00Z`)) : ''
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
        <div className="todayHeading"><h1>Сегодня</h1><div className="nextWeekControl"><button className="nextWeekTrigger" type="button" aria-expanded={weekMenuOpen} onClick={() => setWeekMenuOpen(!weekMenuOpen)}>Следующая неделя{nextWeek?.kind ? `: ${nextWeek.kind === 'vacation' ? 'отпуск' : 'легкая'}` : ''} <span aria-hidden="true">⌄</span></button>{weekMenuOpen && <div className="nextWeekMenu"><strong>Неделя с {upcomingLabel}</strong><p>Выберите исключение из обычного плана. Решение можно отменить до начала недели.</p><button className={nextWeek?.kind === 'deload' ? 'selected' : ''} onClick={() => run(async () => { setNextWeek(await api.setNextWeek('deload')); setWeekMenuOpen(false) })}>Легкая неделя <small>Меньше подходов, ПДО 4</small></button><button className={nextWeek?.kind === 'vacation' ? 'selected' : ''} onClick={() => run(async () => { setNextWeek(await api.setNextWeek('vacation')); setWeekMenuOpen(false) })}>Отпуск <small>Без тренировок; цикл продолжится позже</small></button>{nextWeek?.kind && <button className="clearWeek" onClick={() => run(async () => { setNextWeek(await api.clearNextWeek()); setWeekMenuOpen(false) })}>Отменить решение</button>}</div>}</div></div>
        {sessions.length ? <div className="sessionList">{sessions.map(session =>
          <article className="heroSession" key={session.id}>
            <div className="heroTop"><span className="heroKicker">Тренировка по плану</span><span className={`phasePill phase-${session.phase}`}>{phaseText[session.phase]}</span></div>
            <h2 className="heroTitle">{session.template_name}</h2>
            <div className="heroMeta">{session.muscle_group} · {session.exercises.length} {countWord(session.exercises.length, 'упражнение', 'упражнения', 'упражнений')}</div>
            <div className="phaseRail" aria-label={`Фаза цикла: ${phaseText[session.phase]}`}><span className="current" /><span className={session.phase === 'deload' ? 'current' : ''} /></div>
            <div className="heroExercises">{session.exercises.slice(0, 3).map(item => <div className="heroExercise" key={item.id}><span>{item.name}</span><strong>{item.kind === 'strength' ? `${formatWeight(item.target_weight)} кг · ${item.sets_count} × ${item.target_reps}` : `${item.target_duration_minutes} мин`}</strong></div>)}{session.exercises.length > 3 && <span className="heroMore">И ещё {session.exercises.length - 3}</span>}</div>
            <button className="heroFooter" onClick={() => openSession(session.id)}><span>{session.status === 'in_progress' ? 'Продолжить тренировку' : 'Начать тренировку'}</span><span aria-hidden="true">→</span></button>
          </article>
        )}</div> : error ? <div className="emptyCard"><div className="emptyIcon">!</div><span className="emptyOverline">Данные недоступны</span><h2>План не загрузился.</h2><p>Проверьте соединение и попробуйте ещё раз.</p><button className="outlineButton" onClick={() => { setError(''); refresh().catch((err: Error) => setError(err.message)) }}>Повторить загрузку</button></div> : completedToday.length ? <div className="completedSession"><div className="completedTop"><span>Тренировка завершена</span><span className="completedSymbol" aria-hidden="true">✓</span></div><h2>{completedToday.map(item => item.template_name).join(' · ')}</h2><p>{completedSets} записанных результатов</p><button onClick={() => setTab('history')}>Посмотреть результаты <span aria-hidden="true">→</span></button></div> : <div className="emptyCard"><div className="emptyIcon">—</div><span className="emptyOverline">Пауза в расписании</span><h2>Сегодня без тренировки.</h2><p>План можно открыть вручную, если это не неделя отпуска.</p></div>}
        <div className="sectionHead"><h2>Ваши тренировки</h2><span>{templates.length}</span></div>
        {templates.length ? <div className="templateList">{templates.map((template, index) =>
          <div className="templateMini" key={template.id}>
            <span className="templateOrder">{index + 1}</span>
            <div className="templateDetails"><strong>{template.name}</strong><small>{completedToday.some(item => item.template_id === template.id) ? 'Завершено сегодня' : `${weekdays[template.weekday]} · ${template.send_time}`}</small></div>
            <button className="roundButton" onClick={() => completedToday.some(item => item.template_id === template.id) ? setTab('history') : startSession(template.id)} aria-label={completedToday.some(item => item.template_id === template.id) ? `Результаты ${template.name}` : `Начать ${template.name}`}>{completedToday.some(item => item.template_id === template.id) ? '✓' : '→'}</button>
          </div>
        )}</div> : <button className="primaryButton" onClick={() => setTab('program')}>Создать программу</button>}
        {me && !me.has_started_bot && <p className="hint">Чтобы получать сообщения, сначала отправьте боту команду /start.</p>}
        <section className="homeGuide" aria-labelledby="homeGuideTitle">
          <h2 id="homeGuideTitle">Как работает приложение · FAQ</h2>
          <details><summary>С чего начать?</summary><p>В «Списке упражнений» добавьте движения и укажите их тип. Для силового упражнения выберите основную и дополнительные мышцы. В «Программе» создайте тренировочные дни, выберите упражнения и задайте стартовый вес, диапазон повторов и подходы. Для кардио или растяжки задайте длительность в минутах.</p></details>
          <details><summary>Как записывать тренировку?</summary><p>Откройте тренировку с главной страницы или из сообщения бота. После каждого силового подхода запишите вес, повторы и ПДО; значения можно вводить или менять кнопками −/+. Разминку записывайте отдельно. Для упражнения на время укажите фактические минуты. Когда все упражнения заполнены или пропущены, завершите тренировку. Данные сохраняются сразу.</p></details>
          <details><summary>Что такое ПДО и рабочий подход?</summary><p>ПДО — «повторов до отказа»: сколько чистых повторов вы смогли бы сделать ещё. ПДО 2 означает запас около двух повторов. Рабочий подход выполняется после разминки и входит в общий объём. Подход с ПДО не выше 3 дополнительно считается интенсивным для оценки нагрузки.</p></details>
          <details><summary>Как рассчитывается следующий вес и число повторов?</summary><p>Для каждого упражнения и его места в программе приложение смотрит последнюю обычную тренировку. Если все рабочие подходы достигли верхней границы повторов при ПДО не ниже 1, вес повышается на заданный шаг, а повторы возвращаются к нижней границе. Иначе предлагается ещё одно повторение с тем же весом. При признаках усталости повышение откладывается. После записи подхода может появиться подсказка для следующего.</p></details>
          <details><summary>Как работает цикл и легкая неделя?</summary><p>Обычно идут три недели накопления нагрузки и легкая неделя. Объём может расти постепенно по результатам; при усталости план удержит или снизит его. На легкой неделе подходов примерно вдвое меньше, вес не повышается, цель — ПДО 4. Пропуск обычной тренировки сам по себе фазу не переключает. Восстановление оценивается только по новым подходам с указанным ПДО.</p></details>
          <details><summary>Что делают «Легкая неделя» и «Отпуск» в меню сверху?</summary><p>Эти действия назначают исключение на следующую календарную неделю. Внеочередная легкая неделя снижает нагрузку и завершает текущий блок; после неё начнётся новый. Отпуск убирает тренировки на неделю и ставит цикл на паузу. Когда неделя закончится, план продолжится с той же следующей фазы. Выбор можно отменить до начала недели, пока на неё не создана тренировка.</p></details>
          <details><summary>Что показывают графики прогресса?</summary><p>«Рабочие подходы» — недельный объём по мышцам: основной мышце подход даёт 1, дополнительной — 0,5. Отдельно показаны подходы с ПДО ≤ 3, тоннаж, средний ПДО и сопоставимые повторы. e1RM — примерная оценка максимума на один повтор по формуле «вес × (1 + повторы / 30)» для подходов до 10 повторов. Кардио, растяжка, разминка и отпуск в силовую аналитику не входят.</p></details>
          <details><summary>Что делает бот?</summary><p>После команды /start бот присылает план в заданный день и время по вашему часовому поясу (по умолчанию Москва). Откройте Mini App из сообщения для записи результатов. На неделе отпуска уведомлений о тренировках нет.</p></details>
        </section>
      </> : tab === 'program' ? <ProgramView templates={templates} run={run} />
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
