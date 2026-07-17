import { useState, useEffect, useRef } from 'react'
import { useCanvasStore } from '../store/useCanvasStore'
import { systemApi } from '../lib/api'

export function SystemPanel() {
  const dfPath = useCanvasStore((s) => s.dfPath)
  const setDfPath = useCanvasStore((s) => s.setDfPath)
  const configs = useCanvasStore((s) => s.configs)
  const refreshConfigs = useCanvasStore((s) => s.refreshConfigs)
  const dfStatus = useCanvasStore((s) => s.dfStatus)
  const dfLogs = useCanvasStore((s) => s.dfLogs)
  const refreshStatus = useCanvasStore((s) => s.refreshStatus)

  const [selectedConfig, setSelectedConfig] = useState('')
  const [mode, setMode] = useState('REALTIME')
  const [cycleTime, setCycleTime] = useState(0.5)
  const [port, setPort] = useState(18951)
  const [error, setError] = useState('')
  const logEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    systemApi.getDataFactoryPath().then((p) => {
      setDfPath(p || '')
      if (p) refreshConfigs()
    })
    refreshStatus()
  }, [])

  useEffect(() => {
    if (configs.length > 0 && !selectedConfig) {
      setSelectedConfig(configs[0])
    }
  }, [configs])

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [dfLogs])

  const handleBrowse = async () => {
    const path = await systemApi.browseExe()
    setDfPath(path || '')
    if (path) refreshConfigs()
  }

  const handleStart = async () => {
    setError('')
    if (!dfPath) { setError('请先选择 DataFactory.exe'); return }
    if (!selectedConfig) { setError('请选择配置文件'); return }
    try {
      await systemApi.start({
        configPath: selectedConfig,
        mode,
        cycleTime,
        port,
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
    <div className="flex-1 overflow-y-auto bg-background p-6">
      <div className="mx-auto max-w-2xl space-y-5">
        <h2 className="text-lg font-medium">系统管理</h2>

        {/* DataFactory Path */}
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">DataFactory 路径</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={dfPath}
              readOnly
              placeholder="未设置，请选择 DataFactory.exe"
              className="flex-1 rounded-md border border-border bg-card px-3 py-1.5 text-xs"
            />
            <button
              onClick={handleBrowse}
              className="rounded-md border border-border bg-card px-3 py-1.5 text-xs hover:bg-secondary"
            >
              浏览
            </button>
          </div>
        </div>

        {/* Config Selection */}
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">配置文件</label>
          <div className="flex gap-2">
            <select
              value={selectedConfig}
              onChange={(e) => setSelectedConfig(e.target.value)}
              className="flex-1 rounded-md border border-border bg-card px-3 py-1.5 text-xs"
            >
              {configs.length === 0 && <option value="">（无可用配置）</option>}
              {configs.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            <button
              onClick={refreshConfigs}
              className="rounded-md border border-border bg-card px-3 py-1.5 text-xs hover:bg-secondary"
            >
              刷新
            </button>
          </div>
        </div>

        {/* Parameters */}
        <div className="flex gap-4">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">模式</label>
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              className="rounded-md border border-border bg-card px-3 py-1.5 text-xs"
            >
              <option value="REALTIME">REALTIME</option>
              <option value="GENERATOR">GENERATOR</option>
            </select>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">周期 (秒)</label>
            <input
              type="number"
              value={cycleTime}
              step={0.1}
              min={0.01}
              onChange={(e) => setCycleTime(Number(e.target.value))}
              className="w-24 rounded-md border border-border bg-card px-3 py-1.5 text-xs"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">端口</label>
            <input
              type="number"
              value={port}
              onChange={(e) => setPort(Number(e.target.value))}
              className="w-24 rounded-md border border-border bg-card px-3 py-1.5 text-xs"
            />
          </div>
        </div>

        {/* Control + Status */}
        <div className="flex items-center gap-4">
          {dfStatus.running ? (
            <button
              onClick={handleStop}
              className="rounded-md bg-destructive px-4 py-1.5 text-xs text-destructive-foreground hover:opacity-80"
            >
              停止
            </button>
          ) : (
            <button
              onClick={handleStart}
              className="rounded-md bg-primary px-4 py-1.5 text-xs text-primary-foreground hover:opacity-80"
            >
              启动
            </button>
          )}
          <div className="flex items-center gap-1.5 text-xs">
            <span className={dfStatus.running ? 'text-green-600' : 'text-muted-foreground'}>
              {dfStatus.running ? '●' : '○'}
            </span>
            <span>
              {dfStatus.running
                ? `运行中 (PID: ${dfStatus.pid})`
                : '已停止'}
            </span>
          </div>
        </div>

        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        )}

        {/* Logs */}
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <label className="text-xs text-muted-foreground">日志输出</label>
            <button
              onClick={() => useCanvasStore.getState().clearDfLogs?.()}
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
                <div key={i} className="whitespace-pre-wrap break-all">{log}</div>
              ))
            )}
            <div ref={logEndRef} />
          </div>
        </div>
      </div>
    </div>
  )
}
