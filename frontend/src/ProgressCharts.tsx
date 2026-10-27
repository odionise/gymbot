import { useEffect, useRef, useState } from 'react'
import type { Progress } from './types'
import { weekRange, weekRangeLines, weekStart } from './weekDates'

type WeekRow = Progress['weeks'][number]
type Point = { date: string; value: number | null; phase?: string }
const blue = '#7096d0'
const grey = '#aeb4bd'
const coral = '#dd8580'
const green = '#4aa989'
const amber = '#d5a04c'
const format = (value: number) => value.toLocaleString('ru-RU', { maximumFractionDigits: 2 })

function useWidth() {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(360)
  useEffect(() => {
    if (!ref.current) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, Math.floor(entry.contentRect.width))))
    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [])
  return { ref, width }
}

function stepFor(span: number) {
  const rough = Math.max(0.01, span) / 4
  const scale = 10 ** Math.floor(Math.log10(rough))
  return ([1, 2, 2.5, 5, 6, 7.5, 10].find(value => value * scale >= rough) ?? 10) * scale
}

function Axis({ width, top, bottom, left, right, min, max, unit }: {
  width: number; top: number; bottom: number; left: number; right: number; min: number; max: number; unit: string
}) {
  return <>
    <text x={left} y={14} className="plotUnit">{unit}</text>
    {Array.from({ length: 5 }, (_, i) => {
      const y = bottom - i * (bottom - top) / 4
      return <g key={i}><line x1={left} x2={width - right} y1={y} y2={y} className="plotGrid" />
        <text x={left - 8} y={y + 4} textAnchor="end" className="plotTick">{format(min + (max - min) * i / 4)}</text></g>
    })}
    <line x1={left} x2={left} y1={top} y2={bottom} className="plotAxis" />
    <line x1={left} x2={width - right} y1={bottom} y2={bottom} className="plotAxis" />
  </>
}

function DateAxis({ dates, x, bottom, width, right, label }: {
  dates: string[]; x: (index: number) => number; bottom: number; width: number; right: number; label: string
}) {
  return <>
    {dates.map((day, i) => {
      const [range, month] = weekRangeLines(day)
      return <text key={`${day}-${i}`} x={x(i)} y={bottom + 18} textAnchor="middle" className="plotTick">
        <tspan x={x(i)}>{range}</tspan><tspan x={x(i)} dy="13">{month}</tspan>
      </text>
    })}
    <text x={width - right} y={258} textAnchor="end" className="plotUnit">{label}</text>
  </>
}

function Legend({ items }: { items: { color: string; label: string }[] }) {
  return <div className="plotLegend">{items.map(item => <span key={item.label}><i style={{ background: item.color }} />{item.label}</span>)}</div>
}

