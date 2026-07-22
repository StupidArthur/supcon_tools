/**
 * Host that wires PidFaceplate to runtime snapshot + atomic /writes (stage 5/6).
 * Runtime values never write into template draft.
 * Mode switches use SWAM/SWSV and confirm via snapshot MODE (never write MODE).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRuntimeStore } from '../../runtime/useRuntimeStore'
import {
  observeModeSwitch,
  observeWriteBatch,
  submitAtomicWrites,
} from '../../runtime/runtimeWrites'
import {
  buildModeSwitchWrites,
  formatPidMode,
  MODE_AFTER_COMMAND,
  pidFaceplateMode,
  type PidModeCommand,
} from '../../runtime/pidMode'
import { applyRuntimeOverride } from './writeback'
import { PidFaceplate, type WriteStatus } from './PidFaceplate'
import { WritebackPanel } from './WritebackPanel'

const CONFIRM_TIMEOUT_SECONDS = 5
const CONFIRM_POLL_MS = 200

function num(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v
  if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v)
  return null
}

type PendingWrite = {
  kind: 'values'
  batchId: string
  eventIds: string[]
  expected: Record<string, number>
  deadline: number
}

type PendingMode = {
  kind: 'mode'
  batchId: string
  command: PidModeCommand
  expectedMode: number
  deadline: number
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
  const pendingRef = useRef<PendingWrite | PendingMode | null>(null)

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

  const modeNum = num(values.MODE)
  const faceplateMode = pidFaceplateMode(modeNum)
  const modeLabel = formatPidMode(modeNum)

  useEffect(() => {
    const pending = pendingRef.current
    if (!pending) return
    if (pending.kind === 'values' && writeStatus !== 'pending') return
    if (pending.kind === 'mode' && writeStatus !== 'switching') return

    const tick = () => {
      const p = pendingRef.current
      if (!p) return
      const snap = useRuntimeStore.getState().latestSnapshot
      const timedOut = Date.now() > p.deadline

      if (p.kind === 'mode') {
        const status = observeModeSwitch({
          snapshotMode: num(snap?.pid?.MODE),
          expectedMode: p.expectedMode,
          timedOut,
        })
        if (status === 'applied') {
          pendingRef.current = null
          setWriteStatus('applied')
          setWriteError(null)
        } else if (status === 'failed') {
          const actual = formatPidMode(num(snap?.pid?.MODE))
          pendingRef.current = null
          setWriteStatus('failed')
          setWriteError(
            timedOut
              ? `模式切换超时，当前 ${actual}`
              : `模式未确认，当前 ${actual}`,
          )
        }
        return
      }

      const flat: Record<string, number> = {}
      if (snap?.pid) {
        for (const [k, v] of Object.entries(snap.pid)) {
          if (typeof v === 'number' && Number.isFinite(v)) {
            flat[`pid2.${k}`] = v
          }
        }
      }
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
      // Reject any attempt to write MODE from the faceplate path.
      if (writes.some((w) => /\.MODE$/i.test(w.tag) || w.tag.toUpperCase() === 'MODE')) {
        setWriteStatus('failed')
        setWriteError('禁止写 MODE；请使用 MAN/AUTO/CAS 命令（SWAM/SWSV）')
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
          const oldRaw =
            latestSnapshot?.pid?.[w.tag.replace(/^pid2\./, '') as keyof NonNullable<typeof latestSnapshot>['pid']]
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
          kind: 'values',
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

  const onModeCommand = useCallback(
    async (command: PidModeCommand) => {
      if (!runtimeName) {
        setWriteStatus('failed')
        setWriteError('runtimeName missing')
        return
      }
      const writes = buildModeSwitchWrites(command)
      const expectedMode = MODE_AFTER_COMMAND[command]
      setWriteError(null)
      setWriteStatus('switching')
      try {
        const accepted = await submitAtomicWrites({
          apiHost,
          apiPort,
          runtimeName,
          writes,
          confirmTimeoutSeconds: CONFIRM_TIMEOUT_SECONDS,
        })
        pendingRef.current = {
          kind: 'mode',
          batchId: accepted.batchId,
          command,
          expectedMode,
          deadline: Date.now() + CONFIRM_TIMEOUT_SECONDS * 1000,
        }
      } catch (err) {
        pendingRef.current = null
        setWriteStatus('failed')
        setWriteError(err instanceof Error ? err.message : String(err))
      }
    },
    [apiHost, apiPort, runtimeName],
  )

  if (!runtimeName) {
    return null
  }

  return (
    <div className="border-t border-border p-2" data-testid="pid-faceplate-host">
      <PidFaceplate
        mode={faceplateMode === 'UNKNOWN' ? 'UNKNOWN' : faceplateMode}
        modeLabel={modeLabel}
        values={values}
        writeStatus={writeStatus}
        writeError={writeError}
        onSubmit={onSubmit}
        onModeCommand={onModeCommand}
      />
      <WritebackPanel />
    </div>
  )
}
