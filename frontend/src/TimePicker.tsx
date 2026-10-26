import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { IconChevronDown, IconClock } from '@tabler/icons-react'

const pad = (value: number) => String(value).padStart(2, '0')

export function TimePicker({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const [open, setOpen] = useState(false)
  const [above, setAbove] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const hours = useRef<HTMLDivElement>(null)
  const minutes = useRef<HTMLDivElement>(null)
  const [hour, minute] = value.split(':').map(Number)
  useLayoutEffect(() => {
    if (!open || !menu.current || !trigger.current) return
    const triggerRect = trigger.current.getBoundingClientRect()
    setAbove(triggerRect.bottom + menu.current.offsetHeight + 6 > window.innerHeight - 76 && triggerRect.top > menu.current.offsetHeight + 12)
  }, [open])
  useEffect(() => {
    if (!open) return
    const closeOutside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    const closeEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); trigger.current?.focus() } }
    document.addEventListener('pointerdown', closeOutside)
    document.addEventListener('keydown', closeEscape)
    requestAnimationFrame(() => {
      for (const list of [hours.current, minutes.current]) {
        const chosen = list?.querySelector<HTMLElement>('[aria-selected="true"]')
        if (list && chosen) list.scrollTop = chosen.offsetTop - list.offsetTop - list.clientHeight / 2 + chosen.clientHeight / 2
      }
    })
    return () => { document.removeEventListener('pointerdown', closeOutside); document.removeEventListener('keydown', closeEscape) }
  }, [open])
  return <div className="progressFilter timePicker" ref={root}>
    <span className="filterLabel">{label}</span>
    <button ref={trigger} type="button" className={`filterTrigger ${open ? 'open' : ''}`} aria-label={`${label}: ${value}`} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(!open)}><span className="timeTriggerText"><IconClock size={17} stroke={1.8} aria-hidden="true" />{value}</span><IconChevronDown size={17} stroke={1.8} aria-hidden="true" /></button>
    {open && <div ref={menu} className={`timeMenu ${above ? 'above' : ''}`} role="dialog" aria-label={label}>
      <div className="timeMenuColumns">
        <div className="timeColumn"><span>Часы</span><div className="timeChoices" ref={hours} role="listbox" aria-label="Часы">{Array.from({ length: 24 }, (_, item) => <button type="button" role="option" aria-selected={item === hour} key={item} onClick={() => onChange(`${pad(item)}:${pad(minute)}`)}>{pad(item)}</button>)}</div></div>
        <div className="timeColumn"><span>Минуты</span><div className="timeChoices" ref={minutes} role="listbox" aria-label="Минуты">{Array.from({ length: 60 }, (_, item) => <button type="button" role="option" aria-selected={item === minute} key={item} onClick={() => onChange(`${pad(hour)}:${pad(item)}`)}>{pad(item)}</button>)}</div></div>
      </div>
      <button type="button" className="timeDone" onClick={() => { setOpen(false); trigger.current?.focus() }}>Готово</button>
    </div>}
  </div>
}
