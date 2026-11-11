import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { formatWeight, phaseText } from './App'
import { NextSetDetails, RecommendationDetails } from './RecommendationDetails'
import type { SessionExercise, WorkoutSession } from './types'
import { createSerialQueue } from './asyncQueue'

type Mutate = <T>(action: () => Promise<T>) => Promise<T>
const MutationContext = createContext<Mutate>(action => action())

function SetRow({ item, index, onChange, onError }: {
  item: SessionExercise; index: number; onChange: (value: WorkoutSession) => void; onError: (value: string) => void
}) {
  const saved = item.results.find(result => result.set_index === index)
  const suggestion = item.weight_step !== null && item.next_set?.set_index === index ? item.next_set : null
  const [weight, setWeight] = useState(String(saved?.weight ?? suggestion?.weight ?? item.target_weight))
  const [reps, setReps] = useState(String(saved?.reps ?? suggestion?.reps ?? item.target_reps))
  const [rir, setRir] = useState(saved?.rir_reported == null ? '' : String(saved.rir_reported))
  const [busy, setBusy] = useState(false)
  const mutate = useContext(MutationContext)
  const dirty = useRef({ weight: false, reps: false })
  useEffect(() => {
    // A preceding saved set can change the suggestion while this row contains
    // a manual draft. Only untouched inputs follow the new suggestion.
    if (!dirty.current.weight) setWeight(String(saved?.weight ?? suggestion?.weight ?? item.target_weight))
    if (!dirty.current.reps) setReps(String(saved?.reps ?? suggestion?.reps ?? item.target_reps))
  }, [saved?.weight, saved?.reps, suggestion?.weight, suggestion?.reps, item.target_weight, item.target_reps])
  useEffect(() => { setRir(saved?.rir_reported == null ? '' : String(saved.rir_reported)) }, [saved?.rir_reported])
  const save = async () => {
    setBusy(true)
    try {
      const updated = await mutate(() => api.saveSet(item.id, index, Number(weight), Number(reps), rir === '' ? null : Number(rir), index > 0))
      const stored = updated.exercises.find(value => value.id === item.id)?.results.find(value => value.set_index === index)
      dirty.current = { weight: false, reps: false }
      if (stored) { setWeight(String(stored.weight)); setReps(String(stored.reps)); setRir(stored.rir_reported == null ? '' : String(stored.rir_reported)) }
      onChange(updated)
    }
    catch (err) { onError((err as Error).message) }
    finally { setBusy(false) }
  }
  const remove = async () => {
    setBusy(true)
    try {
      const updated = await mutate(() => api.deleteSet(item.id, index))
      dirty.current = { weight: false, reps: false }
      onChange(updated)
    }
    catch (err) { onError((err as Error).message) }
    finally { setBusy(false) }
  }
  const adjust = (value: string, delta: number, maximum: number, update: (next: string) => void) => {
    const current = Number(value)
    const next = Math.min(maximum, Math.max(0, (Number.isFinite(current) ? current : 0) + delta))
    update(String(Math.round(next * 100) / 100))
  }
  const valueField = (label: string, value: string, update: (next: string) => void, increment: number | null, maximum: number, mode: 'decimal' | 'numeric') =>
    <div className="setField"><span>{label}</span><div className="setValueControl"><button type="button" className="setStepButton" onClick={() => increment !== null && adjust(value, -increment, maximum, update)} disabled={busy || Boolean(saved) || increment === null || Number(value) <= 0} aria-label={`Уменьшить ${label}`} title={increment === null ? 'Шаг веса не сохранён' : `−${increment}`}>−</button><input aria-label={label} inputMode={mode} type="number" min="0" max={maximum} step={mode === 'numeric' ? '1' : 'any'} value={value} onChange={event => update(event.target.value)} disabled={busy || Boolean(saved)} /><button type="button" className="setStepButton" onClick={() => increment !== null && adjust(value, increment, maximum, update)} disabled={busy || Boolean(saved) || increment === null || Number(value) >= maximum} aria-label={`Увеличить ${label}`} title={increment === null ? 'Шаг веса не сохранён' : `+${increment}`}>+</button></div></div>
  return <div className={`setRow ${saved ? 'isSaved' : ''}`}>
    <span className="setNumber">{index > 0 ? index : 'Р' + Math.abs(index)}</span>
    {valueField('вес, кг', weight, value => { dirty.current.weight = true; setWeight(value) }, item.weight_step, 1000, 'decimal')}
    {valueField('повторы', reps, value => { dirty.current.reps = true; setReps(value) }, 1, 100, 'numeric')}
    {valueField('факт ПДО', rir, setRir, 0.5, 10, 'decimal')}
    {saved ? <div className="savedSetActions"><span className="savedSetMarker" role="status"><span aria-hidden="true">✓</span> Сохранено</span><button type="button" className="undoSet" onClick={remove} disabled={busy} aria-label={`Отменить запись подхода ${index > 0 ? index : `разминки ${Math.abs(index)}`}`}>Отменить</button></div> : <button type="button" className="saveSet" onClick={save} disabled={busy || weight === '' || reps === '' || (index > 0 && rir === '')}>Сохранить</button>}
  </div>
}

