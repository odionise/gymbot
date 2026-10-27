import { useEffect, useState } from 'react'
import { api } from './api'
import { formatWeight, phaseText } from './App'
import type { SessionExercise, WorkoutSession } from './types'

function SetRow({ item, index, onChange, onError }: {
  item: SessionExercise; index: number; onChange: (value: WorkoutSession) => void; onError: (value: string) => void
}) {
  const saved = item.results.find(result => result.set_index === index)
  const suggestion = item.next_set?.set_index === index ? item.next_set : null
  const [weight, setWeight] = useState(String(saved?.weight ?? suggestion?.weight ?? item.target_weight))
  const [reps, setReps] = useState(String(saved?.reps ?? suggestion?.reps ?? item.target_reps))
  const [rir, setRir] = useState(String(saved?.rir_reported ?? item.target_rir ?? 2))
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    setWeight(String(saved?.weight ?? suggestion?.weight ?? item.target_weight))
    setReps(String(saved?.reps ?? suggestion?.reps ?? item.target_reps))
    setRir(String(saved?.rir_reported ?? item.target_rir ?? 2))
  }, [saved?.weight, saved?.reps, saved?.rir_reported, suggestion?.weight, suggestion?.reps, item.target_weight, item.target_reps, item.target_rir])
  const save = async () => {
    setBusy(true)
    try { onChange(await api.saveSet(item.id, index, Number(weight), Number(reps), rir === '' ? null : Number(rir), index > 0)) }
    catch (err) { onError((err as Error).message) }
    finally { setBusy(false) }
  }
  const remove = async () => {
    setBusy(true)
    try { onChange(await api.deleteSet(item.id, index)) }
    catch (err) { onError((err as Error).message) }
    finally { setBusy(false) }
  }
  const adjust = (value: string, delta: number, maximum: number, update: (next: string) => void) => {
    const current = Number(value)
    const next = Math.min(maximum, Math.max(0, (Number.isFinite(current) ? current : 0) + delta))
    update(String(Math.round(next * 100) / 100))
  }
  const valueField = (label: string, value: string, update: (next: string) => void, increment: number, maximum: number, mode: 'decimal' | 'numeric') =>
    <div className="setField"><span>{label}</span><div className="setValueControl"><button type="button" className="setStepButton" onClick={() => adjust(value, -increment, maximum, update)} disabled={busy || Number(value) <= 0} aria-label={`Уменьшить ${label}`} title={`−${increment}`}>−</button><input aria-label={label} inputMode={mode} type="number" min="0" max={maximum} step={mode === 'numeric' ? '1' : 'any'} value={value} onChange={event => update(event.target.value)} /><button type="button" className="setStepButton" onClick={() => adjust(value, increment, maximum, update)} disabled={busy || Number(value) >= maximum} aria-label={`Увеличить ${label}`} title={`+${increment}`}>+</button></div></div>
  return <div className={`setRow ${saved ? 'isSaved' : ''}`}>
    <span className="setNumber">{index > 0 ? index : 'Р' + Math.abs(index)}</span>
    {valueField('вес, кг', weight, setWeight, item.weight_step, 1000, 'decimal')}
    {valueField('повторы', reps, setReps, 1, 100, 'numeric')}
    {valueField('ПДО', rir, setRir, 0.5, 10, 'decimal')}
    <button className={`saveSet ${saved ? 'saved' : ''}`} onClick={save} disabled={busy || weight === '' || reps === '' || (index > 0 && rir === '')} aria-label={saved ? 'Обновить подход' : 'Сохранить подход'}>{saved ? '✓' : '→'}</button>
    {saved && <button className="deleteSet" onClick={remove} disabled={busy} aria-label="Удалить подход">×</button>}
  </div>
}

