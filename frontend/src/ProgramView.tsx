import { Fragment, useEffect, useRef, useState } from 'react'
import type { FormEvent, PointerEvent as ReactPointerEvent } from 'react'
import { IconChevronDown, IconGripVertical, IconX } from '@tabler/icons-react'
import { api } from './api'
import { ChoiceDropdown } from './ChoiceDropdown'
import { muscleGroups as suggestedGroups, parseMuscleGroups } from './muscleGroups'
import { ExerciseReplacement } from './ExerciseReplacement'
import { MovementCatalog, movementKinds, timedOptions } from './MovementCatalog'
import { filterMovements, normalizeMovementSearch } from './movementSearch'
import { countWord } from './App'
import type { Exercise, ExerciseInput, Movement, Template } from './types'
import { useSubmission } from './useSubmission'

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
  const nextPosition = Math.max(-1, ...template.exercises.map(item => item.position)) + 1
  const [form, setForm] = useState<ExerciseInput>(exercise ? exerciseInput(exercise) : { ...emptyExercise, position: nextPosition })
  const [pickerOpen, setPickerOpen] = useState(false)
  const [muscleFilter, setMuscleFilter] = useState('all')
  const [search, setSearch] = useState('')
  useEffect(() => {
    setForm(exercise ? exerciseInput(exercise) : { ...emptyExercise, position: nextPosition })
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
      if (exercise) await api.updateExercise(exercise.id, { ...form, position: exercise.position })
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
    {selectedMovement?.kind === 'strength' && <div className="fieldGrid">{numberField('sets_count', 'Подходов по умолчанию')}</div>}
    <button className="primaryButton" type="submit" disabled={!form.movement_id}>{exercise ? 'Сохранить настройки' : 'Сохранить упражнение'}</button>
  </fieldset></form>
}

export function ProgramView({ templates, run, canEditCatalog, onTemplateDeleted, onTemplateReordered }: {
  templates: Template[];
  run: (action: () => Promise<unknown>) => Promise<void>; canEditCatalog: boolean;
  onTemplateDeleted?: (id: string) => void; onTemplateReordered?: (template: Template) => void
}) {
  const templateSubmission = useSubmission()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [creating, setCreating] = useState(templates.length === 0)
  const selected = templates.find(item => item.id === selectedId)
  const [name, setName] = useState('')
  const [selectedGroups, setSelectedGroups] = useState<string[]>([])
  const [groupError, setGroupError] = useState('')
  const [editingTemplate, setEditingTemplate] = useState(false)
  const [exerciseEditor, setExerciseEditor] = useState<string | 'new' | null>(null)
  const [replacementEditor, setReplacementEditor] = useState<string | null>(null)
  const [replacementNotice, setReplacementNotice] = useState('')
  const [movements, setMovements] = useState<Movement[]>([])
  const [detailGroups, setDetailGroups] = useState<Record<string, string[]>>({})
  const [catalogLoadedAt, setCatalogLoadedAt] = useState<string | null>(null)
  const [catalogError, setCatalogError] = useState('')
  const [catalogReload, setCatalogReload] = useState(0)
  const [orderOverride, setOrderOverride] = useState<{ templateId: string; ids: string[] } | null>(null)
  const [reorderBusy, setReorderBusy] = useState(false)
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const dragCleanup = useRef<(() => void) | null>(null)
  useEffect(() => () => dragCleanup.current?.(), [])
  useEffect(() => {
    if (!orderOverride) return
    const current = templates.find(item => item.id === orderOverride.templateId)?.exercises.map(item => item.id)
    if (current?.join('|') === orderOverride.ids.join('|')) setOrderOverride(null)
  }, [templates, orderOverride])
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
    }
  }, [selectedId, selected?.name, selected?.muscle_group])

  const saveTemplate = async (event: FormEvent) => {
    event.preventDefault()
    if (!selectedGroups.length) { setGroupError('Выберите хотя бы один раздел.'); return }
    await templateSubmission.submit(() => run(async () => {
      const data = { name, muscle_group: selectedGroups.join(', '), weekday: selected?.weekday ?? 0, send_time: selected?.send_time ?? '09:00' }
      if (selected && editingTemplate) await api.updateTemplate(selected.id, data)
      else await api.createTemplate(data)
      setSelectedId(null)
      setCreating(false)
      setEditingTemplate(false)
    }))
  }
  const deleteTemplate = async () => {
    if (!selected || !window.confirm(`Удалить тренировку «${selected.name}»? История сохранится.`)) return
    const id = selected.id
    await run(async () => { await api.deleteTemplate(id); setSelectedId(null); onTemplateDeleted?.(id) })
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

  const orderedExercises = selected ? (() => {
    if (orderOverride?.templateId !== selected.id) return selected.exercises
    const byId = new Map(selected.exercises.map(item => [item.id, item]))
    return orderOverride.ids.map(id => byId.get(id)).filter((item): item is Exercise => Boolean(item))
  })() : []
  const persistOrder = async (ids: string[]) => {
    if (!selected || reorderBusy) return
    const templateId = selected.id
    setOrderOverride({ templateId, ids })
    setReorderBusy(true)
    await run(async () => {
      try { onTemplateReordered?.(await api.reorderExercises(templateId, ids)) }
      catch (err) { setOrderOverride(null); throw err }
      finally { setReorderBusy(false) }
    })
  }
  const startDrag = (exerciseId: string, event: ReactPointerEvent<HTMLButtonElement>) => {
    if (!selected || reorderBusy || (event.pointerType === 'mouse' && event.button !== 0)) return
    event.preventDefault()
    dragCleanup.current?.()
    const templateId = selected.id
    const pointerId = event.pointerId
    const original = orderedExercises.map(item => item.id)
    let current = original
    setDraggingId(exerciseId)
    const onMove = (moveEvent: PointerEvent) => {
      if (moveEvent.pointerId !== pointerId) return
      moveEvent.preventDefault()
      if (moveEvent.clientY < 80) window.scrollBy(0, -12)
      else if (moveEvent.clientY > window.innerHeight - 90) window.scrollBy(0, 12)
      const otherRows = Array.from(document.querySelectorAll<HTMLElement>('[data-exercise-row]'))
        .filter(row => row.dataset.templateId === templateId && row.dataset.exerciseId !== exerciseId)
      let destination = otherRows.findIndex(row => {
        const rect = row.querySelector('.programExercise')?.getBoundingClientRect()
        return rect && moveEvent.clientY < rect.top + rect.height / 2
      })
      if (destination < 0) destination = otherRows.length
      const next = current.filter(id => id !== exerciseId)
      next.splice(destination, 0, exerciseId)
      if (next.join('|') !== current.join('|')) {
        current = next
        setOrderOverride({ templateId, ids: next })
      }
    }
    const cleanup = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onCancel)
      dragCleanup.current = null
      setDraggingId(null)
    }
    const onUp = (upEvent: PointerEvent) => {
      if (upEvent.pointerId !== pointerId) return
      cleanup()
      if (current.join('|') !== original.join('|')) void persistOrder(current)
      else setOrderOverride(null)
    }
    const onCancel = (cancelEvent: PointerEvent) => {
      if (cancelEvent.pointerId !== pointerId) return
      cleanup()
      setOrderOverride(null)
    }
    dragCleanup.current = cleanup
    window.addEventListener('pointermove', onMove, { passive: false })
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onCancel)
  }
  const keyboardMove = (exerciseId: string, direction: -1 | 1) => {
    const ids = orderedExercises.map(item => item.id)
    const index = ids.indexOf(exerciseId)
    const destination = index + direction
    if (reorderBusy || index < 0 || destination < 0 || destination >= ids.length) return
    ;[ids[index], ids[destination]] = [ids[destination], ids[index]]
    void persistOrder(ids)
  }

  const selectedPanel = selected && !editingTemplate && <section className="programSessionBlock" aria-label={`Настройка тренировки ${selected.name}`}>
      <div className="programCard"><h2>{selected.name}</h2><p>{selected.muscle_group} · {selected.exercises.length} {countWord(selected.exercises.length, 'упражнение', 'упражнения', 'упражнений')}</p><div className="programActions"><button onClick={() => setEditingTemplate(true)}>Изменить тренировку</button><button className="dangerText" onClick={deleteTemplate}>Удалить</button></div></div>
      <div className="sectionHead"><h2>Упражнения</h2><span>{selected.exercises.length}</span></div>
      {orderedExercises.map((exercise, index) => { const movement = movements.find(item => item.id === exercise.movement_id); const expanded = exerciseEditor === exercise.id; const replacing = replacementEditor === exercise.id; return <div className={`programExerciseItem ${draggingId === exercise.id ? 'isDragging' : ''}`} data-exercise-row data-template-id={selected.id} data-exercise-id={exercise.id} key={exercise.id}>
        <div className="programExercise"><button type="button" className="exerciseDragHandle" aria-label={`Переместить ${exercise.name}. Зажмите и перетащите; с клавиатуры используйте стрелки вверх и вниз`} title="Зажмите и перетащите" disabled={reorderBusy} onPointerDown={event => startDrag(exercise.id, event)} onKeyDown={event => { if (event.key === 'ArrowUp' || event.key === 'ArrowDown') { event.preventDefault(); keyboardMove(exercise.id, event.key === 'ArrowUp' ? -1 : 1) } }}><IconGripVertical size={20} stroke={1.8} aria-hidden="true" /></button><span className="programNumber">{index + 1}</span><div><strong>{movement?.name ?? exercise.name}</strong><small>{movement && movement.kind !== 'strength' ? `${movementKinds[movement.kind]}` : `${movement ? `${movement.primary_group}${movement.is_anchor ? ' · якорное' : ''}` : 'Укажите мышцу в справочнике'} · ${exercise.sets_count} подхода`}</small></div><button className="dangerText" onClick={() => deleteExercise(exercise)} aria-label={`Удалить ${exercise.name}`}>×</button></div>
        <div className="programActions"><button type="button" onClick={() => { setReplacementEditor(null); setExerciseEditor(expanded ? null : exercise.id) }} disabled={!catalogLoadedAt} aria-expanded={expanded} aria-controls={`exercise-editor-${exercise.id}`}>Изменить настройки</button><button type="button" onClick={() => { setExerciseEditor(null); setReplacementEditor(replacing ? null : exercise.id) }} disabled={!catalogLoadedAt} aria-expanded={replacing} aria-controls={`exercise-replacement-${exercise.id}`}>Заменить упражнение</button></div>
        {expanded && <div className="programInlineEditor" id={`exercise-editor-${exercise.id}`}><ExerciseEditor template={selected} movements={movements} detailGroups={detailGroups} exercise={exercise} onClose={() => setExerciseEditor(null)} run={runAndCollapse} /></div>}
        {replacing && <div className="programInlineEditor" id={`exercise-replacement-${exercise.id}`}><ExerciseReplacement exercise={exercise} movements={movements} detailGroups={detailGroups} onClose={() => setReplacementEditor(null)} onReplaced={result => setReplacementNotice(`В программе теперь «${result.exercise.name}». ${result.history_mode === 'resume' ? 'Прежняя база результатов продолжена.' : 'Начата новая база результатов.'} Замена действует со следующей новой тренировки. Уже созданные занятия сохранены (${result.preserved_sessions_count}).`)} run={runAndCollapse} /></div>}
      </div> })}
      {exerciseEditor === 'new' && <ExerciseEditor template={selected} movements={movements} detailGroups={detailGroups} onClose={() => setExerciseEditor(null)} run={runAndCollapse} />}
      {exerciseEditor !== 'new' && <button className="outlineButton" disabled={!catalogLoadedAt} onClick={() => { setReplacementEditor(null); setExerciseEditor('new') }}>+ Добавить упражнение</button>}
    </section>

  return <>
    <div className="eyebrow">Настройки тренировок</div><h1>Программа</h1>
    <p className="intro">Состав тренировок и порядок упражнений. Результаты записываются вручную.</p>
    {replacementNotice && <p className="hint" role="status">{replacementNotice}</p>}
    {catalogError && <div className="emptyCard" role="alert"><p>Не удалось загрузить справочник. {catalogError}</p>{catalogLoadedAt && <p>Показана версия от {new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'long' }).format(new Date(catalogLoadedAt))}.</p>}<button className="outlineButton" onClick={() => setCatalogReload(value => value + 1)}>Повторить загрузку справочника</button></div>}
    {!catalogLoadedAt && !catalogError && <p className="hint" role="status">Загружаем справочник упражнений…</p>}
    <div className="programPicker" aria-label="Тренировки программы">
      {templates.map(item => <Fragment key={item.id}>
        <button type="button" className={selectedId === item.id ? 'chosen' : ''} aria-expanded={selectedId === item.id} onClick={() => {
          setSelectedId(current => current === item.id ? null : item.id)
          setCreating(false)
          setEditingTemplate(false)
          setExerciseEditor(null)
          setReplacementEditor(null)
          setReplacementNotice('')
        }}><span className="programTileName">{item.name}</span><span className="programTileMeta">{item.exercises.length} упражнений</span></button>
        {selectedId === item.id && selectedPanel && <div className="programExpand" key={`details-${item.id}`}>{selectedPanel}</div>}
      </Fragment>)}
      <button type="button" className={creating ? 'chosen addProgram' : 'addProgram'} aria-label="Новая тренировка" aria-expanded={creating} onClick={() => {
        setCreating(current => !current)
        setSelectedId(null)
        setName('')
        setSelectedGroups([])
        setGroupError('')
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
      <button className="primaryButton" type="submit">Сохранить тренировку</button>
    </fieldset></form>}
    {catalogLoadedAt && <MovementCatalog movements={movements} detailGroups={detailGroups} refreshMovements={async () => setMovements(await api.movements())} run={run} canEdit={canEditCatalog} />}
  </>
}
