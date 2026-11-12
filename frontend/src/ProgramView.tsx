import { Fragment, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { IconChevronDown, IconX } from '@tabler/icons-react'
import { api } from './api'
import { ChoiceDropdown } from './ChoiceDropdown'
import { muscleGroups as suggestedGroups, parseMuscleGroups } from './muscleGroups'
import { TimePicker } from './TimePicker'
import { ExerciseReplacement } from './ExerciseReplacement'
import { MovementCatalog, movementKinds, timedOptions } from './MovementCatalog'
import { filterMovements, normalizeMovementSearch } from './movementSearch'
import { countWord, formatWeight } from './App'
import type { CycleConfig, Exercise, ExerciseInput, Movement, Template } from './types'
import { useSubmission } from './useSubmission'

const weekdays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
const emptyExercise: ExerciseInput = {
  name: '', position: 0, sets_count: 3, medium_weight: 0, weight_step: 2.5,
  light_factor: 0.9, heavy_factor: 1.05,
  light_min: 12, light_max: 15, medium_min: 8, medium_max: 12, heavy_min: 6, heavy_max: 8,
  movement_id: null, rep_min: 6, rep_max: 12, duration_minutes: null,
}

function exerciseInput(exercise: Exercise): ExerciseInput {
  const { id: _id, slot_id: _slot, history_id: _history, rir_target: _legacyRir, ...settings } = exercise
  return settings
}

function ExerciseEditor({ template, exercise, movements, detailGroups, onClose, run }: {
  template: Template; exercise?: Exercise; movements: Movement[]; detailGroups: Record<string, string[]>;
  onClose: () => void; run: (action: () => Promise<unknown>) => Promise<void>
}) {
  const { busy, submit } = useSubmission()
  const [form, setForm] = useState<ExerciseInput>(exercise ? exerciseInput(exercise) : { ...emptyExercise, position: template.exercises.length })
  const [pickerOpen, setPickerOpen] = useState(false)
  const [muscleFilter, setMuscleFilter] = useState('all')
  const [search, setSearch] = useState('')
  useEffect(() => {
    setForm(exercise ? exerciseInput(exercise) : { ...emptyExercise, position: template.exercises.length })
    setPickerOpen(false)
    setMuscleFilter('all'); setSearch('')
  }, [exercise?.id, template.id])
  const muscleOptions = Object.values(detailGroups).flat()
  const filteredMovements = filterMovements(movements, muscleFilter, search)
  const query = normalizeMovementSearch(search)
  const selectedMovement = movements.find(item => item.id === form.movement_id)
  const numberField = (key: keyof ExerciseInput, label: string, step = '1') =>
    <label className="field"><span>{label}</span><input type="number" step={step} value={form[key] ?? ''} onChange={event => setForm({ ...form, [key]: Number(event.target.value) })} /></label>
  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (!form.movement_id) return
    await submit(() => run(async () => {
      if (exercise) await api.updateExercise(exercise.id, form)
      else await api.createExercise(template.id, form)
      onClose()
    }))
  }
  return <form className="editorPanel" onSubmit={save} aria-busy={busy}><fieldset className="formFields" disabled={busy}>
    <div className="editorTitle"><h3>{exercise ? 'Изменить настройки' : 'Новое упражнение'}</h3><button type="button" onClick={onClose} aria-label="Отменить изменение настроек">×</button></div>
    {exercise ? <><div className="movementPickerTrigger"><span><strong>{selectedMovement?.name ?? exercise.name}</strong><small>{selectedMovement ? movementKinds[selectedMovement.kind] : 'Движение не связано со справочником'}</small></span></div><p className="fieldHelp">Настройки сохраняют прежнюю базу результатов. Для другого движения используйте «Заменить упражнение». Уже созданные занятия сохраняются.</p></> : <button type="button" className="movementPickerTrigger" aria-label={selectedMovement ? `Выбрать упражнение. Сейчас: ${selectedMovement.name}` : 'Выбрать упражнение'} aria-expanded={pickerOpen} aria-controls="movement-picker-new" onClick={() => setPickerOpen(!pickerOpen)}>
      <span><strong>{selectedMovement?.name ?? 'Выберите упражнение'}</strong>{selectedMovement && <small>{selectedMovement.kind === 'strength' ? selectedMovement.primary_group : movementKinds[selectedMovement.kind]}{selectedMovement.secondary_groups.length ? ` · дополнительно: ${selectedMovement.secondary_groups.join(', ')}` : ''}</small>}</span><IconChevronDown size={19} stroke={1.8} aria-hidden="true" />
    </button>}
    {!exercise && pickerOpen && <div className="movementPickerPanel" id="movement-picker-new">
      <div className="catalogFilters"><ChoiceDropdown label="Мышца или тип" value={muscleFilter} options={[{ value: 'all', label: 'Все упражнения' }, ...muscleOptions.map(group => ({ value: group, label: group })), ...timedOptions]} onChange={setMuscleFilter} /><label className="field"><span>Поиск по названию</span><input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Например, шта или мах" /></label></div>
      {query.length > 0 && query.length < 3 && <p className="fieldHelp">Введите не меньше трёх букв для поиска.</p>}
      <div className="movementChoiceList" role="listbox" aria-label="Выберите упражнение">{filteredMovements.length ? filteredMovements.map(item => <button type="button" role="option" key={item.id} className={form.movement_id === item.id ? 'selected' : ''} aria-selected={form.movement_id === item.id} onClick={() => { setForm({ ...form, movement_id: item.id, name: item.name, duration_minutes: item.kind === 'strength' ? null : form.duration_minutes ?? 20 }); setPickerOpen(false) }}><strong>{item.name}</strong><small>{item.kind === 'strength' ? item.primary_group : movementKinds[item.kind]}{item.secondary_groups.length ? ` · дополнительно: ${item.secondary_groups.join(', ')}` : ''}{item.is_anchor ? ' · якорное' : ''}</small></button>) : <p className="fieldHelp">Упражнения не найдены. Добавьте движение в «Списке упражнений».</p>}</div>
    </div>}
    {selectedMovement?.kind !== 'strength' && selectedMovement ? <div className="fieldGrid">{numberField('duration_minutes', 'План, минут')}{numberField('position', 'Порядок')}</div> : <><div className="fieldGrid">{numberField('medium_weight', 'Стартовый вес, кг', '0.5')}{numberField('weight_step', 'Шаг веса, кг', '0.5')}{numberField('sets_count', 'Базовых подходов')}{numberField('position', 'Порядок')}</div><div className="fieldGrid">{numberField('rep_min', 'Повторы от')}{numberField('rep_max', 'Повторы до')}</div><p className="fieldHelp">ПДО назначается фазой недели и правилом возвращения. Целевое значение показано в тренировке; фактический ПДО записывается после подхода.</p></>}
    <button className="primaryButton" type="submit" disabled={!form.movement_id}>{exercise ? 'Сохранить настройки' : 'Сохранить упражнение'}</button>
  </fieldset></form>
}

