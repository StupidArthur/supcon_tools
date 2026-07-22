/**
 * 拓扑与诊断：只读 program 列表 / 连接关系（不恢复高级组态拖拽）。
 */
import { useEffect, useState } from 'react'
import { configApi, systemApi } from '../../lib/api'
import { useTemplateStore } from '../templates/useTemplateStore'
import { useDslProjectStore } from './useDslProjectStore'

type TopologyRow = {
  name: string
  type: string
  executeFirst?: boolean
  inputs?: Record<string, string>
}

export function TopologyDiagnosticsPanel() {
  const projectKind = useDslProjectStore((s) => s.projectKind)
  const filePath = useDslProjectStore((s) => s.filePath)
  const yamlText = useDslProjectStore((s) => s.yamlText)
  const definition = useTemplateStore((s) => s.definition)
  const validationErrors = useTemplateStore((s) => s.validationErrors)
  const validationWarnings = useTemplateStore((s) => s.validationWarnings)

  const [rows, setRows] = useState<TopologyRow[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      setLoadError(null)
      if (projectKind === 'template' && definition?.programs?.length) {
        if (!cancelled) {
          setRows(
            definition.programs.map((p) => ({
              name: p.name,
              type: p.type,
              executeFirst: p.executeFirst,
              inputs: p.inputs,
            })),
          )
        }
        return
      }
      if (!filePath) {
        setRows([])
        return
      }
      try {
        // Prefer canvas import for generic YAML topology.
        const canvas = await configApi.importYAML(filePath)
        if (cancelled) return
        const nodes = (canvas as any)?.nodes || []
        const mapped: TopologyRow[] = nodes.map((n: any) => ({
          name: n?.data?.name || n?.id || '?',
          type: n?.data?.type || n?.type || '?',
          executeFirst: Boolean(n?.data?.executeFirst),
          inputs: n?.data?.inputs || {},
        }))
        setRows(mapped)
      } catch (err) {
        if (!cancelled) {
          setLoadError(String(err))
          setRows([])
        }
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [projectKind, definition, filePath, yamlText])

  return (
    <div className="flex h-full min-h-0 flex-col overflow-auto p-4" data-testid="topology-diagnostics">
      <h2 className="mb-2 text-sm font-medium">拓扑与诊断</h2>
      <p className="mb-3 text-xs text-muted-foreground">只读视图，不提供拖拽组态。</p>

      {loadError ? (
        <div className="mb-3 text-xs text-destructive">{loadError}</div>
      ) : null}

      <div className="mb-4 space-y-1">
        <div className="text-xs font-medium">校验</div>
        {validationErrors.length === 0 && validationWarnings.length === 0 ? (
          <div className="text-xs text-muted-foreground">无错误 / 无警告</div>
        ) : null}
        {validationErrors.map((e, i) => (
          <div key={`e-${i}`} className="text-xs text-destructive">
            [{e.path}] {e.message}
          </div>
        ))}
        {validationWarnings.map((w, i) => (
          <div key={`w-${i}`} className="text-xs text-amber-700">
            [{w.path}] {w.message}
          </div>
        ))}
      </div>

      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="border-b border-border text-left text-muted-foreground">
            <th className="py-1 pr-2">name</th>
            <th className="py-1 pr-2">type</th>
            <th className="py-1 pr-2">execute_first</th>
            <th className="py-1">inputs</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name} className="border-b border-border/60 align-top">
              <td className="py-1 pr-2 font-medium">{r.name}</td>
              <td className="py-1 pr-2">{r.type}</td>
              <td className="py-1 pr-2">{r.executeFirst ? 'true' : ''}</td>
              <td className="py-1 font-mono text-[11px]">
                {r.inputs
                  ? Object.entries(r.inputs)
                      .map(([k, v]) => `${k}=${v}`)
                      .join(', ')
                  : ''}
              </td>
            </tr>
          ))}
          {rows.length === 0 ? (
            <tr>
              <td colSpan={4} className="py-3 text-muted-foreground">
                无可显示的 program 列表
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>

      {!filePath && projectKind === 'generic' ? (
        <button
          type="button"
          className="mt-4 self-start rounded-md border border-border px-3 py-1.5 text-xs"
          onClick={async () => {
            const path = await systemApi.openYAMLFile()
            if (path) useDslProjectStore.getState().openWorkspace({ filePath: path })
          }}
        >
          打开 DSL 文件以查看拓扑
        </button>
      ) : null}
    </div>
  )
}
