import { useEffect, useState, useCallback } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { api, type APILogEntry } from '@/lib/api'

function formatTime(ms: number): string {
  const d = new Date(ms)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function sourceColor(s: string): string {
  if (s === 'frontend') return 'text-blue-600'
  return 'text-emerald-600'
}

export function APILogView() {
  const [logs, setLogs] = useState<APILogEntry[]>([])

  const reload = useCallback(async () => {
    try {
      const r = await api.getRecentAPILogs(500)
      setLogs(r ?? [])
    } catch {
      // ignore
    }
  }, [])

  useEffect(() => {
    reload()
    const t = setInterval(reload, 2000)
    return () => clearInterval(t)
  }, [reload])

  return (
    <div className="space-y-3.5">
      <Card>
        <CardContent className="py-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">
              接口日志（最近 {logs.length} 条，每 2s 刷新）
            </span>
            <span className="text-xs text-muted-foreground">时间格式 HH:MM:SS</span>
          </div>
          {logs.length === 0 ? (
            <div className="py-8 text-center text-xs text-muted-foreground">暂无日志</div>
          ) : (
            <div className="max-h-[70vh] overflow-y-auto">
              <table className="w-full text-xs">
                <tbody>
                  {logs.map((e, i) => (
                    <tr key={i} className="border-b border-border/40 hover:bg-secondary/30">
                      <td className="w-20 py-1 pr-2 font-mono text-muted-foreground">
                        {formatTime(e.ts)}
                      </td>
                      <td className={`w-16 py-1 pr-2 ${sourceColor(e.source)}`}>
                        [{e.source}]
                      </td>
                      <td className="w-32 py-1 pr-2 font-medium">{e.cluster || '—'}</td>
                      <td className="w-24 py-1 pr-2 text-muted-foreground">{e.phase}</td>
                      <td className="py-1">{e.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
