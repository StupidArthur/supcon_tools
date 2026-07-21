/**
 * Host that wires PidFaceplate to runtime snapshot + atomic /writes (stage 5/6).
 * Runtime values never write into template draft.
 * Write events use REST time for pending and snapshot confirm time for applied.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRuntimeStore } from '../../runtime/useRuntimeStore'
import { observeWriteBatch, submitAtomicWrites } from '../../runtime/runtimeWrites'
import { applyRuntimeOverride } from './writeback'
import { PidFaceplate, type WriteStatus } from './PidFaceplate'
import { WritebackPanel } from './WritebackPanel'

const CONFIRM_TIMEOUT_SECONDS = 5
const CONFIRM_POLL_MS = 200

function modeLabel(modeNum: number | null | undefined): 'AUTO' | 'MAN' | 'CAS' {
  if (modeNum === 3) return 'CAS'
  if (modeNum === 4 || modeNum === 2 || modeNum === 8) return 'MAN'
  return 'AUTO'
}

function num(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v
  if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v)
  return null
}

export function PidFaceplateHost() {
  const latestSnapshot = useRuntimeStore((s) => s.latestSnapshot)
  const runtimeName = useRuntimeStore((s) => s.runtimeName)
  const apiHost = useRuntimeStore((s) => s.apiHost)
  const apiPort = useRuntimeStore((s) => s.apiPort)
  const recordWriteEvent = useRuntimeStore((s) => s.recordWriteEvent)
  const updateWriteEvent = useRuntimeStore((s) => s.updateWriteEvent)

  const [writeStatus, setWriteStatus] = useState<WriteStatus>('idle')
  const [writeError, setWriteError] = useState<string | null>(null)
  const pendingRef = useRef<{
    batchId: string
    eventIds: string[]
    expected: Record<string, number>
    deadline: number
  } | null>(null)

  const pid = latestSnapshot?.pid
  const values = useMemo(
    () => ({
      PV: num(pid?.PV),
      SV: num(pid?.SV),
      CSV: num(pid?.CSV),
      MV: num(pid?.MV),
      PB: num(pid?.PB),
      TI: num(pid?.TI),
      TD: num(pid?.TD),
      KD: num(pid?.KD),
      MODE: pid?.MODE ?? null,
      SWPN: pid?.SWPN ?? null,
    }),
    [pid],
  )

  const faceplateMode = modeLabel(num(values.MODE))

  useEffect(() => {
    const pending = pendingRef.current
    if (!pending || writeStatus !== 'pending') return

    const tick = () => {
      const p = pendingRef.current
      if (!p) return
      const snap = useRuntimeStore.getState().latestSnapshot
      const flat: Record<string, number> = {}
      if (snap?.pid) {
        for (const [k, v] of Object.entries(snap.pid)) {
          if (typeof v === 'number' && Number.isFinite(v)) {
            flat[`pid2.${k}`] = v
          }
        }
      }
      const timedOut = Date.now() > p.deadline
      const status = observeWriteBatch({
        batchId: p.batchId,
        snapshot: flat,
        expected: p.expected,
        timedOut,
      })
      if (status === 'applied') {
        const confirmedAt = Date.now()
        for (const id of p.eventIds) {
          updateWriteEvent(id, { status: 'applied', confirmedAt })
        }
        // Only after full-batch snapshot confirm: feed writeback buffer.
        for (const [tag, value] of Object.entries(p.expected)) {
          applyRuntimeOverride(tag, value)
        }
        pendingRef.current = null
        setWriteStatus('applied')
        setWriteError(null)
      } else if (status === 'failed') {
        for (const id of p.eventIds) {
          updateWriteEvent(id, { status: 'failed' })
        }
        pendingRef.current = null
        setWriteStatus('failed')
        setWriteError('confirm timeout')
      }
    }

    tick()
    const id = window.setInterval(tick, CONFIRM_POLL_MS)
    return () => window.clearInterval(id)
  }, [latestSnapshot, writeStatus, updateWriteEvent])

  const onSubmit = useCallback(
    async (writes: Array<{ tag: string; value: number }>) => {
      if (!runtimeName) {
        setWriteStatus('failed')
        setWriteError('runtimeName missing')
        return
      }
      setWriteError(null)
      setWriteStatus('pending')
      const expected: Record<string, number> = {}
      for (const w of writes) expected[w.tag] = w.value
      const eventIds: string[] = []
      const restReturnedAt = Date.now()
      try {
        const accepted = await submitAtomicWrites({
          apiHost,
          apiPort,
          runtimeName,
          writes,
          confirmTimeoutSeconds: CONFIRM_TIMEOUT_SECONDS,
        })
        for (const w of writes) {
          const id = `${accepted.batchId}:${w.tag}`
          eventIds.push(id)
          const oldRaw = latestSnapshot?.pid?.[w.tag.replace(/^pid2\./, '') as keyof NonNullable<typeof latestSnapshot>['pid']]
          recordWriteEvent({
            id,
            status: 'pending',
            tag: w.tag,
            oldValue: num(oldRaw),
            newValue: w.value,
            source: 'faceplate',
            restReturnedAt,
          })
        }
        pendingRef.current = {
          batchId: accepted.batchId,
          eventIds,
          expected,
          deadline: Date.now() + CONFIRM_TIMEOUT_SECONDS * 1000,
        }
        setWriteStatus('pending')
      } catch (err) {
        pendingRef.current = null
        setWriteStatus('failed')
        setWriteError(err instanceof Error ? err.message : String(err))
      }
    },
    [apiHost, apiPort, runtimeName, latestSnapshot, recordWriteEvent],
  )

  if (!runtimeName) {
    return null
  }

  return (
    <div className="border-t border-border p-2" data-testid="pid-faceplate-host">
      <PidFaceplate
        mode={faceplateMode}
        values={values}
        writeStatus={writeStatus}
        writeError={writeError}
        onSubmit={onSubmit}
      />
      <WritebackPanel />
    </div>
  )
}
