import { useEffect } from 'react'
import { EventsOn } from '../wailsjs/runtime/runtime'
import { useStore } from './store/useStore'
import { debugApi } from './lib/api'
import { Toolbar } from './components/Toolbar'
import { ParamPanel } from './components/ParamPanel'
import { ChartPanel } from './components/ChartPanel'
import { StatusBar } from './components/StatusBar'
import { LogPanel } from './components/LogPanel'

function App() {
  const addLog = useStore((s) => s.addLog)
  const setRunning = useStore((s) => s.setRunning)
  const setBatchRunning = useStore((s) => s.setBatchRunning)
  const setBatchResult = useStore((s) => s.setBatchResult)

  useEffect(() => {
    // 监听引擎日志
    EventsOn('engine:log', (line: string) => {
      addLog('engine', line)
    })

    // 监听引擎停止
    EventsOn('engine:stopped', () => {
      setRunning(false)
      addLog('system', '引擎已停止')
    })

    // 监听批量仿真完成，读取 CSV 结果
    EventsOn('batch:finished', async (csvPath: string) => {
      setBatchRunning(false)
      addLog('system', `批量仿真完成: ${csvPath}`)
      try {
        const result = await debugApi.readBatchResult(csvPath)
        setBatchResult(result)
        addLog('system', `读取结果: ${result.rows.length} 行 × ${result.columns.length - 1} 列`)
      } catch (e: any) {
        addLog('error', `读取 CSV 失败: ${e}`)
      }
    })
  }, [addLog, setRunning, setBatchRunning, setBatchResult])

  return (
    <div className="flex h-screen flex-col">
      <Toolbar />
      <div className="flex flex-1 overflow-hidden">
        <ParamPanel />
        <div className="flex flex-1 flex-col">
          <ChartPanel />
          <LogPanel />
        </div>
      </div>
      <StatusBar />
    </div>
  )
}

export default App
