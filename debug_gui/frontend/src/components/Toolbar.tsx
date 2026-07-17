import { useState } from 'react'
import { useStore } from '../store/useStore'
import { debugApi } from '../lib/api'
import type { RunMode } from '../types'

export function Toolbar() {
  const {
    workDir, pythonPath, configPath, configs, runMode,
    cycles, cycleTime, opcPort,
    running, batchRunning,
    setWorkDir, setPythonPath, setConfigPath, setRunMode,
    setCycles, setCycleTime, setOpcPort,
    refreshConfigs, loadYAMLConfig,
    setRunning, setBatchRunning, setBatchResult,
    addLog,
  } = useStore()

  const [error, setError] = useState('')

  const handleBrowseDir = async () => {
    const path = await debugApi.browseDir('选择 DataFactory 工作目录（含 standalone_main.py 的目录）')
    if (path) {
      setWorkDir(path)
      await refreshConfigs()
    }
  }

  const handleBrowseExe = async () => {
    const path = await debugApi.browseExe()
    if (path) setPythonPath(path)
  }

  const handleBrowseYAML = async () => {
    const path = await debugApi.browseYAML()
    if (path) {
      setConfigPath(path)
      await loadYAMLConfig(path)
    }
  }

  const handleConfigSelect = async (name: string) => {
    if (!workDir) return
    const sep = workDir.includes('\\') ? '\\' : '/'
    const full = `${workDir}${sep}config${sep}${name}`
    setConfigPath(full)
    await loadYAMLConfig(full)
  }

  const handleRun = async () => {
    setError('')
    if (!workDir) { setError('请先选择工作目录'); return }
    if (!configPath) { setError('请先选择配置文件'); return }

    try {
      if (runMode === 'batch') {
        setBatchRunning(true)
        setBatchResult(null)
        addLog('system', `开始批量仿真: ${cycles} 周期`)
        const csvPath = await debugApi.startBatch({
          workDir, pythonPath, configPath, cycles, cycleTime,
        })
        addLog('system', `CSV 临时文件: ${csvPath}`)
      } else {
        setRunning(true)
        addLog('system', `启动实时引擎: 端口 ${opcPort}`)
        await debugApi.startEngine({
          workDir, pythonPath, configPath,
          mode: 'REALTIME', cycleTime, port: opcPort,
        })
      }
    } catch (e: any) {
      setError(String(e))
      setRunning(false)
      setBatchRunning(false)
    }
  }

  const handleStop = async () => {
    setError('')
    try {
      await debugApi.stopEngine()
      setRunning(false)
      setBatchRunning(false)
    } catch (e: any) {
      setError(String(e))
    }
  }

  const handleExport = async () => {
    setError('')
    if (!workDir || !configPath) { setError('请先选择工作目录和配置文件'); return }
    try {
      const exportPath = await debugApi.saveCSVFile()
      if (!exportPath) return
      addLog('system', `导出 CSV: ${exportPath}`)
      await debugApi.exportBatch({
        workDir, pythonPath, configPath, cycles, cycleTime,
      }, exportPath)
      addLog('system', '导出完成')
    } catch (e: any) {
      setError(String(e))
    }
  }

  const isRunning = running || batchRunning

  return (
    <div className="flex flex-wrap items-end gap-3 border-b border-border bg-card px-4 py-2">
      {/* 工作目录 */}
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">工作目录 (review3)</label>
        <div className="flex gap-1">
          <input
            type="text"
            value={workDir}
            readOnly
            placeholder="未设置"
            className="w-56 rounded-md border border-border bg-background px-2 py-1 text-xs"
          />
          <button
            onClick={handleBrowseDir}
            className="rounded-md border border-border bg-card px-2 py-1 text-xs hover:bg-secondary"
          >
            浏览
          </button>
        </div>
      </div>

      {/* Python 路径（可选） */}
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Python 路径（可选）</label>
        <div className="flex gap-1">
          <input
            type="text"
            value={pythonPath}
            readOnly
            placeholder="从 PATH 查找"
            className="w-40 rounded-md border border-border bg-background px-2 py-1 text-xs"
          />
          <button
            onClick={handleBrowseExe}
            className="rounded-md border border-border bg-card px-2 py-1 text-xs hover:bg-secondary"
          >
            浏览
          </button>
        </div>
      </div>

      {/* Config 选择 */}
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">配置文件</label>
        <div className="flex gap-1">
          <select
            value={configPath.split(/[\\/]/).pop() || ''}
            onChange={(e) => handleConfigSelect(e.target.value)}
            className="w-44 rounded-md border border-border bg-background px-2 py-1 text-xs"
          >
            {configs.length === 0 && <option value="">（无）</option>}
            {configs.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <button
            onClick={refreshConfigs}
            className="rounded-md border border-border bg-card px-2 py-1 text-xs hover:bg-secondary"
          >
            刷新
          </button>
          <button
            onClick={handleBrowseYAML}
            className="rounded-md border border-border bg-card px-2 py-1 text-xs hover:bg-secondary"
          >
            打开
          </button>
        </div>
      </div>

      {/* 模式切换 */}
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">模式</label>
        <div className="flex gap-2">
          {(['batch', 'realtime'] as RunMode[]).map((m) => (
            <label
              key={m}
              className={`flex cursor-pointer items-center gap-1 rounded border px-2 py-1 text-xs ${
                runMode === m
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border text-muted-foreground'
              }`}
            >
              <input
                type="radio"
                checked={runMode === m}
                onChange={() => setRunMode(m)}
                className="hidden"
              />
              {m === 'batch' ? '批量仿真' : '实时+OPC UA'}
            </label>
          ))}
        </div>
      </div>

      {/* 周期数 / 端口 */}
      {runMode === 'batch' ? (
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">周期数</label>
          <input
            type="number"
            value={cycles}
            min={1}
            onChange={(e) => setCycles(Number(e.target.value))}
            className="w-24 rounded-md border border-border bg-background px-2 py-1 text-xs"
          />
        </div>
      ) : (
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">OPC UA 端口</label>
          <input
            type="number"
            value={opcPort}
            min={1}
            max={65535}
            onChange={(e) => setOpcPort(Number(e.target.value))}
            className="w-24 rounded-md border border-border bg-background px-2 py-1 text-xs"
          />
        </div>
      )}

      {/* CycleTime */}
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">周期 (秒)</label>
        <input
          type="number"
          value={cycleTime}
          step={0.1}
          min={0.01}
          onChange={(e) => setCycleTime(Number(e.target.value))}
          className="w-20 rounded-md border border-border bg-background px-2 py-1 text-xs"
        />
      </div>

      {/* 运行/停止 */}
      <div className="flex gap-2">
        {isRunning ? (
          <button
            onClick={handleStop}
            className="rounded-md bg-destructive px-4 py-1 text-xs font-medium text-destructive-foreground hover:opacity-80"
          >
            停止
          </button>
        ) : (
          <button
            onClick={handleRun}
            className="rounded-md bg-primary px-4 py-1 text-xs font-medium text-primary-foreground hover:opacity-80"
          >
            {runMode === 'batch' ? '运行仿真' : '启动引擎'}
          </button>
        )}
        <button
          onClick={handleExport}
          disabled={isRunning}
          className="rounded-md border border-border bg-card px-3 py-1 text-xs hover:bg-secondary disabled:opacity-40"
        >
          导出 CSV
        </button>
      </div>

      {error && (
        <div className="ml-auto rounded-md border border-destructive/30 bg-destructive/5 px-3 py-1 text-xs text-destructive">
          {error}
        </div>
      )}
    </div>
  )
}
