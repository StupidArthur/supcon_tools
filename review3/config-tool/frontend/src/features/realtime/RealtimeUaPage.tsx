/**
 * 实时运行与 UA：组态 + 运行 + 画面 三个子 Tab。
 */
import { useState } from 'react'
import { RealtimeTabs, type RealtimeTab } from './RealtimeTabs'
import { RealtimeConfigPage } from './RealtimeConfigPage'
import { RealtimeRunPage } from './RealtimeRunPage'
import { DashboardPage } from './DashboardPage'
import { useRealtimeProjectStore } from './useRealtimeProjectStore'

export function RealtimeUaPage() {
  const [tab, setTab] = useState<RealtimeTab>('config')
  const currentProject = useRealtimeProjectStore((s) => s.currentProject)

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="realtime-ua-page">
      <RealtimeTabs value={tab} onChange={setTab} />
      <div className="min-h-0 flex-1">
        {tab === 'config' ? (
          <RealtimeConfigPage />
        ) : tab === 'run' ? (
          <RealtimeRunPage />
        ) : currentProject ? (
          <DashboardPage projectId={currentProject.id} />
        ) : (
          <div className="p-6 text-center text-sm text-muted-foreground">请先在组态页打开一个实时工程。</div>
        )}
      </div>
    </div>
  )
}
