import { useEffect, useState } from 'react'
import { api } from './api'
import { countWord, formatWeight, phaseText } from './App'
import type { WorkoutSession } from './types'

export function HistoryView() {
  const [items, setItems] = useState<WorkoutSession[] | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [error, setError] = useState('')
  const dateLabel = (date: string) => new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', timeZone: 'UTC' }).format(new Date(`${date}T12:00:00Z`))
  useEffect(() => { api.history().then(setItems).catch(err => setError((err as Error).message)) }, [])
  return <>
    <div className="eyebrow">Ваш журнал</div><h1>История</h1>
    <p className="intro">Завершённые тренировки и подходы.</p>
    {error && <div className="emptyCard">{error}</div>}
    {!items && !error && <div className="emptyCard">Загружаем историю…</div>}
    {items?.length === 0 && <div className="emptyCard"><div className="emptyIcon">▤</div><h2>История пока пуста</h2><p>После первой завершённой тренировки здесь появятся результаты.</p></div>}
    <div className="historyList">{items?.map(session => <section className="historyCard" key={session.id}><button onClick={() => setOpen(open === session.id ? null : session.id)}><div><span className="cardIndex">{dateLabel(session.scheduled_date)} · {phaseText[session.phase]}</span><h2>{session.template_name}</h2><small>{session.muscle_group} · {session.exercises.filter(item => !item.skipped).length} {countWord(session.exercises.filter(item => !item.skipped).length, 'упражнение', 'упражнения', 'упражнений')}</small></div><span className="historyChevron">{open === session.id ? '−' : '+'}</span></button>{open === session.id && <div className="historyDetail">{session.exercises.map(item => <div className="historyExercise" key={item.id}><strong>{item.name}</strong><span>{item.skipped ? 'Пропущено' : item.kind === 'strength' ? item.results.map(result => `${formatWeight(result.weight)} кг × ${result.reps}`).join(' · ') : `${item.actual_duration_minutes ?? '—'} мин`}</span></div>)}</div>}</section>)}</div>
  </>
}
