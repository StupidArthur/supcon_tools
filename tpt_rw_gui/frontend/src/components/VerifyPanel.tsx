import { useEffect, useRef, useState } from 'react';
import { Button, Card, CardContent, CardHeader, CardTitle, Input } from '@/components/ui/primitives';
import { rwApi } from '@/lib/api';
import type { RTValue, HistoryRow } from '@/lib/api';
import { useToast } from '@/components/Toast';
import { TagPickerDialog, TagPickerResult } from '@/components/TagPickerDialog';

interface Props {
  disabled?: boolean; // not logged in
}

// 把日期格式化成平台要求的 "yyyy-MM-dd HH:mm:ss"。
function fmtDate(d: Date): string {
  const pad = (n: number) => n.toString().padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

export function VerifyPanel({ disabled }: Props) {
  const toast = useToast();

  // 选择区(主页唯一上下文)
  const [picked, setPicked] = useState<TagPickerResult | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  // A 卡:实时值
  const [rt, setRt] = useState<RTValue | null>(null);
  const rtTimerRef = useRef<number | null>(null);

  // B 卡:写值
  const [writeVal, setWriteVal] = useState<string>('');
  const [writeBusy, setWriteBusy] = useState(false);
  const writeInputRef = useRef<HTMLInputElement | null>(null);

  // C 卡:历史值
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyStart, setHistoryStart] = useState<string>('');
  const [historyEnd, setHistoryEnd] = useState<string>('');

  const tagName = picked?.tagName ?? null;

  // 初始化历史时间窗口:过去 1 分钟
  useEffect(() => {
    refreshTimeSpan();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 选完标签后:清 RT 旧值,清 input,后续会按新 tagName 开始轮询
  useEffect(() => {
    setRt(null);
    setHistory([]);
    setWriteVal('');
    stopRtPoll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [picked?.tagId]);

  // A 卡:实时值轮询(1 秒),选中后才开始
  function stopRtPoll() {
    if (rtTimerRef.current !== null) {
      window.clearInterval(rtTimerRef.current);
      rtTimerRef.current = null;
    }
  }

  useEffect(() => {
    stopRtPoll();
    if (!tagName) {
      setRt(null);
      return;
    }
    let stopped = false;
    const tick = async () => {
      try {
        const list = await rwApi.readRealtime([tagName]);
        if (stopped) return;
        const first = list[0];
        if (first) {
          setRt((prev) => {
            if ((prev == null || writeVal === '') && writeInputRef.current !== document.activeElement) {
              setWriteVal(first.value);
            }
            return first;
          });
        }
      } catch (e) {
        toast.push({ kind: 'error', message: 'RT 读取失败: ' + (e as Error).message });
      }
    };
    void tick();
    rtTimerRef.current = window.setInterval(tick, 1000);
    return () => {
      stopped = true;
      stopRtPoll();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tagName]);

  // B 卡:写值
  async function writeValue() {
    if (!tagName || writeVal === '' || writeBusy) return;
    setWriteBusy(true);
    try {
      await rwApi.writeValues({
        values: { [tagName]: writeVal },
        readbackDelayMs: 1000,
      });
      toast.push({ kind: 'success', message: `已写入 ${tagName} = ${writeVal}` });
    } catch (e) {
      toast.push({ kind: 'error', message: '写值失败: ' + (e as Error).message });
    } finally {
      setWriteBusy(false);
    }
  }

  // C 卡:历史值
  function refreshTimeSpan() {
    const end = new Date();
    const start = new Date(end.getTime() - 60 * 1000);
    setHistoryEnd(fmtDate(end));
    setHistoryStart(fmtDate(start));
  }

  async function queryHistory() {
    if (!tagName) return;
    setHistoryBusy(true);
    try {
      const rows = await rwApi.readHistory({
        tagNames: [tagName],
        begTime: historyStart,
        endTime: historyEnd,
        interval: 0,
        isSecond: false,
        isSource: false,
        offset: 0,
        option: 0,
        page: 1,
        pageSize: 200,
        sort: '-appTime',
        mode: 'fromdb',
        numberToString: false,
      });
      setHistory(rows);
    } catch (e) {
      toast.push({ kind: 'error', message: '历史查询失败: ' + (e as Error).message });
    } finally {
      setHistoryBusy(false);
    }
  }

  function handleConfirm(result: TagPickerResult) {
    setPicked(result);
  }

  if (disabled) {
    return (
      <div className="rounded-md border border-dashed border-border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
        请先登录
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* ---- 位号选择卡 ---- */}
      <Card>
        <CardHeader><CardTitle>位号选择</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          {picked ? (
            <div className="text-sm">
              <span className="text-muted-foreground">当前选中: </span>
              <span className="font-mono">{picked.dsName}</span>
              <span className="text-muted-foreground"> / </span>
              <span className="font-mono">{picked.tagName}</span>
            </div>
          ) : (
            <span className="text-sm text-muted-foreground">未选中</span>
          )}
          <Button variant="outline" onClick={() => setPickerOpen(true)}>选择位号</Button>
        </CardContent>
      </Card>

      {/* ---- 弹窗 ---- */}
      <TagPickerDialog
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onConfirm={handleConfirm}
      />

      {/* ---- A 卡 / B 卡 / C 卡 ---- */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {/* A 卡:实时值 */}
        <Card>
          <CardHeader>
            <CardTitle>
              实时值 {tagName && <span className="ml-2 text-xs text-muted-foreground">({tagName})</span>}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {!tagName ? (
              <div className="text-sm text-muted-foreground">请先在"位号选择"中选择位号(选中后开始 1s 轮询)</div>
            ) : (
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="p-1">值</th>
                    <th className="p-1">tagTime</th>
                    <th className="p-1">q</th>
                  </tr>
                </thead>
                <tbody>
                  {rt ? (
                    <tr className="border-t border-border">
                      <td className="p-1 font-mono">{rt.value}</td>
                      <td className="p-1 text-xs text-muted-foreground">{rt.tagTime}</td>
                      <td className="p-1">{rt.quality}</td>
                    </tr>
                  ) : (
                    <tr><td colSpan={3} className="p-2 text-sm text-muted-foreground">加载中…</td></tr>
                  )}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>

        {/* B 卡:写值 */}
        <Card>
          <CardHeader>
            <CardTitle>
              写值 {tagName && <span className="ml-2 text-xs text-muted-foreground">→ {tagName}</span>}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {!tagName ? (
              <div className="text-sm text-muted-foreground">请先在"位号选择"中选择位号</div>
            ) : (
              <>
                <Input
                  ref={writeInputRef}
                  value={writeVal}
                  onChange={(e) => setWriteVal(e.target.value)}
                  placeholder="输入要写入的值"
                />
                <Button
                  disabled={writeVal === '' || writeBusy}
                  onClick={writeValue}
                  className="w-full"
                >
                  {writeBusy ? '写中…' : '提交'}
                </Button>
              </>
            )}
          </CardContent>
        </Card>

        {/* C 卡:历史值 */}
        <Card>
          <CardHeader>
            <CardTitle>
              历史值 {tagName && <span className="ml-2 text-xs text-muted-foreground">({tagName})</span>}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {!tagName ? (
              <div className="text-sm text-muted-foreground">请先在"位号选择"中选择位号</div>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-2">
                  <Input
                    value={historyStart}
                    onChange={(e) => setHistoryStart(e.target.value)}
                    placeholder="开始"
                    className="font-mono text-xs"
                  />
                  <Input
                    value={historyEnd}
                    onChange={(e) => setHistoryEnd(e.target.value)}
                    placeholder="结束"
                    className="font-mono text-xs"
                  />
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={refreshTimeSpan} className="flex-1">刷新时间</Button>
                  <Button onClick={queryHistory} disabled={historyBusy} className="flex-1">
                    {historyBusy ? '查询中…' : '查询历史'}
                  </Button>
                </div>
                <div className="max-h-64 overflow-auto rounded border border-border">
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 bg-muted text-left text-xs text-muted-foreground">
                      <tr>
                        <th className="p-1">值</th>
                        <th className="p-1">appTime</th>
                        <th className="p-1">q</th>
                      </tr>
                    </thead>
                    <tbody>
                      {history.length === 0 && (
                        <tr><td colSpan={3} className="p-2 text-center text-xs text-muted-foreground">暂无</td></tr>
                      )}
                      {history.map((r, i) => (
                        <tr key={`${r.appTime}-${i}`} className="border-t border-border">
                          <td className="p-1 font-mono">{r.value}</td>
                          <td className="p-1 text-xs text-muted-foreground">{r.appTime}</td>
                          <td className="p-1">{r.quality}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
