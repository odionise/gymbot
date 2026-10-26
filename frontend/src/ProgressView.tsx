import { useEffect, useState } from 'react'
import { api } from './api'
import { ChoiceDropdown } from './ChoiceDropdown'
import { muscleGroups, parseMuscleGroups } from './muscleGroups'
import type { Phase, Progress, ProgressPoint, Template } from './types'

type Metric = 'weight' | 'reps' | 'volume' | 'estimated_strength'
type Series = { id: string; name: string; points: ProgressPoint[] }
const colors = ['#7096d0', '#e0ac4d', '#dd8580', '#6da995', '#a386bd', '#71899d']
const metricLabels: Record<Metric, string> = { weight: 'Вес', reps: 'Повторы', volume: 'Объём', estimated_strength: 'Оценка силы' }
const phaseLabels = { all: 'Все', light: 'Лёгкая', medium: 'Средняя', heavy: 'Тяжёлая' }
const dateLabel = (date: string) => new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(`${date}T12:00:00Z`))
const exerciseWord = (count: number) => count % 100 >= 11 && count % 100 <= 14 ? 'упражнений' : count % 10 === 1 ? 'упражнение' : count % 10 >= 2 && count % 10 <= 4 ? 'упражнения' : 'упражнений'

function Graph({ series, metric, showLegend }: { series: Series[]; metric: Metric; showLegend: boolean }) {
  const visible = series.map(item => ({ ...item, values: item.points.map(point => ({ date: point.date, value: point[metric] })).filter(point => point.value !== null) as { date: string; value: number }[] })).filter(item => item.values.length)
  if (!visible.length) return <div className="graphEmpty">Для выбранного показателя пока нет данных.</div>
  const all = visible.flatMap(item => item.values)
  const values = all.map(point => point.value)
  const low = Math.min(...values), high = Math.max(...values)
  const span = Math.max(high - low, high * 0.12, 1)
  const min = Math.max(0, low - span * 0.25), max = high + span * 0.25
  const dates = all.map(point => point.date).sort()
  const first = Date.parse(`${dates[0]}T12:00:00Z`), last = Date.parse(`${dates.at(-1)}T12:00:00Z`)
  const coords = (item: typeof visible[number]) => item.values.map(point => ({
    x: first === last ? 50 : 8 + (Date.parse(`${point.date}T12:00:00Z`) - first) / (last - first) * 84,
    y: 82 - (point.value - min) / (max - min) * 64,
  }))
  return <><div className="graphWrap"><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={`График: ${metricLabels[metric]}; ${visible.map(item => item.name).join(', ')}`}>
    {[20, 40, 60, 80].map(y => <line className="gridLine" key={y} x1="0" y1={y} x2="100" y2={y} />)}
    {visible.map((item, index) => { const points = coords(item); const color = colors[index % colors.length]; return <g key={item.id}><polyline className="chartLine" style={{ stroke: color }} points={points.map(point => `${point.x},${point.y}`).join(' ')} />{points.map((point, i) => <ellipse className="chartDot" style={{ fill: color }} key={i} cx={point.x} cy={point.y} rx="1.3" ry="2.8" />)}</g> })}
  </svg><div className="chartLabels"><span>{dateLabel(dates[0])}</span><span>{first === last ? '1 тренировка' : dateLabel(dates.at(-1)!)}</span></div></div>
  {showLegend && <div className="chartLegend">{visible.map((item, index) => <span key={item.id}><i style={{ backgroundColor: colors[index % colors.length] }} />{item.name}</span>)}</div>}</>
}

