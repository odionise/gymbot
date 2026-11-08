import { useEffect, useState } from 'react'
import { api } from './api'
import { ExerciseTrend, LineGraph, VolumeGraph } from './ProgressCharts'
import { ChoiceDropdown } from './ChoiceDropdown'
import { ExerciseStrengthTable } from './ExerciseStrengthTable'
import type { Progress } from './types'

type WeekRow = Progress['weeks'][number] | NonNullable<Progress['weekly_summary']>[number]

export function ProgressView() {
  const [data, setData] = useState<Progress | null>(null)
  const [group, setGroup] = useState('all')
  const [exercise, setExercise] = useState('all')
  const [error, setError] = useState('')
  useEffect(() => { api.progress().then(setData).catch(err => setError((err as Error).message)) }, [])
  const groupOptions = [{ value: 'all', label: 'Все мышцы' }, ...[...new Set(data?.weeks.map(row => row.group) ?? [])].map(value => ({ value, label: value }))]
  const rows = (data?.weeks ?? []).filter(row => group === 'all' || row.group === group)
  const summaryUnavailable = group === 'all' && data !== null && data.weekly_summary === undefined
  const trendRows: WeekRow[] = group === 'all' ? data?.weekly_summary ?? [] : rows
  const unknownRirSets = data?.weekly_summary?.reduce((sum, row) => sum + row.rir_unknown_sets, 0) ?? 0
  const exerciseOptions = [{ value: 'all', label: 'Все упражнения' }, ...(data?.exercises ?? []).filter(item => group === 'all' || item.groups.includes(group)).map(item => ({ value: item.id, label: item.label ?? item.name }))]
  const points = (data?.exercises ?? []).filter(item => exercise === 'all' || item.id === exercise).flatMap(item => item.points.filter(point => group === 'all' || point.groups.includes(group)))
  const tableExercises = (data?.exercises ?? []).filter(item => (exercise === 'all' || item.id === exercise) && (group === 'all' || item.groups.includes(group)))
  return <><div className="eyebrow">Ваши результаты</div><h1>Прогресс</h1>
    {error && <div className="emptyCard" role="alert">{error}</div>}
    {!data && !error && <div className="emptyCard">Загружаем данные…</div>}
    {data && <><div className="progressFilters"><ChoiceDropdown label="Мышца" value={group} options={groupOptions} onChange={value => { setGroup(value); setExercise('all') }} /><ChoiceDropdown label="Упражнение" value={exercise} options={exerciseOptions} onChange={setExercise} /></div>
      {summaryUnavailable ? <div className="emptyCard">Общий свод недоступен в этой версии сервера. Выберите отдельную мышцу.</div> : <>
      {group === 'all' && <p className="hint">В общем своде каждый рабочий подход учтён один раз; разминка и пропуски исключены.{unknownRirSets > 0 && ` У ${unknownRirSets} подходов ПДО неизвестен: их вес и повторы учтены, жёсткость не определена.`}</p>}
      <VolumeGraph rows={trendRows} allMuscles={group === 'all'} />
      <LineGraph rows={trendRows} field="avg_reps_hard" label="Качество: повторы при сопоставимых весе и ПДО" unit="повт." />
      <LineGraph rows={trendRows} field="tonnage" label="Тоннаж рабочих подходов" unit="кг·повт." />
      <LineGraph rows={trendRows} field="avg_rir" label="Средний ПДО" unit="ПДО" />
      </>}
      {exercise !== 'all' && <ExerciseTrend points={points} label={exerciseOptions.find(item => item.value === exercise)?.label} />}
      <div className="sectionHead"><h2>Сигналы</h2></div>{data.signals.length ? <div className="emptyCard">{data.signals.slice(-8).map((item, index) => <p key={index}>{item}</p>)}</div> : <div className="emptyCard">Пока нет сигналов.</div>}
      <div className="sectionHead"><h2>Расчётный максимум по упражнениям</h2></div><ExerciseStrengthTable exercises={tableExercises} />
    </>}
  </>
}
