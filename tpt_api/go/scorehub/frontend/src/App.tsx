import { useState, useEffect, useCallback } from "react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { TeamInfoTab } from "@/components/TeamInfoTab"
import { RankingTab } from "@/components/RankingTab"
import { BatchTab } from "@/components/BatchTab"
import { PersonalTab } from "@/components/PersonalTab"
import { MonitorTab } from "@/components/MonitorTab"
import { ToastProvider, useToast } from "@/components/Toast"
import { teamApi, rankingApi, batchApi, personalApi, type Team, type RankingItem, type EvalConfig, type PersonalRow } from "@/lib/api"

function AppContent() {
  const [teams, setTeams] = useState<Team[]>([])
  const [rankingItems, setRankingItems] = useState<RankingItem[]>([])
  const [batchConfig, setBatchConfig] = useState<EvalConfig | null>(null)
  const [personalRows, setPersonalRows] = useState<PersonalRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rankingError, setRankingError] = useState<string | null>(null)
  const [batchError, setBatchError] = useState<string | null>(null)
  const [personalError, setPersonalError] = useState<string | null>(null)
  const toast = useToast()

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    setRankingError(null)
    setBatchError(null)
    setPersonalError(null)
    const [teamRes, rankRes, batchRes, personalRes] = await Promise.allSettled([
      teamApi.list(),
      rankingApi.fetch(),
      batchApi.getEvalConfig(),
      personalApi.list(),
    ])
    if (teamRes.status === "fulfilled") {
      setTeams(teamRes.value || [])
    } else {
      const msg = teamRes.reason?.message || String(teamRes.reason)
      setError(msg)
      toast("加载队伍信息失败", "error")
    }
    if (rankRes.status === "fulfilled") {
      setRankingItems(rankRes.value || [])
    } else {
      setRankingError(rankRes.reason?.message || String(rankRes.reason))
    }
    if (batchRes.status === "fulfilled") {
      setBatchConfig(batchRes.value)
    } else {
      setBatchError(batchRes.reason?.message || String(batchRes.reason))
    }
    if (personalRes.status === "fulfilled") {
      setPersonalRows(personalRes.value || [])
    } else {
      setPersonalError(personalRes.reason?.message || String(personalRes.reason))
    }
    setLoading(false)
  }, [toast])

  useEffect(() => {
    load()
  }, [load])

  // 切到排名 / 个性化管理时自动刷新一次。
  const handleTabChange = (value: string) => {
    if (value === "ranking" || value === "personal") {
      load()
    }
  }

  return (
    <div className="flex flex-col h-screen">
      <Tabs defaultValue="team" onValueChange={handleTabChange} className="flex flex-col flex-1 min-h-0">
        <header className="flex items-center gap-4 px-7 pt-5">
          <div className="w-9 h-9 rounded-lg bg-primary flex items-center justify-center shadow-sm flex-shrink-0">
            <span className="text-primary-foreground text-[15px] font-bold leading-none">S</span>
          </div>
          <div className="min-w-0">
            <h1 className="text-[15px] font-semibold leading-tight">SUPCON CUP 2026 运维</h1>
            <p className="text-[11.5px] text-muted-foreground leading-tight mt-0.5">决赛队伍与租户管理 · 评分控制台</p>
          </div>
          <div className="ml-4 flex-1 min-w-0">
            <TabsList>
              <TabsTrigger value="team">1. 队伍信息</TabsTrigger>
              <TabsTrigger value="ranking">2. 排名</TabsTrigger>
              <TabsTrigger value="batch">3. 批量管理</TabsTrigger>
              <TabsTrigger value="personal">4. 个性化管理</TabsTrigger>
              <TabsTrigger value="monitor">5. 数据源监控</TabsTrigger>
            </TabsList>
          </div>
          <span className="text-[11px] text-muted-foreground/70 flex-shrink-0">v0.4 designed by @yuzechao</span>
        </header>

        <TabsContent value="team" className="flex-1 overflow-hidden mt-0">
          <TeamInfoTab teams={teams} loading={loading} error={error} />
        </TabsContent>
        <TabsContent value="ranking" className="flex-1 overflow-hidden mt-0">
          <RankingTab items={rankingItems} loading={loading} error={rankingError} onReload={load} />
        </TabsContent>
        <TabsContent value="batch" className="flex-1 overflow-hidden mt-0">
          <BatchTab config={batchConfig} loading={loading} error={batchError} onReload={load} />
        </TabsContent>
        <TabsContent value="personal" className="flex-1 overflow-hidden mt-0">
          <PersonalTab rows={personalRows} loading={loading} error={personalError} onReload={load} />
        </TabsContent>
        <TabsContent value="monitor" className="flex-1 overflow-hidden mt-0">
          <MonitorTab />
        </TabsContent>
      </Tabs>
      <footer className="h-7 border-t border-border bg-muted/30 px-4 text-[11.5px] text-muted-foreground flex items-center gap-2">
        <span className="w-1.5 h-1.5 rounded-full bg-primary" />
        就绪
      </footer>
    </div>
  )
}

function App() {
  return (
    <ToastProvider>
      <AppContent />
    </ToastProvider>
  )
}

export default App
