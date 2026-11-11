import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import type { SessionExercise } from './types'
import { anatomyPaths } from './anatomyPaths'

type Zone = 'chest' | 'upperChest' | 'traps' | 'lats' | 'teresMajor' | 'teresMinor' |
  'rhomboids' | 'erectors' | 'frontDelts' | 'sideDelts' | 'rearDelts' | 'abs' | 'obliques' |
  'biceps' | 'triceps' | 'forearms' | 'quads' | 'hamstrings' | 'glutes' | 'gastro' | 'soleus'

const regions: Record<string, Zone[]> = {
  'Грудь': ['chest', 'upperChest'], 'Верх груди': ['upperChest'],
  'Спина': ['traps', 'lats', 'teresMajor', 'teresMinor', 'rhomboids', 'erectors'],
  'Широчайшие': ['lats'], 'Верх спины': ['traps', 'teresMajor', 'teresMinor', 'rhomboids'],
  'Трапеция': ['traps'], 'Большие круглые': ['teresMajor'], 'Малые круглые': ['teresMinor'],
  'Ромбовидные': ['rhomboids'], 'Разгибатели спины': ['erectors'],
  'Передние дельты': ['frontDelts'], 'Средние дельты': ['sideDelts'], 'Задние дельты': ['rearDelts'],
  'Пресс': ['abs'], 'Косые мышцы живота': ['obliques'],
  'Бицепс': ['biceps'], 'Трицепс': ['triceps'], 'Предплечья': ['forearms'],
  'Квадрицепс': ['quads'], 'Бицепс бедра': ['hamstrings'], 'Задняя поверхность бедра': ['hamstrings'],
  'Ягодичные': ['glutes'], 'Икры': ['gastro', 'soleus'], 'Икроножные': ['gastro'],
  'Камбаловидные': ['soleus'],
}

export type ZoneLoad = Partial<Record<Zone, { direct: number; indirect: number }>>

export function muscleLoads(exercises: SessionExercise[]): ZoneLoad {
  const result: ZoneLoad = {}
  for (const exercise of exercises) {
    if (exercise.kind !== 'strength' || exercise.skipped) continue
    const direct = new Set(regions[exercise.primary_group ?? ''] ?? [])
    const indirect = new Set((exercise.secondary_groups ?? []).flatMap(group => regions[group] ?? []))
    for (const zone of direct) {
      const load = result[zone] ?? { direct: 0, indirect: 0 }
      load.direct += exercise.sets_count
      result[zone] = load
    }
    for (const zone of indirect) {
      if (direct.has(zone)) continue
      const load = result[zone] ?? { direct: 0, indirect: 0 }
      load.indirect += exercise.sets_count * 0.5
      result[zone] = load
    }
  }
  return result
}

export function zoneTone(load: { direct: number; indirect: number } | undefined): string {
  if (!load) return 'transparent'
  if (load.direct > 0) return '#ee594b'
  if (load.indirect > 3) return '#3689dc'
  if (load.indirect >= 2) return '#65acf0'
  return '#a2cefa'
}

function Figure({ view, sex, loads }: { view: 'front' | 'back'; sex: 'male' | 'female'; loads: ZoneLoad }) {
  const atlas = sex === 'male' ? '/anatomy/male-front-back.png' : '/anatomy/female-front-back.png'
  const imageWidth = sex === 'male' ? 1199 : 1536
  const imageHeight = sex === 'male' ? 1312 : 1024
  const crop = sex === 'male' ? (view === 'front' ? '0 0 600 1312' : '600 0 599 1312')
    : (view === 'front' ? '270 0 490 1024' : '780 0 510 1024')
  const anatomy = anatomyPaths[sex][view]
  return <svg viewBox="0 0 120 236" aria-hidden="true" focusable="false">
    <svg x="0" y="0" width="120" height="236" viewBox={crop} preserveAspectRatio="none">
      <image href={atlas} width={imageWidth} height={imageHeight} />
      <g className="anatomyMuscles">
        {Object.entries(anatomy.zones).map(([zone, path]) => path && zoneTone(loads[zone as Zone]) !== 'transparent' &&
          <g key={zone} fill={zoneTone(loads[zone as Zone])}>
            <path d={path} />
            <path d={path} transform={`translate(${anatomy.center * 2} 0) scale(-1 1)`} />
          </g>)}
      </g>
    </svg>
  </svg>
}

export function MuscleDiagram({ exercises, sex }: { exercises: SessionExercise[]; sex: 'male' | 'female' }) {
  const [expanded, setExpanded] = useState(false)
  useEffect(() => {
    if (!expanded) return
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setExpanded(false) }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [expanded])
  const loads = muscleLoads(exercises)
  const primary = [...new Set(exercises.filter(item => item.kind === 'strength' && !item.skipped && item.primary_group).map(item => item.primary_group!))]
  const secondary = [...new Set(exercises.filter(item => item.kind === 'strength' && !item.skipped).flatMap(item => item.secondary_groups ?? []))].filter(group => !primary.includes(group))
  const description = `Основные мышцы: ${primary.join(', ') || 'нет'}. Дополнительные: ${secondary.join(', ') || 'нет'}.`
  return <div className="muscleDiagram">
    <button className="muscleOpen" type="button" onClick={() => setExpanded(true)} aria-label={`Увеличить схему мышц. ${description}`}>
      <div className="muscleFigures"><Figure view="front" sex={sex} loads={loads} /><Figure view="back" sex={sex} loads={loads} /></div>
    </button>
    <span className="muscleDiagramLegend"><i className="muscleMainSwatch" />Основные <i className="muscleExtraSwatch" />Дополнительные</span>
    {expanded && createPortal(<div className="muscleDialogBackdrop" onClick={() => setExpanded(false)}>
      <div className="muscleDialog" role="dialog" aria-modal="true" aria-label="Схема мышц тренировки" onClick={event => event.stopPropagation()}>
        <div className="muscleDialogHead"><h3>Мышцы тренировки</h3><button type="button" onClick={() => setExpanded(false)} aria-label="Закрыть схему">×</button></div>
        <div className="muscleDetailFigures"><Figure view="front" sex={sex} loads={loads} /><Figure view="back" sex={sex} loads={loads} /></div>
        <p><strong>Основные:</strong> {primary.join(', ') || 'нет'}</p><p><strong>Дополнительные:</strong> {secondary.join(', ') || 'нет'}</p>
        <p className="muscleDialogHelp">Красный – основные мышцы, синий - дополнительная (побочная) работа</p>
      </div>
    </div>, document.body)}
  </div>
}
