import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, Search } from 'lucide-react'

export interface SelectOption<T extends string = string> {
  value: T
  label: ReactNode
  /** plain text used for type-ahead and filtering (defaults to label when it is a string) */
  text?: string
  hint?: ReactNode   // second line, muted
  meta?: ReactNode   // right-aligned, mono
  disabled?: boolean
}

interface Props<T extends string> {
  value: T | ''
  onChange: (value: T) => void
  options: SelectOption<T>[]
  id?: string
  placeholder?: string
  disabled?: boolean
  /** show a filter box; defaults to on for long lists */
  searchable?: boolean
  /** compact trigger for page-head toolbars */
  inline?: boolean
  empty?: string
}

const textOf = (o: SelectOption) => (o.text ?? (typeof o.label === 'string' ? o.label : String(o.value))).toLowerCase()

/** Themed replacement for <select>: a button that opens a listbox (WAI-ARIA select-only combobox pattern). */
export function Select<T extends string>({ value, onChange, options, id, placeholder = 'Select…', disabled, searchable,
  inline, empty = 'No matches' }: Props<T>) {
  const autoId = useId()
  const triggerId = id ?? `sel-${autoId}`
  const listId = `${triggerId}-list`
  const [menuOpen, setOpen] = useState(false)
  const open = menuOpen && !disabled
  const [active, setActive] = useState(-1)
  const [query, setQuery] = useState('')
  const [pos, setPos] = useState<{ left: number; width: number; top?: number; bottom?: number; maxHeight: number } | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const typed = useRef({ text: '', at: 0 })

  const withSearch = searchable ?? options.length > 7
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return q ? options.filter((o) => textOf(o).includes(q)) : options
  }, [options, query])
  const selected = options.find((o) => o.value === value)

  const enabledFrom = (start: number, step: 1 | -1) => {
    for (let i = start; i >= 0 && i < shown.length; i += step) if (!shown[i].disabled) return i
    return -1
  }

  const place = () => {
    const r = triggerRef.current?.getBoundingClientRect()
    if (!r) return
    const gap = 6, margin = 12
    const below = window.innerHeight - r.bottom - margin, above = r.top - margin
    const up = below < 220 && above > below
    const width = Math.max(r.width, inline ? 220 : 0)
    const left = Math.min(r.left, window.innerWidth - width - margin)
    setPos(up
      ? { left, width, bottom: window.innerHeight - r.top + gap, maxHeight: Math.min(340, above - gap) }
      : { left, width, top: r.bottom + gap, maxHeight: Math.min(340, below - gap) })
  }

  const openMenu = (at?: 'first' | 'last') => {
    if (disabled) return
    const cur = options.findIndex((o) => o.value === value)
    setActive(at === 'last' ? enabledFrom(options.length - 1, -1) : cur >= 0 && !at ? cur : enabledFrom(0, 1))
    place()
    setOpen(true)
  }
  const close = (refocus = true) => {
    setOpen(false)
    setQuery('')
    if (refocus) triggerRef.current?.focus()
  }
  const choose = (o: SelectOption<T> | undefined) => {
    if (!o || o.disabled) return
    if (o.value !== value) onChange(o.value)
    close()
  }

  // follow the trigger while scrolling/resizing; close on clicks outside
  useLayoutEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (!menuRef.current?.contains(t) && !triggerRef.current?.contains(t)) close(false)
    }
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    document.addEventListener('mousedown', onDown)
    return () => {
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { if (open && withSearch) searchRef.current?.focus() }, [open, withSearch])
  useEffect(() => {
    if (open && active >= 0) menuRef.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [open, active])

  const filter = (q: string) => {
    setQuery(q)
    const next = q.trim().toLowerCase()
    // index into the filtered list, matching `shown` on the next render
    setActive(options.filter((o) => !next || textOf(o).includes(next)).findIndex((o) => !o.disabled))
  }

  const typeAhead = (key: string) => {
    const now = Date.now()
    typed.current = { text: (now - typed.current.at > 600 ? '' : typed.current.text) + key.toLowerCase(), at: now }
    const i = shown.findIndex((o) => !o.disabled && textOf(o).startsWith(typed.current.text))
    if (i >= 0) { if (open) setActive(i); else choose(shown[i]) }
  }

  const onKey = (e: KeyboardEvent) => {
    const fromSearch = e.target === searchRef.current
    if (!open) {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) { e.preventDefault(); openMenu(e.key === 'ArrowUp' ? 'last' : undefined) }
      else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) typeAhead(e.key)
      return
    }
    switch (e.key) {
      case 'ArrowDown': e.preventDefault(); setActive((i) => { const n = enabledFrom(i + 1, 1); return n < 0 ? i : n }); break
      case 'ArrowUp': e.preventDefault(); setActive((i) => { const n = enabledFrom(i - 1, -1); return n < 0 ? i : n }); break
      case 'Home': if (!fromSearch) { e.preventDefault(); setActive(enabledFrom(0, 1)) } break
      case 'End': if (!fromSearch) { e.preventDefault(); setActive(enabledFrom(shown.length - 1, -1)) } break
      case 'Enter': e.preventDefault(); choose(shown[active]); break
      case ' ': if (!fromSearch) { e.preventDefault(); choose(shown[active]) } break
      case 'Escape': e.preventDefault(); e.stopPropagation(); close(); break
      case 'Tab': close(false); break
      default: if (!fromSearch && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) typeAhead(e.key)
    }
  }

  const activeId = open && active >= 0 ? `${listId}-${active}` : undefined

  return (
    <>
      <button type="button" ref={triggerRef} id={triggerId} className={`select-trigger${inline ? ' inline' : ''}${open ? ' open' : ''}`}
        role="combobox" aria-haspopup="listbox" aria-expanded={open} aria-controls={listId}
        aria-activedescendant={withSearch ? undefined : activeId} disabled={disabled}
        onClick={() => (open ? close() : openMenu())} onKeyDown={onKey}>
        <span className={`select-value${selected ? '' : ' placeholder'}`}>
          {selected ? <>{selected.label}{selected.hint && !inline && <small>{selected.hint}</small>}</> : placeholder}
        </span>
        <ChevronDown size={15} className="select-chevron" aria-hidden="true" />
      </button>
      {open && pos && createPortal(
        <div ref={menuRef} className={`select-menu${pos.bottom != null ? ' up' : ''}`}
          style={{ left: pos.left, width: pos.width, top: pos.top, bottom: pos.bottom, maxHeight: pos.maxHeight }}>
          {withSearch && (
            <div className="select-search">
              <Search size={14} aria-hidden="true" />
              <input ref={searchRef} value={query} onChange={(e) => filter(e.target.value)} onKeyDown={onKey}
                placeholder="Type to filter…" aria-label="Filter options" aria-controls={listId} aria-activedescendant={activeId} />
            </div>
          )}
          <ul id={listId} role="listbox" aria-labelledby={triggerId} tabIndex={-1}>
            {shown.map((o, i) => (
              <li key={o.value} id={`${listId}-${i}`} data-i={i} role="option" aria-selected={o.value === value} aria-disabled={o.disabled || undefined}
                className={`select-option${i === active ? ' active' : ''}${o.value === value ? ' selected' : ''}`}
                onMouseMove={() => !o.disabled && active !== i && setActive(i)}
                onMouseDown={(e) => e.preventDefault()} onClick={() => choose(o)}>
                <span className="select-check" aria-hidden="true">{o.value === value && <Check size={14} />}</span>
                <span className="select-text">{o.label}{o.hint && <small>{o.hint}</small>}</span>
                {o.meta != null && <span className="select-meta">{o.meta}</span>}
              </li>
            ))}
            {!shown.length && <li className="select-empty">{empty}</li>}
          </ul>
        </div>,
        document.body,
      )}
    </>
  )
}
