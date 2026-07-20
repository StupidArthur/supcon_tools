import { useEffect } from 'react'
import { ReactFlowProvider } from '@xyflow/react'
import { EventsOn } from '../wailsjs/runtime/runtime'
import { useCanvasStore } from './store/useCanvasStore'
import { Toolbar } from './components/Toolbar'
import { Palette } from './components/Palette'
import { Canvas } from './components/Canvas'
import { PropertyPanel } from './components/PropertyPanel'
import { SystemPanel } from './components/SystemPanel'
import { SimulationPanel } from './components/SimulationPanel'
import { TemplateWorkspace } from './features/templates/TemplateWorkspace'

function App() {
  const init = useCanvasStore((s) => s.init)
  const view = useCanvasStore((s) => s.view)

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

  return (
    <ReactFlowProvider>
      <div className="flex h-screen flex-col">
        <Toolbar />
        <div className="flex flex-1 overflow-hidden">
          {view === 'system' ? (
            <SystemPanel />
          ) : view === 'simulation' ? (
            <SimulationPanel />
          ) : view === 'config' ? (
            <>
              <Palette />
              <Canvas />
              <PropertyPanel />
            </>
          ) : (
            <TemplateWorkspace />
          )}
        </div>
      </div>
    </ReactFlowProvider>
  )
}

export default App
