import { useEffect } from 'react'
import { ReactFlowProvider } from '@xyflow/react'
import { EventsOn } from '../wailsjs/runtime/runtime'
import { useCanvasStore } from './store/useCanvasStore'
import { AppNav } from './features/app/AppNav'
import { DslShell } from './features/dsl/DslShell'
import { RealtimeUaPage } from './features/realtime/RealtimeUaPage'
import { resolvePrimaryView, type AppView } from './features/app/navigation'

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
