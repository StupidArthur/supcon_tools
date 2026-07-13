// Toast 总线 — 全局错误/成功提示。轻量自造,不引第三方。
//
// 用法:
//   <ToastProvider>{children}</ToastProvider> 顶层包一次
//   const { push } = useToast();
//   push({ kind: 'error', message: '写值失败' })

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

export type ToastKind = 'info' | 'success' | 'error';

export interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastContextValue {
  push: (t: { kind: ToastKind; message: string }) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>');
  return ctx;
}

const AUTO_DISMISS_MS = 5000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextIdRef = useRef(1);
  const timersRef = useRef<Map<number, number>>(new Map());

  const remove = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
    const t = timersRef.current.get(id);
    if (t !== undefined) {
      window.clearTimeout(t);
      timersRef.current.delete(id);
    }
  }, []);

  const push = useCallback<ToastContextValue['push']>(
    ({ kind, message }) => {
      const id = nextIdRef.current++;
      setItems((prev) => [...prev, { id, kind, message }]);
      const timer = window.setTimeout(() => remove(id), AUTO_DISMISS_MS);
      timersRef.current.set(id, timer);
    },
    [remove],
  );

  const value = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport items={items} onDismiss={remove} />
    </ToastContext.Provider>
  );
}

function ToastViewport({
  items,
  onDismiss,
}: {
  items: ToastItem[];
  onDismiss: (id: number) => void;
}) {
  return (
    <div className="pointer-events-none fixed right-4 top-4 z-50 flex w-80 flex-col gap-2">
      {items.map((t) => (
        <div
          key={t.id}
          role="alert"
          className={[
            'pointer-events-auto rounded-md border bg-card px-3 py-2 text-sm shadow-md',
            t.kind === 'error' && 'border-red-500 text-red-700',
            t.kind === 'success' && 'border-emerald-500 text-emerald-700',
            t.kind === 'info' && 'border-sky-500 text-sky-700',
          ]
            .filter(Boolean)
            .join(' ')}
        >
          <div className="flex items-start justify-between gap-2">
            <span className="break-all">{t.message}</span>
            <button
              type="button"
              onClick={() => onDismiss(t.id)}
              className="text-xs text-muted-foreground hover:text-foreground"
              aria-label="关闭通知"
            >
              ×
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
