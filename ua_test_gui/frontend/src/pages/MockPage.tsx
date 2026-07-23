// ua-server-mock 管理页:4 行 table 启停 + 性能参数可编辑保存。
import { useState, useEffect, useRef } from "react";
import { api, mock } from "../lib/api";
import { ToastKind } from "../components/Toast";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Badge } from "../components/ui/badge";
import { Card, CardContent } from "../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "../components/ui/table";
import { EventsOn } from "../../wailsjs/runtime/runtime";

// 后端状态:stopped/starting/ready/failed(本进程)+ running(跨进程探测)。ready/running=运行中。
function isRunning(status: string) {
  return status === "ready" || status === "running" || status === "starting";
}

function isTerminal(status: string) {
  return status === "ready" || status === "running" || status === "failed";
}

function statusBadge(status: string) {
  switch (status) {
    case "ready":
    case "running": return <Badge variant="success">运行中</Badge>;
    case "starting": return <Badge variant="warning">启动中</Badge>;
    case "failed": return <Badge variant="destructive">失败</Badge>;
    default: return <Badge variant="secondary">已停止</Badge>;
  }
}

function reasonSummary(reason?: string) {
  if (!reason) return "";
  const firstLine = reason.split("\n").map((line) => line.trim()).find(Boolean) || reason.trim();
  return firstLine.length > 180 ? `${firstLine.slice(0, 180)}…` : firstLine;
}

type MockRow = mock.MockSummary & { reason?: string };

const DEFAULT_PERF: mock.PerfParams = { pollN: 10000, writeN: 1000, ratio: 0.9 };
const BATCH_TIMEOUT_MS = 8 * 60 * 1000;

