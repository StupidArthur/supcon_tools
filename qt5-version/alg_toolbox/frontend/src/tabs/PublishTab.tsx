import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Console } from "@/components/Console"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { api } from "@/lib/api"
import type { main } from "@/lib/api"

export function PublishTab() {
  const [csvPath, setCsvPath] = useState("")
  const [csvCount, setCsvCount] = useState(0)
  const [concurrent, setConcurrent] = useState("3")
  const [running, setRunning] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [compareResult, setCompareResult] = useState<main.CompareResult | null>(null)
  const [csvRecords, setCsvRecords] = useState<main.CSVRecord[]>([])

  useEffect(() => {
    const off = api.onDone("publish", () => setRunning(false))
    return off
  }, [])

  const handleBrowse = async () => {
    const path = await api.pickCSVFile()
    if (!path) return
    setCsvPath(path)
    const result = await api.loadCSVFile(path)
    if (result.error) {
      alert("CSV 加载失败: " + result.error)
      return
    }
    setCsvRecords(result.records)
    setCsvCount(result.count)
  }

  const handlePublish = async () => {
    if (!csvPath || csvRecords.length === 0) {
      alert("请先选择 CSV 文件")
      return
    }
    const conc = parseInt(concurrent) || 3
    const result = await api.compareAlgorithms(csvRecords)
    if (result.error) {
      alert("比对失败: " + result.error)
      return
    }
    setCompareResult(result)
    setShowConfirm(true)
  }

  const handleConfirmPublish = async () => {
    setShowConfirm(false)
    if (!compareResult || compareResult.toRelease.length === 0) return
    setRunning(true)
    const conc = parseInt(concurrent) || 3
    const result = await api.startPublish(compareResult.toRelease, conc)
    if (result.error) {
      setRunning(false)
      alert("启动发布失败: " + result.error)
    }
  }

  return (
    <div className="flex flex-col h-full gap-3">
      <div className="rounded-lg border border-border bg-white p-4 space-y-3">
        <div className="flex items-end gap-2">
          <div className="flex-1 space-y-1">
            <Label>CSV 文件</Label>
            <Input
              value={csvPath}
              onChange={(e) => setCsvPath(e.target.value)}
              placeholder="选择 publish_list_*.csv"
              readOnly
            />
          </div>
          <Button variant="outline" onClick={handleBrowse}>浏览</Button>
        </div>
        {csvCount > 0 && (
          <p className="text-sm text-muted-foreground">已加载 {csvCount} 条记录</p>
        )}
        <div className="flex items-end gap-4">
          <div className="w-32 space-y-1">
            <Label>并发数</Label>
            <Input
              type="number"
              value={concurrent}
              onChange={(e) => setConcurrent(e.target.value)}
            />
          </div>
          <Button
            onClick={handlePublish}
            disabled={running}
          >
            {running ? "执行中..." : "开始发布"}
          </Button>
        </div>
      </div>
      <div className="flex-1 flex flex-col min-h-0">
        <Label className="mb-1">发布日志</Label>
        <Console channel="publish" className="flex-1" />
      </div>

      <Dialog open={showConfirm} onOpenChange={setShowConfirm}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-auto">
          <DialogHeader>
            <DialogTitle>确认发布</DialogTitle>
          </DialogHeader>
          {compareResult && (
            <div className="space-y-3 text-sm">
              <div>
                <p className="font-medium mb-1">已发现差异:</p>
                <pre className={`text-xs whitespace-pre-wrap ${compareResult.differences.length > 0 ? "text-red-600" : "text-green-600"}`}>
                  {compareResult.differences.length > 0 ? compareResult.differences.join("\n") : "  无"}
                </pre>
              </div>
              <div className="border-t pt-2">
                <p>已发布 (无需操作): {compareResult.alreadyReleased.length} 个</p>
                <p className="font-medium text-green-600">待发布: {compareResult.toRelease.length} 个</p>
                <p className="text-red-600">CSV设否但平台已发布: {compareResult.shouldNotRelease.length} 个</p>
                <p className="text-orange-600">CSV有但平台没有: {compareResult.notInPlatform.length} 个</p>
              </div>
              {compareResult.toRelease.length > 0 && (
                <div className="border-t pt-2">
                  <p className="font-medium mb-1">待发布列表:</p>
                  <pre className="text-xs whitespace-pre-wrap">
                    {compareResult.toRelease.map((i) => `  - ${i.name}`).join("\n")}
                  </pre>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowConfirm(false)}>
              取消
            </Button>
            <Button onClick={handleConfirmPublish}>
              确认发布 ({compareResult?.toRelease.length || 0} 个)
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
