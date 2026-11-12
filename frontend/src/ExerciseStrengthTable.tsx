import type { Progress } from './types'
import { periodRange, weekStart } from './weekDates'

type Exercise = Progress['exercises'][number]
type Cell = { value: number | null; light: boolean }

const format = (value: number) => value.toLocaleString('ru-RU', { maximumFractionDigits: 2 })

export function ExerciseStrengthTable({ exercises }: { exercises: Exercise[] }) {
  const weeks = [...new Set(exercises.flatMap(item => item.points.map(point => point.period_start ?? weekStart(point.date))))].sort()
  const durations = new Map(exercises.flatMap(item => item.points.map(point => [point.period_start ?? weekStart(point.date), point.period_days ?? 7] as const)))
  if (!weeks.length) return <div className="chartCard"><p>Пока нет результатов.</p></div>

  const rows = exercises.filter(item => item.points.length).map(item => {
    const cells = new Map<string, Cell>()
    for (const point of item.points) {
      const week = point.period_start ?? weekStart(point.date)
      const previous = cells.get(week)
      const light = point.phase === 'deload'
      if (!previous || (point.estimated_strength !== null && (previous.value === null || point.estimated_strength > previous.value))) {
        cells.set(week, { value: point.estimated_strength, light })
      } else if (light) {
        previous.light = true
      }
    }
    let baseline: number | null = null
    return { id: item.id, name: item.label ?? item.name, cells: weeks.map(week => {
      const cell = cells.get(week)
      if (!cell) return { week, value: null, tone: 'empty' }
      if (cell.light) return { week, value: cell.value, tone: 'light' }
      if (cell.value === null) return { week, value: null, tone: 'empty' }
      const tone = baseline === null ? 'first' : cell.value > baseline + 0.01 ? 'up' : cell.value < baseline - 0.01 ? 'down' : 'same'
      baseline = cell.value
      return { week, value: cell.value, tone }
    }) }
  })

  return <div className="chartCard">
    <div className="strengthTableWrap"><table className="strengthTable">
      <thead><tr><th scope="col">Упражнение</th>{weeks.map(week => <th scope="col" key={week}>{periodRange(week, durations.get(week))}</th>)}</tr></thead>
      <tbody>{rows.map(row => <tr key={row.id}><th scope="row">{row.name}</th>{row.cells.map(cell => <td key={cell.week} className={`strengthCell strengthCell--${cell.tone}`} title={`${row.name} · ${periodRange(cell.week, durations.get(cell.week))}${cell.tone === 'light' ? ' · Лёгкий цикл' : ''}`}>
        {cell.value === null ? '—' : <>{format(cell.value)} <small>кг</small></>}
      </td>)}</tr>)}</tbody>
    </table></div>
    <div className="plotLegend strengthLegend">
      <span><i className="strengthSwatch strengthSwatch--up" />вырос</span>
      <span><i className="strengthSwatch strengthSwatch--same" />без изменений</span>
      <span><i className="strengthSwatch strengthSwatch--down" />снизился</span>
      <span><i className="strengthSwatch strengthSwatch--light" />Лёгкий цикл</span>
    </div>
    <p className="hint chartNote">e1RM — расчётный максимум на одно повторение. Формула Эпли: вес × (1 + повторы / 30). Показан лучший рабочий подход периода с 2–10 повторами. Цвет сравнивает с последним обычным периодом с результатом; лёгкий цикл в сравнении не участвует. e1RM не используется для назначения веса.</p>
  </div>
}