export function MockPage({ pushToast }: { pushToast: (k: ToastKind, t: string) => void }) {
  const [mocks, setMocks] = useState<MockRow[]>([]);
  const [perf, setPerf] = useState<mock.PerfParams>(DEFAULT_PERF);
  const [perfEdit, setPerfEdit] = useState<mock.PerfParams>(DEFAULT_PERF);
  const [busy, setBusy] = useState<string | null>(null);
  const [batchBusy, setBatchBusy] = useState(false);

  const mocksRef = useRef<MockRow[]>([]);
  const busyRef = useRef<string | null>(null);
  const batchBusyRef = useRef(false);
  const batchTarget = useRef<Set<string>>(new Set());
  const batchStartedAt = useRef(0);
  const polling = useRef(false);
  const prevStatus = useRef<Record<string, string>>({});
  const failureReasons = useRef<Record<string, string>>({});

  function commitMocks(next: MockRow[]) {
    mocksRef.current = next;
    setMocks(next);
    return next;
  }

  function setBusyState(next: string | null) {
    busyRef.current = next;
    setBusy(next);
  }

  function setBatchBusyState(next: boolean) {
    batchBusyRef.current = next;
    setBatchBusy(next);
  }

  async function refresh(loadPerf = false): Promise<MockRow[]> {
    try {
      const listRes = await api.listMocks();
      const next = (listRes.mocks || []).map((item) => {
        const reason = failureReasons.current[item.key];
        // 当前后端在异步启动失败后可能重新报告 stopped；保留事件携带的 failed 状态和原因。
        if (reason && item.status === "stopped") {
          return { ...item, status: "failed", reason } as MockRow;
        }
        return { ...item, reason: item.status === "failed" ? reason : undefined } as MockRow;
      });
      commitMocks(next);

      if (loadPerf) {
        const perfRes = await api.getPerformanceParams();
        const p = perfRes.params;
        const effective = p.pollN || p.writeN || p.ratio ? p : DEFAULT_PERF;
        setPerf(effective);
        setPerfEdit(effective);
      }
      return next;
    } catch (e) {
      pushToast("error", (e as Error).message);
      return mocksRef.current;
    }
  }

  function finishBatch(next: MockRow[]) {
    if (!batchBusyRef.current || batchTarget.current.size === 0) return;

    const targets = Array.from(batchTarget.current);
    const allDone = targets.every((key) => {
      const status = next.find((m) => m.key === key)?.status || "stopped";
      return isTerminal(status);
    });

    if (allDone) {
      const failed = targets
        .map((key) => next.find((m) => m.key === key))
        .filter((m): m is MockRow => m?.status === "failed");
      const successCount = targets.length - failed.length;
      batchTarget.current.clear();
      batchStartedAt.current = 0;
      setBatchBusyState(false);
      if (failed.length > 0) {
        pushToast("error", `批量启动结束：${successCount} 个成功，${failed.length} 个失败（${failed.map((m) => m.name).join("、")}）`);
      } else {
        pushToast("success", `批量启动完成（${successCount} 个）`);
      }
      return;
    }

    if (batchStartedAt.current > 0 && Date.now() - batchStartedAt.current > BATCH_TIMEOUT_MS) {
      const pending = targets
        .map((key) => next.find((m) => m.key === key))
        .filter((m): m is MockRow => !m || !isTerminal(m.status));
      batchTarget.current.clear();
      batchStartedAt.current = 0;
      setBatchBusyState(false);
      pushToast("error", `批量启动超时，未完成：${pending.map((m) => m?.name || "未知 mock").join("、")}`);
    }
  }

  function checkTransitions(next: MockRow[]) {
    for (const m of next) {
      const prev = prevStatus.current[m.key];
      if (prev === "starting" && (m.status === "ready" || m.status === "running")) {
        pushToast("success", `${m.name} 已启动就绪`);
      } else if (m.status === "failed" && prev && prev !== "failed") {
        const detail = reasonSummary(m.reason);
        pushToast("error", `${m.name} 启动失败${detail ? `：${detail}` : ""}`);
      }

      if (busyRef.current === m.key && isTerminal(m.status)) {
        setBusyState(null);
      }
    }
    prevStatus.current = Object.fromEntries(next.map((m) => [m.key, m.status]));
    finishBatch(next);
  }

  function applyRuntimeEvent(runtime: mock.MockRuntime) {
    const key = runtime?.spec?.Key;
    if (!key) {
      void refresh().then(checkTransitions);
      return;
    }

    if (runtime.status === "failed") {
      failureReasons.current[key] = runtime.reason || "启动失败，未返回详细原因";
    } else if (runtime.status === "ready" || runtime.status === "stopped") {
      delete failureReasons.current[key];
    }

    const current = mocksRef.current;
    if (current.length > 0) {
      const next = current.map((m) => m.key === key
        ? { ...m, status: runtime.status, endpoint: runtime.endpoint || m.endpoint, reason: runtime.reason || undefined }
        : m);
      commitMocks(next);
      checkTransitions(next);
    }

    // 事件用于保留详细失败原因，刷新用于同步其他 mock 的状态。
    void refresh().then(checkTransitions);
  }

  useEffect(() => {
    void refresh(true).then(checkTransitions);
    const cancel = EventsOn("mock:state", (runtime: mock.MockRuntime) => applyRuntimeEvent(runtime));
    const timer = window.setInterval(() => {
      if (!batchBusyRef.current || polling.current) return;
      polling.current = true;
      void refresh()
        .then(checkTransitions)
        .finally(() => { polling.current = false; });
    }, 1000);
    return () => {
      cancel();
      window.clearInterval(timer);
    };
  }, []);

  async function start(key: string) {
    const mk = mocksRef.current.find((m) => m.key === key);
    if (mk && mk.nodeCount > 500) {
      const sec = Math.ceil(mk.nodeCount / 1000);
      pushToast("info", `${mk.name} 共 ${mk.nodeCount} 个位号，启动约需 ${sec} 秒，请耐心等待`);
    }

    delete failureReasons.current[key];
    setBusyState(key);
    try {
      await api.startMock(key);
      pushToast("info", `${mk?.name || key} 启动中，就绪后会自动刷新`);
      checkTransitions(await refresh());
    } catch (e) {
      const message = (e as Error).message || String(e);
      failureReasons.current[key] = message;
      const next = mocksRef.current.map((m) => m.key === key ? { ...m, status: "failed", reason: message } : m);
      commitMocks(next);
      prevStatus.current[key] = "failed";
      pushToast("error", message);
      setBusyState(null);
    }
  }

  async function stop(key: string) {
    setBusyState(key);
    try {
      await api.stopMock(key);
      delete failureReasons.current[key];
      pushToast("success", `${key} 已停止`);
      checkTransitions(await refresh());
    } catch (e) {
      pushToast("error", (e as Error).message);
    } finally {
      setBusyState(null);
    }
  }

  async function startAll() {
    const startable = mocksRef.current.filter((m) => m.status === "stopped" || m.status === "failed");
    if (startable.length === 0) {
      pushToast("info", "没有可启动的 mock");
      return;
    }

    for (const m of startable) delete failureReasons.current[m.key];
    const prepared = mocksRef.current.map((m) => startable.some((s) => s.key === m.key)
      ? { ...m, status: "stopped", reason: undefined }
      : m);
    commitMocks(prepared);
    prevStatus.current = Object.fromEntries(prepared.map((m) => [m.key, m.status]));

    batchTarget.current = new Set(startable.map((m) => m.key));
    batchStartedAt.current = Date.now();
    setBatchBusyState(true);
    try {
      await api.startAllMocks();
      pushToast("info", `已发起批量启动（${startable.length} 个），将依次就绪`);
      checkTransitions(await refresh());
    } catch (e) {
      pushToast("error", (e as Error).message);
      batchTarget.current.clear();
      batchStartedAt.current = 0;
      setBatchBusyState(false);
    }
  }

  async function stopAll() {
    setBatchBusyState(true);
    try {
      await api.stopAllMocks();
      failureReasons.current = {};
      pushToast("success", "已停止全部 mock");
      checkTransitions(await refresh());
    } catch (e) {
      pushToast("error", (e as Error).message);
    } finally {
      batchTarget.current.clear();
      batchStartedAt.current = 0;
      setBatchBusyState(false);
      setBusyState(null);
    }
  }

  async function savePerf() {
    if (perfEdit.pollN < 1 || perfEdit.writeN < 1 || perfEdit.ratio <= 0 || perfEdit.ratio > 1) {
      pushToast("error", "性能参数无效：位号数必须大于 0，Double 配比必须在 (0, 1] 范围内");
      return;
    }
    try {
      await api.setPerformanceParams(perfEdit);
      setPerf(perfEdit);
      pushToast("success", "性能参数已保存");
    } catch (e) {
      pushToast("error", (e as Error).message);
    }
  }

  const anyRunning = mocks.some((m) => isRunning(m.status));
  const anyStartable = mocks.some((m) => m.status === "stopped" || m.status === "failed");

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-2">
        <Button variant="outline" onClick={() => refresh().then(checkTransitions)} disabled={batchBusy}>刷新</Button>
        <Button variant="default" onClick={startAll} disabled={batchBusy || !anyStartable}>
          {batchBusy && batchTarget.current.size > 0 ? "批量启动中..." : "启动全部"}
        </Button>
        <Button variant="destructive" onClick={stopAll} disabled={batchBusy || !anyRunning}>
          {batchBusy && batchTarget.current.size === 0 ? "批量停止中..." : "停止全部"}
        </Button>
      </div>
      <Table>
        <TableHeader><TableRow><TableHead>名称</TableHead><TableHead>端口</TableHead><TableHead>位号数</TableHead><TableHead>状态</TableHead><TableHead>操作</TableHead></TableRow></TableHeader>
        <TableBody>
          {mocks.map((m) => (
            <TableRow key={m.key}>
              <TableCell>{m.name}<div className="text-xs text-muted-foreground">{m.key}</div></TableCell>
              <TableCell>{m.port}</TableCell>
              <TableCell>{m.nodeCount}</TableCell>
              <TableCell>
                <div className="flex max-w-72 flex-col gap-1">
                  {statusBadge(m.status)}
                  {m.status === "failed" && m.reason && (
                    <div className="break-words text-xs text-destructive" title={m.reason}>{reasonSummary(m.reason)}</div>
                  )}
                </div>
              </TableCell>
              <TableCell>
                {isRunning(m.status)
                  ? <Button size="sm" variant="destructive" disabled={batchBusy || busy === m.key} onClick={() => stop(m.key)}>{busy === m.key ? "..." : "停止"}</Button>
                  : <Button size="sm" disabled={batchBusy || busy === m.key} onClick={() => start(m.key)}>{busy === m.key ? "启动中" : "启动"}</Button>}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Card>
        <CardContent className="p-4 flex flex-col gap-3">
          <div className="font-semibold">性能测试参数（可编辑，启动性能 mock 时生效）</div>
          <div className="flex gap-4 flex-wrap">
            <label className="flex flex-col gap-1.5 text-sm text-muted-foreground flex-1 min-w-40">轮询位号数
              <Input type="number" min={1} value={perfEdit.pollN} onChange={(e) => setPerfEdit({ ...perfEdit, pollN: +e.target.value })} /></label>
            <label className="flex flex-col gap-1.5 text-sm text-muted-foreground flex-1 min-w-40">可写位号数
              <Input type="number" min={1} value={perfEdit.writeN} onChange={(e) => setPerfEdit({ ...perfEdit, writeN: +e.target.value })} /></label>
            <label className="flex flex-col gap-1.5 text-sm text-muted-foreground flex-1 min-w-40">Double:Bool 配比
              <Input type="number" min={0.01} max={1} step="0.1" value={perfEdit.ratio} onChange={(e) => setPerfEdit({ ...perfEdit, ratio: +e.target.value })} /></label>
          </div>
          <div className="text-xs text-muted-foreground">当前生效：轮询 {perf.pollN} / 可写 {perf.writeN} / 配比 {perf.ratio}</div>
          <Button className="w-fit" onClick={savePerf} disabled={batchBusy}>保存</Button>
        </CardContent>
      </Card>
    </div>
  );
}
