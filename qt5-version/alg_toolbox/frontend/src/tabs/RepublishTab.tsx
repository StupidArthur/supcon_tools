import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Console } from "@/components/Console"
import { api } from "@/lib/api"

interface AlgoInfo {
  name: string
  id: number
  cpuGpu: string
  cores: number
  replicas: number
}

export function RepublishTab() {
  const [algos, setAlgos] = useState<AlgoInfo[]>([])
  const [running, setRunning] = useState(false)
  const [fetched, setFetched] = useState(false)

  useEffect(() => {
    const off = api.onDone("republish", () => setRunning(false))
    return off
  }, [])

  const handleView = async () => {
    const result = await api.getPublishedAlgorithms()
    if (result.error) {
      alert("获取失败: " + result.error)
      return
    }
    const list: AlgoInfo[] = (result.algos || []).map((a: any) => ({
      name: a.zhName || a.name || "",
      id: a.id,
      cpuGpu: a.resourceType === 2 ? "GPU" : "CPU",
      cores: a.cores || 1,
      replicas: a.numReplicas || 1,
    }))
    setAlgos(list)
    setFetched(true)
  }

  const handleExec = async () => {
    if (algos.length === 0) return
    setRunning(true)
    const result = await api.startRepublish()
    if (result.error) {
      setRunning(false)
      alert("启动失败: " + result.error)
    }
  }

  return (
    <div className="flex flex-col h-full gap-3">
      <div className="flex gap-2">
        <Button variant="secondary" onClick={handleView} disabled={running}>
          查看已发布算法
        </Button>
        <Button
          variant="destructive"
          onClick={handleExec}
          disabled={running || algos.length === 0}
        >
          {running ? "执行中..." : "执行发布流程"}
        </Button>
        {fetched && (
          <span className="text-sm text-muted-foreground self-center">
            共 {algos.length} 个已发布算法
          </span>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-auto rounded-md border border-border bg-white p-3">
        <Label className="mb-2 block">已发布算法列表</Label>
        {algos.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {fetched ? "无已发布的算法" : "点击「查看已发布算法」获取列表"}
          </p>
        ) : (
          <div className="space-y-1">
            {algos.map((a, i) => (
              <div key={i} className="text-xs font-mono text-gray-700 py-0.5">
                {a.name}  |  id={a.id}  |  {a.cpuGpu}  |  核数={a.cores}  |  副本={a.replicas}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex-1 flex flex-col min-h-0">
        <Label className="mb-1">操作日志</Label>
        <Console channel="republish" className="flex-1" />
      </div>
    </div>
  )
}
