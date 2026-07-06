import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"

interface ConnectionPanelProps {
  onConnected: (count: number) => void
}

export function ConnectionPanel({ onConnected }: ConnectionPanelProps) {
  const [url, setUrl] = useState("http://10.16.11.1:31501")
  const [username, setUsername] = useState("admin")
  const [password, setPassword] = useState("")
  const [tenantID, setTenantID] = useState("")
  const [connecting, setConnecting] = useState(false)
  const [status, setStatus] = useState<"idle" | "ok" | "fail">("idle")
  const [statusText, setStatusText] = useState("未连接")

  const isHTTPS = url.startsWith("https://")

  const handleConnect = async () => {
    if (!url || !username || !password) {
      setStatus("fail")
      setStatusText("请填写完整的连接信息")
      return
    }
    setConnecting(true)
    setStatus("idle")
    setStatusText("连接中...")
    try {
      const result = await api.connect(url, username, password, tenantID)
      if (result.success) {
        setStatus("ok")
        setStatusText(`已连接，缓存 ${result.count} 个算法`)
        onConnected(result.count)
      } else {
        setStatus("fail")
        setStatusText("连接失败: " + result.error)
      }
    } catch (e: any) {
      setStatus("fail")
      setStatusText("连接失败: " + String(e))
    } finally {
      setConnecting(false)
    }
  }

  return (
    <div className="rounded-lg border border-border bg-white p-4 space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label>URL</Label>
          <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://或https://" />
        </div>
        <div className="space-y-1">
          <Label>Username</Label>
          <Input value={username} onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label>Password</Label>
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        {isHTTPS && (
          <div className="space-y-1">
            <Label>Tenant ID</Label>
            <Input value={tenantID} onChange={(e) => setTenantID(e.target.value)} placeholder="HTTPS模式租户ID" />
          </div>
        )}
      </div>
      <div className="flex items-center gap-3">
        <Button onClick={handleConnect} disabled={connecting}>
          {connecting ? "连接中..." : "连接"}
        </Button>
        <span
          className={cn(
            "text-sm font-medium",
            status === "ok" && "text-green-600",
            status === "fail" && "text-red-600",
            status === "idle" && "text-yellow-600"
          )}
        >
          {statusText}
        </span>
      </div>
    </div>
  )
}
