import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { IconCheck, IconChevronDown } from '@tabler/icons-react'

export type Choice = { value: string; label: string }

export function ChoiceDropdown({ label, value, options, onChange, placeholder, hideLabel = false }: {
  label: string
  value: string
  options: Choice[]
  onChange: (value: string) => void
  placeholder?: string
  hideLabel?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [above, setAbove] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    if (!open || !menu.current || !trigger.current) return
    const bottom = trigger.current.getBoundingClientRect().bottom
    setAbove(bottom + menu.current.offsetHeight + 6 > window.innerHeight - 76 && trigger.current.getBoundingClientRect().top > menu.current.offsetHeight + 12)
  }, [open, options.length])
  useEffect(() => {
    if (!open) return
    const closeOutside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    const closeEscape = (event: globalThis.KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); trigger.current?.focus() } }
    document.addEventListener('pointerdown', closeOutside)
    document.addEventListener('keydown', closeEscape)
    return () => { document.removeEventListener('pointerdown', closeOutside); document.removeEventListener('keydown', closeEscape) }
  }, [open])
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!open && event.key === 'ArrowDown') { event.preventDefault(); setOpen(true); return }
    if (!open || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const items = Array.from(root.current?.querySelectorAll<HTMLButtonElement>('[role="option"]') ?? [])
    const current = items.indexOf(document.activeElement as HTMLButtonElement)
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : event.key === 'ArrowDown' ? (current + 1) % items.length : (current - 1 + items.length) % items.length
    items[next]?.focus()
  }
  const selected = options.find(item => item.value === value)?.label
  return <div className="progressFilter" ref={root} onKeyDown={onKeyDown}>
    {!hideLabel && <span className="filterLabel">{label}</span>}
    <button ref={trigger} type="button" className={`filterTrigger ${open ? 'open' : ''}`} aria-label={`${label}: ${selected ?? placeholder ?? 'Выберите'}`} aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen(!open)}><span>{selected ?? placeholder ?? 'Выберите'}</span><IconChevronDown size={17} stroke={1.8} aria-hidden="true" /></button>
    {open && <div ref={menu} className={`filterMenu ${above ? 'above' : ''}`} role="listbox" aria-label={label}>{options.map(item => <button type="button" role="option" aria-selected={item.value === value} key={item.value} onClick={() => { onChange(item.value); setOpen(false); trigger.current?.focus() }}><span>{item.label}</span>{item.value === value && <IconCheck size={16} stroke={2.2} aria-hidden="true" />}</button>)}</div>}
  </div>
}
