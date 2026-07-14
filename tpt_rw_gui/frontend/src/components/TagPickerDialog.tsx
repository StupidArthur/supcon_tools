// 位号选择对话框。
// 弹窗内:
//   1. 数据源 select(用户手选,不预选)
//   2. 关键字 input + "筛选"按钮 — 不点筛选不发起请求
//   3. 列表 — 筛选后展示;只读 radio 单选
//   4. 底部"确认"按钮 — 把选中的 {dsId, dsName, tagName, tagId} 传给 onConfirm;关闭
//   5. X / 遮罩 / Esc 都能关,但不传任何内容(用户主动放弃)

import { useEffect, useState } from 'react';
import { Button, Card, CardContent, Input } from '@/components/ui/primitives';
import { Dialog } from '@/components/ui/Dialog';
import { useToast } from '@/components/Toast';
import { rwApi, DataSource, Tag } from '@/lib/api';

export interface TagPickerResult {
  dsId: number;
  dsName: string;
  tagId: number;
  tagName: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onConfirm: (r: TagPickerResult) => void;
}

export function TagPickerDialog({ open, onClose, onConfirm }: Props) {
  const toast = useToast();
  const [sources, setSources] = useState<DataSource[]>([]);
  const [dsId, setDsId] = useState<number | null>(null);
  const [keyword, setKeyword] = useState('');
  const [tags, setTags] = useState<Tag[]>([]);
  const [pickedId, setPickedId] = useState<number | null>(null);
  const [sourcesBusy, setSourcesBusy] = useState(false);
  const [tagsBusy, setTagsBusy] = useState(false);
  // 列表区诊断状态:idle=未发起 / loading=正在筛 / empty=筛后 0 条 / error=失败
  const [tagStatus, setTagStatus] = useState<'idle' | 'loading' | 'empty' | 'error'>('idle');
  const [tagErrMsg, setTagErrMsg] = useState('');
  const [tagPage, setTagPage] = useState(0);
  const TAG_PAGE_SIZE = 10;

  // 打开时拉数据源
  useEffect(() => {
    if (!open) return;
    setSourcesBusy(true);
    rwApi
      .listDataSources()
      .then((list) => setSources(list))
      .catch((e: unknown) => toast.push({ kind: 'error', message: '数据源获取失败: ' + (e as Error).message }))
      .finally(() => setSourcesBusy(false));
  }, [open, toast]);

  // 关闭时重置本地状态
  useEffect(() => {
    if (open) return;
    setDsId(null);
    setKeyword('');
    setTags([]);
    setPickedId(null);
    setTagStatus('idle');
    setTagErrMsg('');
  }, [open]);

  // 切 DS 时清掉旧列表与诊断,避免误导
  useEffect(() => {
    if (!open) return;
    setTags([]);
    setPickedId(null);
    setTagStatus('idle');
    setTagErrMsg('');
    setTagPage(0);
  }, [dsId, open]);

  // Enter / 点筛选 → 调 listTags,并明确每个分支的诊断状态
  async function fetchTags() {
    if (dsId === null) return;
    setTagsBusy(true);
    setTagStatus('loading');
    setTagErrMsg('');
    try {
      const list = await rwApi.listTags({
        dsId,
        keyword,
        page: 1,
        pageSize: 200,
      });
      setTags(list);
      setPickedId(null);
      setTagPage(0);
      setTagStatus(list.length === 0 ? 'empty' : 'idle');
    } catch (e) {
      const msg = (e as Error).message;
      setTagErrMsg(msg);
      setTagStatus('error');
      toast.push({ kind: 'error', message: '位号筛选失败: ' + msg });
    } finally {
      setTagsBusy(false);
    }
  }

  function confirm() {
    if (dsId === null || pickedId === null) return;
    const ds = sources.find((s) => s.id === dsId);
    const tg = tags.find((t) => t.id === pickedId);
    if (!ds || !tg) return;
    onConfirm({
      dsId: ds.id,
      dsName: ds.name,
      tagId: tg.id,
      tagName: tg.tagName,
    });
    onClose();
  }

  const tagStart = tagPage * TAG_PAGE_SIZE;
  const tagEnd = tagStart + TAG_PAGE_SIZE;
  const pagedTags = tags.slice(tagStart, tagEnd);
  const totalPages = Math.ceil(tags.length / TAG_PAGE_SIZE);

  return (
    <Dialog open={open} onClose={onClose} title="选择位号">
      <Card className="border-0 shadow-none">
        <CardContent className="space-y-3 p-0">
          <label className="block text-sm">
            数据源
            <select
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1 text-sm"
              value={dsId ?? ''}
              onChange={(e) => setDsId(e.target.value ? Number(e.target.value) : null)}
              disabled={sourcesBusy || sources.length === 0}
            >
              <option value="">-- 请选择数据源 --</option>
              {sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.alive ? 'alive' : 'dead'})
                </option>
              ))}
            </select>
          </label>

          <div className="flex items-center gap-2">
            <Input
              className="max-w-[60%]"
              placeholder="输入位号或部分字符串"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') fetchTags();
              }}
              disabled={dsId === null}
            />
            <Button
              className="shrink-0"
              disabled={dsId === null || tagsBusy}
              onClick={fetchTags}
            >
              {tagsBusy ? '筛选中…' : '筛选'}
            </Button>
          </div>

          <div className="max-h-[26rem] overflow-y-auto rounded border border-border">
            {dsId === null ? (
              <div className="p-3 text-center text-sm text-muted-foreground">请先选择数据源</div>
            ) : tagStatus === 'loading' ? (
              <div className="p-3 text-center text-sm text-muted-foreground">正在筛选…</div>
            ) : tagStatus === 'error' ? (
              <div className="p-3 text-center text-sm text-red-600">筛选失败: {tagErrMsg}</div>
            ) : tagStatus === 'empty' ? (
              <div className="p-3 text-center text-sm text-muted-foreground">
                已加载 0 条位号(没匹配到。试试更短的关键字或留空)
              </div>
            ) : tags.length === 0 ? (
              <div className="p-3 text-center text-sm text-muted-foreground">输入关键字后点"筛选"(空关键字也行)</div>
            ) : (
              pagedTags.map((t) => (
                <label
                  key={t.id}
                  className="flex cursor-pointer items-center gap-2 border-b border-border p-2 text-sm last:border-b-0 hover:bg-muted/40"
                >
                  <input
                    type="radio"
                    name="tag-pick"
                    checked={pickedId === t.id}
                    onChange={() => setPickedId(t.id)}
                  />
                  <span className="font-mono">{t.tagName}</span>
                  <span className="ml-auto text-xs text-muted-foreground">
                    q={t.quality} val={t.tagValue ?? ''} dt={t.dataType}
                  </span>
                </label>
              ))
            )}
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 text-sm">
              <Button
                variant="outline"
                className="h-7 px-2"
                disabled={tagPage === 0}
                onClick={() => setTagPage((p) => p - 1)}
              >
                上一页
              </Button>
              <span className="text-muted-foreground">
                {tagPage + 1} / {totalPages} 页(共 {tags.length} 条)
              </span>
              <Button
                variant="outline"
                className="h-7 px-2"
                disabled={tagPage >= totalPages - 1}
                onClick={() => setTagPage((p) => p + 1)}
              >
                下一页
              </Button>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={onClose}>取消</Button>
            <Button disabled={pickedId === null} onClick={confirm}>确认</Button>
          </div>
        </CardContent>
      </Card>
    </Dialog>
  );
}
