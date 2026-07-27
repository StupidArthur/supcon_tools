import { useState, useEffect } from 'react'
import { EventsOn } from '../../../wailsjs/runtime/runtime'

type ServiceState =
  | { tag: 'starting'; message: string; percent: number }
  | { tag: 'ready' }
  | { tag: 'error'; error: string }

export function ServiceLoadingScreen() {
  const [state, setState] = useState<ServiceState>({
    tag: 'starting',
    message: '正在初始化...',
    percent: 0,
  })

  // 进度条前 10 秒自动推进（不精确，仅用于视觉反馈）
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    if (state.tag !== 'starting') return
    if (elapsed >= 100) return
    const id = setInterval(() => {
      setElapsed((p) => Math.min(p + 1, 100))
    }, 100)
    return () => clearInterval(id)
  }, [state.tag, elapsed])

  useEffect(() => {
    const offProgress = EventsOn('df:service-progress', (data: { percent: number; message: string }) => {
      setState({ tag: 'starting', message: data.message, percent: data.percent })
    })
    const offReady = EventsOn('df:service-ready', () => {
      setState({ tag: 'ready' })
    })
    const offError = EventsOn('df:service-error', (data: { error: string }) => {
      setState({ tag: 'error', error: data.error })
    })
    const offStarting = EventsOn('df:service-starting', (data: { message: string }) => {
      setState({ tag: 'starting', message: data.message, percent: 0 })
    })
    return () => {
      offProgress()
      offReady()
      offError()
      offStarting()
    }
  }, [])

  if (state.tag === 'ready') return null

  const barPercent = state.tag === 'starting' ? Math.max(state.percent || 0, elapsed) : 100
  const message = state.tag === 'starting' ? (state.message || '正在启动...') : ''
  const errorMsg = state.tag === 'error' ? state.error : ''

  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-background">
      <div className="w-80 max-w-full px-6">
        <h1 className="mb-6 text-center text-lg font-semibold tracking-tight text-foreground">
          DataFactory 组态工具
        </h1>

        {/* progress bar */}
        <div className="mb-3 h-2 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary transition-all duration-300 ease-out"
            style={{ width: `${barPercent}%` }}
          />
        </div>

        {errorMsg ? (
          <>
            <p className="mb-4 text-center text-xs text-destructive">{errorMsg}</p>
            <button
              type="button"
              onClick={() => {
                window.location.reload()
              }}
              className="rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90"
            >
              重试
            </button>
          </>
        ) : (
          <p className="text-center text-xs text-muted-foreground">{message}</p>
        )}
      </div>
    </div>
  )
}
