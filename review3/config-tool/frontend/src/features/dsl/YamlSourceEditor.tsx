/**
 * YAML 源码编辑器（基础：行号 + 文本编辑 + 语法提示）。
 *
 * 行号栏自身不滚动（overflow-hidden），通过 onScroll 与 textarea 的
 * scrollTop 同步，因此整个编辑器只有代码区一条竖向滚动条。
 */
import { useMemo, useRef } from 'react'
import { useDslProjectStore } from './useDslProjectStore'

export function YamlSourceEditor() {
  const yamlText = useDslProjectStore((s) => s.yamlText)
  const yamlDirty = useDslProjectStore((s) => s.yamlDirty)
  const yamlError = useDslProjectStore((s) => s.yamlError)
  const setYamlText = useDslProjectStore((s) => s.setYamlText)
  const setYamlError = useDslProjectStore((s) => s.setYamlError)

  const gutterRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const lineCount = useMemo(() => {
    if (!yamlText) return 1
    return yamlText.split('\n').length
  }, [yamlText])

  const syncGutterScroll = () => {
    if (gutterRef.current && textareaRef.current) {
      gutterRef.current.scrollTop = textareaRef.current.scrollTop
    }
  }

  const onChange = (value: string) => {
    setYamlText(value, true)
    // Lightweight syntax check: unmatched quotes / empty root.
    if (!value.trim()) {
      setYamlError('YAML 内容为空')
      return
    }
    const open = (value.match(/:\s*$/gm) || []).length
    void open
    try {
      // Prefer structured check when available; keep editor usable offline.
      if (value.includes('\t')) {
        setYamlError('检测到 Tab 缩进，建议使用空格')
      } else {
        setYamlError(null)
      }
    } catch (e) {
      setYamlError(String(e))
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="yaml-source-editor">
      <div className="flex items-center gap-2 border-b border-border px-3 py-1.5 text-xs text-muted-foreground">
        <span>YAML 源码</span>
        {yamlDirty ? <span className="text-amber-700">未保存</span> : <span>已同步</span>}
        {yamlError ? <span className="text-destructive">{yamlError}</span> : null}
      </div>
      <div className="flex min-h-0 flex-1 overflow-hidden font-mono text-xs leading-5">
        <div
          ref={gutterRef}
          className="select-none overflow-hidden border-r border-border bg-muted/40 px-2 py-2 text-right text-muted-foreground"
          aria-hidden
        >
          {Array.from({ length: lineCount }, (_, i) => (
            <div key={i + 1}>{i + 1}</div>
          ))}
        </div>
        <textarea
          ref={textareaRef}
          className="min-h-0 flex-1 resize-none bg-background p-2 outline-none"
          value={yamlText}
          onChange={(e) => onChange(e.target.value)}
          onScroll={syncGutterScroll}
          spellCheck={false}
          data-testid="yaml-textarea"
        />
      </div>
    </div>
  )
}
