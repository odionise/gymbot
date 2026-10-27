import { useState } from 'react'
import type { FormEvent } from 'react'
import { api } from './api'
import { ChoiceDropdown } from './ChoiceDropdown'
import { filterMovements, normalizeMovementSearch } from './movementSearch'
import type { Movement } from './types'

type MovementInput = Omit<Movement, 'id'>

function MovementForm({ movement, muscles, initialMuscle, onSave, onClose }: {
  movement?: Movement; muscles: string[]; initialMuscle: string;
  onSave: (data: MovementInput) => Promise<void>; onClose: () => void
}) {
  const [name, setName] = useState(movement?.name ?? '')
  const [primary, setPrimary] = useState(movement?.primary_group ?? initialMuscle)
  const [secondary, setSecondary] = useState(movement?.secondary_groups ?? [])
  const [anchor, setAnchor] = useState(movement?.is_anchor ?? false)
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!name.trim() || !primary) return
    await onSave({ name: name.trim(), primary_group: primary, secondary_groups: secondary, is_anchor: anchor })
  }
  return <form className="catalogEditor" onSubmit={submit}>
    <div className="editorTitle"><h3>{movement ? 'Изменить упражнение' : 'Новое упражнение'}</h3><button type="button" onClick={onClose} aria-label="Закрыть редактор">×</button></div>
    <label className="field"><span>Название</span><input required maxLength={120} value={name} onChange={event => setName(event.target.value)} /></label>
    <ChoiceDropdown label="Основная мышца" value={primary} options={muscles.map(group => ({ value: group, label: group }))} placeholder="Выберите мышцу" onChange={value => { setPrimary(value); setSecondary(secondary.filter(group => group !== value)) }} />
    <ChoiceDropdown label="Вторичные мышцы" value="" options={muscles.filter(group => group !== primary && !secondary.includes(group)).map(group => ({ value: group, label: group }))} placeholder="Добавить вторичную" onChange={value => setSecondary([...secondary, value])} />
    {secondary.length > 0 && <div className="groupChips">{secondary.map(group => <button type="button" key={group} onClick={() => setSecondary(secondary.filter(item => item !== group))}>{group} ×</button>)}</div>}
    <label className="checkboxField"><input type="checkbox" checked={anchor} onChange={event => setAnchor(event.target.checked)} /><span>Якорное упражнение</span></label>
    <button className="primaryButton" type="submit" disabled={!name.trim() || !primary}>Сохранить упражнение</button>
  </form>
}

export function MovementCatalog({ movements, detailGroups, refreshMovements, run }: {
  movements: Movement[]; detailGroups: Record<string, string[]>;
  refreshMovements: () => Promise<void>; run: (action: () => Promise<unknown>) => Promise<void>
}) {
  const [muscle, setMuscle] = useState('all')
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<string | 'new' | null>(null)
  const muscles = [...new Set(Object.values(detailGroups).flat())]
  const query = normalizeMovementSearch(search)
  const filtered = filterMovements(movements, muscle, search)
  const save = (movement: Movement | undefined, data: MovementInput) => run(async () => {
    if (movement) await api.updateMovement(movement.id, data)
    else await api.createMovement(data)
    await refreshMovements()
    setEditing(null)
  })

  return <section className="settingsBlock movementCatalog">
    <div className="sectionHead"><h2>Список упражнений</h2><span>{filtered.length}</span></div>
    <div className="catalogFilters">
      <ChoiceDropdown label="Основная мышца" value={muscle} options={[{ value: 'all', label: 'Все мышцы' }, ...muscles.map(group => ({ value: group, label: group }))]} onChange={setMuscle} />
      <label className="field"><span>Поиск по названию</span><input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Например, шта или мах" /></label>
    </div>
    {query.length > 0 && query.length < 3 && <p className="fieldHelp">Введите не меньше трёх букв для поиска.</p>}
    <div className="catalogList">{filtered.length ? filtered.map(item => <div className="catalogItem" key={item.id}>
      <div className="catalogItemRow"><div><strong>{item.name}</strong><small>{item.primary_group}{item.secondary_groups.length ? ` · дополнительно: ${item.secondary_groups.join(', ')}` : ''}{item.is_anchor ? ' · якорное' : ''}</small></div><button type="button" onClick={() => setEditing(editing === item.id ? null : item.id)} aria-label={`${editing === item.id ? 'Свернуть настройки' : 'Изменить'} ${item.name}`} aria-expanded={editing === item.id}>✎</button></div>
      {editing === item.id && <MovementForm key={item.id} movement={item} muscles={muscles} initialMuscle="" onSave={data => save(item, data)} onClose={() => setEditing(null)} />}
    </div>) : <p className="fieldHelp catalogEmpty">Упражнения не найдены.</p>}</div>
    {editing === 'new' ? <MovementForm key="new" muscles={muscles} initialMuscle={muscle === 'all' ? '' : muscle} onSave={data => save(undefined, data)} onClose={() => setEditing(null)} />
      : <button className="outlineButton" onClick={() => setEditing('new')}>+ Добавить упражнение</button>}
  </section>
}
