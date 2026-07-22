/**
 * DSL 工程壳：首页 / 工作区
 */
import { DslHomePage } from './DslHomePage'
import { DslWorkspace } from './DslWorkspace'
import { useDslProjectStore } from './useDslProjectStore'

export function DslShell() {
  const phase = useDslProjectStore((s) => s.phase)
  return (
    <div className="flex h-full min-h-0 w-full flex-1 flex-col overflow-hidden">
      {phase === 'workspace' ? <DslWorkspace /> : <DslHomePage />}
    </div>
  )
}
