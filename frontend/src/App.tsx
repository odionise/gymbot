import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { HistoryView } from './HistoryView'
import { ProgramView } from './ProgramView'
import { ProgressView } from './ProgressView'
import { WorkoutView } from './WorkoutView'
import { ProfileForm } from './ProfileForm'
import { AdminView } from './AdminView'
import { MuscleDiagram } from './MuscleDiagram'
import { IconAdjustmentsHorizontal, IconCalendarWeek, IconChartLine, IconHistory, IconPlus, IconShieldLock } from '@tabler/icons-react'
import type { Me, NextWeek, Template, WorkoutSession } from './types'

type Tab = 'today' | 'progress' | 'history' | 'program' | 'admin'
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
    admin: <IconShieldLock aria-hidden="true" stroke={1.7} />,
  }
  return icons[name]
}

const faqItems = [
  {
    question: 'С чего начать?',
    paragraphs: [
      'При первом /start или открытии Mini App заполните анкету: пол, имя и дату рождения. Пол выбирает силуэт на карточке; ответы можно изменить в разделе «Программа».',
      'В «Списке упражнений» добавьте движения и укажите их тип. Для силового упражнения выберите основную и дополнительные мышцы.',
      'В «Программе» создайте тренировочные дни, выберите упражнения и задайте стартовый вес, диапазон повторов и подходы. Для кардио или растяжки задайте длительность в минутах.',
    ],
  },
  {
    question: 'Как записывать тренировку?',
    paragraphs: [
      'Откройте тренировку с главной страницы или из сообщения бота. После каждого силового подхода запишите вес, повторы и ПДО. Значения можно вводить или менять кнопками −/+.',
      'Разминку записывайте отдельно. Для упражнения на время укажите фактические минуты.',
      'Когда все упражнения заполнены или пропущены, завершите тренировку. Результаты сохраняются сразу, поэтому к записи можно вернуться позже.',
    ],
  },
  {
    question: 'Что такое ПДО и рабочий подход?',
    paragraphs: [
      'ПДО — «повторов до отказа»: сколько чистых повторов вы смогли бы сделать ещё. ПДО 2 означает запас примерно в два повтора.',
      'Целевой ПДО выбирается фазой: на обычной неделе — 2, на легкой — 4, при возвращении к обычной неделе после непропущенной легкой — 2,5. Настройка отдельного упражнения эту цель не меняет.',
      'После рабочего подхода укажите фактический ПДО: поле изначально пустое. Ноль означает, что запаса повторов не осталось. Цель и фактический результат сохраняются отдельно.',
      'Рабочий подход выполняется после разминки и входит в недельный объём. Подход с ПДО не выше 3 дополнительно считается интенсивным при оценке нагрузки.',
    ],
  },
  {
    question: 'Как рассчитывается следующий вес и число повторов?',
    paragraphs: [
      'Приложение учитывает выбранную базу результатов движения в конкретном месте программы. Базовый вес — медиана весов первых рабочих подходов до трёх последних завершённых обычных занятий этой базы. Для занятия без рабочих подходов используется его сохранённый плановый вес.',
      'Условия прибавки проверяются по последнему обычному занятию. Если все назначенные рабочие подходы достигли верхней границы повторов при ПДО не ниже 1, к базовому весу добавляется шаг, а цель повторов возвращается к нижней границе. Иначе при известном ПДО не ниже 1 используется округлённая медиана рабочих повторов плюс один, в пределах настроенного диапазона. При недостаточном или неизвестном ПДО — нижняя граница с базовым весом.',
      'Разные веса внутри занятия не усредняются. Текущая проверка прибавки учитывает повторы и ПДО всех рабочих подходов, но не требует одинакового веса. Медиана трёх первых рабочих весов может дать базу ниже последнего веса.',
      'Число подходов рассчитывается отдельно по фазе, недельной нагрузке и ограничениям по мышцам. В «Почему такой план?» показаны сохранённые причины и использованная история; у старых занятий подробностей расчёта может не быть.',
      'Подсказка следующего подхода использует последний записанный рабочий результат. При ПДО на 2 и более выше цели предлагаются плюс два шага веса, кроме легкой недели; при ПДО на 2 и более ниже цели — минус два шага. План в заголовке сохраняется.',
    ],
  },
  {
    question: 'Чем план отличается от фактического результата?',
    paragraphs: [
      'План — сохранённые цели занятия. Вес и повторы можно назначить вручную до записи любых подходов. Это изменение относится к занятию и не сбрасывает стартовый вес программы; ручная цель отмечается отдельно.',
      'Факт — вес, повторы и ПДО каждого выполненного подхода. До завершения занятия его можно исправить; после завершения редактирование недоступно. В прогрессию входят завершённые обычные занятия выбранной базы, без пропущенного упражнения и разминки.',
      'Для завершения нужны все назначенные рабочие подходы либо пропуск упражнения. Если число подходов вручную уменьшено с трёх до двух, два из двух считаются полным текущим планом. Уже созданные планы автоматически не пересчитываются после новых результатов. Явный перенос на другую дату пересчитывает автоматический план для этой даты и сохраняет отмеченные ручные цели.',
      'Если завершить занятие на другой неделе, его исходная фаза и цели сохраняются. Фактическая нагрузка относится к дате выполнения; в истории плановая дата показана отдельно.',
    ],
  },
  {
    question: 'Как заменить упражнение и вернуться к прежнему?',
    paragraphs: [
      'В программе «Изменить настройки» сохраняет движение и его базу результатов. «Заменить упражнение» создаёт новое назначение. Уже созданные тренировки сохраняют прежние упражнения, цели и записанные результаты; замена действует со следующей новой тренировки.',
      'Для нового движения явно задайте стартовый вес или минуты. При возвращении можно продолжить выбранную прежнюю базу того же движения в том же месте программы либо начать новую. Старые результаты сохраняются в обоих случаях; разные базы показаны отдельно.',
      'Если старую историю нельзя достоверно связать с движением, она сохраняется в журнале, но не предлагается для продолжения. Перенос занятия с уже заменённым назначением временно недоступен; записать и завершить его можно.',
    ],
  },
  {
    question: 'Как работает цикл и легкая неделя?',
    paragraphs: [
      'Обычно идут три недели накопления нагрузки и затем легкая неделя. Объём может расти постепенно по результатам; при усталости план удержит или снизит его.',
      'На легкой неделе подходов примерно вдвое меньше, вес не повышается, цель — ПДО 4. Пропуск отдельной тренировки сам по себе фазу не переключает.',
      'Восстановление оценивается только по новым рабочим подходам с указанным ПДО.',
    ],
  },
  {
    question: 'Что означают цвета на схеме мышц?',
    paragraphs: [
      'Две фигуры на карточке сегодняшней тренировки показывают мышцы спереди и сзади. Красным отмечены основные мышцы упражнений, синим — дополнительные. Чем больше запланированных подходов для дополнительной мышцы, тем темнее синий.',
      'Схема строится по плану выбранного занятия: один рабочий подход даёт основной мышце 1, дополнительной — 0,5. Пропущенное упражнение, кардио и растяжка подсветку не создают. Фактические результаты показаны отдельно в прогрессе.',
    ],
  },
  {
    question: 'Что делают «Легкая неделя» и «Отпуск» в меню сверху?',
    paragraphs: [
      'Эти действия назначают исключение на следующую календарную неделю. Внеочередная легкая неделя снижает нагрузку и завершает текущий блок; после неё начнётся новый.',
      'Отпуск убирает тренировки на неделю и ставит цикл на паузу. Когда неделя закончится, план продолжится с той же следующей фазы.',
      'Выбор можно отменить до начала недели, пока на неё и последующие недели не созданы тренировки.',
    ],
  },
  {
    question: 'Что показывают графики прогресса?',
    paragraphs: [
      '«Рабочие подходы» — недельный объём по мышцам: основной мышце подход даёт 1, дополнительной — 0,5. Отдельно показаны подходы с ПДО ≤ 3, тоннаж, средний ПДО и сопоставимые повторы.',
      'В своде «Все мышцы» каждый рабочий подход учтён один раз. Тоннаж — сумма веса × повторы, средний ПДО — по известным фактам. Подход с неизвестным ПДО входит в тоннаж, но его жёсткость не определяется; отсутствие мышечной разметки не удаляет его из общего свода. Для старых записей с неизвестной датой выполнения графики используют плановую дату.',
      'e1RM — примерная оценка максимума на один повтор по формуле «вес × (1 + повторы / 30)» для подходов с 2–10 повторами.',
      'Кардио, растяжка, разминка и отпуск в силовую аналитику не входят.',
    ],
  },
  {
    question: 'Что делает бот?',
    paragraphs: [
      'После команды /start бот присылает план в заданный день и время по вашему часовому поясу. По умолчанию используется московское время.',
      'Откройте Mini App из сообщения для записи результатов. На неделе отпуска уведомлений о тренировках нет.',
      'Команды и личные планы доступны в личном чате с ботом. Расчёты приложения — общие программные правила, не медицинская оценка и не рекомендация заниматься через боль.',
    ],
  },
]

