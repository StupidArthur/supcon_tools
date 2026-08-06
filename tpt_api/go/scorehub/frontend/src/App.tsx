import { useState, useEffect, useCallback } from "react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { TeamInfoTab } from "@/components/TeamInfoTab"
import { EmptyState } from "@/components/EmptyState"
import { ToastProvider, useToast } from "@/components/Toast"
import { teamApi, type Team } from "@/lib/api"

function AppContent() {
  const [teams, setTeams] = useState<Team[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  const loadTeams = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await teamApi.list()
      setTeams(data || [])
    } catch (err: any) {
      const msg = err?.message || String(err)
      setError(msg)
      toast("加载队伍信息失败", "error")
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => {
    loadTeams()
  }, [loadTeams])

  return (
    <div className="flex flex-col h-screen">
      <Tabs defaultValue="team" className="flex flex-col flex-1">
        <div className="border-b border-border px-7 pt-2">
          <TabsList>
            <TabsTrigger value="team">1. 队伍信息</TabsTrigger>
            <TabsTrigger value="ranking">2. 排名</TabsTrigger>
            <TabsTrigger value="control">3. 详细控制</TabsTrigger>
          </TabsList>
        </div>
        <TabsContent value="team" className="flex-1 overflow-hidden mt-0">
          <TeamInfoTab teams={teams} loading={loading} error={error} />
        </TabsContent>
        <TabsContent value="ranking" className="flex-1 mt-0">
          <EmptyState icon="◆" title="排名" desc="待实现" />
        </TabsContent>
        <TabsContent value="control" className="flex-1 mt-0">
          <EmptyState icon="◆" title="详细控制" desc="待实现" />
        </TabsContent>
      </Tabs>
      <footer className="h-6 border-t border-border bg-muted/30 px-3 text-[11.5px] text-muted-foreground flex items-center">
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
