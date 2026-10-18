import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Check } from 'lucide-react'

/** Scout's three reactive micro-states (SCOUT_SPEC §4) plus a resting state. */
export type ScoutState = 'IDLE' | 'NOSE_TO_GROUND' | 'HEAD_TILT_ALERT' | 'PROUD_CHECKMARK'

interface ScoutValue { state: ScoutState; note: string; since: number; set: (s: ScoutState, note: string) => void; clear: () => void }
const Ctx = createContext<ScoutValue | null>(null)

const REST = 'Standing by. Open a return or a product to put ReturnIQ to work.'

export function ScoutProvider({ children }: { children: ReactNode }) {
  const [s, setS] = useState<{ state: ScoutState; note: string; since: number }>({ state: 'IDLE', note: REST, since: Date.now() })
  const value = useMemo<ScoutValue>(() => ({
    ...s,
    set: (state, note) => setS((cur) => (cur.state === state && cur.note === note ? cur : { state, note, since: Date.now() })),
    clear: () => setS((cur) => (cur.state === 'IDLE' ? cur : { state: 'IDLE', note: REST, since: Date.now() })),
  }), [s])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export const useScoutState = () => {
  const v = useContext(Ctx)
  if (!v) throw new Error('useScoutState needs <ScoutProvider>')
  return v
}

/** A screen reports what Scout is doing; the rail aperture reacts. Resets to resting on unmount. */
export function useScout(state: ScoutState | null, note: string) {
  const { set, clear } = useScoutState()
  useEffect(() => {
    if (!state) return
    set(state, note)
    return clear
    // set/clear change identity with every state change; only react to what the screen reports.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, note])
}

export const SCOUT_COPY: Record<ScoutState, { lead: string; em: string; tail?: string; tone: 'idle' | 'work' | 'alert' | 'ok' }> = {
  IDLE: { lead: 'ReturnIQ is', em: 'Ready.', tone: 'idle' },
  NOSE_TO_GROUND: { lead: 'ReturnIQ is', em: 'Analyzing.', tone: 'work' },
  HEAD_TILT_ALERT: { lead: '', em: 'Mismatch', tail: 'detected.', tone: 'alert' },
  PROUD_CHECKMARK: { lead: 'Claim', em: 'verified.', tone: 'ok' },
}

/** The status reticle: ring, crosshair and two "ears". No mascot, just an instrument. */
export function Reticle({ state, size = 44 }: { state: ScoutState; size?: number }) {
  const tone = SCOUT_COPY[state].tone
  return (
    <svg className={`reticle tone-${tone} ${state === 'NOSE_TO_GROUND' ? 'anim-perk' : ''} ${state === 'HEAD_TILT_ALERT' ? 'anim-tilt' : ''}`}
      width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      <g className="ears"><path className="ear ear-l" d="M11.5 12.5 9 4.5l8 4" /><path className="ear ear-r" d="M36.5 12.5 39 4.5l-8 4" /></g>
      <circle className="ring-pulse" cx="24" cy="26" r="15" />
      <circle className="ring" cx="24" cy="26" r="15" />
      <path className="ticks" d="M24 8v5M24 39v5M6 26h5M37 26h5" />
      {tone === 'ok'
        ? <path className="check" d="m17.5 26.5 4.5 4.5 8.5-9.5" />
        : <circle className="core" cx="24" cy="26" r="3" />}
    </svg>
  )
}

/** Rail block "01 / APERTURE": state and one line of context. */
export function Aperture() {
  const { state, note } = useScoutState()
  const copy = SCOUT_COPY[state]
  return (
    <section className={`aperture tone-${copy.tone}`} aria-live="polite" aria-label="ReturnIQ status">
      <div className="mono-label"><span>01</span> / APERTURE</div>
      <div className="aperture-body">
        <Reticle state={state} />
        <div>
          <p className="aperture-state">{copy.lead} <em>{copy.em}</em>{copy.tail ? ` ${copy.tail}` : ''}</p>
          <p className="aperture-note">{note}</p>
        </div>
      </div>
    </section>
  )
}

/** Small inline badge version of the state, for page headers. */
export function StateTag({ ok, children }: { ok: boolean; children: ReactNode }) {
  return <span className={`state-tag ${ok ? 'ok' : 'alert'}`}>{ok ? <Check size={12} strokeWidth={3} /> : <span className="bang">!</span>}{children}</span>
}