function HomeFaq() {
  const [openItem, setOpenItem] = useState<number | null>(null)
  return <section className="homeGuide" aria-labelledby="homeGuideTitle">
    <div className="homeGuideHeader"><span className="homeGuideEyebrow">Помощь по приложению</span><h2 id="homeGuideTitle">Частые вопросы</h2></div>
    <div className="homeGuideList">{faqItems.map((item, index) => {
      const open = openItem === index
      return <div className={`homeGuideItem ${open ? 'isOpen' : ''}`} key={item.question}>
        <h3><button type="button" aria-expanded={open} aria-controls={`home-faq-answer-${index}`} onClick={() => setOpenItem(open ? null : index)}><span className="homeGuideIndex">{String(index + 1).padStart(2, '0')}</span><span className="homeGuideQuestion">{item.question}</span><span className="homeGuideToggle" aria-hidden="true"><IconPlus size={17} stroke={2} /></span></button></h3>
        <div className="homeGuideAnswer" id={`home-faq-answer-${index}`} hidden={!open}>{item.paragraphs.map(paragraph => <p key={paragraph}>{paragraph}</p>)}</div>
      </div>
    })}</div>
  </section>
}

function ProgramLoadError({ cachedAt, onRetry }: { cachedAt: string | null; onRetry: () => void }) {
  return <div className="emptyCard" role="status">
    <h2>{cachedAt ? 'Не удалось обновить программу' : 'Программа не загрузилась'}</h2>
    <p>{cachedAt ? `Показана последняя загруженная версия: ${new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' }).format(new Date(cachedAt))}.` : 'Проверьте соединение и повторите загрузку.'}</p>
    <button className="outlineButton" onClick={onRetry}>Повторить загрузку</button>
  </div>
}

