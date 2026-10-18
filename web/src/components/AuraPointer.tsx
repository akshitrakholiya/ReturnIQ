import { useEffect, useRef } from 'react'

const INTERACTIVE = 'button, a, input, select, textarea, summary, label, [role="button"], [role="option"], .clickable-item, table.clickable tbody tr'
const LERP = 0.16

/**
 * Custom cursor (SCOUT_SPEC §3): a zero-lag gold core, a trailing aura and a click ripple.
 * Only mounts on fine pointers; touch devices and reduced-motion users keep the native cursor behaviour
 * (reduced-motion users get the core only, with no trailing or ripple).
 */
export function AuraPointer() {
  const core = useRef<HTMLDivElement>(null)
  const aura = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!window.matchMedia('(pointer: fine)').matches) return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const c = core.current!, a = aura.current!
    document.documentElement.classList.add('has-aura')

    let tx = -100, ty = -100, ax = -100, ay = -100, raf = 0
    const loop = () => {
      ax += (tx - ax) * LERP; ay += (ty - ay) * LERP
      a.style.transform = `translate3d(${ax}px, ${ay}px, 0) translate(-50%, -50%)`
      raf = requestAnimationFrame(loop)
    }
    const move = (e: MouseEvent) => {
      tx = e.clientX; ty = e.clientY
      c.style.transform = `translate3d(${tx}px, ${ty}px, 0) translate(-50%, -50%)`
      c.style.opacity = a.style.opacity = '1'
      if (reduced) { ax = tx; ay = ty; a.style.transform = c.style.transform }
    }
    const over = (e: MouseEvent) => {
      const hot = (e.target as Element | null)?.closest?.(INTERACTIVE) != null
      c.classList.toggle('is-hovering', hot); a.classList.toggle('is-hovering', hot)
    }
    const down = (e: MouseEvent) => {
      if (reduced) return
      const w = document.createElement('div')
      w.className = 'pointer-wave'
      w.style.left = `${e.clientX}px`; w.style.top = `${e.clientY}px`
      document.body.appendChild(w)
      setTimeout(() => w.remove(), 550)
    }
    const leave = () => { c.style.opacity = a.style.opacity = '0' }
    if (!reduced) raf = requestAnimationFrame(loop)
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseover', over)
    window.addEventListener('mousedown', down)
    document.documentElement.addEventListener('mouseleave', leave)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseover', over)
      window.removeEventListener('mousedown', down)
      document.documentElement.removeEventListener('mouseleave', leave)
      document.documentElement.classList.remove('has-aura')
    }
  }, [])

  return (
    <>
      <div id="pointer-aura" ref={aura} aria-hidden="true" />
      <div id="pointer-core" ref={core} aria-hidden="true" />
    </>
  )
}
