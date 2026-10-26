import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { IconX } from '@tabler/icons-react'
import { api } from './api'
import { ChoiceDropdown } from './ChoiceDropdown'
import { muscleGroups as suggestedGroups, parseMuscleGroups } from './muscleGroups'
import { TimePicker } from './TimePicker'
import { countWord, formatWeight, phaseText } from './App'
import type { Exercise, ExerciseInput, Me, Template } from './types'

const weekdays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
const emptyExercise: ExerciseInput = {
  name: '', position: 0, sets_count: 3, medium_weight: 0, weight_step: 2.5,
  light_factor: 0.9, heavy_factor: 1.05,
  light_min: 12, light_max: 15, medium_min: 8, medium_max: 12, heavy_min: 6, heavy_max: 8,
}

function ExerciseEditor({ template, exercise, onClose, run }: {
  template: Template; exercise?: Exercise; onClose: () => void; run: (action: () => Promise<unknown>) => Promise<void>
}) {
  const [form, setForm] = useState<ExerciseInput>(exercise ? { ...exercise } : { ...emptyExercise, position: template.exercises.length })
  useEffect(() => setForm(exercise ? { ...exercise } : { ...emptyExercise, position: template.exercises.length }), [exercise?.id, template.id])
  const numberField = (key: keyof ExerciseInput, label: string, step = '1') =>
    <label className="field"><span>{label}</span><input type="number" step={step} value={form[key]} onChange={event => setForm({ ...form, [key]: Number(event.target.value) })} /></label>
  const save = async (event: FormEvent) => {
    event.preventDefault()
    await run(async () => {
      if (exercise) await api.updateExercise(exercise.id, form)
      else await api.createExercise(template.id, form)
      onClose()
    })
  }
  return <form className="editorPanel" onSubmit={save}>
    <div className="editorTitle"><h3>{exercise ? 'Изменить упражнение' : 'Новое упражнение'}</h3><button type="button" onClick={onClose}>×</button></div>
    <label className="field"><span>Название</span><input required maxLength={120} value={form.name} placeholder="Например, жим лёжа" onChange={event => setForm({ ...form, name: event.target.value })} /></label>
    <div className="fieldGrid">{numberField('medium_weight', 'Вес среднего дня, кг', '0.5')}{numberField('weight_step', 'Шаг веса, кг', '0.5')}{numberField('sets_count', 'Подходов')}{numberField('position', 'Порядок')}</div>
    <div className="editorDivider">ДИАПАЗОНЫ ПОВТОРОВ</div>
    <div className="fieldGrid">{numberField('light_min', 'Лёгкая: от')}{numberField('light_max', 'Лёгкая: до')}{numberField('medium_min', 'Средняя: от')}{numberField('medium_max', 'Средняя: до')}{numberField('heavy_min', 'Тяжёлая: от')}{numberField('heavy_max', 'Тяжёлая: до')}</div>
    <div className="editorDivider">НАЧАЛЬНЫЙ ВЕС</div>
    <p className="fieldHelp">Множитель от веса среднего дня. 0,9 = 90%, 1,05 = 105%.</p>
    <div className="fieldGrid">{numberField('light_factor', 'Лёгкая', '0.01')}{numberField('heavy_factor', 'Тяжёлая', '0.01')}</div>
    <button className="primaryButton" type="submit">Сохранить упражнение <span>↗</span></button>
  </form>
}

export function ProgramView({ templates, me, refresh, run }: {
  templates: Template[]; me: Me | null; refresh: () => Promise<void>;
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
  const [timezone, setTimezone] = useState(me?.timezone ?? 'Europe/Moscow')

  useEffect(() => {
    if (selected) {
      setName(selected.name); setSelectedGroups(parseMuscleGroups(selected.muscle_group)); setGroupError('')
      setWeekday(selected.weekday); setSendTime(selected.send_time)
    }
  }, [selectedId, selected?.name, selected?.muscle_group, selected?.weekday, selected?.send_time])
  useEffect(() => setTimezone(me?.timezone ?? 'Europe/Moscow'), [me?.timezone])

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
      <button className="primaryButton" type="submit">Сохранить тренировку <span>↗</span></button>
    </form> : selected && <>
      <div className="programCard"><div className="programCardTop"><span>{weekdays[selected.weekday]} · {selected.send_time}</span><span className={`phasePill phase-${selected.next_phase}`}>Далее: {phaseText[selected.next_phase]}</span></div><h2>{selected.name}</h2><p>{selected.muscle_group} · {selected.exercises.length} {countWord(selected.exercises.length, 'упражнение', 'упражнения', 'упражнений')}</p><div className="programActions"><button onClick={() => setEditingTemplate(true)}>Изменить расписание</button><button className="dangerText" onClick={deleteTemplate}>Удалить</button></div></div>
      <div className="sectionHead"><h2>Упражнения</h2><span>{selected.exercises.length}</span></div>
      {selected.exercises.map((exercise, index) => <div className="programExercise" key={exercise.id}><span className="programNumber">{index + 1}</span><div><strong>{exercise.name}</strong><small>{exercise.sets_count} {countWord(exercise.sets_count, 'подход', 'подхода', 'подходов')} · {formatWeight(exercise.medium_weight)} кг средний день · шаг {formatWeight(exercise.weight_step)} кг</small></div><button onClick={() => setExerciseEditor(exercise.id)} aria-label={`Изменить ${exercise.name}`}>✎</button><button className="dangerText" onClick={() => deleteExercise(exercise)} aria-label={`Удалить ${exercise.name}`}>×</button></div>)}
      {exerciseEditor && <ExerciseEditor template={selected} exercise={selected.exercises.find(item => item.id === exerciseEditor)} onClose={() => setExerciseEditor(null)} run={run} />}
      {!exerciseEditor && <button className="outlineButton" onClick={() => setExerciseEditor('new')}>+ Добавить упражнение</button>}
    </>}
    <div className="settingsBlock"><div className="sectionHead"><h2>Уведомления</h2></div><label className="field"><span>Часовой пояс (IANA)</span><input value={timezone} onChange={event => setTimezone(event.target.value)} placeholder="Europe/Moscow" /></label><button className="outlineButton" onClick={() => run(async () => { await api.updateMe(timezone); await refresh() })}>Сохранить часовой пояс</button></div>
  </>
}
