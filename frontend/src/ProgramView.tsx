import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { IconChevronDown, IconX } from '@tabler/icons-react'
import { api } from './api'
import { ChoiceDropdown } from './ChoiceDropdown'
import { muscleGroups as suggestedGroups, parseMuscleGroups } from './muscleGroups'
import { TimePicker } from './TimePicker'
import { MovementCatalog } from './MovementCatalog'
import { filterMovements, normalizeMovementSearch } from './movementSearch'
import { countWord, formatWeight } from './App'
import type { Exercise, ExerciseInput, Movement, Template } from './types'

const weekdays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
const emptyExercise: ExerciseInput = {
  name: '', position: 0, sets_count: 3, medium_weight: 0, weight_step: 2.5,
  light_factor: 0.9, heavy_factor: 1.05,
  light_min: 12, light_max: 15, medium_min: 8, medium_max: 12, heavy_min: 6, heavy_max: 8,
  movement_id: null, rep_min: 6, rep_max: 12, rir_target: 2,
}

function ExerciseEditor({ template, exercise, movements, detailGroups, onClose, run }: {
  template: Template; exercise?: Exercise; movements: Movement[]; detailGroups: Record<string, string[]>;
  onClose: () => void; run: (action: () => Promise<unknown>) => Promise<void>
}) {
  const [form, setForm] = useState<ExerciseInput>(exercise ? { ...exercise } : { ...emptyExercise, position: template.exercises.length })
  const [pickerOpen, setPickerOpen] = useState(false)
  const [muscleFilter, setMuscleFilter] = useState('all')
  const [search, setSearch] = useState('')
  useEffect(() => {
    setForm(exercise ? { ...exercise } : { ...emptyExercise, position: template.exercises.length })
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
    await run(async () => {
      if (exercise) await api.updateExercise(exercise.id, form)
      else await api.createExercise(template.id, form)
      onClose()
    })
  }
  return <form className="editorPanel" onSubmit={save}>
    <div className="editorTitle"><h3>{exercise ? 'Изменить упражнение' : 'Новое упражнение'}</h3><button type="button" onClick={onClose}>×</button></div>
    <button type="button" className="movementPickerTrigger" aria-label={selectedMovement ? `Выбрать упражнение. Сейчас: ${selectedMovement.name}` : 'Выбрать упражнение'} aria-expanded={pickerOpen} aria-controls={`movement-picker-${exercise?.id ?? 'new'}`} onClick={() => setPickerOpen(!pickerOpen)}>
      <span><strong>{selectedMovement?.name ?? 'Выберите упражнение'}</strong>{selectedMovement && <small>{selectedMovement.primary_group}{selectedMovement.secondary_groups.length ? ` · дополнительно: ${selectedMovement.secondary_groups.join(', ')}` : ''}</small>}</span><IconChevronDown size={19} stroke={1.8} aria-hidden="true" />
    </button>
    {pickerOpen && <div className="movementPickerPanel" id={`movement-picker-${exercise?.id ?? 'new'}`}>
      <div className="catalogFilters"><ChoiceDropdown label="Основная мышца" value={muscleFilter} options={[{ value: 'all', label: 'Все мышцы' }, ...muscleOptions.map(group => ({ value: group, label: group }))]} onChange={setMuscleFilter} /><label className="field"><span>Поиск по названию</span><input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Например, шта или мах" /></label></div>
      {query.length > 0 && query.length < 3 && <p className="fieldHelp">Введите не меньше трёх букв для поиска.</p>}
      <div className="movementChoiceList" role="listbox" aria-label="Выберите упражнение">{filteredMovements.length ? filteredMovements.map(item => <button type="button" role="option" key={item.id} className={form.movement_id === item.id ? 'selected' : ''} aria-selected={form.movement_id === item.id} onClick={() => { setForm({ ...form, movement_id: item.id, name: item.name }); setPickerOpen(false) }}><strong>{item.name}</strong><small>{item.primary_group}{item.secondary_groups.length ? ` · дополнительно: ${item.secondary_groups.join(', ')}` : ''}{item.is_anchor ? ' · якорное' : ''}</small></button>) : <p className="fieldHelp">Упражнения не найдены. Добавьте движение в «Списке упражнений».</p>}</div>
    </div>}
    <div className="fieldGrid">{numberField('medium_weight', 'Стартовый вес, кг', '0.5')}{numberField('weight_step', 'Шаг веса, кг', '0.5')}{numberField('sets_count', 'Базовых подходов')}{numberField('position', 'Порядок')}</div>
    <div className="fieldGrid">{numberField('rep_min', 'Повторы от')}{numberField('rep_max', 'Повторы до')}{numberField('rir_target', 'Целевой ПДО', '0.5')}</div>
    <button className="primaryButton" type="submit" disabled={!form.movement_id}>Сохранить упражнение</button>
  </form>
}

export function ProgramView({ templates, run }: {
  templates: Template[];
  run: (action: () => Promise<unknown>) => Promise<void>
}) {
  const [selectedId, setSelectedId] = useState<string | null>(templates[0]?.id ?? null)
  const selected = templates.find(item => item.id === selectedId)
  const [name, setName] = useState('')
  const [selectedGroups, setSelectedGroups] = useState<string[]>([])
  const [groupError, setGroupError] = useState('')
  const [weekday, setWeekday] = useState(0)
  const [sendTime, setSendTime] = useState('09:00')
  const [editingTemplate, setEditingTemplate] = useState(false)
  const [exerciseEditor, setExerciseEditor] = useState<string | 'new' | null>(null)
  const [movements, setMovements] = useState<Movement[]>([])
  const [detailGroups, setDetailGroups] = useState<Record<string, string[]>>({})
  useEffect(() => { Promise.all([api.movements(), api.muscleGroups()]).then(([items, groups]) => { setMovements(items); setDetailGroups(groups) }).catch(() => {}) }, [])

  useEffect(() => {
    if (selected) {
      setName(selected.name); setSelectedGroups(parseMuscleGroups(selected.muscle_group)); setGroupError('')
      setWeekday(selected.weekday); setSendTime(selected.send_time)
    }
  }, [selectedId, selected?.name, selected?.muscle_group, selected?.weekday, selected?.send_time])

  const saveTemplate = async (event: FormEvent) => {
    event.preventDefault()
    if (!selectedGroups.length) { setGroupError('Выберите хотя бы одну мышечную группу.'); return }
    await run(async () => {
      const data = { name, muscle_group: selectedGroups.join(', '), weekday, send_time: sendTime }
      if (selected && editingTemplate) await api.updateTemplate(selected.id, data)
      else { const created = await api.createTemplate(data); setSelectedId(created.id) }
      setEditingTemplate(false)
    })
  }
  const deleteTemplate = async () => {
    if (!selected || !window.confirm(`Удалить тренировку «${selected.name}»? История сохранится.`)) return
    await run(async () => { await api.deleteTemplate(selected.id); setSelectedId(null) })
  }
  const deleteExercise = async (exercise: Exercise) => {
    if (!window.confirm(`Удалить «${exercise.name}» из программы? История сохранится.`)) return
    await run(() => api.deleteExercise(exercise.id))
  }
  const showForm = !selected || editingTemplate

  return <>
    <div className="eyebrow">Настройки тренировок</div><h1>Программа</h1>
    <p className="intro">Упражнения, расписание и нагрузка.</p>
    <div className="programPicker">{templates.map(item => <button className={selectedId === item.id ? 'chosen' : ''} key={item.id} onClick={() => { setSelectedId(item.id); setEditingTemplate(false); setExerciseEditor(null) }}>{item.name}</button>)}<button className={!selected ? 'chosen addProgram' : 'addProgram'} onClick={() => { setSelectedId(null); setName(''); setSelectedGroups([]); setGroupError(''); setWeekday(0); setSendTime('09:00'); setEditingTemplate(false); setExerciseEditor(null) }}>+ Новая</button></div>
    {showForm ? <form className="editorPanel" onSubmit={saveTemplate}>
      <div className="editorTitle"><h2>{editingTemplate ? 'Изменить тренировку' : 'Новая тренировка'}</h2>{editingTemplate && <button type="button" onClick={() => setEditingTemplate(false)}>×</button>}</div>
      <label className="field"><span>Название тренировки</span><input required maxLength={120} value={name} placeholder="Например, Грудь и трицепс" onChange={event => setName(event.target.value)} /></label>
      <div className="groupField"><span className="filterLabel">Мышечные группы</span>{selectedGroups.length > 0 && <div className="groupChips">{selectedGroups.map(group => <button type="button" key={group} onClick={() => setSelectedGroups(selectedGroups.filter(item => item !== group))} aria-label={`Убрать группу ${group}`}>{group}<IconX size={15} stroke={1.8} aria-hidden="true" /></button>)}</div>}{suggestedGroups.some(group => !selectedGroups.includes(group)) ? <ChoiceDropdown label="Мышечные группы" hideLabel value="" options={suggestedGroups.filter(group => !selectedGroups.includes(group)).map(group => ({ value: group, label: group }))} placeholder="+ Добавить группу" onChange={group => { setSelectedGroups([...selectedGroups, group]); setGroupError('') }} /> : <div className="allGroupsSelected">Все группы выбраны</div>}{groupError && <small className="fieldError" role="alert">{groupError}</small>}</div>
      <div className="fieldGrid scheduleFields"><ChoiceDropdown label="День недели" value={String(weekday)} options={weekdays.map((day, index) => ({ value: String(index), label: day }))} onChange={value => setWeekday(Number(value))} /><TimePicker label="Начало тренировки" value={sendTime} onChange={setSendTime} /></div>
      <button className="primaryButton" type="submit">Сохранить тренировку</button>
    </form> : selected && <section className="programSessionBlock" aria-label={`Настройка тренировки ${selected.name}`}>
      <div className="programCard"><div className="programCardTop"><span>{weekdays[selected.weekday]} · {selected.send_time}</span><span className="phasePill phase-medium">План накопления</span></div><h2>{selected.name}</h2><p>{selected.muscle_group} · {selected.exercises.length} {countWord(selected.exercises.length, 'упражнение', 'упражнения', 'упражнений')}</p><div className="programActions"><button onClick={() => setEditingTemplate(true)}>Изменить расписание</button><button className="dangerText" onClick={deleteTemplate}>Удалить</button></div></div>
      <div className="sectionHead"><h2>Упражнения</h2><span>{selected.exercises.length}</span></div>
      {selected.exercises.map((exercise, index) => { const movement = movements.find(item => item.id === exercise.movement_id); const expanded = exerciseEditor === exercise.id; return <div className="programExerciseItem" key={exercise.id}>
        <div className="programExercise"><span className="programNumber">{index + 1}</span><div><strong>{movement?.name ?? exercise.name}</strong><small>{movement ? `${movement.primary_group}${movement.is_anchor ? ' · якорное' : ''}` : 'Укажите мышцу в справочнике'} · {exercise.sets_count} подхода · {exercise.rep_min}–{exercise.rep_max} · {formatWeight(exercise.medium_weight)} кг</small></div><button onClick={() => setExerciseEditor(expanded ? null : exercise.id)} aria-label={`${expanded ? 'Свернуть настройки' : 'Изменить'} ${exercise.name}`} aria-expanded={expanded} aria-controls={`exercise-editor-${exercise.id}`}>✎</button><button className="dangerText" onClick={() => deleteExercise(exercise)} aria-label={`Удалить ${exercise.name}`}>×</button></div>
        {expanded && <div className="programInlineEditor" id={`exercise-editor-${exercise.id}`}><ExerciseEditor template={selected} movements={movements} detailGroups={detailGroups} exercise={exercise} onClose={() => setExerciseEditor(null)} run={run} /></div>}
      </div> })}
      {exerciseEditor === 'new' && <ExerciseEditor template={selected} movements={movements} detailGroups={detailGroups} onClose={() => setExerciseEditor(null)} run={run} />}
      {exerciseEditor !== 'new' && <button className="outlineButton" onClick={() => setExerciseEditor('new')}>+ Добавить упражнение</button>}
    </section>}
    <MovementCatalog movements={movements} detailGroups={detailGroups} refreshMovements={async () => setMovements(await api.movements())} run={run} />
  </>
}
