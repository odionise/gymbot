import { useEffect, useState } from 'react'
import { api } from './api'
import { ExerciseTrend, LineGraph, VolumeGraph } from './ProgressCharts'
import { ChoiceDropdown } from './ChoiceDropdown'
import { ExerciseStrengthTable } from './ExerciseStrengthTable'
import type { Progress } from './types'

type WeekRow = Progress['weeks'][number]

function combinedWeeks(rows: WeekRow[]): WeekRow[] {
  const dates = [...new Set(rows.map(row => row.week_start))].sort()
  const weighted = (items: WeekRow[], field: 'avg_rir' | 'avg_reps_hard', weight: 'working_sets' | 'hard_sets') => {
    const known = items.filter(row => row[field] !== null && row[weight] > 0)
    const total = known.reduce((sum, row) => sum + row[weight], 0)
    return total ? known.reduce((sum, row) => sum + (row[field] as number) * row[weight], 0) / total : null
  }
  return dates.map(day => {
    const items = rows.filter(row => row.week_start === day)
    const first = items[0]
    return { ...first, group: 'Все мышцы',
      hard_sets: items.reduce((sum, row) => sum + row.hard_sets, 0),
      working_sets: items.reduce((sum, row) => sum + row.working_sets, 0),
      tonnage: items.reduce((sum, row) => sum + row.tonnage, 0),
      avg_rir: weighted(items, 'avg_rir', 'working_sets'),
      avg_reps_hard: weighted(items, 'avg_reps_hard', 'hard_sets') }
  })
}

export function ProgressView() {
  const [data, setData] = useState<Progress | null>(null)
  const [group, setGroup] = useState('all')
  const [exercise, setExercise] = useState('all')
  const [error, setError] = useState('')
  useEffect(() => { api.progress().then(setData).catch(err => setError((err as Error).message)) }, [])
  const groupOptions = [{ value: 'all', label: 'Все мышцы' }, ...[...new Set(data?.weeks.map(row => row.group) ?? [])].map(value => ({ value, label: value }))]
  const rows = (data?.weeks ?? []).filter(row => group === 'all' || row.group === group)
  const trendRows = group === 'all' ? combinedWeeks(rows) : rows
  const exerciseOptions = [{ value: 'all', label: 'Все упражнения' }, ...(data?.exercises ?? []).filter(item => group === 'all' || item.groups.includes(group)).map(item => ({ value: item.id, label: item.name }))]
  const points = (data?.exercises ?? []).filter(item => exercise === 'all' || item.id === exercise).flatMap(item => item.points.filter(point => group === 'all' || point.groups.includes(group)))
  const tableExercises = (data?.exercises ?? []).filter(item => (exercise === 'all' || item.id === exercise) && (group === 'all' || item.groups.includes(group)))
  return <><div className="eyebrow">Ваши результаты</div><h1>Прогресс</h1>
    {error && <div className="emptyCard" role="alert">{error}</div>}
    {!data && !error && <div className="emptyCard">Загружаем данные…</div>}
    {data && <><div className="progressFilters"><ChoiceDropdown label="Мышца" value={group} options={groupOptions} onChange={value => { setGroup(value); setExercise('all') }} /><ChoiceDropdown label="Упражнение" value={exercise} options={exerciseOptions} onChange={setExercise} /></div>
      <VolumeGraph rows={trendRows} allMuscles={group === 'all'} />
      <LineGraph rows={trendRows} field="avg_reps_hard" label="Качество: повторы при сопоставимых весе и ПДО" unit="повт." />
      <LineGraph rows={trendRows} field="tonnage" label="Тоннаж рабочих подходов" unit="кг·повт." />
      <LineGraph rows={trendRows} field="avg_rir" label="Средний ПДО" unit="ПДО" />
      {exercise !== 'all' && <ExerciseTrend points={points} />}
      <div className="sectionHead"><h2>Сигналы</h2></div>{data.signals.length ? <div className="emptyCard">{data.signals.slice(-8).map((item, index) => <p key={index}>{item}</p>)}</div> : <div className="emptyCard">Пока нет сигналов.</div>}
      <div className="sectionHead"><h2>Расчётный максимум по упражнениям</h2></div><ExerciseStrengthTable exercises={tableExercises} />
    </>}
  </>
}