function ExerciseBlock({ item, onChange, onError }: {
  item: SessionExercise; onChange: (value: WorkoutSession) => void; onError: (value: string) => void
}) {
  const mutate = useContext(MutationContext)
  const hasManualTarget = Boolean(item.recommendation?.manual_override && Object.keys(item.recommendation.manual_override).length)
  const [editing, setEditing] = useState(false)
  const [warmups, setWarmups] = useState(Math.max(1, ...item.results.filter(result => !result.is_working).map(result => Math.abs(result.set_index))))
  const lastWarmupSaved = item.results.some(result => !result.is_working && result.set_index === -warmups)
  const [warmupBusy, setWarmupBusy] = useState(false)
  const [weight, setWeight] = useState(String(item.target_weight))
  const [reps, setReps] = useState(String(item.target_reps))
  const override = async () => {
    try { onChange(await mutate(() => api.override(item.id, Number(weight), Number(reps)))); setEditing(false) }
    catch (err) { onError((err as Error).message) }
  }
  const skip = async () => {
    try { onChange(await mutate(() => api.skip(item.id, !item.skipped))) }
    catch (err) { onError((err as Error).message) }
  }
  const removeWarmup = async () => {
    if (warmups === 0 || warmupBusy) return
    if (!lastWarmupSaved) { setWarmups(count => count - 1); return }
    setWarmupBusy(true)
    try {
      const updated = await mutate(() => api.deleteSet(item.id, -warmups))
      setWarmups(count => count - 1)
      onChange(updated)
    } catch (err) { onError((err as Error).message) }
    finally { setWarmupBusy(false) }
  }
  return <section className={`exerciseCard ${item.skipped ? 'skipped' : ''}`}>
    <div className="exerciseHead"><div><span className="cardIndex">Упражнение {item.position + 1}</span><h2>{item.name}</h2></div><span className="exerciseCheck">{item.results.filter(result => result.is_working).length}<span> / {item.sets_count}</span></span></div>
    <div className="targetLine"><div className="targetWeight"><span>План, вес</span><strong>{formatWeight(item.target_weight)}<small> кг</small></strong></div><div className="targetReps"><span>План, повторы</span><strong>{item.sets_count} × {item.target_reps}</strong><small>Диапазон {item.min_reps}–{item.max_reps} · целевой ПДО {item.target_rir ?? '—'}</small></div></div>
    {hasManualTarget ? <p className="hint"><strong>План изменён вручную.</strong> {item.recommendation?.calculated ? 'Исходный расчёт сохранён в объяснении.' : 'Подробности исходного расчёта не сохранены.'}</p> : item.action_label && <p className="hint">{item.action_label}</p>}
    <RecommendationDetails item={item} />
    {item.weight_step !== null && item.next_set && <p className="hint">Следующий подход: {formatWeight(item.next_set.weight)} кг × {item.next_set.reps}; {item.next_set.reason.toLowerCase()}.</p>}
    {item.weight_step !== null && <NextSetDetails item={item} />}
    {item.weight_step === null && <p className="hint">В старом занятии шаг веса не сохранён. Вес можно вводить вручную; кнопки изменения веса и подсказка следующего подхода недоступны.</p>}
    {!item.results.length && <button className="textButton" onClick={() => setEditing(!editing)}>{editing ? 'Скрыть изменение' : 'Изменить цель'}</button>}
    {editing && !item.results.length && <div className="overrideBox"><label>Вес, кг<input type="number" min="0" step="0.5" value={weight} onChange={event => setWeight(event.target.value)} /></label><label>Повторы<input type="number" min="1" value={reps} onChange={event => setReps(event.target.value)} /></label><button onClick={override}>Сохранить</button></div>}
    {!item.skipped && <div className="setsList"><div className="setsCaption"><span>Подходы</span><span>Факт: вес, повторы, ПДО</span></div><p className="fieldHelp">Запишите фактический ПДО каждого рабочего подхода. Поле пустое до вашего ввода; 0 означает отсутствие запаса повторов.</p><small>Разминка (не входит в объём)</small>{Array.from({ length: warmups }, (_, n) => <SetRow key={-n - 1} item={item} index={-n - 1} onChange={onChange} onError={onError} />)}<div className="programActions warmupActions"><button disabled={warmups >= 5 || warmupBusy} onClick={() => setWarmups(count => count + 1)}>+ Разминка</button><button disabled={warmups === 0 || warmupBusy} onClick={removeWarmup}>− Разминка</button></div>{Array.from({ length: item.sets_count }, (_, n) => <SetRow key={n + 1} item={item} index={n + 1} onChange={onChange} onError={onError} />)}<div className="programActions"><button disabled={item.sets_count >= 12} onClick={async () => { try { onChange(await mutate(() => api.changeSetsCount(item.id, item.sets_count + 1))) } catch (err) { onError((err as Error).message) } }}>+ Подход</button><button disabled={item.sets_count <= 1 || item.results.some(result => result.is_working && result.set_index === item.sets_count)} onClick={async () => { try { onChange(await mutate(() => api.changeSetsCount(item.id, item.sets_count - 1))) } catch (err) { onError((err as Error).message) } }}>− Подход</button></div></div>}
    <button className="skipButton" onClick={skip}>{item.skipped ? 'Вернуть упражнение' : 'Пропустить упражнение'}</button>
  </section>
}

