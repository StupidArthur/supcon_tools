import { useState, useRef } from 'react'
import { useTemplateStore } from './useTemplateStore'
import type { TemplateRuntimeState } from './types'
import { systemApi, templateApi } from '../../lib/api'
import { useCanvasStore } from '../../store/useCanvasStore'
import { useRuntimeStore } from '../runtime/useRuntimeStore'

// RuntimeToolbar 是模板工作区顶部的工具栏。
// 包含模板名称、状态、保存、仿真等操作按钮。
export function RuntimeToolbar() {
  const templateId = useTemplateStore((s) => s.templateId)
  const definition = useTemplateStore((s) => s.definition)
  const sourcePath = useTemplateStore((s) => s.sourcePath)
  const dirtyPaths = useTemplateStore((s) => s.dirtyPaths)
  const runtimeState = useTemplateStore((s) => s.runtimeState)
  const validationErrors = useTemplateStore((s) => s.validationErrors)
  const save = useTemplateStore((s) => s.save)
  const reset = useTemplateStore((s) => s.reset)
  const setRuntimeState = useTemplateStore((s) => s.setRuntimeState)
  const setRunningIdentity = useTemplateStore((s) => s.setRunningIdentity)
  const setView = useCanvasStore((s) => s.setView)

  // 阶段 4：runtime 状态接入
  const runtimeConnectionState = useRuntimeStore((s) => s.connectionState)
  const runtimeStale = useRuntimeStore((s) => s.stale)
  const runtimeName = useRuntimeStore((s) => s.runtimeName)
  const runtimeApiHost = useRuntimeStore((s) => s.apiHost)
  const runtimeApiPort = useRuntimeStore((s) => s.apiPort)
  const runtimeConnect = useRuntimeStore((s) => s.connect)
  const runtimeDisconnect = useRuntimeStore((s) => s.disconnect)
  const rotatePreviousRun = useRuntimeStore((s) => s.rotatePreviousRun)

  const [startError, setStartError] = useState<string | null>(null)
  // operation token：Stop 开始时递增，使正在等待的 Start 操作失效
  const operationIdRef = useRef(0)

  const hasErrors = validationErrors.length > 0
  const isDirty = dirtyPaths.size > 0
  const isRunning = runtimeState === 'SIMULATION_RUNNING' || runtimeState === 'REALTIME_RUNNING'
  const isStarting = runtimeState === 'STARTING'
  const isStopping = runtimeState === 'STOPPING'

  // 阶段 3 只支持 second_order_tank
  if (templateId !== 'second_order_tank' || !definition) {
    return null
  }

  const handleSaveAs = async (): Promise<boolean> => {
    if (hasErrors) return false
    try {
      const targetPath = await systemApi.saveYAMLFile()
      if (!targetPath) return false // 用户取消
      await save({ targetPath, allowOverwrite: true })
      return true
    } catch (err) {
      console.error('另存为失败:', err)
      return false
    }
  }

  const handleSave = async (): Promise<boolean> => {
    if (hasErrors) return false
    try {
      if (sourcePath && await templateApi.isBuiltin(sourcePath)) {
        return await handleSaveAs()
      }
      await save()
      return true
    } catch (err) {
      console.error('保存失败:', err)
      return false
    }
  }

  const handleStartSimulation = async () => {
    setStartError(null)

    // 如果有未保存的修改，先保存
    if (isDirty) {
      const saved = await handleSave()
      if (!saved) {
        return
      }
    }

    // 保存后重新读取最新的 store 值
    const storeState = useTemplateStore.getState()
    const currentSourcePath = storeState.sourcePath
    const currentCycleTime = storeState.draft?.cycleTime

    if (!currentSourcePath) {
      setStartError('没有可启动的配置文件')
      return
    }

    // 捕获当前 operation id
    const myOperationId = ++operationIdRef.current

    setRuntimeState('STARTING')

    try {
      // 新一次运行：归档上一轮趋势，避免普通 rerender 清空。
      rotatePreviousRun()

      // 后端 Start 会同步等待 API ready
      await systemApi.start({
        configPath: currentSourcePath,
        mode: 'REALTIME',
        cycleTime: currentCycleTime || 0.5,
        port: 18951,
        apiHost: '127.0.0.1',
        apiPort: 8000,
        runtimeName: 'second_order_tank',
        enableOpcUa: true,
      })

      // 检查 operation 是否仍有效
      if (myOperationId !== operationIdRef.current) {
        // Stop 已开始，不再更新状态
        return
      }

      // 从后端获取真实的运行状态
      const status = await systemApi.status()

      // 再次检查 operation 是否仍有效
      if (myOperationId !== operationIdRef.current) {
        return
      }

      // 验证 status 必须包含必要字段
      if (!status.running || !status.apiReady || !status.configPath || !status.configHash || !status.startedAt) {
        throw new Error('后端状态不完整')
      }

      // 记录运行配置标识（完全来自后端 status）
      setRunningIdentity({
        path: status.configPath,
        contentHash: status.configHash,
        startedAt: status.startedAt,
      })

      // 阶段 4：连接 WebSocket（runtime store 会先 GET /api/status，再用真实 runtimeName 连 WS）。
      try {
        await runtimeConnect()
      } catch (wsErr) {
        console.warn('runtime connect failed:', wsErr)
      }

      setRuntimeState('SIMULATION_RUNNING')
    } catch (err: any) {
      // 检查 operation 是否仍有效
      if (myOperationId !== operationIdRef.current) {
        return
      }
      const errorMsg = err?.message || String(err)
      console.error('启动仿真失败:', errorMsg)
      setStartError(errorMsg)
      setRuntimeState('ERROR')
      setRunningIdentity(null)
    }
  }

  const handleStop = async (): Promise<boolean> => {
    if (isStopping) return false

    // 递增 operation id，使正在等待的 Start 操作失效
    operationIdRef.current++

    setRuntimeState('STOPPING')
    try {
      // 阶段 4：先断 WS 再停进程（避免停进程时还连着 WS 触发重连）
      runtimeDisconnect()
      await systemApi.stop()
      setRuntimeState('STOPPED_EDITING')
      setRunningIdentity(null)
      return true
    } catch (err: any) {
      const errorMsg = err?.message || String(err)
      console.error('停止失败:', errorMsg)
      setStartError(errorMsg)
      setRuntimeState('ERROR')
      return false
    }
  }

  const handleBack = async () => {
    if (isDirty) {
      if (!confirm('有未保存的修改，确定要离开吗？')) return
    }
    if (isStarting || isRunning) {
      if (!confirm('仿真正在运行，确定要停止并离开吗？')) return
      const stopped = await handleStop()
      if (!stopped) {
        return
      }
    }
    // 阶段 4：确保 WS / 定时器 / 重连任务在离开页面时关闭
    runtimeDisconnect()
    reset()
    setView('system')
  }

  return (
    <header
      className="flex items-center gap-3 border-b border-border bg-card px-4 py-2"
      data-testid="runtime-toolbar"
    >
      {/* 返回按钮 */}
      <button
        onClick={handleBack}
        className="rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
        data-testid="back-button"
      >
        ← 返回
      </button>

      {/* 模板名称 */}
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">{definition.displayName}</span>
        {sourcePath && (
          <span className="text-xs text-muted-foreground truncate max-w-[200px]" title={sourcePath}>
            {sourcePath}
          </span>
        )}
      </div>

      {/* Dirty 标记 */}
      {isDirty && (
        <span
          className="rounded-md bg-amber-100 px-2 py-0.5 text-xs text-amber-900"
          data-testid="dirty-badge"
        >
          未保存 {dirtyPaths.size} 处
        </span>
      )}

      {/* 状态指示 */}
      <StatusBadge state={runtimeState} />

      {/* 阶段 4：runtime 连接状态 */}
      {(isRunning || isStarting) && (
        <ConnectionBadge
          connectionState={runtimeConnectionState}
          stale={runtimeStale}
          runtimeName={runtimeName}
          apiHost={runtimeApiHost}
          apiPort={runtimeApiPort}
        />
      )}

      {/* 错误信息 */}
      {startError && (
        <span
          className="rounded-md bg-red-100 px-2 py-0.5 text-xs text-red-900 truncate max-w-[300px]"
          title={startError}
          data-testid="start-error"
        >
          {startError}
        </span>
      )}

      {/* 占位 */}
      <div className="flex-1" />

      {/* 保存按钮 */}
      <button
        onClick={handleSave}
        disabled={!isDirty || hasErrors || isRunning || isStarting || isStopping}
        className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
          isDirty && !hasErrors && !isRunning && !isStarting && !isStopping
            ? 'bg-primary text-primary-foreground hover:bg-primary/90'
            : 'bg-secondary text-muted-foreground cursor-not-allowed'
        }`}
        data-testid="save-button"
      >
        保存
      </button>

      {/* 另存为按钮 */}
      <button
        onClick={handleSaveAs}
        disabled={hasErrors || isRunning || isStarting || isStopping}
        className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
          hasErrors || isRunning || isStarting || isStopping
            ? 'bg-secondary text-muted-foreground cursor-not-allowed'
            : 'bg-secondary text-foreground hover:bg-secondary/80'
        }`}
        data-testid="save-as-button"
      >
        另存为
      </button>

      {/* 启动仿真按钮 */}
      {!isRunning && !isStarting && !isStopping && (
        <button
          onClick={handleStartSimulation}
          disabled={hasErrors || !sourcePath}
          className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
            hasErrors || !sourcePath
              ? 'bg-secondary text-muted-foreground cursor-not-allowed'
              : 'bg-green-600 text-white hover:bg-green-700'
          }`}
          data-testid="start-button"
        >
          启动仿真
        </button>
      )}

      {/* 停止按钮 */}
      {(isRunning || isStarting) && (
        <button
          onClick={handleStop}
          disabled={isStopping}
          className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
            isStopping
              ? 'bg-gray-400 text-white cursor-not-allowed'
              : 'bg-red-600 text-white hover:bg-red-700'
          }`}
          data-testid="stop-button"
        >
          {isStopping ? '停止中...' : '停止'}
        </button>
      )}

      {/* 高级 DSL 视图入口 */}
      <button
        onClick={() => setView('config')}
        className="rounded-md px-3 py-1.5 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
        data-testid="advanced-view-button"
      >
        高级视图
      </button>
    </header>
  )
}

