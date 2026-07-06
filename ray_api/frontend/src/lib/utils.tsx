import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import * as React from 'react'

/** cn: 合并 Tailwind 类名，处理冲突（Shadcn 标配）。 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** 格式化字节为人类可读（GB/MB）。 */
export function fmtBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return '0'
  const gb = bytes / 1024 / 1024 / 1024
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  const mb = bytes / 1024 / 1024
  return `${mb.toFixed(0)} MB`
}

/** 毫秒时间戳转 HH:mm:ss。 */
export function fmtTime(ms: number): string {
  if (!ms) return '-'
  return new Date(ms).toLocaleTimeString('zh-CN', { hour12: false })
}

/** 毫秒时间戳转 MM-dd HH:mm。 */
export function fmtDateTime(ms: number): string {
  if (!ms) return '-'
  const d = new Date(ms)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 计算使用率百分比。 */
export function pct(used: number, total: number): number {
  if (!total) return 0
  return Math.round((used / total) * 100)
}

/**
 * FilterInput 列头筛选输入框。
 * 包含 contains 语义，调用方做大小写不敏感的匹配（utils.ts 没有内置）。
 * 配套用法见 NodesView / WorkersView 等 view：每列一个，state 在 view 内。
 */
export function FilterInput({
  value,
  onChange,
  placeholder = '筛选',
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  return (
    <input
      type="text"
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className="h-7 w-full rounded border border-border bg-background px-1.5 text-xs outline-none focus:border-ring"
    />
  )
}

/**
 * applyFilters 通用筛选函数：按 columnGetters 的 key 拿到该列字符串值，
 * 与 filter 字符串做 case-insensitive contains 匹配。
 * 任何 filter 都不匹配 → 整行被过滤掉。
 */
export function applyFilters<T>(
  items: T[],
  filters: Record<string, string>,
  columnGetters: Record<string, (item: T) => string>,
): T[] {
  const active = Object.entries(filters).filter(([, v]) => v && v.trim())
  if (active.length === 0) return items
  return items.filter((item) =>
    active.every(([k, v]) => {
      const getter = columnGetters[k]
      if (!getter) return true
      return getter(item).toLowerCase().includes(v.toLowerCase())
    }),
  )
}
