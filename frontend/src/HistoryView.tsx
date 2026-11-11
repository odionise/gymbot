import { useEffect, useState } from 'react'
import { api } from './api'
import { countWord, formatWeight, phaseText } from './App'
import { RecommendationDetails } from './RecommendationDetails'
import type { WorkoutSession } from './types'

const dateLabel = (date: string) => new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${date}T12:00:00Z`))

export function HistoryEntry({ session, expanded, onToggle }: { session: WorkoutSession; expanded: boolean; onToggle: () => void }) {
  return <section className="historyCard">
    <button onClick={onToggle} aria-expanded={expanded}><div>
      <span className="cardIndex">{session.actual_date ? dateLabel(session.actual_date) : 'Дата выполнения неизвестна'} · {phaseText[session.phase]}</span>
      <h2>{session.template_name}</h2>
      {session.actual_date !== session.scheduled_date && <small>По плану: {dateLabel(session.scheduled_date)}</small>}
      <small>{session.muscle_group} · {session.exercises.filter(item => !item.skipped).length} {countWord(session.exercises.filter(item => !item.skipped).length, 'упражнение', 'упражнения', 'упражнений')}</small>
    </div><span className="historyChevron">{expanded ? '−' : '+'}</span></button>
    {expanded && <div className="historyDetail">{session.exercises.map(item => <div className="historyExercise" key={item.id}>
      <strong>{item.name}</strong>
      <span>{item.skipped ? 'Пропущено' : item.kind === 'strength' ? item.results.map(result => `${result.is_working ? `Подход ${result.set_index}` : `Разминка ${Math.abs(result.set_index)}`}: ${formatWeight(result.weight)} кг × ${result.reps}${result.rir_reported == null ? '' : `, ПДО ${result.rir_reported}`}`).join(' · ') : `${item.actual_duration_minutes ?? '—'} мин`}</span>
      {item.kind === 'strength' && <RecommendationDetails item={item} />}
    </div>)}</div>}
  </section>
}

export function HistoryView() {
  const [items, setItems] = useState<WorkoutSession[] | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [month, setMonth] = useState(() => { const now = new Date(); return new Date(Date.UTC(now.getFullYear(), now.getMonth(), 1)) })
  const [selectedDay, setSelectedDay] = useState<string | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { api.history().then(result => { setItems(result); const latest = result.find(session => session.actual_date)?.actual_date; if (latest) setMonth(new Date(`${latest.slice(0, 7)}-01T12:00:00Z`)) }).catch(err => setError((err as Error).message)) }, [])
  const year = month.getUTCFullYear()
  const monthIndex = month.getUTCMonth()
  const firstWeekday = (month.getUTCDay() + 6) % 7
  const weeks = Math.ceil((firstWeekday + new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate()) / 7)
  const days = Array.from({ length: weeks * 7 }, (_, index) => {
    const date = new Date(Date.UTC(year, monthIndex, index - firstWeekday + 1))
    return { key: date.toISOString().slice(0, 10), day: date.getUTCDate(), current: date.getUTCMonth() === monthIndex }
  })
  const visibleItems = items?.filter(session => session.actual_date?.slice(0, 7) === `${year}-${String(monthIndex + 1).padStart(2, '0')}`) ?? []
  const dayItems = selectedDay ? visibleItems.filter(session => session.actual_date === selectedDay) : visibleItems
  const monthTitle = new Intl.DateTimeFormat('ru-RU', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(month)
  const shiftMonth = (step: number) => { setMonth(new Date(Date.UTC(year, monthIndex + step, 1))); setSelectedDay(null); setOpen(null) }
  return <>
    <div className="historyMonthHead"><div><span className="historyOverline">История тренировок</span><h1>{monthTitle}</h1></div><div className="historyMonthActions"><button type="button" onClick={() => shiftMonth(-1)} aria-label="Предыдущий месяц">←</button><button type="button" onClick={() => shiftMonth(1)} aria-label="Следующий месяц">→</button></div></div>
    <div className="historyWeekdays" aria-hidden="true">{['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map(day => <span key={day}>{day}</span>)}</div>
    <div className="historyCalendar" aria-label={`Календарь тренировок: ${monthTitle}`}>{Array.from({ length: weeks }, (_, weekIndex) => <div className="historyWeek" key={weekIndex}>{days.slice(weekIndex * 7, weekIndex * 7 + 7).map(day => { const count = items?.filter(session => session.actual_date === day.key).length ?? 0; const today = day.key === new Date().toLocaleDateString('en-CA'); return <button type="button" key={day.key} className={`${day.current ? '' : 'outside'} ${selectedDay === day.key ? 'selected' : ''} ${today ? 'today' : ''}`} onClick={() => { setSelectedDay(selectedDay === day.key ? null : day.key); setOpen(null) }} aria-label={`${dateLabel(day.key)}: ${count} тренировок`} aria-pressed={selectedDay === day.key}><span>{day.day}</span>{count > 0 && <i aria-hidden="true" />}</button> })}</div>)}</div>
    {error && <div className="emptyCard">{error}</div>}
    {!items && !error && <div className="emptyCard">Загружаем историю…</div>}
    {items?.length === 0 && <div className="emptyCard"><div className="emptyIcon">▤</div><h2>История пока пуста</h2><p>После первой завершённой тренировки здесь появятся результаты.</p></div>}
    {items && items.length > 0 && <section className="historyResults"><div className="sectionHead"><h2>{selectedDay ? dateLabel(selectedDay) : 'Тренировки месяца'}</h2><span>{dayItems.length}</span></div>{dayItems.length ? <div className="historyList">{dayItems.map(session => <HistoryEntry key={session.id} session={session} expanded={open === session.id} onToggle={() => setOpen(open === session.id ? null : session.id)} />)}</div> : <p className="historyNoResults">За этот период тренировок нет. Выберите другой день или месяц.</p>}</section>}
  </>
}