function LineChart({ title, points, unit, fromZero = false, note, assessment = 'none', xAxisLabel = 'Начало недели' }: {
  title: string; points: Point[]; unit: string; fromZero?: boolean; note: string; assessment?: 'none' | 'quality' | 'rir'; xAxisLabel?: string
}) {
  const { ref, width } = useWidth()
  const valid = points.map((point, index) => ({ ...point, index })).filter(point => point.value !== null)
  if (!valid.length) return <div className="chartCard"><h3>{title}</h3><p className="hint">Пока нет сопоставимых данных.</p></div>
  const values = valid.map(point => point.value as number)
  const min = fromZero ? 0 : Math.max(0, Math.floor(Math.min(...values)) - 1)
  const span = Math.max(...values) - min
  const max = min + (unit === 'повт.' ? Math.max(1, Math.ceil(span / 4)) : stepFor(span)) * 4
  const left = 56, right = 40, top = 26, bottom = 190
  const chartWidth = Math.max(width, 500, points.length * 86 + left + right)
  const plotWidth = chartWidth - left - right
  const x = (i: number) => left + (points.length === 1 ? plotWidth / 2 : i / (points.length - 1) * plotWidth)
  const y = (value: number) => bottom - (value - min) / (max - min) * (bottom - top)
  const bandWidth = Math.min(44, plotWidth / Math.max(1, points.length - 1) * 0.8)
  const tone = (index: number) => {
    const point = points[index]
    if (point.phase === 'deload') return grey
    if (point.phase === 'missed_deload') return coral
    if (assessment === 'rir' && point.value !== null) return point.value < 1 ? coral : point.value <= 3 ? green : amber
    if (assessment === 'quality' && index > 0 && point.value !== null && points[index - 1].value !== null) {
      const change = point.value - points[index - 1].value!
      return change > 0.25 ? green : change < -0.25 ? coral : blue
    }
    return blue
  }
  return <div className="chartCard"><h3>{title}</h3><div className="plotWrap" ref={ref}>
    <svg width={chartWidth} height="265" viewBox={`0 0 ${chartWidth} 265`} role="img" aria-label={`${title}, ${unit}`}>
      {points.map((point, i) => point.phase === 'deload' || point.phase === 'missed_deload'
        ? <rect key={`band-${i}`} x={x(i) - bandWidth / 2} y={top} width={bandWidth} height={bottom - top} className="plotDeload" /> : null)}
      <Axis width={chartWidth} top={top} bottom={bottom} left={left} right={right} min={min} max={max} unit={unit} />
      {points.slice(1).map((point, i) => point.value !== null && points[i].value !== null
        ? <line key={`segment-${i}`} x1={x(i)} y1={y(points[i].value!)} x2={x(i + 1)} y2={y(point.value)} className="plotLine" stroke={tone(i + 1)} /> : null)}
      {valid.map(point => <g key={point.index}>
        <circle cx={x(point.index)} cy={y(point.value!)} r="3.5" className="plotPoint" stroke={tone(point.index)}>
          <title>{`${weekRange(point.date)}: ${format(point.value!)} ${unit}`}</title>
        </circle>
        <text x={x(point.index)} y={y(point.value!) < top + 22 ? y(point.value!) + 19 : y(point.value!) - 10} textAnchor="middle" className="plotValue">{format(point.value!)}</text>
      </g>)}
      <DateAxis dates={points.map(point => point.date)} x={x} bottom={bottom} width={chartWidth} right={right} label={xAxisLabel} />
    </svg>
  </div>{assessment === 'quality' && <Legend items={[{ color: green, label: 'лучше: больше повторов' }, { color: blue, label: 'без заметного изменения' }, { color: coral, label: 'хуже: меньше повторов' }]} />}
    {assessment === 'rir' && <Legend items={[{ color: coral, label: 'ПДО < 1: высокая усталость' }, { color: green, label: 'ПДО 1–3: цель' }, { color: amber, label: 'ПДО > 3: запас выше цели' }, { color: grey, label: 'Легкая неделя' }]} />}
    <p className="hint chartNote">Последнее значение: {format(values.at(-1)!)} {unit}{unit.endsWith('.') ? '' : '.'} {note}</p></div>
}

export function LineGraph({ rows, field, label, unit }: {
  rows: WeekRow[]; field: 'avg_reps_hard' | 'tonnage' | 'avg_rir'; label: string; unit: string
}) {
  const points = rows.map(row => ({ date: row.week_start,
    value: field === 'avg_reps_hard' && row.phase !== 'accumulation' ? null : row[field], phase: row.phase }))
  return <LineChart title={label} points={points} unit={unit} fromZero={field !== 'avg_reps_hard'} assessment={field === 'avg_reps_hard' ? 'quality' : field === 'avg_rir' ? 'rir' : 'none'}
    note={field === 'avg_reps_hard' ? 'Цвет сравнивает соседние сопоставимые недели; Легкая неделя исключена из линии.' : field === 'tonnage' ? 'Синий — изменение нагрузки без оценки «лучше/хуже»; Легкая неделя серым.' : 'Легкая неделя отмечена серым.'} />
}

