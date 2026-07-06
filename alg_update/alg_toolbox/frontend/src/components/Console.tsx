import { useEffect, useRef } from "react"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"

interface ConsoleProps {
  channel: string
  className?: string
}

export function Console({ channel, className }: ConsoleProps) {
  const logsRef = useRef<HTMLPreElement>(null)
  const linesRef = useRef<string[]>([])

  useEffect(() => {
    const off = api.onLog(channel, (msg: string) => {
      linesRef.current = [...linesRef.current, msg]
      if (logsRef.current) {
        logsRef.current.textContent = linesRef.current.join("\n")
        logsRef.current.scrollTop = logsRef.current.scrollHeight
      }
    })
    return off
  }, [channel])

  return (
    <pre
      ref={logsRef}
      className={cn(
        "flex-1 overflow-auto rounded-md border border-border bg-gray-50 p-3 font-mono text-xs leading-relaxed text-gray-700 whitespace-pre-wrap",
        className
      )}
    />
  )
}
