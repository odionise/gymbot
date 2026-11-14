import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import type { Movement, SessionExercise, Template, WorkoutSession } from './types'
import choiceHtml from './one-rep/choice.html?raw'
import workoutHtml from './one-rep/workout.html?raw'
import summaryHtml from './one-rep/summary.html?raw'

type RepSet = { w: number; r: number; pdo: number; done: boolean }
type PlanExercise = {
  id: string; exerciseId: string; name: string; kind: Movement['kind']; skipped: boolean
  past: { date: string; work: string[] }; warm: RepSet[]; work: RepSet[]
  minutes: number; durationDone: boolean
}
type FlowMessage = { source: string; type: string; templateId?: string; light?: boolean; plan?: PlanExercise[]; height?: number }

const scriptJson = (value: unknown) => JSON.stringify(value).replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026')
const escapeHtml = (value: string) => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')
const format = (value: number) => value.toLocaleString('ru-RU', { maximumFractionDigits: 1 })
const dateLabel = (date: string) => new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short' }).format(new Date(`${date}T12:00:00Z`))
const ordinary = (session: WorkoutSession) => session.status === 'completed' && session.phase !== 'deload' && session.phase !== 'light'

function fromExercise(exercise: SessionExercise, previous?: SessionExercise, date = ''): PlanExercise {
  const past = previous?.results.filter(item => item.is_working).sort((a, b) => a.set_index - b.set_index) ?? []
  const currentWork = exercise.results.filter(item => item.is_working).sort((a, b) => a.set_index - b.set_index)
  const currentWarm = exercise.results.filter(item => !item.is_working).sort((a, b) => b.set_index - a.set_index)
  const asSet = (item: { weight: number; reps: number; rir_reported: number | null }): RepSet => ({ w: item.weight, r: item.reps, pdo: item.rir_reported ?? 0, done: true })
  return {
    id: exercise.id, exerciseId: exercise.exercise_id, name: exercise.name, kind: exercise.kind, skipped: exercise.skipped,
    past: { date, work: past.map(item => `${format(item.weight)} кг × ${item.reps}`) },
    warm: currentWarm.map(asSet),
    work: Array.from({ length: exercise.sets_count }, (_, index) => {
      const saved = currentWork.find(item => item.set_index === index + 1)
      return saved ? asSet(saved) : { w: past[index]?.weight ?? 0, r: past[index]?.reps ?? 0, pdo: past[index]?.rir_reported ?? 0, done: false }
    }),
    minutes: exercise.actual_duration_minutes ?? previous?.actual_duration_minutes ?? 1,
    durationDone: exercise.actual_duration_minutes !== null,
  }
}

function lightExercises(template: Template, movements: Movement[], previous: WorkoutSession | null): PlanExercise[] {
  return [...template.exercises].sort((a, b) => a.position - b.position).map(exercise => {
    const movement = movements.find(item => item.id === exercise.movement_id)
    const prior = previous?.exercises.find(item => item.exercise_id === exercise.id)
    const past = prior?.results.filter(item => item.is_working).sort((a, b) => a.set_index - b.set_index) ?? []
    return {
      id: exercise.id, exerciseId: exercise.id, name: movement?.name ?? exercise.name,
      kind: movement?.kind ?? 'strength', skipped: false,
      past: { date: previous ? dateLabel(previous.actual_date ?? previous.scheduled_date) : '', work: past.map(item => `${format(item.weight)} кг × ${item.reps}`) },
      warm: [], work: Array.from({ length: exercise.sets_count }, (_, i) => ({ w: past[i]?.weight ?? 0, r: past[i]?.reps ?? 0, pdo: past[i]?.rir_reported ?? 0, done: false })),
      minutes: prior?.actual_duration_minutes ?? exercise.duration_minutes ?? 1, durationDone: false,
    }
  })
}

function summaryData(plan: PlanExercise[], previous: WorkoutSession | null) {
  return plan.filter(item => !item.skipped).map(item => {
    const prior = previous?.exercises.find(exercise => exercise.exercise_id === item.exerciseId)
    return {
      name: item.name, kind: item.kind, duration: item.kind === 'strength' ? null : item.minutes,
      pastDuration: prior?.actual_duration_minutes ?? null,
      date: previous ? dateLabel(previous.actual_date ?? previous.scheduled_date) : null, done: true,
      current: item.kind === 'strength' ? item.work.filter(set => set.done).map(set => ({ w: set.w, r: set.r, p: set.pdo })) : [],
      past: prior?.results.filter(set => set.is_working).sort((a, b) => a.set_index - b.set_index).map(set => ({ w: set.weight, r: set.reps, p: set.rir_reported ?? undefined })) ?? [],
    }
  })
}

