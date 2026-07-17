import { useRef, useEffect } from 'react'
import { useStore } from '../store/useStore'

export function LogPanel() {
  const logs = useStore((s) => s.logs)
  const clearLogs = useStore((s) => s.clearLogs)
  const logEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  return (
    <div className="h-40 flex flex-col border-t border-border bg-card">
      <div className="flex items-center justify-between px-3 py-1 border-b border-border">
        <span className="text-xs text-muted-foreground">日志输出</span>
        <button
          onClick={clearLogs}
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          清空
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-1 font-mono text-xs">
        {logs.length === 0 ? (
          <div className="text-muted-foreground">暂无日志</div>
        ) : (
          logs.map((log, i) => (
            <div key={i} className="whitespace-pre-wrap break-all">
              <span className="text-muted-foreground/60">
                [{log.source}]
              </span>{' '}
              {log.text}
            </div>
          ))
        )}
        <div ref={logEndRef} />
      </div>
    </div>
  )
}
