// 历史页:run 列表 + 点击看详情(tag 级结果)。交互不变,样式换 Tailwind + Shadcn。
import { useState, useEffect } from "react";
import { api, verify } from "../lib/api";
import { ToastKind } from "../components/Toast";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Card, CardContent, CardTitle } from "../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "../components/ui/table";

export function HistoryPage({ pushToast }: { pushToast: (k: ToastKind, t: string) => void }) {
  const [runs, setRuns] = useState<verify.RunRecord[]>([]);
  const [detail, setDetail] = useState<{ run: verify.RunRecord; results: verify.VerifyTagResult[] } | null>(null);

  async function refresh() {
    try { setRuns((await api.listRuns()).runs || []); }
    catch (e) { pushToast("error", (e as Error).message); }
  }
  useEffect(() => { refresh(); }, []);

  async function openRun(id: number) {
    try { setDetail(await api.getRunDetail(id)); }
    catch (e) { pushToast("error", (e as Error).message); }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-2"><Button variant="outline" onClick={refresh}>刷新</Button></div>
      <Table>
        <TableHeader><TableRow><TableHead>ID</TableHead><TableHead>开始时间</TableHead><TableHead>状态</TableHead><TableHead>Mock</TableHead><TableHead>通过/失败</TableHead><TableHead>进度</TableHead><TableHead>操作</TableHead></TableRow></TableHeader>
        <TableBody>
          {runs.map((r) => (
            <TableRow key={r.id}>
              <TableCell>{r.id}</TableCell><TableCell>{r.startedAt}</TableCell>
              <TableCell>{r.status === "finished"
                ? <Badge variant="success">完成</Badge>
                : <Badge variant="warning">{r.status}</Badge>}</TableCell>
              <TableCell>{r.mockKey}</TableCell><TableCell>{r.passed}/{r.failed}</TableCell><TableCell>{r.progress}/{r.total}</TableCell>
              <TableCell><Button size="sm" variant="outline" onClick={() => openRun(r.id)}>详情</Button></TableCell>
            </TableRow>
          ))}
          {runs.length === 0 && <TableRow><TableCell colSpan={7} className="text-muted-foreground text-center">暂无历史</TableCell></TableRow>}
        </TableBody>
      </Table>
      {detail && (
        <Card>
          <CardContent className="p-4 flex flex-col gap-3">
            <CardTitle>Run #{detail.run.id} 详情({detail.run.passed} 通过 / {detail.run.failed} 失败)</CardTitle>
            <Table>
              <TableHeader><TableRow><TableHead>类型</TableHead><TableHead>位号</TableHead><TableHead>写入值</TableHead><TableHead>RT 后</TableHead><TableHead>结果</TableHead><TableHead>说明</TableHead></TableRow></TableHeader>
              <TableBody>
                {detail.results.map((r, i) => (
                  <TableRow key={i}>
                    <TableCell>{r.type}</TableCell><TableCell>{r.tagName}</TableCell><TableCell>{JSON.stringify(r.writeVal)}</TableCell><TableCell>{JSON.stringify(r.rtAfter)}</TableCell>
                    <TableCell>{r.ok ? <Badge variant="success">通过</Badge> : <Badge variant="destructive">失败</Badge>}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{r.msg}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
