import { useEffect, useState } from 'react'
import { api } from './api'
import { formatWeight, phaseText } from './App'
import type { SessionExercise, WorkoutSession } from './types'

function SetRow({ item, index, onChange, onError }: {
  item: SessionExercise; index: number; onChange: (value: WorkoutSession) => void; onError: (value: string) => void
}) {
  const saved = item.results.find(result => result.set_index === index)
  const [weight, setWeight] = useState(String(saved?.weight ?? item.target_weight))
  const [reps, setReps] = useState(String(saved?.reps ?? item.target_reps))
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    setWeight(String(saved?.weight ?? item.target_weight))
    setReps(String(saved?.reps ?? item.target_reps))
  }, [saved?.weight, saved?.reps, item.target_weight, item.target_reps])
  const save = async () => {
    setBusy(true)
    try { onChange(await api.saveSet(item.id, index, Number(weight), Number(reps))) }
    catch (err) { onError((err as Error).message) }
    finally { setBusy(false) }
  }
  const remove = async () => {
    setBusy(true)
    try { onChange(await api.deleteSet(item.id, index)) }
    catch (err) { onError((err as Error).message) }
    finally { setBusy(false) }
  }
  return <div className={`setRow ${saved ? 'isSaved' : ''}`}>
    <span className="setNumber">{index}</span>
    <label><span>кг</span><input inputMode="decimal" type="number" min="0" step="0.5" value={weight} onChange={event => setWeight(event.target.value)} /></label>
    <span className="multiply">×</span>
    <label><span>повт.</span><input inputMode="numeric" type="number" min="0" max="100" value={reps} onChange={event => setReps(event.target.value)} /></label>
    <button className={`saveSet ${saved ? 'saved' : ''}`} onClick={save} disabled={busy || weight === '' || reps === ''} aria-label={saved ? 'Обновить подход' : 'Сохранить подход'}>{saved ? '✓' : '→'}</button>
    {saved && <button className="deleteSet" onClick={remove} disabled={busy} aria-label="Удалить подход">×</button>}
  </div>
}

function ExerciseBlock({ item, onChange, onError }: {
  item: SessionExercise; onChange: (value: WorkoutSession) => void; onError: (value: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [weight, setWeight] = useState(String(item.target_weight))
  const [reps, setReps] = useState(String(item.target_reps))
  const override = async () => {
    try { onChange(await api.override(item.id, Number(weight), Number(reps))); setEditing(false) }
    catch (err) { onError((err as Error).message) }
  }
  const skip = async () => {
    try { onChange(await api.skip(item.id, !item.skipped)) }
    catch (err) { onError((err as Error).message) }
  }
  return <section className={`exerciseCard ${item.skipped ? 'skipped' : ''}`}>
    <div className="exerciseHead"><div><span className="cardIndex">Упражнение {item.position + 1}</span><h2>{item.name}</h2></div><span className="exerciseCheck">{item.results.length}<span> / {item.sets_count}</span></span></div>
    <div className="targetLine"><div className="targetWeight"><span>Вес</span><strong>{formatWeight(item.target_weight)}<small> кг</small></strong></div><div className="targetReps"><span>Повторы</span><strong>{item.sets_count} × {item.target_reps}</strong><small>Диапазон {item.min_reps}–{item.max_reps}</small></div></div>
    {!item.results.length && <button className="textButton" onClick={() => setEditing(!editing)}>{editing ? 'Скрыть изменение' : 'Изменить цель'}</button>}
    {editing && !item.results.length && <div className="overrideBox"><label>Вес, кг<input type="number" min="0" step="0.5" value={weight} onChange={event => setWeight(event.target.value)} /></label><label>Повторы<input type="number" min="1" value={reps} onChange={event => setReps(event.target.value)} /></label><button onClick={override}>Сохранить</button></div>}
    {!item.skipped && <div className="setsList"><div className="setsCaption"><span>Подходы</span><span>Вес и повторы</span></div>{Array.from({ length: item.sets_count }, (_, n) => <SetRow key={n + 1} item={item} index={n + 1} onChange={onChange} onError={onError} />)}</div>}
    <button className="skipButton" onClick={skip}>{item.skipped ? 'Вернуть упражнение' : 'Пропустить упражнение'}</button>
  </section>
}

export function WorkoutView({ session, onChange, onBack, onComplete, onError }: {
  session: WorkoutSession; onChange: (value: WorkoutSession) => void; onBack: () => void; onComplete: () => void; onError: (value: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const saved = session.exercises.reduce((count, item) => count + item.results.length, 0)
  const total = session.exercises.reduce((count, item) => count + (item.skipped ? 0 : item.sets_count), 0)
  const dateLabel = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', timeZone: 'UTC' }).format(new Date(`${session.scheduled_date}T12:00:00Z`))
  const complete = async () => {
    setBusy(true)
    try { await api.complete(session.id); onComplete() }
    catch (err) { onError((err as Error).message) }
    finally { setBusy(false) }
  }
  return <>
    <button className="backButton" onClick={onBack}>← <span>К плану</span></button>
    <div className="workoutTitle"><span className="eyebrow">{dateLabel} · {phaseText[session.phase]} тренировка</span><h1>{session.template_name}</h1><p>{session.muscle_group}</p></div>
    <div className="completionMeter"><div className="meterTop"><span>Записано подходов</span><strong aria-live="polite">{saved}<em> / {total}</em></strong></div><div className="meterTrack"><div style={{ width: `${total ? saved / total * 100 : 0}%` }} /></div></div>
    {session.exercises.map(item => <ExerciseBlock key={item.id} item={item} onChange={onChange} onError={onError} />)}
    <button className="primaryButton finishButton" onClick={complete} disabled={busy || saved !== total || total === 0}>Завершить тренировку <span>↗</span></button>
    <p className="hint">Записанные подходы сохраняются сразу. К тренировке можно вернуться позже.</p>
  </>
}