export function OneRepFlow({ templates, onProgram, onActiveChange }: { templates: Template[]; onProgram: () => void; onActiveChange?: (active: boolean) => void }) {
  const frame = useRef<HTMLIFrameElement>(null)
  const synced = useRef<PlanExercise[]>([])
  const current = useRef<PlanExercise[]>([])
  const session = useRef<WorkoutSession | null>(null)
  const previous = useRef<WorkoutSession | null>(null)
  const queue = useRef<Promise<void>>(Promise.resolve())
  const syncFailed = useRef(false)
  const [step, setStep] = useState<'choice' | 'workout' | 'summary'>('choice')
  const [doc, setDoc] = useState('')
  const [height, setHeight] = useState(600)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [light, setLight] = useState(false)
  const [chosen, setChosen] = useState<Template | null>(null)
  const [history, setHistory] = useState<WorkoutSession[]>([])
  const [active, setActive] = useState<WorkoutSession | null>(null)
  const [movements, setMovements] = useState<Movement[]>([])
  useEffect(() => {
    onActiveChange?.(step !== 'choice')
    return () => onActiveChange?.(false)
  }, [step, onActiveChange])

  useEffect(() => {
    let live = true
    Promise.all([api.history(), api.activeManual(), api.movements()]).then(([items, ongoing, catalog]) => {
      if (!live) return
      setHistory(items); setActive(ongoing[0] ?? null); setMovements(catalog)
    }).catch(err => { if (live) setError((err as Error).message) })
    return () => { live = false }
  }, [])

  const choiceDoc = useMemo(() => {
    const latest = history.filter(ordinary).sort((a, b) => (b.completed_at ?? '').localeCompare(a.completed_at ?? ''))[0]
    const lastText = latest ? `Прошлая: <strong>${escapeHtml(latest.template_name)}</strong><span class="last-date">${dateLabel(latest.actual_date ?? latest.scheduled_date)}</span>` : 'Пока нет завершённых обычных тренировок'
    const options = templates.map(template => ({ id: template.id, title: escapeHtml(template.name), count: `${template.exercises.length} упражнений`, icon: '<path d="M2 9v6M5 7v10M19 7v10M22 9v6M5 12h14"/>' }))
    return choiceHtml.replace('__CHOICE_ITEMS__', scriptJson(options)).replace('__LAST_TRAINING__', lastText)
  }, [templates, history])
  useEffect(() => { if (step === 'choice') setDoc(choiceDoc) }, [choiceDoc, step])

  const showWorkout = (template: Template, ongoing: WorkoutSession | null, past: WorkoutSession | null, isLight: boolean, catalog: Movement[]) => {
    const plans = ongoing
      ? [...ongoing.exercises].sort((a, b) => a.position - b.position).map(exercise => fromExercise(exercise, past?.exercises.find(item => item.exercise_id === exercise.exercise_id), past ? dateLabel(past.actual_date ?? past.scheduled_date) : ''))
      : lightExercises(template, catalog, past)
    current.current = plans
    synced.current = structuredClone(plans)
    syncFailed.current = false
    session.current = ongoing
    previous.current = past
    setChosen(template); setLight(isLight); setActive(null); setStep('workout')
    setDoc(workoutHtml.replace('__WORKOUT_PLANS__', scriptJson(plans)).replace('__WORKOUT_TITLE__', escapeHtml(template.name)))
  }

  const start = async (templateId: string, isLight: boolean) => {
    const template = templates.find(item => item.id === templateId)
    if (!template || busy) return
    setBusy(true); setError('')
    try {
      const past = await api.lastCompleted(templateId)
      const ongoing = isLight ? null : await api.manualStart(templateId)
      showWorkout(template, ongoing, past, isLight, movements)
    } catch (err) {
      setError((err as Error).message)
      setDoc(choiceDoc)
    } finally { setBusy(false) }
  }

  const resume = async () => {
    if (!active || busy) return
    const template = templates.find(item => item.id === active.template_id)
    if (!template) return
    setBusy(true); setError('')
    try { showWorkout(template, active, await api.lastCompleted(template.id), false, movements) }
    catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }

  const sync = async (next: PlanExercise[]) => {
    const old = synced.current
    if (!session.current) { synced.current = structuredClone(next); return }
    for (const [i, item] of next.entries()) {
      const before = old[i]
      if (!before || item.id !== before.id) continue
      if (item.skipped !== before.skipped) session.current = await api.skip(item.id, item.skipped)
      if (item.kind !== 'strength') {
        if (item.durationDone !== before.durationDone || (item.durationDone && item.minutes !== before.minutes)) {
          session.current = item.durationDone ? await api.saveDuration(item.id, item.minutes) : await api.clearDuration(item.id)
        }
        continue
      }
      if (item.work.length !== before.work.length) session.current = await api.changeSetsCount(item.id, item.work.length)
      for (const kind of ['warm', 'work'] as const) {
        for (const [index, set] of item[kind].entries()) {
          const prior = before[kind][index]
          const setIndex = kind === 'work' ? index + 1 : -index - 1
          if (set.done && (!prior?.done || set.w !== prior.w || set.r !== prior.r || set.pdo !== prior.pdo))
            session.current = await api.saveSet(item.id, setIndex, set.w, set.r, set.pdo, kind === 'work')
          else if (!set.done && prior?.done) session.current = await api.deleteSet(item.id, setIndex)
        }
        if (kind === 'warm' && before.warm.length > item.warm.length)
          for (let index = item.warm.length; index < before.warm.length; index++)
            if (before.warm[index].done) session.current = await api.deleteSet(item.id, -index - 1)
      }
    }
    synced.current = structuredClone(next)
  }

  const finish = async (plan: PlanExercise[]) => {
    if (!chosen || busy) return
    setBusy(true); setError('')
    try {
      await queue.current
      if (syncFailed.current) throw new Error('Часть подходов не сохранилась. Проверьте занятие и завершите его повторно.')
      if (!plan.some(item => !item.skipped)) throw new Error('Отметьте хотя бы одно упражнение')
      if (!light && session.current) session.current = await api.complete(session.current.id)
      const today = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short' }).format(new Date())
      setDoc(summaryHtml.replace('__SUMMARY_DATA__', scriptJson(summaryData(plan, previous.current)))
        .replace('__SUMMARY_TITLE__', escapeHtml(chosen.name)).replace('__SUMMARY_DATE__', today))
      setStep('summary'); setHistory(items => session.current ? [session.current, ...items] : items)
    } catch (err) {
      setError((err as Error).message)
      setDoc(workoutHtml.replace('__WORKOUT_PLANS__', scriptJson(current.current)).replace('__WORKOUT_TITLE__', escapeHtml(chosen.name)))
    }
    finally { setBusy(false) }
  }

  useEffect(() => {
    const onMessage = (event: MessageEvent<FlowMessage>) => {
      if (event.source !== frame.current?.contentWindow || event.data?.source !== 'one-rep') return
      const message = event.data
      if (message.type === 'height' && message.height) setHeight(Math.max(450, Math.min(3000, message.height + 8)))
      if (message.type === 'start' && message.templateId) void start(message.templateId, Boolean(message.light))
      if (message.type === 'state' && message.plan) {
        const next = structuredClone(message.plan)
        current.current = next
        queue.current = queue.current.then(() => sync(next)).catch(async err => {
          syncFailed.current = true
          setError(`Не удалось сохранить изменение: ${(err as Error).message}`)
          if (session.current) {
            try {
              session.current = await api.session(session.current.id)
              if (chosen) showWorkout(chosen, session.current, previous.current, false, movements)
            } catch { /* keep current error */ }
          }
        })
      }
      if (message.type === 'complete' && message.plan) void finish(message.plan)
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  })

  const reset = () => { setStep('choice'); setDoc(choiceDoc); setError(''); setChosen(null); session.current = null; previous.current = null }
  return <div className="oneRepFlow">
    {error && <div className="oneRepNotice" role="alert">{error}<button type="button" onClick={() => setError('')}>×</button></div>}
    {step === 'choice' && active && <button className="oneRepResume" type="button" onClick={() => void resume()} disabled={busy}>Продолжить: {active.template_name}</button>}
    {step === 'choice' && !templates.length && <button className="oneRepResume" type="button" onClick={onProgram}>Создать тренировку в «Программе»</button>}
    {step !== 'choice' && <button className="oneRepBack" type="button" onClick={reset}>← К выбору тренировки</button>}
    {step === 'workout' && light && <p className="oneRepLight">Лёгкая тренировка · результаты не сохраняются</p>}
    <iframe ref={frame} title={step === 'choice' ? 'Выбор тренировки' : step === 'workout' ? 'Ход тренировки' : 'Итоги тренировки'} sandbox="allow-scripts" srcDoc={doc} style={{ height }} />
    {busy && <p className="oneRepStatus" role="status">Открываем тренировку…</p>}
  </div>
}
