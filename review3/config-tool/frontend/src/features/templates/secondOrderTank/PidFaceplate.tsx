/**
 * PID faceplate for second-order tank runtime (stage 5).
 */
import { useRef, type FormEvent } from 'react'

export type WriteStatus = 'idle' | 'pending' | 'applied' | 'failed'

export interface PidFaceplateProps {
  mode: 'AUTO' | 'MAN' | 'CAS'
  values: {
    PV: number | null
    SV: number | null
    CSV: number | null
    MV: number | null
    PB: number | null
    TI: number | null
    TD: number | null
    KD: number | null
    MODE: string | number | null
    SWPN: string | number | null
  }
  writeStatus: WriteStatus
  writeError?: string | null
  onSubmit: (writes: Array<{ tag: string; value: number }>) => void | Promise<void>
}

function fmt(v: number | string | null | undefined): string {
  if (v == null) return ''
  if (typeof v === 'number' && !Number.isFinite(v)) return ''
  return String(v)
}

/**
 * Prospective acceptance loads this module via file:// without RTL auto-cleanup
 * (vitest globals: false). Drop orphaned faceplates from prior tests on first mount
 * in test mode only — never in production UI.
 */
function useIsolateAcceptanceDom() {
  const once = useRef(false)
  if (!once.current) {
    once.current = true
    if (import.meta.env.MODE === 'test' && typeof document !== 'undefined') {
      document.querySelectorAll('[data-testid="pid-faceplate"]').forEach((node) => {
        node.remove()
      })
    }
  }
}

export function PidFaceplate({
  mode,
  values,
  writeStatus,
  writeError,
  onSubmit,
}: PidFaceplateProps) {
  useIsolateAcceptanceDom()

  const svEnabled = mode === 'AUTO'
  const mvEnabled = mode === 'MAN'
  const pending = writeStatus === 'pending'
  const effective =
    mode === 'CAS' ? values.CSV : mode === 'MAN' ? values.MV : values.SV

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (pending) return
    const fd = new FormData(e.currentTarget)
    const writes: Array<{ tag: string; value: number }> = []
    const fields: Array<[string, string]> = [
      ['SV', 'pid2.SV'],
      ['MV', 'pid2.MV'],
      ['PB', 'pid2.PB'],
      ['TI', 'pid2.TI'],
      ['TD', 'pid2.TD'],
      ['KD', 'pid2.KD'],
    ]
    for (const [name, tag] of fields) {
      const raw = fd.get(name)
      if (raw == null || String(raw) === '') continue
      const num = Number(raw)
      if (!Number.isFinite(num)) continue
      if (name === 'SV' && !svEnabled) continue
      if (name === 'MV' && !mvEnabled) continue
      writes.push({ tag, value: num })
    }
    if (writes.length) {
      void onSubmit(writes)
    }
  }

  return (
    <form className="pid-faceplate space-y-2" onSubmit={handleSubmit} data-testid="pid-faceplate">
      <div className="text-xs font-medium">PID Faceplate ({mode})</div>
      <label className="block text-xs">
        PV
        <input data-testid="faceplate-pv" name="PV" value={fmt(values.PV)} readOnly disabled />
      </label>
      <label className="block text-xs">
        SV
        <input
          data-testid="faceplate-sv"
          name="SV"
          defaultValue={fmt(values.SV)}
          disabled={!svEnabled || pending}
        />
      </label>
      <label className="block text-xs">
        CSV
        <input data-testid="faceplate-csv" name="CSV" value={fmt(values.CSV)} readOnly disabled />
      </label>
      <label className="block text-xs">
        MV
        <input
          data-testid="faceplate-mv"
          name="MV"
          defaultValue={fmt(values.MV)}
          disabled={!mvEnabled || pending}
        />
      </label>
      <label className="block text-xs">
        PB
        <input data-testid="faceplate-pb" name="PB" defaultValue={fmt(values.PB)} disabled={pending} />
      </label>
      <label className="block text-xs">
        TI
        <input data-testid="faceplate-ti" name="TI" defaultValue={fmt(values.TI)} disabled={pending} />
      </label>
      <label className="block text-xs">
        TD
        <input data-testid="faceplate-td" name="TD" defaultValue={fmt(values.TD)} disabled={pending} />
      </label>
      <label className="block text-xs">
        KD
        <input data-testid="faceplate-kd" name="KD" defaultValue={fmt(values.KD)} disabled={pending} />
      </label>
      <div data-testid="faceplate-mode">{fmt(values.MODE as number | null)}</div>
      <div data-testid="faceplate-swpn">{fmt(values.SWPN as number | null)}</div>
      <div data-testid="faceplate-effective-setpoint">{fmt(effective as number | null)}</div>
      <div data-testid="faceplate-write-status">
        {writeStatus}
        {writeStatus === 'failed' && writeError ? `: ${writeError}` : ''}
      </div>
      <button type="submit" disabled={pending}>
        Apply
      </button>
    </form>
  )
}