function TimedExerciseBlock({ item, onChange, onError }: {
  item: SessionExercise; onChange: (value: WorkoutSession) => void; onError: (value: string) => void
}) {
  const mutate = useContext(MutationContext)
  const [minutes, setMinutes] = useState(String(item.actual_duration_minutes ?? item.target_duration_minutes ?? 20))
  const [busy, setBusy] = useState(false)
  useEffect(() => setMinutes(String(item.actual_duration_minutes ?? item.target_duration_minutes ?? 20)), [item.actual_duration_minutes, item.target_duration_minutes])
  const save = async () => {
    setBusy(true)
    try { onChange(await mutate(() => api.saveDuration(item.id, Number(minutes)))) } catch (err) { onError((err as Error).message) }
    finally { setBusy(false) }
  }
  const skip = async () => {
    try { onChange(await mutate(() => api.skip(item.id, !item.skipped))) } catch (err) { onError((err as Error).message) }
  }
  return <section className={`exerciseCard timedExercise ${item.skipped ? 'skipped' : ''}`}>
    <div className="exerciseHead"><div><span className="cardIndex">Упражнение {item.position + 1}</span><h2>{item.name}</h2></div><span className="exerciseCheck">{item.actual_duration_minutes ? '✓' : '—'}</span></div>
    <p className="hint">План: {item.target_duration_minutes} мин. Запишите фактическое время.</p>
    {!item.skipped && <div className="timedInputRow"><div className="setField"><span>Минуты</span><div className="setValueControl"><button type="button" className="setStepButton" onClick={() => setMinutes(String(Math.max(1, Number(minutes) - 1)))} disabled={busy || Number(minutes) <= 1}>−</button><input aria-label="Фактическая длительность, минут" type="number" min="1" max="600" inputMode="numeric" value={minutes} onChange={event => setMinutes(event.target.value)} /><button type="button" className="setStepButton" onClick={() => setMinutes(String(Math.min(600, Number(minutes) + 1)))} disabled={busy || Number(minutes) >= 600}>+</button></div></div><button className="outlineButton" onClick={save} disabled={busy || Number(minutes) < 1 || Number(minutes) > 600}>{item.actual_duration_minutes ? 'Обновить время' : 'Сохранить время'}</button>{item.actual_duration_minutes && <button className="textButton" disabled={busy} onClick={async () => { try { onChange(await mutate(() => api.clearDuration(item.id))) } catch (err) { onError((err as Error).message) } }}>Удалить запись</button>}</div>}
    <button className="skipButton" onClick={skip} disabled={Boolean(item.actual_duration_minutes) && !item.skipped}>{item.skipped ? 'Вернуть упражнение' : 'Пропустить упражнение'}</button>
  </section>
}