export function ProgramView({ templates, run }: {
  templates: Template[];
  run: (action: () => Promise<unknown>) => Promise<void>
}) {
  const templateSubmission = useSubmission()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [creating, setCreating] = useState(templates.length === 0)
  const selected = templates.find(item => item.id === selectedId)
  const [name, setName] = useState('')
  const [selectedGroups, setSelectedGroups] = useState<string[]>([])
  const [groupError, setGroupError] = useState('')
  const [weekday, setWeekday] = useState(0)
  const [sendTime, setSendTime] = useState('09:00')
  const [editingTemplate, setEditingTemplate] = useState(false)
  const [exerciseEditor, setExerciseEditor] = useState<string | 'new' | null>(null)
  const [replacementEditor, setReplacementEditor] = useState<string | null>(null)
  const [replacementNotice, setReplacementNotice] = useState('')
  const [movements, setMovements] = useState<Movement[]>([])
  const [detailGroups, setDetailGroups] = useState<Record<string, string[]>>({})
  const [catalogLoadedAt, setCatalogLoadedAt] = useState<string | null>(null)
  const [catalogError, setCatalogError] = useState('')
  const [catalogReload, setCatalogReload] = useState(0)
  const [cycleConfig, setCycleConfig] = useState<CycleConfig | null>(null)
  const [cycleDays, setCycleDays] = useState(7)
  const [cycleStart, setCycleStart] = useState('')
  const [cycleSlots, setCycleSlots] = useState<CycleConfig['slots']>([])
  const [cycleBusy, setCycleBusy] = useState(false)
  useEffect(() => {
    let active = true
    api.programCycle().then(config => {
      if (!active) return
      setCycleConfig(config)
      setCycleDays(config.length_days ?? 7)
      setCycleStart(config.start_date ?? new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Moscow' }).format(new Date()))
      setCycleSlots(config.length_days === null ? templates.map(template => ({ day: template.weekday + 1, template_id: template.id })) : config.slots)
    }).catch(() => { if (active) setCycleConfig(null) })
    return () => { active = false }
  }, [templates])
  useEffect(() => {
    let active = true
    Promise.all([api.movements(), api.muscleGroups()]).then(([items, groups]) => {
      if (!active) return
      setMovements(items); setDetailGroups(groups); setCatalogError('')
      setCatalogLoadedAt(new Date().toISOString())
    }).catch((err: Error) => { if (active) setCatalogError(err.message) })
    return () => { active = false }
  }, [templates, catalogReload])

  useEffect(() => {
    if (selected) {
      setName(selected.name); setSelectedGroups(parseMuscleGroups(selected.muscle_group)); setGroupError('')
      setWeekday(selected.weekday); setSendTime(selected.send_time)
    }
  }, [selectedId, selected?.name, selected?.muscle_group, selected?.weekday, selected?.send_time])

  const saveTemplate = async (event: FormEvent) => {
    event.preventDefault()
    if (!selectedGroups.length) { setGroupError('Выберите хотя бы один раздел.'); return }
    await templateSubmission.submit(() => run(async () => {
      const data = { name, muscle_group: selectedGroups.join(', '), weekday, send_time: sendTime }
      if (selected && editingTemplate) await api.updateTemplate(selected.id, data)
      else await api.createTemplate(data)
      setSelectedId(null)
      setCreating(false)
      setEditingTemplate(false)
    }))
  }
  const saveCycle = async (event: FormEvent) => {
    event.preventDefault()
    setCycleBusy(true)
    try {
      await run(async () => {
        const config = await api.updateProgramCycle({ length_days: cycleDays, start_date: cycleStart, slots: cycleSlots })
        setCycleConfig(config)
      })
    } finally { setCycleBusy(false) }
  }
  const deleteTemplate = async () => {
    if (!selected || !window.confirm(`Удалить тренировку «${selected.name}»? История сохранится.`)) return
    await run(async () => { await api.deleteTemplate(selected.id); setSelectedId(null) })
  }
  const deleteExercise = async (exercise: Exercise) => {
    if (!window.confirm(`Удалить «${exercise.name}» из программы? История сохранится.`)) return
    await run(() => api.deleteExercise(exercise.id))
  }
  const showForm = creating || editingTemplate
  const runAndCollapse = (action: () => Promise<unknown>) => run(async () => {
    await action()
    setSelectedId(null)
    setExerciseEditor(null)
    setReplacementEditor(null)
  })

  const selectedPanel = selected && !editingTemplate && <section className="programSessionBlock" aria-label={`Настройка тренировки ${selected.name}`}>
      <div className="programCard"><div className="programCardTop"><span>{cycleConfig?.length_days ? `Дни цикла: ${selected.cycle_days.join(', ') || 'не назначены'}` : weekdays[selected.weekday]} · {selected.send_time}</span><span className="phasePill phase-medium">План накопления</span></div><h2>{selected.name}</h2><p>{selected.muscle_group} · {selected.exercises.length} {countWord(selected.exercises.length, 'упражнение', 'упражнения', 'упражнений')}</p><div className="programActions"><button onClick={() => setEditingTemplate(true)}>Изменить расписание</button><button className="dangerText" onClick={deleteTemplate}>Удалить</button></div></div>
      <div className="sectionHead"><h2>Упражнения</h2><span>{selected.exercises.length}</span></div>
      {selected.exercises.map((exercise, index) => { const movement = movements.find(item => item.id === exercise.movement_id); const expanded = exerciseEditor === exercise.id; const replacing = replacementEditor === exercise.id; return <div className="programExerciseItem" key={exercise.id}>
        <div className="programExercise"><span className="programNumber">{index + 1}</span><div><strong>{movement?.name ?? exercise.name}</strong><small>{movement && movement.kind !== 'strength' ? `${movementKinds[movement.kind]} · ${exercise.duration_minutes ?? '—'} мин` : `${movement ? `${movement.primary_group}${movement.is_anchor ? ' · якорное' : ''}` : 'Укажите мышцу в справочнике'} · ${exercise.sets_count} подхода · ${exercise.rep_min}–${exercise.rep_max} · ${formatWeight(exercise.medium_weight)} кг`}</small></div><button className="dangerText" onClick={() => deleteExercise(exercise)} aria-label={`Удалить ${exercise.name}`}>×</button></div>
        <div className="programActions"><button type="button" onClick={() => { setReplacementEditor(null); setExerciseEditor(expanded ? null : exercise.id) }} disabled={!catalogLoadedAt} aria-expanded={expanded} aria-controls={`exercise-editor-${exercise.id}`}>Изменить настройки</button><button type="button" onClick={() => { setExerciseEditor(null); setReplacementEditor(replacing ? null : exercise.id) }} disabled={!catalogLoadedAt} aria-expanded={replacing} aria-controls={`exercise-replacement-${exercise.id}`}>Заменить упражнение</button></div>
        {expanded && <div className="programInlineEditor" id={`exercise-editor-${exercise.id}`}><ExerciseEditor template={selected} movements={movements} detailGroups={detailGroups} exercise={exercise} onClose={() => setExerciseEditor(null)} run={runAndCollapse} /></div>}
        {replacing && <div className="programInlineEditor" id={`exercise-replacement-${exercise.id}`}><ExerciseReplacement exercise={exercise} movements={movements} detailGroups={detailGroups} onClose={() => setReplacementEditor(null)} onReplaced={result => setReplacementNotice(`В программе теперь «${result.exercise.name}». ${result.history_mode === 'resume' ? 'Прежняя база результатов продолжена.' : 'Начата новая база результатов.'} Замена действует со следующей новой тренировки. Уже созданные занятия сохранены (${result.preserved_sessions_count}).`)} run={runAndCollapse} /></div>}
      </div> })}
      {exerciseEditor === 'new' && <ExerciseEditor template={selected} movements={movements} detailGroups={detailGroups} onClose={() => setExerciseEditor(null)} run={runAndCollapse} />}
      {exerciseEditor !== 'new' && <button className="outlineButton" disabled={!catalogLoadedAt} onClick={() => { setReplacementEditor(null); setExerciseEditor('new') }}>+ Добавить упражнение</button>}
    </section>

  return <>
    <div className="eyebrow">Настройки тренировок</div><h1>Программа</h1>
    <p className="intro">Упражнения, расписание и нагрузка.</p>
    {replacementNotice && <p className="hint" role="status">{replacementNotice}</p>}
    {catalogError && <div className="emptyCard" role="alert"><p>Не удалось загрузить справочник. {catalogError}</p>{catalogLoadedAt && <p>Показана версия от {new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'long' }).format(new Date(catalogLoadedAt))}.</p>}<button className="outlineButton" onClick={() => setCatalogReload(value => value + 1)}>Повторить загрузку справочника</button></div>}
    {!catalogLoadedAt && !catalogError && <p className="hint" role="status">Загружаем справочник упражнений…</p>}
    {templates.length > 0 && <form className="editorPanel cycleEditor" onSubmit={saveCycle}>
      <div className="editorTitle"><h2>Тренировочный цикл</h2></div>
      <p className="intro">Три полностью завершённых цикла накопления, затем один лёгкий цикл. Пропуск или перенос не переключает фазу.</p>
      <div className="fieldGrid"><label className="field"><span>Длина цикла, дней</span><input type="number" min={2} max={30} value={cycleDays} onChange={event => setCycleDays(Number(event.target.value))} required /></label><label className="field"><span>Начало первого или следующего цикла</span><input type="date" value={cycleStart} onChange={event => setCycleStart(event.target.value)} required /></label></div>
      <div className="cycleSlots">{cycleSlots.map((slot, index) => <div className="cycleSlot" key={index}><label className="field"><span>День</span><input type="number" min={1} max={cycleDays} value={slot.day} onChange={event => setCycleSlots(items => items.map((item, i) => i === index ? { ...item, day: Number(event.target.value) } : item))} /></label><ChoiceDropdown label="Тренировка" value={slot.template_id} options={templates.map(template => ({ value: template.id, label: template.name }))} onChange={value => setCycleSlots(items => items.map((item, i) => i === index ? { ...item, template_id: value } : item))} /><button type="button" className="textButton" onClick={() => setCycleSlots(items => items.filter((_, i) => i !== index))} aria-label={`Удалить занятие ${index + 1}`}>×</button></div>)}</div>
      <button type="button" className="outlineButton" disabled={cycleSlots.length >= 30} onClick={() => setCycleSlots(items => [...items, { day: Math.min(cycleDays, (items.at(-1)?.day ?? 0) + 1), template_id: templates[0].id }])}>+ Занятие в цикле</button>
      <button className="primaryButton" type="submit" disabled={cycleBusy || cycleSlots.length === 0}>{cycleBusy ? 'Сохраняем…' : 'Сохранить цикл'}</button>
    </form>}
    <div className="programPicker" aria-label="Тренировки программы">
      {templates.map(item => <Fragment key={item.id}>
        <button type="button" className={selectedId === item.id ? 'chosen' : ''} aria-expanded={selectedId === item.id} onClick={() => {
          setSelectedId(current => current === item.id ? null : item.id)
          setCreating(false)
          setEditingTemplate(false)
          setExerciseEditor(null)
          setReplacementEditor(null)
          setReplacementNotice('')
        }}><span className="programTileName">{item.name}</span><span className="programTileMeta">{cycleConfig?.length_days ? `Дни ${item.cycle_days.join(', ') || '—'}` : weekdays[item.weekday]} · {item.send_time}</span></button>
        {selectedId === item.id && selectedPanel && <div className="programExpand" key={`details-${item.id}`}>{selectedPanel}</div>}
      </Fragment>)}
      <button type="button" className={creating ? 'chosen addProgram' : 'addProgram'} aria-label="Новая тренировка" aria-expanded={creating} onClick={() => {
        setCreating(current => !current)
        setSelectedId(null)
        setName('')
        setSelectedGroups([])
        setGroupError('')
        setWeekday(0)
        setSendTime('09:00')
        setEditingTemplate(false)
        setExerciseEditor(null)
        setReplacementEditor(null)
        setReplacementNotice('')
      }}><span aria-hidden="true">+</span><span className="programTileMeta">Новая тренировка</span></button>
    </div>
    {showForm && <form className="editorPanel" onSubmit={saveTemplate} aria-busy={templateSubmission.busy}><fieldset className="formFields" disabled={templateSubmission.busy}>
      <div className="editorTitle"><h2>{editingTemplate ? 'Изменить тренировку' : 'Новая тренировка'}</h2>{editingTemplate && <button type="button" onClick={() => setEditingTemplate(false)}>×</button>}</div>
      <label className="field"><span>Название тренировки</span><input required maxLength={120} value={name} placeholder="Например, Грудь и трицепс" onChange={event => setName(event.target.value)} /></label>
      <div className="groupField"><span className="filterLabel">Разделы тренировки</span>{selectedGroups.length > 0 && <div className="groupChips">{selectedGroups.map(group => <button type="button" key={group} onClick={() => setSelectedGroups(selectedGroups.filter(item => item !== group))} aria-label={`Убрать раздел ${group}`}>{group}<IconX size={15} stroke={1.8} aria-hidden="true" /></button>)}</div>}{suggestedGroups.some(group => !selectedGroups.includes(group)) ? <ChoiceDropdown label="Разделы тренировки" hideLabel value="" options={suggestedGroups.filter(group => !selectedGroups.includes(group)).map(group => ({ value: group, label: group }))} placeholder="+ Добавить раздел" onChange={group => { setSelectedGroups([...selectedGroups, group]); setGroupError('') }} /> : <div className="allGroupsSelected">Все разделы выбраны</div>}{groupError && <small className="fieldError" role="alert">{groupError}</small>}</div>
      <div className="fieldGrid scheduleFields">{!cycleConfig?.length_days && <ChoiceDropdown label="День недели" value={String(weekday)} options={weekdays.map((day, index) => ({ value: String(index), label: day }))} onChange={value => setWeekday(Number(value))} />}<TimePicker label="Начало тренировки" value={sendTime} onChange={setSendTime} /></div>
      {cycleConfig?.length_days && <p className="intro">Дни этой тренировки назначаются в блоке «Тренировочный цикл».</p>}
      <button className="primaryButton" type="submit">Сохранить тренировку</button>
    </fieldset></form>}
    {catalogLoadedAt && <MovementCatalog movements={movements} detailGroups={detailGroups} refreshMovements={async () => setMovements(await api.movements())} run={run} />}
  </>
}
