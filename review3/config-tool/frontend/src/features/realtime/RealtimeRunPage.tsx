import { useEffect, useMemo, useRef, useState } from 'react'
import { realtimeProjectApi, realtimeRuntimeApi } from '../../lib/api'
import { backendBatchBusy, useCanvasStore } from '../../store/useCanvasStore'
import { useGenericSimStore } from '../dsl/useGenericSimStore'
import { useRuntimeStore } from '../runtime/useRuntimeStore'
import { useRealtimeProjectStore } from './useRealtimeProjectStore'
import { useRealtimeRunSessionStore } from './useRealtimeRunSessionStore'
import { RuntimeInstanceTable } from './RuntimeInstanceTable'
import { RuntimeInstanceDetail } from './RuntimeInstanceDetail'

/**
 * 实时运行页（todo.md §9）：
 * - 运行参数（控制周期 / UA 地址 / UA 端口）来自工程组态持久化的 runtime 默认值。
 * - 整页主体交给实例列表 / 实例详情（位号表）。
 * - 顶部保留状态条 + 启停按钮（启动运行 / 停止运行）。
 * - 不再请求 / 缓存 DataFactory.exe 路径；服务由 Config Tool 自行管理。
 * - 不再硬编码 API 端口 8000；服务端口由 Go 端在 /api/realtime/connection 中返回。
 */
export function RealtimeRunPage() {
  const dfStatus = useCanvasStore((s) => s.dfStatus)
  const refreshStatus = useCanvasStore((s) => s.refreshStatus)

  const currentProject = useRealtimeProjectStore((s) => s.currentProject)
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

  const [error, setError] = useState('')
  const [selectedInstance, setSelectedInstance] = useState<string | null>(null)
  const initOnce = useRef(false)

  // 工程组态里持久化的运行时默认参数（页面不再编辑）。
  // 旧工程可能没有 runtime 字段，回退到与 Go 端一致的默认值（0.5s / 0.0.0.0 / 18951）。
  const runtimeDefaults = currentProject?.runtime ?? {
    cycleTime: 0.5,
    opcUaHost: '0.0.0.0',
    opcUaPort: 18951,
  }

  useEffect(() => {
    refreshStatus()
    void refreshSession()
  }, [refreshStatus, refreshSession])

  // generation guard + runtime token bootstrap
  useEffect(() => {
    const rtStore = useRuntimeStore.getState()
    const myGen = ++useRealtimeRunSessionStore.getState().bootstrapGen
    const mySessionId = session?.sessionId ?? null
    if (dfStatus.running && dfStatus.apiReady && session?.sourceKind === 'project') {
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
    if (!currentProject) {
      setError('请先打开一个实时工程')
      return
    }
    if (instances.length === 0) {
      setError('工程没有可运行的实例')
      return
    }
    if (!runtimeDefaults) {
      setError('工程组态中尚未配置运行时默认参数（控制周期 / UA 地址 / UA 端口）')
      return
    }
    const ok = await startProject(currentProject.id, {
      cycleTime: runtimeDefaults.cycleTime,
      opcUaHost: runtimeDefaults.opcUaHost,
      opcUaPort: runtimeDefaults.opcUaPort,
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

  if (!currentProject) {
    return (
      <div className="flex flex-1 items-center justify-center bg-background p-6 text-sm text-muted-foreground" data-testid="realtime-run-no-project">
        请先在「工程组态」打开或新建工程，再回到「实时运行」启动运行。
      </div>
    )
  }

  const isRunning = Boolean(dfStatus.running && session)

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-background" data-testid="realtime-run-page">
      {/* 顶部状态条：状态 + 启停（运行参数统一在「工程组态」维护） */}
      <header
        className="flex shrink-0 items-center gap-3 border-b border-border bg-card px-4 py-2 text-xs"
        data-testid="runtime-status-bar"
      >
        <span className="text-muted-foreground">运行状态</span>
        <span className="rounded bg-secondary px-2 py-0.5 text-xs font-medium" data-testid="runtime-status-value">
          {status}
        </span>
        {dfStatus.running ? (
          <span className="text-xs text-muted-foreground">PID: {dfStatus.pid}</span>
        ) : null}
        {runtimeDefaults ? (
          <span className="ml-2 text-xs text-muted-foreground">
            周期 {runtimeDefaults.cycleTime}s · UA {runtimeDefaults.opcUaHost}:{runtimeDefaults.opcUaPort}
          </span>
        ) : (
          <span className="ml-2 text-xs text-destructive" data-testid="runtime-missing-config">
            工程组态尚未配置运行时参数
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {error || sessionError ? (
            <span
              className="rounded-md border border-destructive/30 bg-destructive/5 px-2 py-0.5 text-xs text-destructive"
              data-testid="runtime-status-error"
            >
              {error || sessionError}
            </span>
          ) : null}
          {isRunning ? (
            <button
              type="button"
              onClick={() => void handleStop()}
              disabled={sessionLoading}
              className="rounded-md bg-destructive px-3 py-1 text-xs text-destructive-foreground disabled:opacity-40"
              data-testid="runtime-control-stop"
            >
              停止运行
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void handleStart()}
              disabled={sessionLoading || offlineRunning || globalBatchRunning || !runtimeDefaults}
              className="rounded-md bg-primary px-3 py-1 text-xs text-primary-foreground disabled:opacity-40"
              data-testid="runtime-control-start"
            >
              启动运行
            </button>
          )}
        </div>
      </header>

      {/* 主体：实例列表 / 实例详情 */}
      <main className="flex min-h-0 flex-1 flex-col p-4" data-testid="runtime-instance-area">
        {selectedInstance ? (
          <RuntimeInstanceDetail
            instanceName={selectedInstance}
            onBack={() => setSelectedInstance(null)}
          />
        ) : (
          <RuntimeInstanceTable
            instances={instances}
            sources={currentProject.sources || []}
            onSelect={(name) => setSelectedInstance(name)}
          />
        )}
      </main>
    </div>
  )
}