import { useEffect, useRef, useState } from 'react'
import { realtimeRuntimeApi, systemApi } from '../../lib/api'
import { backendBatchBusy, useCanvasStore } from '../../store/useCanvasStore'
import { useDslProjectStore } from '../dsl/useDslProjectStore'
import { useGenericSimStore } from '../dsl/useGenericSimStore'
import { useRuntimeStore } from '../runtime/useRuntimeStore'
import { useRealtimeProjectStore } from './useRealtimeProjectStore'
import { useRealtimeRunSessionStore } from './useRealtimeRunSessionStore'
import { RuntimeTagTable } from './RuntimeTagTable'
import { GenericTrendPanel } from '../runtime/GenericTrendPanel'
import { AlarmPanel } from './AlarmPanel'
import { RunHistoryPanel } from './RunHistoryPanel'

export function RealtimeRunPage() {
  const dfStatus = useCanvasStore((s) => s.dfStatus)
  const dfLogs = useCanvasStore((s) => s.dfLogs)
  const refreshStatus = useCanvasStore((s) => s.refreshStatus)
  const setDfPath = useCanvasStore((s) => s.setDfPath)

  const filePath = useDslProjectStore((s) => s.filePath)
  const projectName = useDslProjectStore((s) => s.projectName)
  const yamlDirty = useDslProjectStore((s) => s.yamlDirty)
  const openWorkspace = useDslProjectStore((s) => s.openWorkspace)
  const pushRecent = useDslProjectStore((s) => s.pushRecent)
  const setYamlText = useDslProjectStore((s) => s.setYamlText)

  const currentProject = useRealtimeProjectStore((s) => s.currentProject)

  const session = useRealtimeRunSessionStore((s) => s.session)
  const sessionLoading = useRealtimeRunSessionStore((s) => s.loading)
  const sessionError = useRealtimeRunSessionStore((s) => s.error)
  const refreshSession = useRealtimeRunSessionStore((s) => s.refresh)
  const startProject = useRealtimeRunSessionStore((s) => s.startProject)
  const startSingleYaml = useRealtimeRunSessionStore((s) => s.startSingleYaml)
  const stopSession = useRealtimeRunSessionStore((s) => s.stop)

  const offlineRunning = useGenericSimStore((s) => s.status === 'running')
  const globalBatchRunning = useGenericSimStore((s) => s.globalBatchRunning)

  const [cycleTime, setCycleTime] = useState(0.5)
  const [port, setPort] = useState(18951)
  const [apiHost, setApiHost] = useState('127.0.0.1')
  const [apiPort, setApiPort] = useState(8000)
  const [showAdvancedPorts, setShowAdvancedPorts] = useState(false)
  const [error, setError] = useState('')
  const [currentRevision, setCurrentRevision] = useState<string | null>(null)
  const logEndRef = useRef<HTMLDivElement>(null)

  const isDirty = yamlDirty
  const batchBusy = globalBatchRunning || backendBatchBusy(dfStatus)
  const canStart =
    Boolean(filePath) && !isDirty && !offlineRunning && !batchBusy && !dfStatus.running

  useEffect(() => {
    systemApi.getDataFactoryPath().then((p) => {
      if (p) setDfPath(p)
    })
    refreshStatus()
    void refreshSession()
  }, [refreshStatus, setDfPath, refreshSession])

  useEffect(() => {
    if (!currentProject) {
      setCurrentRevision(null)
      return
    }
    realtimeRuntimeApi
      .getProjectRevision(currentProject.id)
      .then((r) => setCurrentRevision(r))
      .catch(() => setCurrentRevision(null))
  }, [currentProject])

  useEffect(() => {
    if (!batchBusy) return
    const id = setInterval(() => refreshStatus(), 1000)
    return () => clearInterval(id)
  }, [batchBusy, refreshStatus])

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [dfLogs])

  useEffect(() => {
    const rtStore = useRuntimeStore.getState()
    if (dfStatus.running && dfStatus.apiReady) {
      const host = session?.apiHost || apiHost
      const port = session?.apiPort || apiPort
      // 自动从 Go 侧获取本次运行的 connection info（host / port / runtimeName / token）。
      // 仅在内存使用，绝不写入持久化。
      void (async () => {
        try {
          const info = await realtimeRuntimeApi.getConnectionInfo()
          if (info.apiToken) {
            rtStore.setEndpoint(info.apiHost || host, info.apiPort || port, info.apiToken)
          } else {
            // 进程已运行但 token 暂时拿不到（极端时序），等下一次 dfStatus 变化再试。
            rtStore.setEndpoint(info.apiHost || host, info.apiPort || port)
          }
        } catch {
          rtStore.setEndpoint(host, port)
        }
        void rtStore.connect()
      })()
    } else if (!dfStatus.running) {
      rtStore.disconnect()
    }
  }, [dfStatus.running, dfStatus.apiReady, apiHost, apiPort, session])

  const openDsl = async () => {
    const path = await systemApi.openYAMLFile()
    if (!path) return
    try {
      const text = await systemApi.readTextFile(path)
      openWorkspace({
        filePath: path,
        projectKind: 'generic',
        projectName: path.replace(/^.*[\\/]/, ''),
        editorTab: 'yaml',
        simTab: 'run',
      })
      setYamlText(text, false)
      pushRecent(path)
      setError('')
    } catch (err) {
      setError('打开失败: ' + String(err))
    }
  }

  const handleStart = async () => {
    setError('')
    const latestDf = useCanvasStore.getState().dfStatus
    if (offlineRunning || globalBatchRunning || backendBatchBusy(latestDf)) {
      setError('离线批量任务正在运行，禁止启动实时运行')
      return
    }
    if (!filePath) {
      setError('请先打开已保存的 DSL 文件')
      return
    }
    if (isDirty) {
      setError('实时运行使用已保存的 DSL，请先保存。')
      return
    }
    const p = await systemApi.getDataFactoryPath()
    if (p) setDfPath(p)
    const ok = await startSingleYaml(filePath, {
      cycleTime,
      opcUaPort: port,
      apiHost,
      apiPort,
      runtimeName: 'default',
    })
    if (ok) refreshStatus()
  }

  const handleStop = async () => {
    setError('')
    await stopSession()
    refreshStatus()
  }

  const handleStartProject = async () => {
    if (!currentProject) return
    setError('')
    const latestDf = useCanvasStore.getState().dfStatus
    if (offlineRunning || globalBatchRunning || backendBatchBusy(latestDf)) {
      setError('离线批量任务正在运行，禁止启动实时运行')
      return
    }
    const p = await systemApi.getDataFactoryPath()
    if (p) setDfPath(p)
    const ok = await startProject(currentProject.id, {
      cycleTime,
      opcUaPort: port,
      apiHost,
      apiPort,
      runtimeName: currentProject.name,
    })
    if (ok) refreshStatus()
  }

  return (
    <div className="flex-1 overflow-y-auto bg-background p-6" data-testid="realtime-run-page">
      <div className="mx-auto max-w-2xl space-y-5">
        <div>
          <h2 className="text-lg font-medium">实时运行</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            基于实时工程或已保存 DSL 启动实时实例并提供 OPC UA Server。与 DSL 离线仿真互斥。
          </p>
        </div>

        {session ? (
          <section className="space-y-1 rounded-md border border-green-300 bg-green-50 p-3" data-testid="realtime-session-card">
            <div className="text-xs font-medium">
              正在运行：{session.sourceKind === 'project' ? session.projectName : session.sourcePath}
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
              <span>来源：{session.sourceKind === 'project' ? '实时工程' : '单 YAML'}</span>
              <span>运行版本：{session.runtimeRevision || '—'}</span>
              <span>配置哈希：{session.configHash ? session.configHash.slice(0, 8) : '—'}</span>
              <span>启动时间：{session.startedAt || '—'}</span>
              <span>周期：{session.cycleTime} 秒</span>
              <span>OPC UA：{session.opcUaPort}</span>
              <span>REST/WS：{session.apiHost}:{session.apiPort}</span>
            </div>
          </section>
        ) : null}

        {session && session.sourceKind === 'project' && currentProject &&
          currentProject.id === session.projectId &&
          currentRevision && currentRevision !== session.runtimeRevision ? (
          <div className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900" data-testid="realtime-config-changed">
            当前工程组态已修改。正在运行的仍是启动时版本，停止并重新启动后生效。
          </div>
        ) : null}

        {currentProject ? (
          <section className="space-y-2 rounded-md border border-primary/30 bg-primary/5 p-3" data-testid="realtime-project-run">
            <div className="text-xs font-medium">实时工程</div>
            <div className="text-xs">
              {currentProject.name}
              <span className="ml-2 text-muted-foreground">
                {currentProject.sources.length} 个 YAML
              </span>
            </div>
            {!dfStatus.running ? (
              <button
                type="button"
                onClick={() => void handleStartProject()}
                disabled={offlineRunning || batchBusy}
                className="rounded-md bg-primary px-4 py-1.5 text-xs text-primary-foreground disabled:opacity-40"
                data-testid="realtime-start-project"
              >
                启动工程
              </button>
            ) : null}
          </section>
        ) : null}

        <section className="space-y-2 rounded-md border border-border bg-card p-3">
          <div className="text-xs font-medium">单 YAML 运行（旧入口）</div>
          {filePath ? (
            <div className="truncate text-xs" title={filePath} data-testid="realtime-dsl-path">
              {projectName || filePath}
              <div className="text-muted-foreground">{filePath}</div>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => void openDsl()}
              className="rounded-md border border-border px-3 py-1.5 text-xs hover:bg-secondary"
              data-testid="realtime-open-dsl"
            >
              打开 DSL 文件
            </button>
          )}
          {filePath ? (
            <button
              type="button"
              onClick={() => void openDsl()}
              className="text-xs text-muted-foreground underline"
            >
              更换文件
            </button>
          ) : null}
          {!filePath ? (
            <div className="text-xs text-muted-foreground">没有已保存文件，无法启动实时运行。</div>
          ) : null}
          {isDirty ? (
            <div className="rounded-md bg-amber-50 px-2 py-1.5 text-xs text-amber-900" data-testid="realtime-unsaved-warn">
              实时运行使用已保存的 DSL，请先保存。
            </div>
          ) : null}
          {offlineRunning || batchBusy ? (
            <div className="rounded-md bg-amber-50 px-2 py-1.5 text-xs text-amber-900">
              离线批量任务正在运行，禁止启动实时运行。
            </div>
          ) : null}
        </section>

        <section className="flex flex-wrap gap-4">
          <label className="space-y-1 text-xs">
            <span className="text-muted-foreground">控制周期 (秒)</span>
            <input
              type="number"
              value={cycleTime}
              step={0.1}
              min={0.01}
              onChange={(e) => setCycleTime(Number(e.target.value))}
              className="block w-28 rounded-md border border-border bg-card px-3 py-1.5"
              data-testid="realtime-cycle-time"
            />
          </label>
          <label className="space-y-1 text-xs">
            <span className="text-muted-foreground">OPC UA 端口</span>
            <input
              type="number"
              value={port}
              onChange={(e) => setPort(Number(e.target.value))}
              className="block w-28 rounded-md border border-border bg-card px-3 py-1.5"
              data-testid="realtime-ua-port"
            />
          </label>
        </section>

        <div>
          <button
            type="button"
            className="text-xs text-muted-foreground underline"
            onClick={() => setShowAdvancedPorts((v) => !v)}
          >
            {showAdvancedPorts ? '收起高级端口配置' : '高级端口配置'}
          </button>
          {showAdvancedPorts ? (
            <div className="mt-2 flex gap-4">
              <label className="space-y-1 text-xs">
                <span className="text-muted-foreground">REST Host</span>
                <input
                  value={apiHost}
                  onChange={(e) => setApiHost(e.target.value)}
                  className="block w-36 rounded-md border border-border bg-card px-3 py-1.5"
                />
              </label>
              <label className="space-y-1 text-xs">
                <span className="text-muted-foreground">REST/WS 端口</span>
                <input
                  type="number"
                  value={apiPort}
                  onChange={(e) => setApiPort(Number(e.target.value))}
                  className="block w-28 rounded-md border border-border bg-card px-3 py-1.5"
                />
              </label>
            </div>
          ) : null}
        </div>

        <div className="flex items-center gap-4">
          {dfStatus.running ? (
            <button
              type="button"
              onClick={() => void handleStop()}
              className="rounded-md bg-destructive px-4 py-1.5 text-xs text-destructive-foreground"
              data-testid="realtime-stop"
            >
              停止
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void handleStart()}
              disabled={!canStart}
              className="rounded-md bg-primary px-4 py-1.5 text-xs text-primary-foreground disabled:opacity-40"
              data-testid="realtime-start"
            >
              启动实时运行
            </button>
          )}
          <div className="text-xs" data-testid="realtime-status">
            {dfStatus.running ? `运行中 (PID: ${dfStatus.pid})` : '已停止'}
            {dfStatus.running && dfStatus.port ? ` · UA :${dfStatus.port}` : ''}
          </div>
        </div>

        {(error || sessionError) ? (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error || sessionError}
          </div>
        ) : null}

        {sessionLoading ? (
          <div className="text-xs text-muted-foreground">处理中...</div>
        ) : null}

        <RuntimeTagTable />

        <GenericTrendPanel projectId={currentProject?.id} />

        <AlarmPanel />

        <RunHistoryPanel />

        <section className="space-y-1">
          <div className="flex items-center justify-between">
            <label className="text-xs text-muted-foreground">日志输出</label>
            <button
              type="button"
              onClick={() => useCanvasStore.getState().clearDfLogs()}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              清空
            </button>
          </div>
          <div className="h-64 overflow-y-auto rounded-md border border-border bg-card p-3 font-mono text-xs">
            {dfLogs.length === 0 ? (
              <div className="text-muted-foreground">暂无日志</div>
            ) : (
              dfLogs.map((log, i) => (
                <div key={i} className="whitespace-pre-wrap break-all">
                  {log}
                </div>
              ))
            )}
            <div ref={logEndRef} />
          </div>
        </section>
      </div>
    </div>
  )
}