export function WorkoutView({ session, onChange, onBack, onComplete, onError }: {
  session: WorkoutSession; onChange: (value: WorkoutSession) => void; onBack: () => void; onComplete: () => void; onError: (value: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const queue = useRef(createSerialQueue()).current
  const [pending, setPending] = useState(0)
  const mutate: Mutate = action => {
    setPending(value => value + 1)
    return queue(action).finally(() => setPending(value => value - 1))
  }
  const [newDate, setNewDate] = useState(session.scheduled_date)
  const saved = session.exercises.reduce((count, item) => count + (item.kind === 'strength' ? item.results.filter(result => result.is_working).length : item.actual_duration_minutes && !item.skipped ? 1 : 0), 0)
  const total = session.exercises.reduce((count, item) => count + (item.skipped ? 0 : item.kind === 'strength' ? item.sets_count : 1), 0)
  const dateLabel = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', timeZone: 'UTC' }).format(new Date(`${session.scheduled_date}T12:00:00Z`))
  const complete = async () => {
    setBusy(true)
    try { await mutate(() => api.complete(session.id)); onComplete() }
    catch (err) { onError((err as Error).message) }
    finally { setBusy(false) }
  }
  return <MutationContext.Provider value={mutate}>
    <button className="backButton" onClick={onBack} disabled={pending > 0}>← <span>К плану</span></button>
    <fieldset className="workoutFields" disabled={pending > 0 || busy} aria-busy={pending > 0}>
    <div className="workoutTitle"><span className="eyebrow">{dateLabel} · {session.phase === 'deload' ? 'Легкая неделя' : `${phaseText[session.phase]} тренировка`}</span><h1>{session.template_name}</h1><p>{session.muscle_group}</p></div>
    {session.deload_reason && <p className="hint">Легкая неделя: {session.deload_reason === 'scheduled' ? 'по календарю' : session.deload_reason === 'auto' ? 'по сигналам восстановления' : 'по вашему выбору'}.</p>}
    {session.week_start && <button className="outlineButton" onClick={async () => { try { await mutate(() => api.setRecovery(session.week_start!, !session.feeling_beat_up)); onChange({ ...session, feeling_beat_up: !session.feeling_beat_up }) } catch (err) { onError((err as Error).message) } }}>{session.feeling_beat_up ? 'Отмечено: тяжело / болит' : 'Отметить: тяжело / болит'}</button>}
    {session.status === 'planned' && <div className="fieldGrid"><label className="field"><span>Перенести на дату</span><input type="date" value={newDate} onChange={event => setNewDate(event.target.value)} /></label><button className="outlineButton" onClick={async () => { try { onChange(await mutate(() => api.reschedule(session.id, newDate))) } catch (err) { onError((err as Error).message) } }}>Перенести</button></div>}
    <div className="completionMeter"><div className="meterTop"><span>Записано результатов</span><strong aria-live="polite">{saved}<em> / {total}</em></strong></div><div className="meterTrack"><div style={{ width: `${total ? saved / total * 100 : 0}%` }} /></div></div>
    {session.exercises.map(item => item.kind === 'strength' ? <ExerciseBlock key={item.id} item={item} onChange={onChange} onError={onError} /> : <TimedExerciseBlock key={item.id} item={item} onChange={onChange} onError={onError} />)}
    <button className="primaryButton finishButton" onClick={complete} disabled={busy || saved !== total || total === 0}>Завершить тренировку</button>
    <p className="hint">{pending > 0 ? 'Сохраняем изменения…' : 'Результаты сохраняются сразу. К тренировке можно вернуться позже.'}</p>
    </fieldset>
  </MutationContext.Provider>
}
