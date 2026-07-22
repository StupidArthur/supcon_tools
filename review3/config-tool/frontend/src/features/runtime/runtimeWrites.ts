/**
 * Atomic online writes client (stage 5).
 * Posts entire batch to POST /api/instances/{runtimeName}/writes.
 */

const KNOWN_WRITABLE = new Set([
  'pid2.SV',
  'pid2.PB',
  'pid2.TI',
  'pid2.TD',
  'pid2.KD',
  'pid2.MV',
  'pid2.CSV',
  'pid2.SWAM',
  'pid2.SWSV',
  'pid2.SWPN',
])

const FORBIDDEN = new Set([
  'pid2.PV',
  'pid2.MODE',
  'pid2.AUTO',
  'pid2.CAS',
  'PV',
  'MODE',
  'tank_1.level',
  'tank_2.level',
  'valve_1.current_opening',
  'AUTO',
  'CAS',
  'source_flow',
])

export interface AtomicWriteInput {
  apiHost: string
  apiPort: number
  runtimeName: string
  writes: Array<{ tag: string; value: number }>
  confirmTimeoutSeconds?: number
  signal?: AbortSignal
}

export interface AtomicWriteAccepted {
  batchId: string
  status: 'pending'
}

function assertClientPrecheck(writes: Array<{ tag: string; value: number }>): void {
  if (!writes.length) {
    throw new Error('writes must not be empty')
  }
  const seen = new Set<string>()
  for (const item of writes) {
    const tag = String(item.tag)
    if (seen.has(tag)) {
      throw new Error(`duplicate tag: ${tag}`)
    }
    seen.add(tag)
    if (FORBIDDEN.has(tag) || FORBIDDEN.has(tag.split('.').pop() || '')) {
      throw new Error(`readonly or forbidden tag: ${tag}`)
    }
    if (!KNOWN_WRITABLE.has(tag) && !tag.startsWith('pid2.')) {
      throw new Error(`unknown tag: ${tag}`)
    }
    const v = item.value
    if (typeof v !== 'number' || !Number.isFinite(v)) {
      throw new Error(`non-finite value for ${tag}`)
    }
  }
}

/**
 * Read JSON from a fetch Response or a test mock that only implements `.json()`.
 */
async function readJsonBody(resp: {
  ok: boolean
  status: number
  json?: () => Promise<unknown>
  text?: () => Promise<string>
}): Promise<{ json: Record<string, unknown>; text: string }> {
  if (typeof resp.json === 'function') {
    try {
      const data = await resp.json()
      if (data && typeof data === 'object') {
        const json = data as Record<string, unknown>
        return { json, text: JSON.stringify(json) }
      }
      return { json: {}, text: String(data ?? '') }
    } catch {
      // fall through to text()
    }
  }
  if (typeof resp.text === 'function') {
    const text = await resp.text()
    try {
      const json = text ? (JSON.parse(text) as Record<string, unknown>) : {}
      return { json, text }
    } catch {
      return { json: { detail: text }, text }
    }
  }
  return { json: {}, text: '' }
}

export async function submitAtomicWrites(input: AtomicWriteInput): Promise<AtomicWriteAccepted> {
  assertClientPrecheck(input.writes)
  const url = `http://${input.apiHost}:${input.apiPort}/api/instances/${encodeURIComponent(input.runtimeName)}/writes`
  const body: Record<string, unknown> = { writes: input.writes }
  if (input.confirmTimeoutSeconds != null) {
    body.confirm_timeout_s = input.confirmTimeoutSeconds
  }
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: input.signal,
  })
  const { json, text } = await readJsonBody(resp)
  if (!resp.ok) {
    throw new Error(String(json.detail || json.error || text || `HTTP ${resp.status}`))
  }
  const batchId = String(json.batch_id || json.batchId || '')
  if (!batchId) {
    throw new Error('missing batch_id in response')
  }
  if (json.status && json.status !== 'pending') {
    throw new Error(`expected pending, got ${String(json.status)}`)
  }
  return { batchId, status: 'pending' }
}

const OBSERVE_TOL = 1e-6

export function observeWriteBatch(input: {
  batchId: string
  snapshot: Record<string, number>
  expected: Record<string, number>
  timedOut?: boolean
}): 'pending' | 'applied' | 'failed' {
  if (input.timedOut) {
    return 'failed'
  }
  for (const [tag, expected] of Object.entries(input.expected)) {
    const actual = input.snapshot[tag]
    if (typeof actual !== 'number' || !Number.isFinite(actual)) {
      return 'pending'
    }
    if (Math.abs(actual - expected) > OBSERVE_TOL) {
      return 'pending'
    }
  }
  return 'applied'
}

/**
 * Confirm a mode-switch command by snapshot MODE (not by SWAM/SWSV values).
 */
export function observeModeSwitch(input: {
  snapshotMode: number | null | undefined
  expectedMode: number
  timedOut?: boolean
}): 'pending' | 'applied' | 'failed' {
  if (input.timedOut) {
    return 'failed'
  }
  if (typeof input.snapshotMode !== 'number' || !Number.isFinite(input.snapshotMode)) {
    return 'pending'
  }
  if (Math.trunc(input.snapshotMode) === input.expectedMode) {
    return 'applied'
  }
  return 'pending'
}
