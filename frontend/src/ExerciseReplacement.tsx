import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { api, ApiError } from './api'
import { ChoiceDropdown } from './ChoiceDropdown'
import { countWord, formatWeight } from './App'
import { movementKinds, timedOptions } from './MovementCatalog'
import { filterMovements, normalizeMovementSearch } from './movementSearch'
import type { Exercise, ExerciseHistoryOption, ExerciseHistoryOptions, Movement, ReplacementInput, ReplacementResult } from './types'

function historyLabel(option: ExerciseHistoryOption) {
  const date = option.last_completed_date ? new Date(option.last_completed_date) : null
  const lastDate = date && !Number.isNaN(date.getTime())
    ? new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).format(date)
    : 'дата неизвестна'
  const result = option.last_result
  const lastResult = result?.duration_minutes != null ? `${result.duration_minutes} мин`
    : result?.weight != null && result.reps != null ? `${formatWeight(result.weight)} кг × ${result.reps}` : 'результат не указан'
  return `${option.name} · ${option.completed_sessions} ${countWord(option.completed_sessions, 'занятие', 'занятия', 'занятий')} · ${lastDate} · ${lastResult}`
}

export function ExerciseReplacement({ exercise, movements, detailGroups, onClose, onReplaced, run }: {
  exercise: Exercise
  movements: Movement[]
  detailGroups: Record<string, string[]>
  onClose: () => void
  onReplaced: (result: ReplacementResult) => void
  run: (action: () => Promise<unknown>) => Promise<void>
}) {
  const [movementId, setMovementId] = useState('')
  const [muscleFilter, setMuscleFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [options, setOptions] = useState<ExerciseHistoryOptions | null>(null)
  const [historyMode, setHistoryMode] = useState<ReplacementInput['history_mode']>('new')
  const [historyId, setHistoryId] = useState('')
  const [historyError, setHistoryError] = useState('')
  const [reload, setReload] = useState(0)
  const [saveError, setSaveError] = useState('')
  const [conflict, setConflict] = useState(false)
  const [busy, setBusy] = useState(false)
  const [weight, setWeight] = useState('')
  const [step, setStep] = useState('2.5')
  const [sets, setSets] = useState('3')
  const [repMin, setRepMin] = useState('6')
  const [repMax, setRepMax] = useState('12')
  const [minutes, setMinutes] = useState('')
  const movement = movements.find(item => item.id === movementId)
  const filteredMovements = filterMovements(movements, muscleFilter, search)
  const query = normalizeMovementSearch(search)
  const selectedHistory = options?.options.find(item => item.history_id === historyId)

  useEffect(() => {
    let cancelled = false
    setOptions(null); setHistoryError('')
    if (movementId) {
      api.exerciseHistoryOptions(exercise.id, movementId)
        .then(value => { if (!cancelled) setOptions(value) })
        .catch((err: Error) => { if (!cancelled) setHistoryError(err.message) })
    }
    return () => { cancelled = true }
  }, [exercise.id, movementId, reload])

  const chooseMovement = (id: string) => {
    setMovementId(id); setHistoryMode('new'); setHistoryId('')
    // A replacement never inherits another movement's starting weight or time.
    setWeight(''); setMinutes(''); setSaveError(''); setConflict(false)
  }
  const strength = movement?.kind === 'strength'
  const validNumbers = strength
    ? weight !== '' && Number(weight) >= 0 && Number(weight) <= 1000
      && Number(step) > 0 && Number(step) <= 100
      && Number.isInteger(Number(sets)) && Number(sets) >= 1 && Number(sets) <= 12
      && Number.isInteger(Number(repMin)) && Number(repMin) >= 1
      && Number.isInteger(Number(repMax)) && Number(repMax) <= 50 && Number(repMin) <= Number(repMax)
    : minutes !== '' && Number.isInteger(Number(minutes)) && Number(minutes) >= 1 && Number(minutes) <= 600
  const canSave = Boolean(movement && options && validNumbers && (historyMode === 'new' || selectedHistory))

  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (!movement || !canSave || busy) return
    const settings: ReplacementInput['settings'] = movement.kind === 'strength'
      ? { sets_count: Number(sets), medium_weight: Number(weight), weight_step: Number(step), rep_min: Number(repMin), rep_max: Number(repMax) }
      : { duration_minutes: Number(minutes) }
    setBusy(true); setSaveError(''); setConflict(false)
    try {
      await run(async () => {
        try {
          const result = await api.replaceExercise(exercise.id, {
            movement_id: movement.id, history_mode: historyMode,
            history_id: historyMode === 'resume' ? historyId : null, settings,
          })
          onReplaced(result)
          onClose()
        } catch (err) {
          setSaveError((err as Error).message)
          setConflict(err instanceof ApiError && err.status === 409)
          throw err
        }
      })
    } finally { setBusy(false) }
  }
  const numberField = (label: string, value: string, update: (value: string) => void, minimum: number, maximum: number, increment = '1') =>
    <label className="field"><span>{label}</span><input required type="number" value={value} min={minimum} max={maximum} step={increment} onChange={event => update(event.target.value)} disabled={busy} /></label>

  return <form className="editorPanel" onSubmit={save} aria-busy={busy}>
    <div className="editorTitle"><h3>Заменить упражнение</h3><button type="button" onClick={onClose} disabled={busy} aria-label="Отменить замену">×</button></div>
    <p className="fieldHelp">Сейчас в программе: <strong>{exercise.name}</strong>. Уже созданные занятия сохранят прежнее упражнение и цели. Замена действует со следующей новой тренировки.</p>
    {!movement ? <>
      <div className="catalogFilters"><ChoiceDropdown label="Мышца или тип" value={muscleFilter} options={[{ value: 'all', label: 'Все упражнения' }, ...Object.values(detailGroups).flat().map(group => ({ value: group, label: group })), ...timedOptions]} onChange={setMuscleFilter} /><label className="field"><span>Поиск по названию</span><input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Название движения" /></label></div>
      {query.length > 0 && query.length < 3 && <p className="fieldHelp">Введите не меньше трёх букв для поиска.</p>}
      <div className="movementChoiceList" role="listbox" aria-label="Движение для замены">{filteredMovements.map(item => <button type="button" role="option" aria-selected={false} key={item.id} onClick={() => chooseMovement(item.id)}><strong>{item.name}</strong><small>{item.kind === 'strength' ? item.primary_group : movementKinds[item.kind]}</small></button>)}{!filteredMovements.length && <p className="fieldHelp">Движения не найдены. Добавьте нужное движение в справочник.</p>}</div>
    </> : <>
      <div className="movementPickerTrigger"><span><strong>{movement.name}</strong><small>{movementKinds[movement.kind]}</small></span><button type="button" className="textButton" disabled={busy} onClick={() => chooseMovement('')}>Выбрать другое</button></div>
      {!options && !historyError && <p className="fieldHelp" role="status">Проверяем прежние базы результатов…</p>}
      {historyError && <div><p className="fieldError" role="alert">Не удалось проверить историю: {historyError}</p><button type="button" className="textButton" disabled={busy} onClick={() => setReload(value => value + 1)}>Повторить проверку</button></div>}
      {options && <>
        {options.options.length > 0 && <p className="fieldHelp">Для этого движения есть прежняя история в том же месте программы. Выберите, продолжить её или начать новую базу.</p>}
        <ChoiceDropdown label="База результатов" value={historyMode} options={[{ value: 'new', label: 'Начать новую базу' }, ...(options.options.length ? [{ value: 'resume', label: 'Продолжить прежнюю историю' }] : [])]} onChange={value => { if (!busy) { setHistoryMode(value as ReplacementInput['history_mode']); setHistoryId('') } }} />
        {historyMode === 'resume' ? <>
          <ChoiceDropdown label="Прежняя база" value={historyId} placeholder="Выберите базу результатов" options={options.options.map(item => ({ value: item.history_id, label: historyLabel(item) }))} onChange={value => { if (!busy) setHistoryId(value) }} />
          {selectedHistory && <><p className="fieldHelp">{historyLabel(selectedHistory)}</p><p className="fieldHelp">Будет продолжена выбранная база. Вес рассчитывается по её собственным результатам; это не обязательно последний записанный вес.</p></>}
        </> : <p className="fieldHelp">Прежние результаты останутся в истории. Для новой базы используются заданные ниже стартовые параметры.</p>}
        {!options.options.length && <p className="fieldHelp">Подходящей прежней базы здесь нет. Задайте явный старт.</p>}
        {options.excluded_legacy && <p className="fieldHelp">Часть старой истории нельзя достоверно связать с этим движением. Эти записи сохранены, но не предлагаются для продолжения.</p>}
      </>}
      {strength ? <>
        <div className="fieldGrid">{numberField(historyMode === 'new' ? 'Стартовый вес, кг' : 'Старт без подходящей истории, кг', weight, setWeight, 0, 1000, 'any')}{numberField('Шаг веса, кг', step, setStep, 0.01, 100, '0.01')}{numberField('Базовых подходов', sets, setSets, 1, 12)}</div>
        <div className="fieldGrid">{numberField('Повторы от', repMin, setRepMin, 1, 50)}{numberField('Повторы до', repMax, setRepMax, 1, 50)}</div>
        <p className="fieldHelp">Ноль килограммов допустим, если вы ввели его явно. Шаг веса — от 0,01 кг, до двух знаков после запятой. ПДО задаётся фазой недели или правилом возвращения.</p>
      </> : <><div className="fieldGrid">{numberField('План, минут', minutes, setMinutes, 1, 600)}</div><p className="fieldHelp">Цель по времени задаётся здесь. Автоматической прибавки минут нет.</p></>}
    </>}
    {saveError && <div><p className="fieldError" role="alert">{saveError}</p><p className="fieldHelp">Ввод сохранён. Если ответ потерялся, сначала обновите программу и проверьте, применена ли замена.</p>{conflict && <button type="button" className="textButton" disabled={busy} onClick={() => run(async () => {})}>Обновить программу</button>}</div>}
    <button className="primaryButton" type="submit" disabled={busy || !canSave}>{busy ? 'Сохраняем замену…' : 'Заменить упражнение'}</button>
    <button className="textButton" type="button" disabled={busy} onClick={onClose}>Отмена</button>
  </form>
}
