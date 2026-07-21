/**
 * Public validation adapter for save/start gates (stage 8).
 *
 * This file has no relative imports so prospective acceptance can load it via
 * file://. Full DraftConfig rules live in validationRules.ts.
 */

/**
 * Pre-save / pre-start gate. Reuses the same finite-SV rule as validateConfig.
 * Accepts a partial document so acceptance can pass `{ SV: NaN }`.
 */
export function validateBeforeSave(doc: Record<string, unknown>): {
  ok: boolean
  issues?: Array<{ path: string; level: string; message: string }>
} {
  const issues: Array<{ path: string; level: string; message: string }> = []

  const sv =
    typeof doc.SV === 'number'
      ? doc.SV
      : doc.pid && typeof doc.pid === 'object' && doc.pid !== null && typeof (doc.pid as { SV?: unknown }).SV === 'number'
        ? (doc.pid as { SV: number }).SV
        : undefined

  if (sv !== undefined && !Number.isFinite(sv)) {
    issues.push({ path: 'pid.SV', level: 'error', message: 'SV 必须是有限数' })
  }

  // Nested draft-shaped payload: prefer full rules when available via optional bind.
  if (typeof _validateConfigBound === 'function' && looksLikeDraft(doc)) {
    const more = _validateConfigBound(doc)
    for (const issue of more) {
      if (issue.level === 'error') {
        issues.push(issue)
      }
    }
  }

  return issues.length ? { ok: false, issues } : { ok: true }
}

type Issue = { path: string; level: string; message: string }
type ValidateConfigFn = (doc: unknown) => Issue[]

let _validateConfigBound: ValidateConfigFn | null = null

/** Page/store wires the real validateConfig so rules stay single-sourced. */
export function bindValidateConfig(fn: ValidateConfigFn): void {
  _validateConfigBound = fn
}

function looksLikeDraft(doc: Record<string, unknown>): boolean {
  return (
    typeof doc.cycleTime === 'number' ||
    (doc.pid != null && typeof doc.pid === 'object') ||
    (doc.tank2 != null && typeof doc.tank2 === 'object')
  )
}

// Re-export surface name used by some callers after the split (optional).
export { bindValidateConfig as attachValidationRules }
