import { useStore } from '../store/useStore'

export function StatusBar() {
  const { running, batchRunning, runMode, engineStatus, batchResult, cycles } = useStore()

  const isRunning = running || batchRunning

  return (
    <div className="flex items-center gap-4 border-t border-border bg-card px-4 py-1.5 text-xs">
      {/* 运行状态灯 */}
      <div className="flex items-center gap-1.5">
        <span className={isRunning ? 'text-green-600' : 'text-muted-foreground'}>
          {isRunning ? '●' : '○'}
        </span>
        <span className={isRunning ? 'text-foreground' : 'text-muted-foreground'}>
          {isRunning ? '运行中' : '已停止'}
        </span>
      </div>

      <span className="text-muted-foreground">|</span>

      {/* 模式 */}
      <span className="text-muted-foreground">
        模式: <span className="text-foreground">
          {runMode === 'batch' ? '批量仿真' : '实时+OPC UA'}
        </span>
      </span>

      {/* 批量模式进度 */}
      {batchRunning && (
        <>
          <span className="text-muted-foreground">|</span>
          <span className="text-muted-foreground">
            周期: <span className="text-foreground">{cycles}</span>
          </span>
        </>
      )}

      {/* 批量结果 */}
      {batchResult && !batchRunning && (
        <>
          <span className="text-muted-foreground">|</span>
          <span className="text-muted-foreground">
            结果: <span className="text-foreground">
              {batchResult.rows.length} 行 × {batchResult.columns.length - 1} 列
            </span>
          </span>
        </>
      )}

      {/* 实时模式引擎状态 */}
      {engineStatus?.running && (
        <>
          <span className="text-muted-foreground">|</span>
          <span className="text-muted-foreground">
            PID: <span className="text-foreground">{engineStatus.pid}</span>
          </span>
          <span className="text-muted-foreground">|</span>
          <span className="text-muted-foreground">
            端口: <span className="text-foreground">{engineStatus.port}</span>
          </span>
        </>
      )}

      {/* 右侧水印 */}
      <div className="ml-auto text-muted-foreground/60">
        DataFactory 调试工具
      </div>
    </div>
  )
}
