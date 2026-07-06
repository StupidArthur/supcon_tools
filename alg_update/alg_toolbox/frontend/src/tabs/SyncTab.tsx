import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Checkbox } from "@/components/ui/checkbox"
import { Console } from "@/components/Console"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { api } from "@/lib/api"

export function SyncTab() {
  const [dir, setDir] = useState("resource")
  const [skipEdit, setSkipEdit] = useState(false)
  const [running, setRunning] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)

  useEffect(() => {
    const off = api.onDone("sync", () => setRunning(false))
    return off
  }, [])

  const handleBrowse = async () => {
    const path = await api.pickDirectory()
    if (path) setDir(path)
  }

  const handleStart = async () => {
    if (!dir) return
    setRunning(true)
    const result = await api.startSync(dir, skipEdit)
    if (result.error) {
      setRunning(false)
      return
    }
  }

  const handleExport = async () => {
    const path = await api.saveCSVFile("alg_info_export.csv")
    if (!path) return
    const result = await api.exportAlgorithms(path)
    if (result.success) {
      alert(`导出成功: ${result.count} 个算法`)
    } else {
      alert("导出失败: " + result.error)
    }
  }

  return (
    <div className="flex flex-col h-full gap-3">
      <div className="rounded-lg border border-border bg-white p-4 space-y-3">
        <div className="flex items-end gap-2">
          <div className="flex-1 space-y-1">
            <Label>算法目录</Label>
            <Input value={dir} onChange={(e) => setDir(e.target.value)} placeholder="resource" />
          </div>
          <Button variant="outline" onClick={handleBrowse}>浏览</Button>
        </div>
        <div className="flex items-center gap-2">
          <Checkbox
            id="skip-edit"
            checked={skipEdit}
            onCheckedChange={(v) => setSkipEdit(v === true)}
          />
          <Label htmlFor="skip-edit" className="cursor-pointer">
            跳过编辑（仅上传文件，不调用编辑接口）
          </Label>
        </div>
        <div className="flex gap-2">
          <Button
            variant="destructive"
            onClick={handleStart}
            disabled={running}
          >
            {running ? "执行中..." : "开始更新"}
          </Button>
          <Button variant="secondary" onClick={handleExport}>
            导出算法信息
          </Button>
        </div>
      </div>
      <div className="flex-1 flex flex-col min-h-0">
        <Label className="mb-1">控制台输出</Label>
        <Console channel="sync" className="flex-1" />
      </div>
    </div>
  )
}