export function ProgressView() {
  const [data, setData] = useState<Progress | null>(null)
  const [templates, setTemplates] = useState<Template[]>([])
  const [group, setGroup] = useState('Грудь')
  const [selected, setSelected] = useState('all')
  const [metric, setMetric] = useState<Metric>('volume')
  const [phase, setPhase] = useState<Phase | 'all'>('all')
  const [error, setError] = useState('')
  useEffect(() => { Promise.all([api.progress(), api.templates()]).then(([progress, program]) => {
    setData(progress)
    setTemplates(program)
    setGroup(progress.exercises[0]?.groups[0] ?? parseMuscleGroups(program[0]?.muscle_group ?? '')[0] ?? 'Грудь')
  }).catch(err => setError((err as Error).message)) }, [])

  const groupOptions = [...new Set([...muscleGroups, ...templates.flatMap(item => parseMuscleGroups(item.muscle_group)), ...(data?.exercises.flatMap(item => item.groups) ?? [])])].map(item => ({ value: item, label: item }))
  const exerciseNames = new Map<string, string>()
  templates.filter(item => parseMuscleGroups(item.muscle_group).includes(group)).forEach(item => item.exercises.forEach(exercise => exerciseNames.set(exercise.id, exercise.name)))
  data?.exercises.filter(item => item.groups.includes(group)).forEach(item => exerciseNames.set(item.id, item.name))
  const exerciseOptions = [{ value: 'all', label: 'Все' }, ...[...exerciseNames].map(([value, label]) => ({ value, label }))]
  const series = (data?.exercises ?? []).filter(item => item.groups.includes(group) && (selected === 'all' || item.id === selected)).map(item => ({ id: item.id, name: item.name, points: item.points.filter(point => point.groups.includes(group) && (phase === 'all' || point.phase === phase)) }))
  const currentValue = selected === 'all' ? null : series[0]?.points.at(-1)?.[metric]
  const summary = data?.groups.find(item => item.group === group)
  const unit = metric === 'reps' ? 'повт.' : metric === 'volume' ? 'кг·повт.' : 'кг'
  const exerciseCount = exerciseOptions.length - 1

  return <>
    <div className="eyebrow">Ваши результаты</div><h1>Прогресс</h1>
    <p className="intro">Следите за нагрузкой и повторениями по каждому упражнению.</p>
    {error && <div className="emptyCard" role="alert">{error}</div>}
    {!data && !error && <div className="emptyCard">Загружаем данные…</div>}
    {data && <>
      <div className="sectionHead progressFirstHead"><h2>Динамика</h2></div>
      <div className="progressFilters">
        <ChoiceDropdown label="Мышечная группа" value={group} options={groupOptions} onChange={value => { setGroup(value); setSelected('all'); setPhase('all') }} />
        <ChoiceDropdown label="Упражнение" value={selected} options={exerciseOptions} onChange={value => { setSelected(value); setPhase('all') }} />
      </div>
      <div className="chartCard">
        <div className="metricTabs">{(Object.keys(metricLabels) as Metric[]).map(item => <button key={item} className={item === metric ? 'active' : ''} onClick={() => setMetric(item)}>{metricLabels[item]}</button>)}</div>
        <div className="phaseTabs">{(['all', 'light', 'medium', 'heavy'] as const).map(item => <button key={item} className={item === phase ? 'active' : ''} onClick={() => setPhase(item)}>{phaseLabels[item]}</button>)}</div>
        <div className="chartValue">{selected === 'all' ? <>{exerciseCount}<span> {exerciseWord(exerciseCount)}</span></> : <>{currentValue == null ? '—' : currentValue.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}{currentValue != null && <span> {unit}</span>}</>}</div>
        <Graph series={series} metric={metric} showLegend={selected === 'all'} />
        <div className="chartNote">{!series.some(item => item.points.length) ? 'График появится после сохранённой тренировки.' : metric === 'estimated_strength' ? 'Оценка силы рассчитана по подходам с 2–10 повторениями.' : selected === 'all' ? 'Каждая линия — отдельное упражнение с записанными подходами.' : phase === 'all' ? 'Выберите тип дня, чтобы сравнивать одинаковые нагрузки.' : 'Показаны тренировки выбранного типа.'}</div>
      </div>
      <div className="sectionHead"><h2>Сводка · {group}</h2></div>
      {summary ? <div className="summaryGrid"><div className="summaryCard"><span>Изменение силы</span><strong>{summary.strength_change_percent === null ? '—' : `${summary.strength_change_percent >= 0 ? '+' : ''}${summary.strength_change_percent}%`}</strong><small>По одинаковым типам тренировок</small><div className="summaryDivider" /><small>Объём тренировок с группой · {Math.min(summary.sessions, 3)}</small><b>{summary.cycle_volume.toLocaleString('ru-RU')} кг·повт.</b></div></div> : <div className="emptyCard"><h2>Пока нет результатов</h2><p>Завершите тренировку этой группы, и здесь появится сводка.</p></div>}
    </>}
  </>
}
