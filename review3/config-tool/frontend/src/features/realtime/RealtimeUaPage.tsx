/**
 * 实时运行与 UA：组态 + 运行 两个子 Tab。
 */
import { useState } from 'react'
import { RealtimeTabs } from './RealtimeTabs'
import { RealtimeConfigPage } from './RealtimeConfigPage'
import { RealtimeRunPage } from './RealtimeRunPage'

export function RealtimeUaPage() {
  const [tab, setTab] = useState<'config' | 'run'>('config')

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="realtime-ua-page">
      <RealtimeTabs value={tab} onChange={setTab} />
      <div className="min-h-0 flex-1">
        {tab === 'config' ? <RealtimeConfigPage /> : <RealtimeRunPage />}
      </div>
    </div>
  )
}
