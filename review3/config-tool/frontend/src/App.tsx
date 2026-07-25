import { useEffect } from 'react'
import { ReactFlowProvider } from '@xyflow/react'
import { EventsOn } from '../wailsjs/runtime/runtime'
import { useCanvasStore } from './store/useCanvasStore'
import { AppNav } from './features/app/AppNav'
import { DslShell } from './features/dsl/DslShell'
import { RealtimeConfigPage } from './features/realtime/RealtimeConfigPage'
import { RealtimeRunPage } from './features/realtime/RealtimeRunPage'
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
    if (!(window as any).runtime?.EventsOnMultiple) {
      console.warn('wails runtime unavailable; skip df event subscriptions')
      return
    }
    const offLog = EventsOn('df:log', (log: string) => {
      useCanvasStore.getState().addDfLog(log)
    })
    const offStatus = EventsOn('df:status', (status: any) => {
      useCanvasStore.getState().setDfStatus(status)
    })
    const offExited = EventsOn('df:exited', (info: { exitCode: number; error: unknown }) => {
      useRealtimeRunSessionStore.setState({ session: null, error: null })
      useRuntimeStore.getState().endRuntimeSession()
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
    return () => {
      try {
        offLog()
        offStatus()
        offExited()
      } catch (err) {
        console.warn('EventsOff failed:', err)
      }
    }
  }, [])

  const primary = resolvePrimaryView(view)

  return (
    <ReactFlowProvider>
      <div className="flex h-screen flex-col">
        <AppNav />
        <div className="flex flex-1 overflow-hidden">
          {primary === 'dsl' ? (
            <DslShell />
          ) : primary === 'project-config' ? (
            <RealtimeConfigPage />
          ) : (
            <RealtimeRunPage />
          )}
        </div>
      </div>
    </ReactFlowProvider>
  )
}

export default App