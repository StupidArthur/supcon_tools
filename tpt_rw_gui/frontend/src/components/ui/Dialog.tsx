// 通用模态对话框。支持:
//   - X 关闭按钮(右上角)
//   - 点击遮罩(弹窗外空白)关闭
//   - Esc 键关闭
//   - body 区内容由 children 提供
// 不引第三方依赖,纯 React + 少量 inline style。

import { useEffect, type ReactNode } from 'react';
import { cn } from '@/lib/utils';

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  className?: string;
  children: ReactNode;
}

export function Dialog({ open, onClose, title, className, children }: DialogProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className={cn(
          'relative w-[min(720px,90vw)] max-h-[85vh] overflow-auto rounded-lg border border-border bg-card text-card-foreground shadow-lg',
          className,
        )}
      >
        {title && (
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <h2 className="text-base font-semibold">{title}</h2>
            <button
              type="button"
              aria-label="关闭对话框"
              onClick={onClose}
              className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <span aria-hidden>×</span>
            </button>
          </div>
        )}
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}
