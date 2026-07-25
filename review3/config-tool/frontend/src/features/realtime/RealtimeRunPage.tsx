import { useEffect, useMemo, useRef, useState } from 'react'
import { realtimeProjectApi, realtimeRuntimeApi, systemApi } from '../../lib/api'
import { backendBatchBusy, useCanvasStore } from '../../store/useCanvasStore'
import { useGenericSimStore } from '../dsl/useGenericSimStore'
import { useRuntimeStore } from '../runtime/useRuntimeStore'
import { useRealtimeProjectStore } from './useRealtimeProjectStore'
import { useRealtimeRunSessionStore } from './useRealtimeRunSessionStore'
import { RuntimeInstanceTable } from './RuntimeInstanceTable'
import { RuntimeInstanceDetail } from './RuntimeInstanceDetail'

export function RealtimeRunPage() {
  const dfStatus = useCanvasStore((s) => s.dfStatus)
  const setDfPath = useCanvasStore((s) => s.setDfPath)
  const refreshStatus = useCanvasStore((s) => s.refreshStatus)

  const currentProject = useRealtimeProjectStore((s) => s.currentProject)
  const currentProjectFile = useRealtimeProjectStore((s) => s.currentProjectFile)
  const instances = useRealtimeProjectStore((s) => s.instances)

  const session = useRealtimeRunSessionStore((s) => s.session)
  const sessionLoading = useRealtimeRunSessionStore((s) => s.loading)
  const sessionError = useRealtimeRunSessionStore((s) => s.error)
  const refreshSession = useRealtimeRunSessionStore((s) => s.refresh)
  const startProject = useRealtimeRunSessionStore((s) => s.startProject)
  const stopSession = useRealtimeRunSessionStore((s) => s.stop)
  const clearSessionError = useRealtimeRunSessionStore((s) => s.clearError)

  const offlineRunning = useGenericSimStore((s) => s.status === 'running')
  const globalBatchRunning = useGenericSimStore((s) => s.globalBatchRunning)

  // 初始默认值（来自工程 runtime 持久化）
  const [cycleTime, setCycleTime] = useState(0.5)
  const [opcUaHost, setOpcUaHost] = useState('0.0.0.0')
  const [opcUaPort, setOpcUaPort] = useState(18951)
  const [error, setError] = useState('')
  const [selectedInstance, setSelectedInstance] = useState<string | null>(null)
  const initOnce = useRef(false)

  // 当工程打开 / runtime 变化时，加载持久化默认值
  useEffect(() => {
    if (initOnce.current) return
    if (currentProject?.runtime) {
      setCycleTime(currentProject.runtime.cycleTime || 0.5)
      setOpcUaHost(currentProject.runtime.opcUaHost || '0.0.0.0')
      setOpcUaPort(currentProject.runtime.opcUaPort || 18951)
    }
  }, [currentProject?.id, currentProject?.runtime])

  useEffect(() => {
    systemApi.getDataFactoryPath().then((p) => {
      if (p) setDfPath(p)
    })
    refreshStatus()
    void refreshSession()
  }, [refreshStatus, setDfPath, refreshSession])

  // generation guard + runtime token bootstrap
  useEffect(() => {
    const rtStore = useRuntimeStore.getState()
    const myGen = ++useRealtimeRunSessionStore.getState().bootstrapGen
    const mySessionId = session?.sessionId ?? null
    if (dfStatus.running && dfStatus.apiReady && session?.sourceKind === 'project') {
      const host = session.apiHost
      const port = session.apiPort
      void (async () => {
        let info
        try {
          info = await realtimeRuntimeApi.getConnectionInfo()
        } catch (e) {
          if (
            useRealtimeRunSessionStore.getState().bootstrapGen !== myGen ||
            (mySessionId !== null &&
              useRealtimeRunSessionStore.getState().session?.sessionId !== mySessionId) ||
            !useCanvasStore.getState().dfStatus.running
          ) {
            return
          }
          setError(`无法获取运行 token：${String(e)}。请重新启动实时工程。`)
          return
        }
        if (
          useRealtimeRunSessionStore.getState().bootstrapGen !== myGen ||
          (mySessionId !== null &&
            useRealtimeRunSessionStore.getState().session?.sessionId !== mySessionId) ||
          !useCanvasStore.getState().dfStatus.running
        ) {
          return
        }
        if (!info.apiToken) {
          setError('运行 token 为空，连接被拒绝。请重新启动实时工程。')
          return
        }
        if (!info.apiHost || !info.apiPort) {
          setError('运行 host/port 缺失，连接被拒绝。请重新启动实时工程。')
          return
        }
        rtStore.setEndpoint(info.apiHost, info.apiPort, info.apiToken)
        void rtStore.connect()
      })()
    } else if (!dfStatus.running) {
      rtStore.disconnect()
    }
    return () => {
      useRealtimeRunSessionStore.setState((s) => ({ bootstrapGen: s.bootstrapGen + 1 }))
    }
  }, [dfStatus.running, dfStatus.apiReady, session?.sessionId, session?.sourceKind])

  const status = useMemo(() => {
    if (sessionError || error) return '运行异常'
    if (!dfStatus.running && !session) return '未运行'
    if (dfStatus.running && session?.state === 'running') return '运行中'
    if (session?.state === 'starting') return '启动中'
    if (session?.state === 'stopping') return '停止中'
    if (session?.state === 'stop-failed') return '运行异常'
    return '运行异常'
  }, [dfStatus.running, session?.state, session, sessionError, error])

  const handleStart = async () => {
    setError('')
    const latestDf = useCanvasStore.getState().dfStatus
    if (offlineRunning || globalBatchRunning || backendBatchBusy(latestDf)) {
      setError('离线批量任务正在运行，禁止启动实时运行')
      return
    }
    if (!currentProject || !currentProjectFile) {
      setError('请先打开一个实时工程')
      return
    }
    if (instances.length === 0) {
      setError('工程没有可运行的实例')
      return
    }
    const ok = await startProject(currentProject.id, {
      cycleTime,
      opcUaHost,
      opcUaPort,
      apiHost: '127.0.0.1',
      apiPort: 8000,
      runtimeName: currentProject.name,
    })
    if (ok) {
      refreshStatus()
      initOnce.current = true
    }
  }

  const handleStop = async () => {
    setError('')
    await stopSession()
    refreshStatus()
    clearSessionError()
  }

  // 未打开工程 → 占位提示
  if (!currentProject) {
    return (
      <div className="flex flex-1 items-center justify-center bg-background p-6 text-sm text-muted-foreground" data-testid="realtime-run-no-project">
        请先在「工程组态」打开或新建工程，再回到「实时运行」启动服务。
      </div>
    )
  }

  const isRunning = Boolean(dfStatus.running && session)
  const inputsDisabled = isRunning

  return (
    <div className="flex flex-1 overflow-hidden bg-background" data-testid="realtime-run-page">
      {/* 左侧运行控制 */}
      <aside className="flex w-72 shrink-0 flex-col gap-3 border-r border-border p-4" data-testid="runtime-control-panel">
        <h3 className="text-sm font-medium">运行控制</h3>
        <label className="space-y-1 text-xs">
          <span className="text-muted-foreground">控制周期 (秒)</span>
          <input
            type="number"
            min={0.01}
            step={0.1}
            value={cycleTime}
            disabled={inputsDisabled}
            onChange={(e) => setCycleTime(Number(e.target.value))}
            className="block w-full rounded-md border border-border bg-card px-3 py-1.5 disabled:opacity-50"
            data-testid="runtime-control-cycle"
          />
        </label>
        <label className="space-y-1 text-xs">
          <span className="text-muted-foreground">UA 地址</span>
          <input
            value={opcUaHost}
            disabled={inputsDisabled}
            onChange={(e) => setOpcUaHost(e.target.value)}
            className="block w-full rounded-md border border-border bg-card px-3 py-1.5 disabled:opacity-50"
            data-testid="runtime-control-opc-host"
          />
        </label>
        <label className="space-y-1 text-xs">
          <span className="text-muted-foreground">UA 端口</span>
          <input
            type="number"
            value={opcUaPort}
            disabled={inputsDisabled}
            onChange={(e) => setOpcUaPort(Number(e.target.value))}
            className="block w-full rounded-md border border-border bg-card px-3 py-1.5 disabled:opacity-50"
            data-testid="runtime-control-opc-port"
          />
        </label>
        <div className="rounded-md border border-border bg-card px-3 py-2 text-xs" data-testid="runtime-control-status">
          <div className="text-muted-foreground">服务状态</div>
          <div className="mt-1 text-sm font-medium">{status}</div>
          {dfStatus.running ? <div className="text-xs text-muted-foreground">PID: {dfStatus.pid}</div> : null}
        </div>
        <div className="mt-auto flex flex-col gap-2">
          {isRunning ? (
            <button
              type="button"
              onClick={() => void handleStop()}
              disabled={sessionLoading}
              className="rounded-md bg-destructive px-4 py-2 text-sm text-destructive-foreground disabled:opacity-40"
              data-testid="runtime-control-stop"
            >
              停止
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void handleStart()}
              disabled={sessionLoading || offlineRunning || globalBatchRunning}
              className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-40"
              data-testid="runtime-control-start"
            >
              启动
            </button>
          )}
          {error || sessionError ? (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 px-2 py-1.5 text-xs text-destructive" data-testid="runtime-control-error">
              {error || sessionError}
            </div>
          ) : null}
        </div>
      </aside>

      {/* 右侧：实例列表 / 实例详情 */}
      <main className="flex min-w-0 flex-1 flex-col p-4" data-testid="runtime-instance-area">
        {selectedInstance ? (
          <RuntimeInstanceDetail
            instanceName={selectedInstance}
            onBack={() => setSelectedInstance(null)}
          />
        ) : (
          <RuntimeInstanceTable
            instances={instances}
            sources={currentProject.sources}
            onSelect={(name) => setSelectedInstance(name)}
          />
        )}
      </main>
    </div>
  )
}