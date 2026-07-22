/**
 * DSL 工程壳：首页 / 工作区
 */
import { DslHomePage } from './DslHomePage'
import { DslWorkspace } from './DslWorkspace'
import { useDslProjectStore } from './useDslProjectStore'

export function DslShell() {
  const phase = useDslProjectStore((s) => s.phase)
  if (phase === 'workspace') {
    return <DslWorkspace />
  }
  return <DslHomePage />
}