export function ProgramPanel({ templates, loadedAt, error, onRetry, run }: {
  templates: Template[]; loadedAt: string | null; error: string; onRetry: () => void;
  run: (action: () => Promise<unknown>) => Promise<void>
}) {
  return <>
    {error && <ProgramLoadError cachedAt={loadedAt} onRetry={onRetry} />}
    {loadedAt ? <ProgramView templates={templates} run={run} /> : !error && <div className="emptyCard">Загружаем программу…</div>}
  </>
}

export default function App() {
  const [tab, setTab] = useState<Tab>('today')
  const [me, setMe] = useState<Me | null>(null)
  const [templates, setTemplates] = useState<Template[]>([])
  const [programLoadedAt, setProgramLoadedAt] = useState<string | null>(null)
  const [programError, setProgramError] = useState('')
  const programRequestVersion = useRef(0)
  const [sessions, setSessions] = useState<WorkoutSession[]>([])
  const [completedToday, setCompletedToday] = useState<WorkoutSession[]>([])
  const [selected, setSelected] = useState<WorkoutSession | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [nextWeek, setNextWeek] = useState<NextWeek | null>(null)
  const [weekMenuOpen, setWeekMenuOpen] = useState(false)
  const [editingProfile, setEditingProfile] = useState(false)

  const refresh = useCallback(async () => {
    const version = ++programRequestVersion.current
    const profile = await api.me()
    if (version !== programRequestVersion.current) return
    setMe(profile)
    if (!profile.profile_complete) return
    const programRequest = api.templates().then(program => {
      if (version !== programRequestVersion.current) return
      setTemplates(program)
      setProgramLoadedAt(new Date().toISOString())
      setProgramError('')
    }).catch((err: Error) => {
      if (version === programRequestVersion.current) setProgramError(err.message)
      throw err
    })
    // A failure in today's plan must not discard an already loaded program.
    const loaded = await Promise.all([programRequest, api.today(), api.history(), api.nextWeek()]).catch(err => {
      if (version === programRequestVersion.current) throw err
      return null
    })
    if (!loaded || version !== programRequestVersion.current) return
    const [, today, history, upcoming] = loaded
    const dateParts = new Intl.DateTimeFormat('en-US', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone: profile.timezone }).formatToParts(new Date())
    const part = (type: string) => dateParts.find(item => item.type === type)?.value ?? ''
    const localDate = `${part('year')}-${part('month')}-${part('day')}`
    setSessions(today)
    setCompletedToday(history.filter(item => (item.actual_date ?? item.scheduled_date) === localDate))
    setNextWeek(upcoming)
  }, [])

  useEffect(() => {
    refresh().then(async () => {
      const sessionId = new URLSearchParams(window.location.search).get('session')
      if (sessionId && (await api.me()).profile_complete) {
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
    try { await action() } catch (err) { setError((err as Error).message); return }
    try { await refresh() } catch (err) {
      setError(`Сервер подтвердил действие, но экран не обновился. Повторите загрузку вместо повторного сохранения. ${(err as Error).message}`)
    }
  }

  const openSession = async (id: string) => {
    setError('')
    try { setSelected(await api.session(id)) } catch (err) { setError((err as Error).message) }
  }

  const startSession = async (id: string) => {
    await run(async () => { setSelected(await api.start(id)); setTab('today') })
  }

  const retryLoad = () => {
    setError('')
    refresh().catch((err: Error) => setError(err.message))
  }

  if (loading) return <div className="loading"><span className="loadingMark" />Загружаем тренировку<span className="loadingDots">…</span></div>

  if (!me?.profile_complete) return <div className="appShell"><main className="page">
    {me ? <ProfileForm profile={me} onSaved={profile => { setMe(profile); refresh().catch((err: Error) => setError(err.message)) }} />
      : <div className="emptyCard" role="alert"><h2>Профиль не загрузился</h2><p>{error || 'Проверьте соединение.'}</p><button className="outlineButton" onClick={retryLoad}>Повторить загрузку</button></div>}
  </main></div>

  const todayLabel = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', weekday: 'long', timeZone: me?.timezone || 'Europe/Moscow' }).format(new Date())
  const completedSets = completedToday.reduce((sum, item) => sum + item.exercises.reduce((count, exercise) => count + (exercise.kind === 'strength' ? exercise.results.length : exercise.actual_duration_minutes ? 1 : 0), 0), 0)
  const upcomingLabel = nextWeek ? new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', timeZone: 'UTC' }).format(new Date(`${nextWeek.week_start}T12:00:00Z`)) : ''
  return <div className={`appShell ${selected && selected.status !== 'completed' ? 'isWorkout' : ''}`}>
    {error && <div className="errorToast" role="alert"><span>{error}</span><button onClick={() => setError('')} aria-label="Закрыть сообщение об ошибке">×</button></div>}

    <main className="page">
      {selected && selected.status !== 'completed' ? <WorkoutView
        session={selected}
        onChange={value => { setError(''); setSelected(value) }}
        onBack={() => { setSelected(null); refresh().catch((err: Error) => setError(err.message)) }}
        onComplete={() => { setError(''); setSelected(null); refresh().catch((err: Error) => setError(err.message)); setTab('history') }}
        onError={setError}
      /> : tab === 'today' ? <>
        <div className="eyebrow todayDate">{todayLabel}</div>
        <div className="todayHeading"><h1>Сегодня</h1><div className="nextWeekControl"><button className="nextWeekTrigger" type="button" aria-expanded={weekMenuOpen} onClick={() => setWeekMenuOpen(!weekMenuOpen)}>Следующая неделя{nextWeek?.kind ? `: ${nextWeek.kind === 'vacation' ? 'отпуск' : 'легкая'}` : ''} <span aria-hidden="true">⌄</span></button>{weekMenuOpen && <div className="nextWeekMenu"><strong>Неделя с {upcomingLabel}</strong><p>Выберите исключение из обычного плана. Решение можно отменить до начала недели.</p><button className={nextWeek?.kind === 'deload' ? 'selected' : ''} onClick={() => run(async () => { setNextWeek(await api.setNextWeek('deload')); setWeekMenuOpen(false) })}>Легкая неделя <small>Меньше подходов, ПДО 4</small></button><button className={nextWeek?.kind === 'vacation' ? 'selected' : ''} onClick={() => run(async () => { setNextWeek(await api.setNextWeek('vacation')); setWeekMenuOpen(false) })}>Отпуск <small>Без тренировок; цикл продолжится позже</small></button>{nextWeek?.kind && <button className="clearWeek" onClick={() => run(async () => { setNextWeek(await api.clearNextWeek()); setWeekMenuOpen(false) })}>Отменить решение</button>}</div>}</div></div>
        {sessions.length ? <div className="sessionList">{sessions.map(session =>
          <article className="heroSession" key={session.id}>
            <div className="heroTop"><span className="heroKicker">Тренировка по плану</span><span className={`phasePill phase-${session.phase}`}>{phaseText[session.phase]}</span></div>
            <div className="heroIntroduction"><div className="heroIntroductionText"><h2 className="heroTitle">{session.template_name}</h2>
            <div className="heroMeta">{session.muscle_group} · {session.exercises.length} {countWord(session.exercises.length, 'упражнение', 'упражнения', 'упражнений')}</div></div>
            {me?.sex && <MuscleDiagram sex={me.sex} exercises={session.exercises} />}</div>
            <div className="phaseRail" aria-label={`Фаза цикла: ${phaseText[session.phase]}`}><span className="current" /><span className={session.phase === 'deload' ? 'current' : ''} /></div>
            <div className="heroExercises">{session.exercises.slice(0, 3).map(item => <div className="heroExercise" key={item.id}><span>{item.name}</span><strong>{item.kind === 'strength' ? `${formatWeight(item.target_weight)} кг · ${item.sets_count} × ${item.target_reps}` : `${item.target_duration_minutes} мин`}</strong></div>)}{session.exercises.length > 3 && <span className="heroMore">И ещё {session.exercises.length - 3}</span>}</div>
            <button className="heroFooter" onClick={() => openSession(session.id)}><span>{session.status === 'in_progress' ? 'Продолжить тренировку' : 'Начать тренировку'}</span><span aria-hidden="true">→</span></button>
          </article>
        )}</div> : error ? <div className="emptyCard"><div className="emptyIcon">!</div><span className="emptyOverline">Данные недоступны</span><h2>План не загрузился.</h2><p>Проверьте соединение и попробуйте ещё раз.</p><button className="outlineButton" onClick={() => { setError(''); refresh().catch((err: Error) => setError(err.message)) }}>Повторить загрузку</button></div> : completedToday.length ? <div className="completedSession"><div className="completedTop"><span>Тренировка завершена</span><span className="completedSymbol" aria-hidden="true">✓</span></div><h2>{completedToday.map(item => item.template_name).join(' · ')}</h2><p>{completedSets} записанных результатов</p><button onClick={() => setTab('history')}>Посмотреть результаты <span aria-hidden="true">→</span></button></div> : <div className="emptyCard"><div className="emptyIcon">—</div><span className="emptyOverline">Пауза в расписании</span><h2>Сегодня без тренировки.</h2><p>План можно открыть вручную, если это не неделя отпуска.</p></div>}
        <div className="sectionHead"><h2>Ваши тренировки</h2><span>{programLoadedAt ? templates.length : 'н/д'}</span></div>
        {programError && <ProgramLoadError cachedAt={programLoadedAt} onRetry={retryLoad} />}
        {!programLoadedAt ? !programError && <div className="emptyCard">Загружаем программу…</div> : templates.length ? <div className="templateList">{templates.map((template, index) =>
          <div className="templateMini" key={template.id}>
            <span className="templateOrder">{index + 1}</span>
            <div className="templateDetails"><strong>{template.name}</strong><small>{completedToday.some(item => item.template_id === template.id) ? 'Завершено сегодня' : `${weekdays[template.weekday]} · ${template.send_time}`}</small></div>
            <button className="roundButton" onClick={() => completedToday.some(item => item.template_id === template.id) ? setTab('history') : startSession(template.id)} aria-label={completedToday.some(item => item.template_id === template.id) ? `Результаты ${template.name}` : `Начать ${template.name}`}>{completedToday.some(item => item.template_id === template.id) ? '✓' : '→'}</button>
          </div>
        )}</div> : <button className="primaryButton" onClick={() => setTab('program')}>Создать программу</button>}
        {me && !me.has_started_bot && <p className="hint">Чтобы получать сообщения, сначала отправьте боту команду /start.</p>}
        <HomeFaq />
      </> : tab === 'program' ? <><div className="profileShortcut"><span>{me?.display_name}{me?.age !== null ? ` · ${me?.age} лет` : ''}</span><button type="button" className="textButton" onClick={() => setEditingProfile(!editingProfile)}>{editingProfile ? 'Свернуть анкету' : 'Изменить анкету'}</button></div>{editingProfile && me && <ProfileForm profile={me} onSaved={profile => { setMe(profile); setEditingProfile(false) }} onClose={() => setEditingProfile(false)} />}<ProgramPanel templates={templates} loadedAt={programLoadedAt} error={programError} onRetry={retryLoad} run={run} /></>
        : tab === 'progress' ? <ProgressView />
          : tab === 'admin' && me.is_admin ? <AdminView /> : <HistoryView />}
    </main>

    {!selected && <nav className="bottomNav" aria-label="Навигация">
      <button className={tab === 'today' ? 'active' : ''} onClick={() => setTab('today')}><NavIcon name="today" />Сегодня</button>
      <button className={tab === 'progress' ? 'active' : ''} onClick={() => setTab('progress')}><NavIcon name="progress" />Прогресс</button>
      <button className={tab === 'history' ? 'active' : ''} onClick={() => setTab('history')}><NavIcon name="history" />История</button>
      <button className={tab === 'program' ? 'active' : ''} onClick={() => setTab('program')}><NavIcon name="program" />Программа</button>
      {me.is_admin && <button className={tab === 'admin' ? 'active' : ''} onClick={() => setTab('admin')}><NavIcon name="admin" />Админ</button>}
    </nav>}
  </div>
}
