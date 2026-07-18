import { useState } from 'react'
import { useStore } from '../store/useStore'

export function ConfigEditor() {
  const configPath = useStore((s) => s.configPath)
  const yamlContent = useStore((s) => s.yamlContent)
  const yamlDirty = useStore((s) => s.yamlDirty)
  const setYamlContent = useStore((s) => s.setYamlContent)
  const saveYAMLContent = useStore((s) => s.saveYAMLContent)
  const addLog = useStore((s) => s.addLog)
  const [error, setError] = useState('')

  const handleSave = async () => {
    setError('')
    if (!configPath) {
      setError('未选择配置文件')
      return
    }
    try {
      await saveYAMLContent(configPath, yamlContent)
      addLog('system', `配置已保存: ${configPath}`)
    } catch (e: any) {
      setError(String(e))
    }
  }

  const handleReload = async () => {
    setError('')
    if (!configPath) return
    const { loadYAMLContent } = useStore.getState()
    try {
      await loadYAMLContent(configPath)
      addLog('system', `配置已重新加载: ${configPath}`)
    } catch (e: any) {
      setError(String(e))
    }
  }

  if (!configPath) {
    return (
      <div className="flex h-full items-center justify-center p-4">
        <div className="text-xs text-muted-foreground">请先选择 YAML 配置文件</div>
      </div>
    )
  }

  const fileName = configPath.split(/[\\/]/).pop() || configPath

  return (
    <div className="flex h-full flex-col">
      {/* 顶部工具栏 */}
      <div className="flex items-center justify-between border-b border-border bg-card px-2 py-1.5">
        <div className="flex items-center gap-2 text-xs">
          <span className="font-medium text-foreground">{fileName}</span>
          {yamlDirty && (
            <span className="text-amber-600">● 未保存</span>
          )}
        </div>
        <div className="flex gap-1">
          <button
            onClick={handleReload}
            className="rounded border border-border bg-card px-2 py-0.5 text-xs hover:bg-secondary"
            title="放弃改动，重新从磁盘加载"
          >
            重载
          </button>
          <button
            onClick={handleSave}
            disabled={!yamlDirty}
            className="rounded bg-primary px-2 py-0.5 text-xs text-primary-foreground hover:opacity-80 disabled:opacity-40"
          >
            保存
          </button>
        </div>
      </div>

      {/* 编辑器 */}
      <textarea
        value={yamlContent}
        onChange={(e) => setYamlContent(e.target.value)}
        spellCheck={false}
        className="flex-1 resize-none bg-background p-2 font-mono text-xs leading-relaxed text-foreground outline-none"
        placeholder="YAML 配置内容..."
      />

      {/* 错误提示 */}
      {error && (
        <div className="border-t border-destructive/30 bg-destructive/5 px-2 py-1 text-xs text-destructive">
          {error}
        </div>
      )}
    </div>
  )
}
