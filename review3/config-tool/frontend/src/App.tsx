import { useEffect } from 'react'
import { ReactFlowProvider } from '@xyflow/react'
import { EventsOn } from '../wailsjs/runtime/runtime'
import { useCanvasStore } from './store/useCanvasStore'
import { AppNav } from './features/app/AppNav'
import { DslShell } from './features/dsl/DslShell'
import { RealtimeUaPage } from './features/realtime/RealtimeUaPage'
import { resolvePrimaryView, type AppView } from './features/app/navigation'
import { useRealtimeRunSessionStore } from './features/realtime/useRealtimeRunSessionStore'
import { useRuntimeStore } from './features/runtime/useRuntimeStore'

function App() {
  const init = useCanvasStore((s) => s.init)
  const view = useCanvasStore((s) => s.view) as AppView

  useEffect(() => {
    init()
  }, [init])

  useEffect(() => {
    // wails runtime 未注入时 EventsOn 会抛错，导致白屏；开发态/异常启动需容错。
    if (!(window as any).runtime?.EventsOnMultiple) {
      console.warn('wails runtime unavailable; skip df event subscriptions')
      return
    }
    try {
      EventsOn('df:log', (log: string) => {
        useCanvasStore.getState().addDfLog(log)
      })
      EventsOn('df:status', (status: any) => {
        useCanvasStore.getState().setDfStatus(status)
      })
      // 关键：DataFactory 异常退出 / 主动停止时，前端必须同步清理 session 和 WS。
      // 之前仅在 useEffect 依赖 dfStatus.running 触发的清理路径不可靠：
      // df:status 事件被后端先于 df:exited 发出，useEffect 重跑会发起新连接；
      // 没有 df:exited 直接监听，session 卡片可能持续显示"正在运行"。
      EventsOn('df:exited', (info: { exitCode: number; error: unknown }) => {
        // 强制清空 session store（不依赖任何 refresh）。
        useRealtimeRunSessionStore.setState({ session: null, error: null })
        // 关闭 runtime store 的 WS + 清空 token，避免后续无意义重连。
        useRuntimeStore.getState().endRuntimeSession()
        // 显式把 dfStatus.running 置为 false，触发所有依赖它的 useEffect。
        const cur = useCanvasStore.getState().dfStatus
        useCanvasStore.getState().setDfStatus({
          ...cur,
          running: false,
          apiReady: false,
        })
        if (info && info.error) {
          console.warn('DataFactory exited with error:', info)
        }
      })
    } catch (err) {
      console.warn('EventsOn failed:', err)
    }
  }, [])

  const primary = resolvePrimaryView(view)

  return (
    <ReactFlowProvider>
      <div className="flex h-screen flex-col">
        <AppNav />
        <div className="flex flex-1 overflow-hidden">
          {primary === 'realtime' ? <RealtimeUaPage /> : <DslShell />}
        </div>
      </div>
    </ReactFlowProvider>
  )
}

export default App
