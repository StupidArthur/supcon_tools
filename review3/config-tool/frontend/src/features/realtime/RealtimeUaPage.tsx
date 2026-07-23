/**
 * 实时运行与 UA：仅已保存 DSL + 周期/UA 端口。
 * DSL 路径唯一来源：useDslProjectStore.filePath（不保留独立 dslPath）。
 */
import { useEffect, useRef, useState } from 'react'
import { systemApi } from '../../lib/api'
import { useCanvasStore } from '../../store/useCanvasStore'
import { useDslProjectStore } from '../dsl/useDslProjectStore'
import { useGenericSimStore } from '../dsl/useGenericSimStore'

export function RealtimeUaPage() {
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

  const offlineRunning = useGenericSimStore((s) => s.status === 'running')
  const globalBatchRunning = useGenericSimStore((s) => s.globalBatchRunning)

  const [cycleTime, setCycleTime] = useState(0.5)
  const [port, setPort] = useState(18951)
  const [apiHost, setApiHost] = useState('127.0.0.1')
  const [apiPort, setApiPort] = useState(8000)
  const [showAdvancedPorts, setShowAdvancedPorts] = useState(false)
  const [error, setError] = useState('')
  const logEndRef = useRef<HTMLDivElement>(null)

  const isDirty = yamlDirty
  const canStart =
    Boolean(filePath) && !isDirty && !offlineRunning && !globalBatchRunning && !dfStatus.running

  useEffect(() => {
    systemApi.getDataFactoryPath().then((p) => {
      if (p) setDfPath(p)
    })
    refreshStatus()
  }, [refreshStatus, setDfPath])

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [dfLogs])

  const openDsl = async () => {
    const path = await systemApi.openYAMLFile()
    if (!path) return
    try {
      const text = await systemApi.readTextFile(path)
      // Sync into project store only — no parallel long-lived path.
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
    if (offlineRunning || globalBatchRunning) {
      setError('离线批量任务进行中，禁止启动实时运行')
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
    try {
      const p = await systemApi.getDataFactoryPath()
      if (p) setDfPath(p)
      await systemApi.start({
        configPath: filePath,
        mode: 'REALTIME',
        cycleTime,
        port,
        apiHost,
        apiPort,
        runtimeName: 'default',
        enableOpcUa: true,
      })
      refreshStatus()
    } catch (e: any) {
      setError(String(e))
    }
  }

  const handleStop = async () => {
    setError('')
    try {
      await systemApi.stop()
      refreshStatus()
    } catch (e: any) {
      setError(String(e))
    }
  }

  return (
    <div className="flex-1 overflow-y-auto bg-background p-6" data-testid="realtime-ua-page">
      <div className="mx-auto max-w-2xl space-y-5">
        <div>
          <h2 className="text-lg font-medium">实时运行与 UA</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            基于已保存 DSL 启动实时实例并提供 OPC UA Server。与 DSL 离线仿真互斥。
          </p>
        </div>

        <section className="space-y-2 rounded-md border border-border bg-card p-3">
          <div className="text-xs font-medium">当前 DSL</div>
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
          {offlineRunning || globalBatchRunning ? (
            <div className="rounded-md bg-amber-50 px-2 py-1.5 text-xs text-amber-900">
              离线批量任务进行中，禁止启动实时运行。
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

        {error ? (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        ) : null}

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
