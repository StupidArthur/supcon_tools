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
    EventsOn('df:log', (log: string) => {
      useCanvasStore.getState().addDfLog(log)
    })
    EventsOn('df:status', (status: any) => {
      useCanvasStore.getState().setDfStatus(status)
    })
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