export function VolumeGraph({ rows, allMuscles }: { rows: WeekRow[]; allMuscles: boolean }) {
  const { ref, width } = useWidth()
  if (!rows.length) return <div className="emptyCard">График появится после тренировки с указанным ПДО и мышцей упражнения.</div>
  const max = stepFor(Math.max(...rows.map(row => Math.max(row.working_sets, allMuscles ? 0 : row.target_high)))) * 4
  const left = 52, right = 10, top = 26, bottom = 190
  const chartWidth = Math.max(width, rows.length * 86 + left + right)
  const plotWidth = chartWidth - left - right, plotHeight = bottom - top
  const slot = plotWidth / rows.length
  const barWidth = Math.min(32, slot * 0.5)
  const y = (value: number) => bottom - value / max * plotHeight
  return <div className="chartCard"><h3>Рабочие подходы по неделям</h3><div className="plotWrap" ref={ref}>
    <svg width={chartWidth} height="265" viewBox={`0 0 ${chartWidth} 265`} role="img" aria-label={`Рабочие и жёсткие подходы, ${allMuscles ? 'все мышцы' : rows[0].group}`}>
      <Axis width={chartWidth} top={top} bottom={bottom} left={left} right={right} min={0} max={max} unit="Рабочие подходы" />
      {rows.map((row, i) => {
        const center = left + (i + 0.5) * slot
        const deload = row.phase === 'deload' || row.phase === 'missed_deload'
        const color = row.phase === 'missed_deload' ? coral : deload ? grey : allMuscles ? blue : row.working_sets < row.target_low ? amber : row.working_sets > row.target_high ? coral : green
        return <g key={row.week_start}>
          {deload && <rect x={left + i * slot + 2} y={top} width={slot - 4} height={plotHeight} className="plotDeload" />}
          {!allMuscles && !deload && <rect x={center - barWidth / 2 - 3} y={y(row.target_high)} width={barWidth + 6} height={y(row.target_low) - y(row.target_high)} className="plotTarget" />}
          <rect x={center - barWidth / 2} y={y(row.working_sets)} width={barWidth} height={bottom - y(row.working_sets)} rx="4" fill={color} opacity="0.3">
            <title>{`${weekRange(row.week_start)}${deload ? ' · Легкая неделя' : ''}: ${format(row.working_sets)} рабочих, из них ${format(row.hard_sets)} с ПДО ≤ 3`}</title>
          </rect>
          {row.hard_sets > 0 && <rect x={center - barWidth * 0.32} y={y(row.hard_sets)} width={barWidth * 0.64} height={bottom - y(row.hard_sets)} rx="3" fill={color}>
            <title>{`${weekRange(row.week_start)}: ${format(row.hard_sets)} рабочих подходов с ПДО ≤ 3`}</title>
          </rect>}
          <text x={center} y={Math.max(top + 12, y(row.working_sets) - 6)} textAnchor="middle" className="plotBarValue">{format(row.working_sets)}</text>
        </g>
      })}
      <DateAxis dates={rows.map(row => row.week_start)} x={i => left + (i + 0.5) * slot} bottom={bottom} width={chartWidth} right={right} label="Неделя" />
    </svg>
  </div><Legend items={allMuscles ? [{ color: blue, label: 'сумма по всем мышцам' }, { color: grey, label: 'Легкая неделя' }] : [{ color: amber, label: 'ниже цели' }, { color: green, label: 'в пределах цели' }, { color: coral, label: 'выше цели' }, { color: grey, label: 'Легкая неделя' }]} />
    <p className="hint chartNote">Число и светлый столбец — все рабочие подходы; тёмная часть — жёсткие рабочие подходы с ПДО ≤ 3. {allMuscles ? 'Выберите мышцу, чтобы увидеть её целевой коридор.' : 'Цвет определяется по числу рабочих подходов относительно цели.'}</p></div>
}

export function ExerciseTrend({ points }: { points: Progress['exercises'][number]['points'] }) {
  if (!points.length) return null
  const weekly = new Map<string, { date: string; value: number; phase: string }>()
  for (const point of points) {
    const date = weekStart(point.date)
    const previous = weekly.get(date)
    if (!previous || point.reps > previous.value) weekly.set(date, { date, value: point.reps, phase: point.phase })
  }
  const series = [...weekly.values()].sort((a, b) => a.date.localeCompare(b.date))
  return <LineChart title="Повторения выбранного упражнения" points={series} unit="повт." xAxisLabel="Неделя" note="Показан лучший результат недели; Легкая неделя отмечена серым." />
}
