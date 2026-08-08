import type { ReactNode } from "react"

interface Props {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
  width?: string
}

export function Modal({ open, onClose, title, children, footer, width = "w-[640px]" }: Props) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />
      <div className={`relative bg-card border border-border rounded-xl shadow-lg ${width} max-h-[80vh] flex flex-col animate-modal-in`}>
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border flex-shrink-0">
          <h3 className="text-[14px] font-semibold truncate">{title}</h3>
          <button
            onClick={onClose}
            className="w-6 h-6 rounded-md flex items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground transition-colors duration-150 text-[12px]"
          >
            ✕
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <div className="px-5 py-3.5 border-t border-border flex justify-end gap-2 flex-shrink-0">{footer}</div>
        )}
      </div>
    </div>
  )
}