// 状态徽章组件
function StatusBadge({ state }: { state: TemplateRuntimeState }) {
  const config: Record<TemplateRuntimeState, { label: string; className: string }> = {
    STOPPED_EDITING: {
      label: '组态预览',
      className: 'bg-secondary text-muted-foreground',
    },
    STARTING: {
      label: '启动中...',
      className: 'bg-blue-100 text-blue-900',
    },
    SIMULATION_RUNNING: {
      label: '仿真运行中',
      className: 'bg-green-100 text-green-900',
    },
    REALTIME_RUNNING: {
      label: '实时运行中',
      className: 'bg-green-100 text-green-900',
    },
    BATCH_RUNNING: {
      label: '批量运行中',
      className: 'bg-blue-100 text-blue-900',
    },
    STOPPING: {
      label: '停止中...',
      className: 'bg-yellow-100 text-yellow-900',
    },
    ERROR: {
      label: '错误',
      className: 'bg-red-100 text-red-900',
    },
  }

  const { label, className } = config[state]

  return (
    <span
      className={`rounded-md px-2 py-0.5 text-xs ${className}`}
      data-testid="status-badge"
    >
      {label}
    </span>
  )
}

// 阶段 4：runtime 连接状态徽章
function ConnectionBadge({
  connectionState,
  stale,
  runtimeName,
  apiHost,
  apiPort,
}: {
  connectionState: 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error'
  stale: boolean
  runtimeName: string | null
  apiHost: string
  apiPort: number
}) {
  const connLabel: Record<typeof connectionState, string> = {
    idle: '空闲',
    connecting: '连接中',
    connected: '已连接',
    disconnected: '断开',
    error: '错误',
  }
  const baseClass: Record<typeof connectionState, string> = {
    idle: 'bg-secondary text-muted-foreground',
    connecting: 'bg-blue-100 text-blue-900',
    connected: 'bg-green-100 text-green-900',
    disconnected: 'bg-yellow-100 text-yellow-900',
    error: 'bg-red-100 text-red-900',
  }
  const cls = stale
    ? 'bg-red-100 text-red-900'
    : baseClass[connectionState]
  const label = stale ? '数据已过期' : connLabel[connectionState]

  return (
    <span
      className={`flex items-center gap-1 rounded-md px-2 py-0.5 text-xs ${cls}`}
      data-testid="runtime-connection-badge"
      data-connection-state={connectionState}
      data-stale={stale ? 'true' : 'false'}
      title={`runtime=${runtimeName ?? '?'} api=${apiHost}:${apiPort}`}
    >
      <span className="font-medium">{label}</span>
      {runtimeName && (
        <span className="font-mono text-[10px] text-muted-foreground">
          {runtimeName}
        </span>
      )}
    </span>
  )
}
