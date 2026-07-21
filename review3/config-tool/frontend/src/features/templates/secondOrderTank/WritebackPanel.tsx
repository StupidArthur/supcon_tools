/**
 * Writeback UI: confirmed Faceplate overrides → ApplyRuntimeOverrides.
 * Does not mutate draft; calls saveWriteback() only.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTemplateStore } from '../useTemplateStore'
import { templateApi } from '../../../lib/api'
import {
  listConfirmedOverrides,
  listWritebackCandidates,
  saveWriteback,
  setWritebackCandidateSelected,
  subscribeWriteback,
} from './writeback'

export function WritebackPanel() {
  const sourcePath = useTemplateStore((s) => s.sourcePath)
  const [, setTick] = useState(0)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isBuiltin, setIsBuiltin] = useState(false)

  useEffect(() => subscribeWriteback(() => setTick((n) => n + 1)), [])

  useEffect(() => {
    let cancelled = false
    if (!sourcePath) {
      setIsBuiltin(false)
      return
    }
    templateApi
      .isBuiltin(sourcePath)
      .then((v) => {
        if (!cancelled) setIsBuiltin(Boolean(v))
      })
      .catch(() => {
        if (!cancelled) setIsBuiltin(false)
      })
    return () => {
      cancelled = true
    }
  }, [sourcePath])

  const confirmed = listConfirmedOverrides()
  const candidates = listWritebackCandidates()
  const confirmedTags = Object.keys(confirmed)

  const onWriteback = useCallback(async () => {
    setBusy(true)
    setMessage(null)
    setError(null)
    try {
      // Production path: no acceptance {fail} args.
      const result = await saveWriteback()
      if (!result.savedUpdated) {
        setError(result.error || '写回失败')
        return
      }
      setMessage('已写回配置文件（当前运行仍使用启动时配置；Stop 后重新 Start 生效）')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }, [])

  if (confirmedTags.length === 0 && !message && !error) {
    // Still show panel shell so users discover writeback after first applied write.
  }

  return (
    <div className="space-y-2 border-t border-border p-2 text-xs" data-testid="writeback-panel">
      <div className="font-medium">写回配置文件</div>
      {isBuiltin ? (
        <div className="text-amber-800" data-testid="writeback-builtin-hint">
          当前为内置模板，禁止直接写回。请先「另存为」外部文件后再写回。
        </div>
      ) : null}
      {confirmedTags.length === 0 ? (
        <div className="text-muted-foreground">尚无已确认（applied）的运行参数</div>
      ) : (
        <ul className="space-y-1" data-testid="writeback-confirmed-list">
          {candidates
            .filter((c) => confirmed[c.tag] != null)
            .map((c) => (
              <li key={c.tag} className="flex items-center gap-2">
                <label className="inline-flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={c.selected}
                    disabled={isBuiltin || busy}
                    onChange={(e) => setWritebackCandidateSelected(c.tag, e.target.checked)}
                  />
                  <span>
                    {c.tag} = {confirmed[c.tag]}
                  </span>
                </label>
              </li>
            ))}
        </ul>
      )}
      <button
        type="button"
        data-testid="writeback-save-button"
        disabled={isBuiltin || busy || confirmedTags.length === 0}
        onClick={() => void onWriteback()}
        className="rounded-md bg-secondary px-2 py-1 disabled:cursor-not-allowed disabled:opacity-50"
      >
        写回配置文件
      </button>
      {message ? (
        <div className="text-green-800" data-testid="writeback-success">
          {message}
        </div>
      ) : null}
      {error ? (
        <div className="text-red-800" data-testid="writeback-error">
          {error}
        </div>
      ) : null}
    </div>
  )
}