function ExerciseBlock({ item, onChange, onError }: {
  item: SessionExercise; onChange: (value: WorkoutSession) => void; onError: (value: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [warmups, setWarmups] = useState(Math.max(1, ...item.results.filter(result => !result.is_working).map(result => Math.abs(result.set_index))))
  const lastWarmupSaved = item.results.some(result => !result.is_working && result.set_index === -warmups)
  const [warmupBusy, setWarmupBusy] = useState(false)
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
  const removeWarmup = async () => {
    if (warmups === 0 || warmupBusy) return
    if (!lastWarmupSaved) { setWarmups(count => count - 1); return }
    setWarmupBusy(true)
    try {
      const updated = await api.deleteSet(item.id, -warmups)
      setWarmups(count => count - 1)
      onChange(updated)
    } catch (err) { onError((err as Error).message) }
    finally { setWarmupBusy(false) }
  }
  return <section className={`exerciseCard ${item.skipped ? 'skipped' : ''}`}>
    <div className="exerciseHead"><div><span className="cardIndex">Упражнение {item.position + 1}</span><h2>{item.name}</h2></div><span className="exerciseCheck">{item.results.filter(result => result.is_working).length}<span> / {item.sets_count}</span></span></div>
    <div className="targetLine"><div className="targetWeight"><span>Вес</span><strong>{formatWeight(item.target_weight)}<small> кг</small></strong></div><div className="targetReps"><span>Повторы</span><strong>{item.sets_count} × {item.target_reps}</strong><small>Диапазон {item.min_reps}–{item.max_reps} · ПДО {item.target_rir ?? '—'}</small></div></div>
    {item.action_label && <p className="hint">{item.action_label}</p>}
    {item.next_set && <p className="hint">Следующий подход: {formatWeight(item.next_set.weight)} кг × {item.next_set.reps}; {item.next_set.reason.toLowerCase()}.</p>}
    {!item.results.length && <button className="textButton" onClick={() => setEditing(!editing)}>{editing ? 'Скрыть изменение' : 'Изменить цель'}</button>}
    {editing && !item.results.length && <div className="overrideBox"><label>Вес, кг<input type="number" min="0" step="0.5" value={weight} onChange={event => setWeight(event.target.value)} /></label><label>Повторы<input type="number" min="1" value={reps} onChange={event => setReps(event.target.value)} /></label><button onClick={override}>Сохранить</button></div>}
    {!item.skipped && <div className="setsList"><div className="setsCaption"><span>Подходы</span><span>Вес, повторы и ПДО</span></div><small>Разминка (не входит в объём)</small>{Array.from({ length: warmups }, (_, n) => <SetRow key={-n - 1} item={item} index={-n - 1} onChange={onChange} onError={onError} />)}<div className="programActions warmupActions"><button disabled={warmups >= 5 || warmupBusy} onClick={() => setWarmups(count => count + 1)}>+ Разминка</button><button disabled={warmups === 0 || warmupBusy} onClick={removeWarmup}>− Разминка</button></div>{Array.from({ length: item.sets_count }, (_, n) => <SetRow key={n + 1} item={item} index={n + 1} onChange={onChange} onError={onError} />)}<div className="programActions"><button disabled={item.sets_count >= 12} onClick={async () => { try { onChange(await api.changeSetsCount(item.id, item.sets_count + 1)) } catch (err) { onError((err as Error).message) } }}>+ Подход</button><button disabled={item.sets_count <= 1 || item.results.some(result => result.is_working && result.set_index === item.sets_count)} onClick={async () => { try { onChange(await api.changeSetsCount(item.id, item.sets_count - 1)) } catch (err) { onError((err as Error).message) } }}>− Подход</button></div></div>}
    <button className="skipButton" onClick={skip}>{item.skipped ? 'Вернуть упражнение' : 'Пропустить упражнение'}</button>
  </section>
}

function TimedExerciseBlock({ item, onChange, onError }: {
  item: SessionExercise; onChange: (value: WorkoutSession) => void; onError: (value: string) => void
}) {
  const [minutes, setMinutes] = useState(String(item.actual_duration_minutes ?? item.target_duration_minutes ?? 20))
  const [busy, setBusy] = useState(false)
  useEffect(() => setMinutes(String(item.actual_duration_minutes ?? item.target_duration_minutes ?? 20)), [item.actual_duration_minutes, item.target_duration_minutes])
  const save = async () => {
    setBusy(true)
    try { onChange(await api.saveDuration(item.id, Number(minutes))) } catch (err) { onError((err as Error).message) }
    finally { setBusy(false) }
  }
  const skip = async () => {
    try { onChange(await api.skip(item.id, !item.skipped)) } catch (err) { onError((err as Error).message) }
  }
  return <section className={`exerciseCard timedExercise ${item.skipped ? 'skipped' : ''}`}>
    <div className="exerciseHead"><div><span className="cardIndex">Упражнение {item.position + 1}</span><h2>{item.name}</h2></div><span className="exerciseCheck">{item.actual_duration_minutes ? '✓' : '—'}</span></div>
    <p className="hint">План: {item.target_duration_minutes} мин. Запишите фактическое время.</p>
    {!item.skipped && <div className="timedInputRow"><div className="setField"><span>Минуты</span><div className="setValueControl"><button type="button" className="setStepButton" onClick={() => setMinutes(String(Math.max(1, Number(minutes) - 1)))} disabled={busy || Number(minutes) <= 1}>−</button><input aria-label="Фактическая длительность, минут" type="number" min="1" max="600" inputMode="numeric" value={minutes} onChange={event => setMinutes(event.target.value)} /><button type="button" className="setStepButton" onClick={() => setMinutes(String(Math.min(600, Number(minutes) + 1)))} disabled={busy || Number(minutes) >= 600}>+</button></div></div><button className="outlineButton" onClick={save} disabled={busy || Number(minutes) < 1 || Number(minutes) > 600}>{item.actual_duration_minutes ? 'Обновить время' : 'Сохранить время'}</button>{item.actual_duration_minutes && <button className="textButton" disabled={busy} onClick={async () => { try { onChange(await api.clearDuration(item.id)) } catch (err) { onError((err as Error).message) } }}>Удалить запись</button>}</div>}
    <button className="skipButton" onClick={skip} disabled={Boolean(item.actual_duration_minutes) && !item.skipped}>{item.skipped ? 'Вернуть упражнение' : 'Пропустить упражнение'}</button>
  </section>
}

export function WorkoutView({ session, onChange, onBack, onComplete, onError }: {
  session: WorkoutSession; onChange: (value: WorkoutSession) => void; onBack: () => void; onComplete: () => void; onError: (value: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const [newDate, setNewDate] = useState(session.scheduled_date)
  const saved = session.exercises.reduce((count, item) => count + (item.kind === 'strength' ? item.results.filter(result => result.is_working).length : item.actual_duration_minutes && !item.skipped ? 1 : 0), 0)
  const total = session.exercises.reduce((count, item) => count + (item.skipped ? 0 : item.kind === 'strength' ? item.sets_count : 1), 0)
  const dateLabel = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', timeZone: 'UTC' }).format(new Date(`${session.scheduled_date}T12:00:00Z`))
  const complete = async () => {
    setBusy(true)
    try { await api.complete(session.id); onComplete() }
    catch (err) { onError((err as Error).message) }
    finally { setBusy(false) }
  }
  return <>
    <button className="backButton" onClick={onBack}>← <span>К плану</span></button>
    <div className="workoutTitle"><span className="eyebrow">{dateLabel} · {session.phase === 'deload' ? 'Легкая неделя' : `${phaseText[session.phase]} тренировка`}</span><h1>{session.template_name}</h1><p>{session.muscle_group}</p></div>
    {session.deload_reason && <p className="hint">Легкая неделя: {session.deload_reason === 'scheduled' ? 'по календарю' : session.deload_reason === 'auto' ? 'по сигналам восстановления' : 'по вашему выбору'}.</p>}
    {session.week_start && <button className="outlineButton" onClick={async () => { try { await api.setRecovery(session.week_start!, !session.feeling_beat_up); onChange({ ...session, feeling_beat_up: !session.feeling_beat_up }) } catch (err) { onError((err as Error).message) } }}>{session.feeling_beat_up ? 'Отмечено: тяжело / болит' : 'Отметить: тяжело / болит'}</button>}
    {session.status === 'planned' && <div className="fieldGrid"><label className="field"><span>Перенести на дату</span><input type="date" value={newDate} onChange={event => setNewDate(event.target.value)} /></label><button className="outlineButton" onClick={async () => { try { onChange(await api.reschedule(session.id, newDate)) } catch (err) { onError((err as Error).message) } }}>Перенести</button></div>}
    <div className="completionMeter"><div className="meterTop"><span>Записано результатов</span><strong aria-live="polite">{saved}<em> / {total}</em></strong></div><div className="meterTrack"><div style={{ width: `${total ? saved / total * 100 : 0}%` }} /></div></div>
    {session.exercises.map(item => item.kind === 'strength' ? <ExerciseBlock key={item.id} item={item} onChange={onChange} onError={onError} /> : <TimedExerciseBlock key={item.id} item={item} onChange={onChange} onError={onError} />)}
    <button className="primaryButton finishButton" onClick={complete} disabled={busy || saved !== total || total === 0}>Завершить тренировку</button>
    <p className="hint">Результаты сохраняются сразу. К тренировке можно вернуться позже.</p>
  </>
}
