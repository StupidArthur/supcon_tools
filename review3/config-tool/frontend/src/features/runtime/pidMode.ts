/**
 * ECS-700 / DCS PID MODE definitions and mode-switch command helpers.
 * MODE is status only; switch MAN/AUTO/CAS via SWAM/SWSV writes.
 */

/** Formal MODE map (1..8). */
export const PID_MODE_MAP = {
  1: 'OOS',
  2: 'IMAN',
  3: 'TR',
  4: 'MAN',
  5: 'AUTO',
  6: 'CAS',
  7: 'RCAS',
  8: 'ROUT',
} as const

export type PidModeName = (typeof PID_MODE_MAP)[keyof typeof PID_MODE_MAP]
export type PidModeLabel = PidModeName | `UNKNOWN(${number})` | 'UNKNOWN'

/** Switch command targets that change MODE via SWAM/SWSV. */
export type PidModeCommand = 'MAN' | 'AUTO' | 'CAS'

/** ECS ON/OFF for switches. */
export const SW_ON = 1
export const SW_OFF = 0

/** Expected MODE after a successful switch command. */
export const MODE_AFTER_COMMAND: Record<PidModeCommand, number> = {
  MAN: 4,
  AUTO: 5,
  CAS: 6,
}

/**
 * Format MODE for display. Unrecognized values → UNKNOWN(value).
 */
export function formatPidMode(modeNum: number | null | undefined): PidModeLabel {
  if (modeNum == null || !Number.isFinite(modeNum)) return 'UNKNOWN'
  const n = Math.trunc(modeNum)
  if (n !== modeNum) return `UNKNOWN(${modeNum})`
  const name = (PID_MODE_MAP as Record<number, PidModeName>)[n]
  return name ?? `UNKNOWN(${n})`
}

/**
 * Working-mode label used for faceplate enablement (MAN/AUTO/CAS family).
 * Does not invent AUTO for unknown values.
 */
export function pidFaceplateMode(modeNum: number | null | undefined): PidModeName | 'UNKNOWN' {
  const label = formatPidMode(modeNum)
  if (label.startsWith('UNKNOWN')) return 'UNKNOWN'
  return label as PidModeName
}

/** Whether SV may be edited in this MODE. */
export function isSvEditable(mode: PidModeName | 'UNKNOWN'): boolean {
  return mode === 'AUTO'
}

/** Whether MV may be edited in this MODE (manual-class). */
export function isMvEditable(mode: PidModeName | 'UNKNOWN'): boolean {
  return mode === 'MAN' || mode === 'IMAN' || mode === 'TR' || mode === 'ROUT'
}

/** Effective setpoint source for display. */
export function effectiveSetpointSource(
  mode: PidModeName | 'UNKNOWN',
): 'SV' | 'CSV' | 'MV' | 'none' {
  if (mode === 'CAS' || mode === 'RCAS') return 'CSV'
  if (isMvEditable(mode)) return 'MV'
  if (mode === 'AUTO') return 'SV'
  return 'none'
}

/**
 * Build atomic write batch for a mode switch command.
 * Never writes MODE; only SWAM/SWSV.
 */
export function buildModeSwitchWrites(
  command: PidModeCommand,
  tagPrefix = 'pid2',
): Array<{ tag: string; value: number }> {
  switch (command) {
    case 'MAN':
      return [{ tag: `${tagPrefix}.SWAM`, value: SW_OFF }]
    case 'AUTO':
      return [
        { tag: `${tagPrefix}.SWAM`, value: SW_ON },
        { tag: `${tagPrefix}.SWSV`, value: SW_OFF },
      ]
    case 'CAS':
      return [
        { tag: `${tagPrefix}.SWAM`, value: SW_ON },
        { tag: `${tagPrefix}.SWSV`, value: SW_ON },
      ]
  }
}
